"""Apply Alembic migrations to the queue database."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic import command, context
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import Engine

from megila.config import Settings
from megila.jobs.queue.engine import (
    create_db_engine,
    database_path,
    install_sqlite_pragmas,
    prepare_database_path,
    sqlite_url,
)
from megila.jobs.queue.models import Base

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows has no fcntl
    fcntl = None  # type: ignore[assignment]

_MIGRATIONS = Path(__file__).resolve().parent / "migrations"


@contextmanager
def _migration_lock(database: Path) -> Iterator[None]:
    """Serialize migrations of one database across processes.

    Two processes that open a new database together would both run the
    initial revision and collide on ``CREATE TABLE`` or on ``alembic_version``.
    The lock is an advisory ``flock`` on a sidecar file. Without ``fcntl``
    (Windows) migrations are not serialized.
    """
    if fcntl is None:  # pragma: no cover - Windows has no fcntl
        yield
        return
    lock_path = database.with_name(f"{database.name}.migrate.lock")
    with lock_path.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def upgrade_database(path: Path, revision: str = "head", *, sql: bool = False) -> None:
    """Upgrade the database at ``path`` to ``revision``.

    The parent directory is created. A recognized network filesystem is
    refused before the file is opened. The default revision is ``head``.
    ``sql=True`` prints the SQL and does not open the database file.

    Raises:
        DatabaseLocationError: ``path`` is on a refused filesystem.
    """
    absolute = prepare_database_path(path)
    if sql:
        command.upgrade(_config(absolute), revision, sql=True)
        return
    with _migration_lock(absolute):
        command.upgrade(_config(absolute), revision)


def downgrade_database(path: Path, revision: str = "base") -> None:
    """Downgrade the database at ``path`` to ``revision``.

    The default revision is ``base``, which drops the queue tables. The file
    itself remains. A missing file is an error.

    Raises:
        DatabaseLocationError: ``path`` is on a refused filesystem.
        FileNotFoundError: The database file does not exist.
    """
    absolute = prepare_database_path(path)
    if not absolute.is_file():
        raise FileNotFoundError(absolute)
    command.downgrade(_config(absolute), revision)


def current_revision(path: Path) -> str | None:
    """Return the Alembic revision stamped on ``path``.

    ``None`` means the file has no revision row, or that the file does not
    exist. A missing file is not created.
    """
    if not path.expanduser().resolve().is_file():
        return None
    engine = create_db_engine(path)
    try:
        return _read_revision(engine)
    finally:
        engine.dispose()


def open_database(settings: Settings) -> Engine:
    """Migrate the queue database for ``settings`` and return an engine.

    The file is :func:`megila.jobs.queue.engine.database_path`. Every
    connection uses WAL, ``synchronous=FULL``, foreign keys and a 5000 ms
    busy timeout.
    """
    path = database_path(settings)
    upgrade_database(path)
    return create_db_engine(path)


def run_migrations() -> None:
    """Run the migration Alembic's ``env.py`` delegates to.

    Online mode opens SQLite and installs the queue pragmas on that
    connection. Offline mode prints SQL and does not open the file.
    ``render_as_batch`` is on so a later SQLite ``ALTER`` can rebuild a table.
    """
    if context.is_offline_mode():
        _run_migrations_offline()
    else:
        _run_migrations_online()


def _database_url() -> str:
    config = _alembic_config()
    url = config.get_main_option("sqlalchemy.url")
    if url is None or url == "":
        message = "sqlalchemy.url is not configured"
        raise RuntimeError(message)
    return url


def _alembic_config() -> Config:
    config = context.config
    if config is None:
        message = "Alembic config is missing"
        raise RuntimeError(message)
    return config


def _run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=Base.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_migrations_online() -> None:
    config = _alembic_config()
    section = dict(config.get_section(config.config_ini_section) or {})
    section["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    install_sqlite_pragmas(connectable)
    try:
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=Base.metadata,
                render_as_batch=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


def _config(database: Path) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", _MIGRATIONS.as_posix())
    cfg.set_main_option("sqlalchemy.url", sqlite_url(database))
    # Alembic warns when this is unset. ``os`` keeps paths platform-native.
    cfg.set_main_option("path_separator", "os")
    return cfg


def _read_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        return context.get_current_revision()
