"""Two processes write the queue database at the same time."""

from __future__ import annotations

import multiprocessing
import traceback
from pathlib import Path

import pytest
from sqlalchemy import text

from megila.jobs.queue import (
    Job,
    create_db_engine,
    session_factory,
    upgrade_database,
)

_WRITES = 20


def _write_jobs(database: str, worker: str, count: int) -> None:
    """Insert ``count`` jobs. A traceback is left beside the database on failure."""
    log_path = Path(database).with_name(f"{Path(database).stem}.{worker}.log")
    try:
        engine = create_db_engine(Path(database))
        try:
            factory = session_factory(engine)
            for index in range(count):
                with factory.begin() as session:
                    session.add(
                        Job(
                            id=f"{worker}-{index}",
                            payload="{}",
                            idempotency_key=f"{worker}-{index}",
                        )
                    )
        finally:
            engine.dispose()
    except Exception:
        log_path.write_text(traceback.format_exc(), encoding="utf-8")
        raise


def test_two_processes_write_at_once(tmp_path: Path) -> None:
    database = tmp_path / "megila.sqlite3"
    upgrade_database(database)
    context = multiprocessing.get_context("spawn")
    processes = [
        context.Process(target=_write_jobs, args=(str(database), worker, _WRITES))
        for worker in ("a", "b")
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(60)
        if process.is_alive():
            process.terminate()
            process.join(10)

    failures: list[str] = []
    for worker, process in zip(("a", "b"), processes, strict=True):
        log_path = database.with_name(f"{database.stem}.{worker}.log")
        detail = log_path.read_text(encoding="utf-8") if log_path.is_file() else ""
        if process.exitcode != 0:
            failures.append(f"{worker} exit {process.exitcode}\n{detail}")
    if failures:
        pytest.fail("\n".join(failures))

    engine = create_db_engine(database)
    try:
        with engine.connect() as connection:
            rows = connection.execute(text("SELECT id FROM jobs")).scalars().all()
    finally:
        engine.dispose()
    assert len(rows) == _WRITES * 2
    assert sum(row.startswith("a-") for row in rows) == _WRITES
    assert sum(row.startswith("b-") for row in rows) == _WRITES
