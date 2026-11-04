"""Typed schema for the local queue.

The tables are ``jobs``, ``steps``, ``chunks``, ``events``, ``artifacts``,
``reviews``, ``qa_checks``, ``profiles``, ``breakers`` and ``workers``.
Column meanings follow ADR 0003: a job is ``pending``, ``leased``,
``succeeded`` or ``dead``. ``dead`` is the dead-letter queue. There is no
second database.

Instants are UTC text, ``YYYY-MM-DDTHH:MM:SS.mmmZ``. The format is fixed
width, so a text comparison matches chronological order. The application
and the SQLite ``strftime`` default both use millisecond precision.

Claim, heartbeat and the transition into ``dead`` are not implemented here.
The columns they need are on ``jobs`` so a later ``UPDATE ... RETURNING``
can run without another migration.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Text,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql.elements import TextClause

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# ADR 0003. ``dead`` is the dead-letter queue.
JOB_STATUSES: tuple[str, ...] = ("pending", "leased", "succeeded", "dead")
STEP_STATUSES: tuple[str, ...] = (
    "pending",
    "running",
    "succeeded",
    "failed",
    "skipped",
)
REVIEW_STATUSES: tuple[str, ...] = ("pending", "approved", "rejected")
QA_STATUSES: tuple[str, ...] = ("passed", "failed", "skipped")
BREAKER_STATES: tuple[str, ...] = ("closed", "open", "half_open")

# ADR 0003: five failures move the job to ``dead``.
DEFAULT_MAX_ATTEMPTS = 5
# Higher values are claimed first. Zero is the ordinary priority.
DEFAULT_PRIORITY = 0


def utc_now() -> str:
    """Return the current UTC time as ``YYYY-MM-DDTHH:MM:SS.mmmZ``."""
    moment = datetime.now(UTC)
    millis = moment.microsecond // 1000
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


def new_id() -> str:
    """Return a new random id (UUID 4, canonical text)."""
    return str(uuid.uuid4())


def _sql_utc_now() -> TextClause:
    """SQLite default that matches :func:`utc_now` (millisecond, ``Z``)."""
    return text("(strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))")


def _choices(column: str, values: tuple[str, ...]) -> str:
    rendered = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({rendered})"


def _json_object(column: str) -> str:
    return f"json_valid({column}) AND json_type({column}) = 'object'"


class Base(DeclarativeBase):
    """Declarative base for the queue schema."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class ProfileRecord(Base):
    """A stored profile snapshot.

    ``document`` is the exported profile (prompts, language, toggles, provider
    name). It has no API key. The TOML file remains the place a person edits;
    this row is what a job can point at.
    """

    __tablename__ = "profiles"
    __table_args__ = (
        CheckConstraint(_json_object("document"), name="ck_profiles_document_json"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    document: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=utc_now, server_default=_sql_utc_now()
    )
    updated_at: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=_sql_utc_now(),
    )

    jobs: Mapped[list[Job]] = relationship(back_populates="profile")


class Worker(Base):
    """A process that may hold a lease.

    ``jobs.lease_owner`` stores this id as text and is not a foreign key.
    The job stays readable if the worker row is removed.
    """

    __tablename__ = "workers"
    __table_args__ = (
        CheckConstraint(_json_object("info"), name="ck_workers_info_json"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    hostname: Mapped[str] = mapped_column(Text, nullable=False)
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=utc_now, server_default=_sql_utc_now()
    )
    heartbeat_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=utc_now, server_default=_sql_utc_now()
    )
    stopped_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    info: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}", server_default=text("'{}'")
    )


class Breaker(Base):
    """Circuit-breaker state for a named dependency.

    ``name`` is a stable id such as ``provider:local`` or ``stage:transcribe``.
    ``state`` is ``closed``, ``open`` or ``half_open``. ``retry_after`` is the
    instant an open breaker may be tried again. This table stores the state.
    It does not open or close the breaker.
    """

    __tablename__ = "breakers"
    __table_args__ = (
        CheckConstraint(_choices("state", BREAKER_STATES), name="ck_breakers_state"),
        CheckConstraint("failure_count >= 0", name="ck_breakers_failure_count"),
        CheckConstraint("threshold >= 1", name="ck_breakers_threshold"),
    )

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    state: Mapped[str] = mapped_column(
        Text, nullable=False, default="closed", server_default=text("'closed'")
    )
    failure_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    threshold: Mapped[int] = mapped_column(
        Integer, nullable=False, default=DEFAULT_MAX_ATTEMPTS, server_default=text("5")
    )
    opened_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_after: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_class: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=_sql_utc_now(),
    )


class Job(Base):
    """One item in the resumable queue.

    ``status`` moves ``pending`` → ``leased`` → ``succeeded``, or to ``dead``
    when ``attempt`` reaches ``max_attempts``. ``dead`` is the dead-letter
    queue: the payload, the error and the chunks stay.

    ``run_after`` holds the job until that UTC instant. ``priority`` breaks
    ties; a higher number is claimed first. ``lease_owner``, ``lease_token``,
    ``lease_until`` and ``heartbeat_at`` are the lease. ``attempt`` counts
    failures and expired leases. ``error_class`` is a stable failure category
    (for example ``DiskFull``), and ``last_error`` is the human-readable text.

    ``payload`` is a JSON object: paths and the two prompts. It must not
    contain an API key. ``idempotency_key`` identifies the same input (media,
    both prompts, encode profile). SQLite allows many NULL keys; a real key
    is unique.
    """

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(_choices("status", JOB_STATUSES), name="ck_jobs_status"),
        CheckConstraint("attempt >= 0", name="ck_jobs_attempt"),
        CheckConstraint("max_attempts >= 1", name="ck_jobs_max_attempts"),
        CheckConstraint(_json_object("payload"), name="ck_jobs_payload_json"),
        Index("ix_jobs_claim", "status", "priority", "run_after", "created_at"),
        Index("ix_jobs_lease", "status", "lease_until"),
        Index("ix_jobs_profile_id", "profile_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="pending", server_default=text("'pending'")
    )
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=DEFAULT_PRIORITY,
        server_default=text("0"),
    )
    run_after: Mapped[str] = mapped_column(
        Text, nullable=False, default=utc_now, server_default=_sql_utc_now()
    )
    lease_owner: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_until: Mapped[str | None] = mapped_column(Text, nullable=True)
    heartbeat_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=DEFAULT_MAX_ATTEMPTS,
        server_default=text("5"),
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_class: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(
        Text, nullable=True, unique=True
    )
    profile_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey(
            "profiles.id",
            name="fk_jobs_profile_id_profiles",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=utc_now, server_default=_sql_utc_now()
    )
    updated_at: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=_sql_utc_now(),
    )

    profile: Mapped[ProfileRecord | None] = relationship(back_populates="jobs")
    steps: Mapped[list[Step]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Step.position",
    )
    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    events: Mapped[list[Event]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    artifacts: Mapped[list[Artifact]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    reviews: Mapped[list[Review]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    qa_checks: Mapped[list[QaCheck]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Step(Base):
    """One named stage of a job.

    ``name`` is free text (``transcribe``, ``encode``, ``summary``, ...).
    ``position`` is the order inside the job. Both are unique per job.
    """

    __tablename__ = "steps"
    __table_args__ = (
        CheckConstraint(_choices("status", STEP_STATUSES), name="ck_steps_status"),
        CheckConstraint("position >= 0", name="ck_steps_position"),
        CheckConstraint("attempt >= 0", name="ck_steps_attempt"),
        Index("uq_steps_job_id_name", "job_id", "name", unique=True),
        Index("uq_steps_job_id_position", "job_id", "position", unique=True),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("jobs.id", name="fk_steps_job_id_jobs", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="pending", server_default=text("'pending'")
    )
    attempt: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    started_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    finished_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_class: Mapped[str | None] = mapped_column(Text, nullable=True)

    job: Mapped[Job] = relationship(back_populates="steps")
    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="step",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Chunk.chunk_index",
    )
    events: Mapped[list[Event]] = relationship(back_populates="step")
    artifacts: Mapped[list[Artifact]] = relationship(back_populates="step")


class Chunk(Base):
    """A confirmed piece of a long step.

    ADR 0003 calls this the checkpoint. The primary key is
    ``(step_id, chunk_index)``, one row per piece of a step.
    ``artifact_path`` is the final file. ``content_hash`` is the SHA-256 hex
    digest of that file (64 hexadecimal characters). ``job_id`` is repeated
    so a resume can list the pieces of a job without joining.
    """

    __tablename__ = "chunks"
    __table_args__ = (
        CheckConstraint("chunk_index >= 0", name="ck_chunks_chunk_index"),
        CheckConstraint(
            "length(content_hash) = 64 AND content_hash NOT GLOB '*[^0-9a-fA-F]*'",
            name="ck_chunks_content_hash",
        ),
        Index("ix_chunks_job_id", "job_id"),
    )

    job_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("jobs.id", name="fk_chunks_job_id_jobs", ondelete="CASCADE"),
        nullable=False,
    )
    step_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("steps.id", name="fk_chunks_step_id_steps", ondelete="CASCADE"),
        primary_key=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    artifact_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=utc_now, server_default=_sql_utc_now()
    )

    job: Mapped[Job] = relationship(back_populates="chunks")
    step: Mapped[Step] = relationship(back_populates="chunks")


class Event(Base):
    """Append-only note about a job or a step.

    ``kind`` is free text (``enqueued``, ``claimed``, ``heartbeat``,
    ``checkpoint``, ``failed``, ``dead``, ``replayed``, ...). ``payload`` is
    a JSON object. ``job_id`` may be NULL for a process-level note.
    """

    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint(_json_object("payload"), name="ck_events_payload_json"),
        Index("ix_events_job_id_id", "job_id", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("jobs.id", name="fk_events_job_id_jobs", ondelete="CASCADE"),
        nullable=True,
    )
    step_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("steps.id", name="fk_events_step_id_steps", ondelete="SET NULL"),
        nullable=True,
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    payload: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}", server_default=text("'{}'")
    )
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=utc_now, server_default=_sql_utc_now()
    )

    job: Mapped[Job | None] = relationship(back_populates="events")
    step: Mapped[Step | None] = relationship(back_populates="events")


class Artifact(Base):
    """A file the job produced (``transcript.json``, ``video.mp4``, ...).

    The bytes stay on disk. This row records the path, the size and, when
    known, the SHA-256 hex digest.
    """

    __tablename__ = "artifacts"
    __table_args__ = (
        CheckConstraint(
            "byte_size IS NULL OR byte_size >= 0",
            name="ck_artifacts_byte_size",
        ),
        CheckConstraint(
            "content_hash IS NULL OR ("
            "length(content_hash) = 64 "
            "AND content_hash NOT GLOB '*[^0-9a-fA-F]*')",
            name="ck_artifacts_content_hash",
        ),
        Index("uq_artifacts_job_id_name", "job_id", "name", unique=True),
        Index("ix_artifacts_step_id", "step_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("jobs.id", name="fk_artifacts_job_id_jobs", ondelete="CASCADE"),
        nullable=False,
    )
    step_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("steps.id", name="fk_artifacts_step_id_steps", ondelete="SET NULL"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=utc_now, server_default=_sql_utc_now()
    )

    job: Mapped[Job] = relationship(back_populates="artifacts")
    step: Mapped[Step | None] = relationship(back_populates="artifacts")
    reviews: Mapped[list[Review]] = relationship(back_populates="artifact")


class Review(Base):
    """A human decision about a job, optionally about one artifact."""

    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint(_choices("status", REVIEW_STATUSES), name="ck_reviews_status"),
        Index("ix_reviews_job_id", "job_id"),
        Index("ix_reviews_artifact_id", "artifact_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("jobs.id", name="fk_reviews_job_id_jobs", ondelete="CASCADE"),
        nullable=False,
    )
    artifact_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey(
            "artifacts.id",
            name="fk_reviews_artifact_id_artifacts",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="pending", server_default=text("'pending'")
    )
    reviewer: Mapped[str | None] = mapped_column(Text, nullable=True)
    comment: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=utc_now, server_default=_sql_utc_now()
    )

    job: Mapped[Job] = relationship(back_populates="reviews")
    artifact: Mapped[Artifact | None] = relationship(back_populates="reviews")


class QaCheck(Base):
    """One quality measurement for a job.

    ``name`` is unique per job (``vmaf``, ``summary``, ...). ``score`` is
    optional because a pass/fail gate may not have a number. ``detail`` is a
    JSON object.
    """

    __tablename__ = "qa_checks"
    __table_args__ = (
        CheckConstraint(_choices("status", QA_STATUSES), name="ck_qa_checks_status"),
        CheckConstraint(_json_object("detail"), name="ck_qa_checks_detail_json"),
        Index("uq_qa_checks_job_id_name", "job_id", "name", unique=True),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("jobs.id", name="fk_qa_checks_job_id_jobs", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    detail: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}", server_default=text("'{}'")
    )
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=utc_now, server_default=_sql_utc_now()
    )

    job: Mapped[Job] = relationship(back_populates="qa_checks")
