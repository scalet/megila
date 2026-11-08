"""Alembic upgrade and downgrade of the queue database."""

from __future__ import annotations

import ast
import os
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import MetaData, create_engine, inspect, text
from sqlalchemy.engine import Engine

from megila.config import load_settings
from megila.jobs.queue import (
    Base,
    Chunk,
    Job,
    Step,
    create_db_engine,
    current_revision,
    downgrade_database,
    open_database,
    session_factory,
    upgrade_database,
)
from megila.jobs.queue.migrations.versions import initial_schema

_INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
_HASH = "ab" * 32

# Published column contract of revision 0001_initial. A model change has to
# update this map in the same change as the migration.
EXPECTED_COLUMNS: dict[str, set[str]] = {
    "profiles": {"id", "name", "document", "created_at", "updated_at"},
    "workers": {
        "id",
        "hostname",
        "pid",
        "started_at",
        "heartbeat_at",
        "stopped_at",
        "info",
    },
    "breakers": {
        "name",
        "state",
        "failure_count",
        "threshold",
        "opened_at",
        "retry_after",
        "last_error",
        "error_class",
        "updated_at",
    },
    "jobs": {
        "id",
        "status",
        "payload",
        "priority",
        "run_after",
        "lease_owner",
        "lease_token",
        "lease_until",
        "heartbeat_at",
        "attempt",
        "max_attempts",
        "last_error",
        "error_class",
        "idempotency_key",
        "profile_id",
        "created_at",
        "updated_at",
    },
    "steps": {
        "id",
        "job_id",
        "name",
        "position",
        "status",
        "attempt",
        "started_at",
        "finished_at",
        "last_error",
        "error_class",
    },
    "chunks": {
        "job_id",
        "step_id",
        "chunk_index",
        "artifact_path",
        "content_hash",
        "created_at",
    },
    "events": {
        "id",
        "job_id",
        "step_id",
        "kind",
        "message",
        "payload",
        "created_at",
    },
    "artifacts": {
        "id",
        "job_id",
        "step_id",
        "name",
        "path",
        "content_hash",
        "media_type",
        "byte_size",
        "created_at",
    },
    "reviews": {
        "id",
        "job_id",
        "artifact_id",
        "status",
        "reviewer",
        "comment",
        "created_at",
    },
    "qa_checks": {
        "id",
        "job_id",
        "name",
        "status",
        "score",
        "detail",
        "created_at",
    },
}


@pytest.fixture
def database(tmp_path: Path) -> Path:
    return tmp_path / "megila.sqlite3"


@pytest.fixture
def engine(database: Path) -> Iterator[Engine]:
    upgrade_database(database)
    opened = create_db_engine(database)
    try:
        yield opened
    finally:
        opened.dispose()


def test_revision_module_is_the_initial_schema() -> None:
    assert initial_schema.revision == "0001_initial"
    assert initial_schema.down_revision is None
    script = Path(initial_schema.__file__).resolve()
    assert script.is_file()
    assert script.parent.name == "versions"


def test_upgrade_matches_models_and_the_column_contract(
    engine: Engine, database: Path
) -> None:
    reflected = MetaData()
    reflected.reflect(engine)
    assert set(reflected.tables) - {"alembic_version"} == set(EXPECTED_COLUMNS)
    for name, columns in EXPECTED_COLUMNS.items():
        model_columns = set(Base.metadata.tables[name].columns.keys())
        assert model_columns == columns
        got = reflected.tables[name]
        assert set(got.columns.keys()) == columns
        for column in Base.metadata.tables[name].columns:
            reflected_column = got.columns[column.name]
            assert reflected_column.nullable == column.nullable
            assert reflected_column.primary_key == column.primary_key
    assert current_revision(database) == "0001_initial"


def test_schema_sql_keeps_the_queue_contract(engine: Engine) -> None:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT sql FROM sqlite_master "
                "WHERE sql IS NOT NULL AND type IN ('table', 'index')"
            )
        ).scalars()
        sql = "\n".join(rows)
    for snippet in (
        "ix_jobs_claim",
        "ix_jobs_lease",
        "idempotency_key",
        "lease_until",
        "heartbeat_at",
        "run_after",
        "error_class",
        "json_valid(payload)",
        "'dead'",
        "content_hash",
        "ck_chunks_content_hash",
        "fk_jobs_profile_id_profiles",
    ):
        assert snippet in sql


def test_raw_insert_uses_server_defaults(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO jobs (id, payload) VALUES ('job-1', '{}')")
        )
        row = connection.execute(
            text(
                "SELECT status, priority, attempt, max_attempts, run_after, "
                "created_at, updated_at FROM jobs WHERE id = 'job-1'"
            )
        ).one()
    assert row.status == "pending"
    assert row.priority == 0
    assert row.attempt == 0
    assert row.max_attempts == 5
    assert _INSTANT.fullmatch(row.run_after)
    assert _INSTANT.fullmatch(row.created_at)
    assert _INSTANT.fullmatch(row.updated_at)


def test_upgrade_is_idempotent(database: Path, engine: Engine) -> None:
    del engine
    upgrade_database(database)
    assert current_revision(database) == "0001_initial"


def test_downgrade_drops_populated_tables_and_upgrade_recreates_them(
    database: Path,
) -> None:
    upgrade_database(database)
    opened = create_db_engine(database)
    factory = session_factory(opened)
    with factory.begin() as session:
        job = Job(payload="{}")
        session.add(job)
        session.flush()
        step = Step(job_id=job.id, name="transcribe", position=0)
        session.add(step)
        session.flush()
        session.add(
            Chunk(
                job_id=job.id,
                step_id=step.id,
                chunk_index=0,
                artifact_path="/tmp/piece-0",
                content_hash=_HASH,
            )
        )
    opened.dispose()

    downgrade_database(database)
    assert current_revision(database) is None
    leftover = create_db_engine(database)
    try:
        names = set(inspect(leftover).get_table_names())
    finally:
        leftover.dispose()
    assert "jobs" not in names
    assert "chunks" not in names
    assert "steps" not in names

    upgrade_database(database)
    assert current_revision(database) == "0001_initial"
    restored = create_db_engine(database)
    try:
        with restored.connect() as connection:
            count = connection.execute(text("SELECT count(*) FROM jobs")).scalar_one()
    finally:
        restored.dispose()
    assert count == 0


def test_offline_upgrade_prints_sql_without_creating_the_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "subdir" / "megila.sqlite3"
    upgrade_database(path, sql=True)
    captured = capsys.readouterr().out
    assert "CREATE TABLE jobs" in captured
    assert "CREATE TABLE chunks" in captured
    assert not path.exists()


def test_downgrade_of_a_missing_file_fails(tmp_path: Path) -> None:
    missing = tmp_path / "missing.sqlite3"
    with pytest.raises(FileNotFoundError):
        downgrade_database(missing)


def test_open_database_migrates_and_sets_pragmas(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for key in list(os.environ):
        if key.lower().startswith("megila_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    data_dir = tmp_path / "data"
    settings = load_settings(config_file=tmp_path / "missing.toml", data_dir=data_dir)
    engine = open_database(settings)
    try:
        with engine.connect() as connection:
            assert connection.execute(text("PRAGMA journal_mode")).scalar_one() == "wal"
            assert connection.execute(text("PRAGMA synchronous")).scalar_one() == 2
            assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
            assert connection.execute(text("PRAGMA busy_timeout")).scalar_one() == 5000
            names = set(inspect(connection).get_table_names())
    finally:
        engine.dispose()
    assert "jobs" in names
    assert current_revision(data_dir / "megila.sqlite3") == "0001_initial"


def test_current_revision_of_a_missing_file_does_not_create_it(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "absent" / "megila.sqlite3"
    assert current_revision(missing) is None
    assert not missing.exists()
    assert not missing.parent.exists()


def _schema_sql(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL")
        ).scalars()
        return {" ".join(row.split()) for row in rows}


def test_models_match_the_frozen_initial_schema(engine: Engine, tmp_path: Path) -> None:
    """A model change without a new revision fails here."""
    fresh = create_engine(f"sqlite:///{tmp_path / 'from-models.sqlite3'}")
    try:
        Base.metadata.create_all(fresh)
        from_models = _schema_sql(fresh)
    finally:
        fresh.dispose()
    from_revision = _schema_sql(engine)
    assert from_revision - {s for s in from_revision if "alembic_version" in s} == (
        from_models
    )


def test_initial_revision_does_not_depend_on_the_models() -> None:
    tree = ast.parse(Path(initial_schema.__file__).read_text(encoding="utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    called = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert not {m for m in imported if m.startswith("megila")}
    assert not {"create_all", "drop_all"} & called
