"""SQLite engine for the queue database.

Every connection sets the pragmas from ADR 0003:

* ``journal_mode=WAL``
* ``synchronous=FULL``
* ``foreign_keys=ON``
* ``busy_timeout=5000``

``journal_mode`` is stored in the file. ``foreign_keys`` and ``busy_timeout``
are not, so they are applied again on each new connection. ``synchronous``
is applied on each connection as well, so a later change of the default
cannot silently weaken a commit.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from sqlalchemy import URL, Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from megila.config import Settings
from megila.jobs.queue.errors import DatabaseLocationError
from megila.jobs.queue.filesystem import (
    REFUSED_FILESYSTEM_TYPES,
    detect_filesystem_type,
)

DATABASE_FILENAME = "megila.sqlite3"
BUSY_TIMEOUT_MS = 5000

logger = logging.getLogger(__name__)

_PRAGMAS: tuple[tuple[str, str], ...] = (
    ("journal_mode", "WAL"),
    ("synchronous", "FULL"),
    ("foreign_keys", "ON"),
    ("busy_timeout", str(BUSY_TIMEOUT_MS)),
)


def database_path(settings: Settings) -> Path:
    """Return the queue file for ``settings``.

    The file is ``<data_dir>/megila.sqlite3``. ``data_dir`` comes from the
    configuration model (``$XDG_DATA_HOME/megila`` by default). There is no
    separate database-path setting.
    """
    return settings.data_dir / DATABASE_FILENAME


def sqlite_url(path: Path) -> str:
    """Return a SQLAlchemy URL for the absolute form of ``path``."""
    absolute = path.expanduser().resolve()
    return URL.create("sqlite", database=str(absolute)).render_as_string(
        hide_password=False
    )


def prepare_database_path(path: Path) -> Path:
    """Create the parent directory and refuse a network filesystem.

    The detected type is written to the log, including when it is unknown.
    The directory is created only after the check, so a refused mount is
    not written to.

    Raises:
        DatabaseLocationError: The filesystem type is NFS, SMB/CIFS, or rclone.
    """
    absolute = path.expanduser().resolve()
    parent = absolute.parent
    fstype = detect_filesystem_type(parent)
    rendered = fstype if fstype is not None else "unknown"
    logger.info("queue database %s filesystem type: %s", absolute, rendered)
    if fstype is not None and fstype.strip().lower() in REFUSED_FILESYSTEM_TYPES:
        raise DatabaseLocationError(
            f"Refusing to open {absolute} on filesystem type {fstype!r}. "
            "The queue database must live on a local disk, not on nfs, "
            "cifs, smb, or fuse.rclone."
        )
    parent.mkdir(parents=True, exist_ok=True)
    return absolute


def create_db_engine(path: Path) -> Engine:
    """Return an engine that applies the queue pragmas on every connection.

    The pool is ``NullPool``: each checkout opens a connection, runs the
    pragmas, and closes it when the checkout ends. SQLite transactions in
    this queue are short, and a pooled connection would skip the connect
    hook the second time it was used only if the hook were not installed.
    The hook is installed. ``NullPool`` keeps "every connection" literal.

    The sqlite3 ``timeout`` matches ``busy_timeout`` so the driver waits
    even before the pragma runs.
    """
    absolute = prepare_database_path(path)
    engine = create_engine(
        sqlite_url(absolute),
        poolclass=NullPool,
        connect_args={"timeout": BUSY_TIMEOUT_MS / 1000},
    )
    install_sqlite_pragmas(engine)
    return engine


def session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return a session factory bound to ``engine``.

    Objects stay usable after commit (``expire_on_commit=False``) so a caller
    can read the id it just wrote without another query.
    """
    return sessionmaker(bind=engine, expire_on_commit=False)


def install_sqlite_pragmas(engine: Engine) -> None:
    """Attach the ADR 0003 pragma hook to ``engine``."""
    event.listen(engine, "connect", _set_sqlite_pragmas)


def _set_sqlite_pragmas(
    dbapi_connection: sqlite3.Connection,
    connection_record: object,
) -> None:
    """Set WAL, full synchronous, foreign keys, and the busy timeout.

    The connect event runs before SQLAlchemy begins a transaction.
    ``journal_mode`` and ``foreign_keys`` are ignored inside a transaction,
    which is why they are set here and their results are consumed.
    """
    del connection_record
    cursor = dbapi_connection.cursor()
    try:
        for name, value in _PRAGMAS:
            cursor.execute(f"PRAGMA {name}={value}")
            cursor.fetchall()
    finally:
        cursor.close()
