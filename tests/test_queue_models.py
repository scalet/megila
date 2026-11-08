"""Unit tests for the queue ORM models."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from megila.jobs.queue import (
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_PRIORITY,
    JOB_STATUSES,
    Artifact,
    Breaker,
    Chunk,
    Event,
    Job,
    ProfileRecord,
    QaCheck,
    Review,
    Step,
    Worker,
    create_db_engine,
    new_id,
    session_factory,
    upgrade_database,
    utc_now,
)

_INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
_HASH = "cd" * 32


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    path = tmp_path / "megila.sqlite3"
    upgrade_database(path)
    engine = create_db_engine(path)
    db = session_factory(engine)()
    try:
        yield db
    finally:
        db.rollback()
        db.close()
        engine.dispose()


def _count(session: Session, table: str) -> int:
    value = session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
    assert isinstance(value, int)
    return value


def test_new_id_and_utc_now() -> None:
    assert _INSTANT.fullmatch(utc_now())
    first = new_id()
    second = new_id()
    assert first != second
    assert len(first) == 36


def test_job_round_trip_keeps_queue_fields(session: Session) -> None:
    job = Job(
        payload='{"video_prompt": "a", "summary_prompt": "b"}',
        status="leased",
        priority=3,
        run_after="2026-11-04T00:00:00.000Z",
        lease_owner="worker-1",
        lease_token="token-1",
        lease_until="2026-11-04T00:02:00.000Z",
        heartbeat_at="2026-11-04T00:00:20.000Z",
        attempt=2,
        max_attempts=5,
        last_error="disk full",
        error_class="DiskFull",
        idempotency_key="media-1",
    )
    session.add(job)
    session.commit()
    loaded = session.get(Job, job.id)
    assert loaded is not None
    assert loaded.status == "leased"
    assert loaded.priority == 3
    assert loaded.run_after == "2026-11-04T00:00:00.000Z"
    assert loaded.lease_owner == "worker-1"
    assert loaded.lease_token == "token-1"
    assert loaded.lease_until == "2026-11-04T00:02:00.000Z"
    assert loaded.heartbeat_at == "2026-11-04T00:00:20.000Z"
    assert loaded.attempt == 2
    assert loaded.max_attempts == 5
    assert loaded.last_error == "disk full"
    assert loaded.error_class == "DiskFull"
    assert loaded.idempotency_key == "media-1"
    assert _INSTANT.fullmatch(loaded.created_at)
    assert _INSTANT.fullmatch(loaded.updated_at)
    loaded.status = "dead"
    session.commit()
    dead = session.get(Job, job.id)
    assert dead is not None
    assert dead.status == "dead"


def test_job_defaults_match_the_adr(session: Session) -> None:
    job = Job(payload="{}")
    session.add(job)
    session.commit()
    assert job.status == "pending"
    assert job.priority == DEFAULT_PRIORITY
    assert job.attempt == 0
    assert job.max_attempts == DEFAULT_MAX_ATTEMPTS
    assert job.lease_owner is None
    assert job.lease_token is None
    assert job.lease_until is None
    assert "dead" in JOB_STATUSES


def test_null_idempotency_keys_do_not_collide(session: Session) -> None:
    session.add(Job(payload="{}"))
    session.add(Job(payload="{}"))
    session.commit()
    assert _count(session, "jobs") == 2


def test_duplicate_idempotency_key_is_rejected(session: Session) -> None:
    session.add(Job(payload="{}", idempotency_key="same"))
    session.commit()
    session.add(Job(payload="{}", idempotency_key="same"))
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("status", "running"),
        ("payload", "[]"),
        ("payload", "not-json"),
        ("attempt", -1),
        ("max_attempts", 0),
    ],
)
def test_job_checks_reject_bad_values(
    session: Session, column: str, value: object
) -> None:
    job = Job(payload="{}")
    setattr(job, column, value)
    session.add(job)
    with pytest.raises(IntegrityError):
        session.commit()


def test_relationships_and_chunk_identity(session: Session) -> None:
    profile = ProfileRecord(name="default", document='{"language": "pt-BR"}')
    job = Job(payload="{}", profile=profile, lease_owner="not-a-worker-row")
    step = Step(job=job, name="transcribe", position=0)
    chunk = Chunk(
        job=job,
        step=step,
        chunk_index=0,
        artifact_path="/tmp/piece-0",
        content_hash=_HASH,
    )
    artifact = Artifact(
        job=job,
        step=step,
        name="transcript.json",
        path="/tmp/transcript.json",
        content_hash=_HASH,
        media_type="application/json",
        byte_size=12,
    )
    review = Review(job=job, artifact=artifact, status="approved", comment="ok")
    check = QaCheck(job=job, name="summary", status="passed", score=1.0, detail="{}")
    event = Event(job=job, step=step, kind="checkpoint", message="piece 0")
    session.add_all([profile, job, step, chunk, artifact, review, check, event])
    session.commit()

    loaded = session.scalars(select(Job)).one()
    assert loaded.profile is not None
    assert loaded.profile.name == "default"
    assert [item.name for item in loaded.steps] == ["transcribe"]
    assert loaded.steps[0].chunks[0].content_hash == _HASH
    assert loaded.artifacts[0].name == "transcript.json"
    assert loaded.reviews[0].status == "approved"
    assert loaded.qa_checks[0].score == 1.0
    assert loaded.events[0].kind == "checkpoint"
    assert loaded.lease_owner == "not-a-worker-row"


def test_missing_job_cannot_own_a_step(session: Session) -> None:
    session.add(Step(job_id="missing", name="transcribe", position=0))
    with pytest.raises(IntegrityError):
        session.commit()


def test_duplicate_chunk_and_bad_hash_are_rejected(session: Session) -> None:
    job = Job(payload="{}")
    step = Step(job=job, name="encode", position=1)
    session.add_all([job, step])
    session.flush()
    insert_chunk = text(
        "INSERT INTO chunks ("
        "job_id, step_id, chunk_index, artifact_path, content_hash"
        ") VALUES (:job_id, :step_id, :chunk_index, :path, :content_hash)"
    )
    session.execute(
        insert_chunk,
        {
            "job_id": job.id,
            "step_id": step.id,
            "chunk_index": 1,
            "path": "/tmp/a",
            "content_hash": _HASH,
        },
    )
    session.commit()
    with pytest.raises(IntegrityError):
        session.execute(
            insert_chunk,
            {
                "job_id": job.id,
                "step_id": step.id,
                "chunk_index": 1,
                "path": "/tmp/b",
                "content_hash": _HASH,
            },
        )
    session.rollback()
    with pytest.raises(IntegrityError):
        session.execute(
            insert_chunk,
            {
                "job_id": job.id,
                "step_id": step.id,
                "chunk_index": 2,
                "path": "/tmp/c",
                "content_hash": "abcd",
            },
        )


def test_deleting_a_job_removes_dependents(session: Session) -> None:
    job = Job(payload="{}")
    step = Step(job=job, name="transcribe", position=0)
    artifact = Artifact(job=job, step=step, name="video.mp4", path="/tmp/video.mp4")
    session.add_all(
        [
            job,
            step,
            Chunk(
                job=job,
                step=step,
                chunk_index=0,
                artifact_path="/tmp/piece",
                content_hash=_HASH,
            ),
            artifact,
            Event(job=job, step=step, kind="claimed"),
            Review(job=job, artifact=artifact),
            QaCheck(job=job, name="vmaf", status="failed", detail='{"reason": "low"}'),
        ]
    )
    session.commit()
    session.execute(text("DELETE FROM jobs WHERE id = :id"), {"id": job.id})
    session.commit()
    for table in ("steps", "chunks", "events", "artifacts", "reviews", "qa_checks"):
        assert _count(session, table) == 0


def test_deleting_a_profile_keeps_the_job(session: Session) -> None:
    profile = ProfileRecord(name="aula", document="{}")
    job = Job(payload="{}", profile=profile)
    session.add(job)
    session.commit()
    session.execute(text("DELETE FROM profiles WHERE id = :id"), {"id": profile.id})
    session.commit()
    session.expire_all()
    loaded = session.get(Job, job.id)
    assert loaded is not None
    assert loaded.profile_id is None
    assert _count(session, "jobs") == 1


def test_step_name_is_unique_per_job(session: Session) -> None:
    job = Job(payload="{}")
    session.add(Step(job=job, name="summary", position=0))
    session.commit()
    session.add(Step(job=job, name="summary", position=1))
    with pytest.raises(IntegrityError):
        session.commit()


def test_worker_breaker_and_event_defaults(session: Session) -> None:
    worker = Worker(hostname="local")
    breaker = Breaker(name="provider:local")
    event = Event(kind="process")
    session.add_all([worker, breaker, event])
    session.commit()
    assert worker.pid is None
    assert worker.info == "{}"
    assert _INSTANT.fullmatch(worker.heartbeat_at)
    assert breaker.state == "closed"
    assert breaker.failure_count == 0
    assert breaker.threshold == DEFAULT_MAX_ATTEMPTS
    assert event.job_id is None
    assert event.payload == "{}"
    second = Event(kind="process")
    session.add(second)
    session.commit()
    assert second.id != event.id


def test_breaker_and_review_status_checks(session: Session) -> None:
    session.add(Breaker(name="stage:transcribe", state="open"))
    session.commit()
    session.add(Breaker(name="stage:encode", state="broken"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    job = Job(payload="{}")
    session.add(Review(job=job, status="maybe"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_qa_name_is_unique_and_artifact_hash_is_optional(session: Session) -> None:
    job = Job(payload="{}")
    session.add(QaCheck(job=job, name="summary", status="skipped"))
    session.add(Artifact(job=job, name="summary.txt", path="/tmp/summary.txt"))
    session.commit()
    session.add(QaCheck(job=job, name="summary", status="passed"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    session.add(
        Artifact(job=job, name="other.txt", path="/tmp/other.txt", byte_size=-1)
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_chunk_cannot_pair_a_step_with_another_jobs_id(session: Session) -> None:
    first = Job(payload="{}")
    second = Job(payload="{}")
    step = Step(job=first, name="encode", position=0)
    session.add_all([first, second, step])
    session.flush()
    insert_chunk = text(
        "INSERT INTO chunks ("
        "job_id, step_id, chunk_index, artifact_path, content_hash"
        ") VALUES (:job_id, :step_id, 0, '/tmp/a', :content_hash)"
    )
    session.execute(
        insert_chunk,
        {"job_id": first.id, "step_id": step.id, "content_hash": _HASH},
    )
    session.commit()
    with pytest.raises(IntegrityError):
        session.execute(
            text(
                "INSERT INTO chunks ("
                "job_id, step_id, chunk_index, artifact_path, content_hash"
                ") VALUES (:job_id, :step_id, 1, '/tmp/b', :content_hash)"
            ),
            {"job_id": second.id, "step_id": step.id, "content_hash": _HASH},
        )
