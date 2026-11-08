"""Create the queue tables.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-04

Tables: jobs, steps, chunks, events, artifacts, reviews, qa_checks, profiles,
breakers, workers.

The DDL below is frozen. It is a literal copy of what the models in
``megila.jobs.queue.models`` produced when this revision was written, not a
call into those models, so a later change to the models cannot change what
this revision creates. A schema change is a new revision. The test
``test_models_match_the_frozen_initial_schema`` fails when the models drift
from this file without one.

The revision has not shipped, so until the first release a schema fix may
still edit this file together with the models and the column contract in
``tests/test_queue_migration.py``.
"""

from __future__ import annotations

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

_CREATE: tuple[str, ...] = (
    """CREATE TABLE profiles (
	id TEXT NOT NULL,
	name TEXT NOT NULL,
	document TEXT NOT NULL,
	created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
	updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
	CONSTRAINT pk_profiles PRIMARY KEY (id),
	CONSTRAINT ck_profiles_ck_profiles_document_json CHECK (json_valid(document) AND json_type(document) = 'object'),
	CONSTRAINT uq_profiles_name UNIQUE (name)
)""",
    """CREATE TABLE workers (
	id TEXT NOT NULL,
	hostname TEXT NOT NULL,
	pid INTEGER,
	started_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
	heartbeat_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
	stopped_at TEXT,
	info TEXT DEFAULT '{}' NOT NULL,
	CONSTRAINT pk_workers PRIMARY KEY (id),
	CONSTRAINT ck_workers_ck_workers_info_json CHECK (json_valid(info) AND json_type(info) = 'object')
)""",
    """CREATE TABLE breakers (
	name TEXT NOT NULL,
	state TEXT DEFAULT 'closed' NOT NULL,
	failure_count INTEGER DEFAULT 0 NOT NULL,
	threshold INTEGER DEFAULT 5 NOT NULL,
	opened_at TEXT,
	retry_after TEXT,
	last_error TEXT,
	error_class TEXT,
	updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
	CONSTRAINT pk_breakers PRIMARY KEY (name),
	CONSTRAINT ck_breakers_ck_breakers_state CHECK (state IN ('closed', 'open', 'half_open')),
	CONSTRAINT ck_breakers_ck_breakers_failure_count CHECK (failure_count >= 0),
	CONSTRAINT ck_breakers_ck_breakers_threshold CHECK (threshold >= 1)
)""",
    """CREATE TABLE jobs (
	id TEXT NOT NULL,
	status TEXT DEFAULT 'pending' NOT NULL,
	payload TEXT NOT NULL,
	priority INTEGER DEFAULT 0 NOT NULL,
	run_after TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
	lease_owner TEXT,
	lease_token TEXT,
	lease_until TEXT,
	heartbeat_at TEXT,
	attempt INTEGER DEFAULT 0 NOT NULL,
	max_attempts INTEGER DEFAULT 5 NOT NULL,
	last_error TEXT,
	error_class TEXT,
	idempotency_key TEXT,
	profile_id TEXT,
	created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
	updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
	CONSTRAINT pk_jobs PRIMARY KEY (id),
	CONSTRAINT ck_jobs_ck_jobs_status CHECK (status IN ('pending', 'leased', 'succeeded', 'dead')),
	CONSTRAINT ck_jobs_ck_jobs_attempt CHECK (attempt >= 0),
	CONSTRAINT ck_jobs_ck_jobs_max_attempts CHECK (max_attempts >= 1),
	CONSTRAINT ck_jobs_ck_jobs_payload_json CHECK (json_valid(payload) AND json_type(payload) = 'object'),
	CONSTRAINT uq_jobs_idempotency_key UNIQUE (idempotency_key),
	CONSTRAINT fk_jobs_profile_id_profiles FOREIGN KEY(profile_id) REFERENCES profiles (id) ON DELETE SET NULL
)""",
    """CREATE INDEX ix_jobs_claim ON jobs (status, priority, run_after, created_at)""",
    """CREATE INDEX ix_jobs_lease ON jobs (status, lease_until)""",
    """CREATE INDEX ix_jobs_profile_id ON jobs (profile_id)""",
    """CREATE TABLE steps (
	id TEXT NOT NULL,
	job_id TEXT NOT NULL,
	name TEXT NOT NULL,
	position INTEGER NOT NULL,
	status TEXT DEFAULT 'pending' NOT NULL,
	attempt INTEGER DEFAULT 0 NOT NULL,
	started_at TEXT,
	finished_at TEXT,
	last_error TEXT,
	error_class TEXT,
	CONSTRAINT pk_steps PRIMARY KEY (id),
	CONSTRAINT ck_steps_ck_steps_status CHECK (status IN ('pending', 'running', 'succeeded', 'failed', 'skipped')),
	CONSTRAINT ck_steps_ck_steps_position CHECK (position >= 0),
	CONSTRAINT ck_steps_ck_steps_attempt CHECK (attempt >= 0),
	CONSTRAINT fk_steps_job_id_jobs FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE CASCADE
)""",
    """CREATE UNIQUE INDEX uq_steps_job_id_position ON steps (job_id, position)""",
    """CREATE UNIQUE INDEX uq_steps_id_job_id ON steps (id, job_id)""",
    """CREATE UNIQUE INDEX uq_steps_job_id_name ON steps (job_id, name)""",
    """CREATE TABLE qa_checks (
	id TEXT NOT NULL,
	job_id TEXT NOT NULL,
	name TEXT NOT NULL,
	status TEXT NOT NULL,
	score FLOAT,
	detail TEXT DEFAULT '{}' NOT NULL,
	created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
	CONSTRAINT pk_qa_checks PRIMARY KEY (id),
	CONSTRAINT ck_qa_checks_ck_qa_checks_status CHECK (status IN ('passed', 'failed', 'skipped')),
	CONSTRAINT ck_qa_checks_ck_qa_checks_detail_json CHECK (json_valid(detail) AND json_type(detail) = 'object'),
	CONSTRAINT fk_qa_checks_job_id_jobs FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE CASCADE
)""",
    """CREATE UNIQUE INDEX uq_qa_checks_job_id_name ON qa_checks (job_id, name)""",
    """CREATE TABLE chunks (
	job_id TEXT NOT NULL,
	step_id TEXT NOT NULL,
	chunk_index INTEGER NOT NULL,
	artifact_path TEXT NOT NULL,
	content_hash TEXT NOT NULL,
	created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
	CONSTRAINT pk_chunks PRIMARY KEY (step_id, chunk_index),
	CONSTRAINT ck_chunks_ck_chunks_chunk_index CHECK (chunk_index >= 0),
	CONSTRAINT ck_chunks_ck_chunks_content_hash CHECK (length(content_hash) = 64 AND content_hash NOT GLOB '*[^0-9a-fA-F]*'),
	CONSTRAINT fk_chunks_step_id_steps FOREIGN KEY(step_id, job_id) REFERENCES steps (id, job_id) ON DELETE CASCADE,
	CONSTRAINT fk_chunks_job_id_jobs FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE CASCADE
)""",
    """CREATE INDEX ix_chunks_job_id ON chunks (job_id)""",
    """CREATE TABLE events (
	id INTEGER NOT NULL,
	job_id TEXT,
	step_id TEXT,
	kind TEXT NOT NULL,
	message TEXT DEFAULT '' NOT NULL,
	payload TEXT DEFAULT '{}' NOT NULL,
	created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
	CONSTRAINT pk_events PRIMARY KEY (id),
	CONSTRAINT ck_events_ck_events_payload_json CHECK (json_valid(payload) AND json_type(payload) = 'object'),
	CONSTRAINT fk_events_job_id_jobs FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE CASCADE,
	CONSTRAINT fk_events_step_id_steps FOREIGN KEY(step_id) REFERENCES steps (id) ON DELETE SET NULL
)""",
    """CREATE INDEX ix_events_job_id_id ON events (job_id, id)""",
    """CREATE TABLE artifacts (
	id TEXT NOT NULL,
	job_id TEXT NOT NULL,
	step_id TEXT,
	name TEXT NOT NULL,
	path TEXT NOT NULL,
	content_hash TEXT,
	media_type TEXT,
	byte_size INTEGER,
	created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
	CONSTRAINT pk_artifacts PRIMARY KEY (id),
	CONSTRAINT ck_artifacts_ck_artifacts_byte_size CHECK (byte_size IS NULL OR byte_size >= 0),
	CONSTRAINT ck_artifacts_ck_artifacts_content_hash CHECK (content_hash IS NULL OR (length(content_hash) = 64 AND content_hash NOT GLOB '*[^0-9a-fA-F]*')),
	CONSTRAINT fk_artifacts_job_id_jobs FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE CASCADE,
	CONSTRAINT fk_artifacts_step_id_steps FOREIGN KEY(step_id) REFERENCES steps (id) ON DELETE SET NULL
)""",
    """CREATE UNIQUE INDEX uq_artifacts_job_id_name ON artifacts (job_id, name)""",
    """CREATE INDEX ix_artifacts_step_id ON artifacts (step_id)""",
    """CREATE TABLE reviews (
	id TEXT NOT NULL,
	job_id TEXT NOT NULL,
	artifact_id TEXT,
	status TEXT DEFAULT 'pending' NOT NULL,
	reviewer TEXT,
	comment TEXT DEFAULT '' NOT NULL,
	created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL,
	CONSTRAINT pk_reviews PRIMARY KEY (id),
	CONSTRAINT ck_reviews_ck_reviews_status CHECK (status IN ('pending', 'approved', 'rejected')),
	CONSTRAINT fk_reviews_job_id_jobs FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE CASCADE,
	CONSTRAINT fk_reviews_artifact_id_artifacts FOREIGN KEY(artifact_id) REFERENCES artifacts (id) ON DELETE SET NULL
)""",
    """CREATE INDEX ix_reviews_artifact_id ON reviews (artifact_id)""",
    """CREATE INDEX ix_reviews_job_id ON reviews (job_id)""",
)

# Children first: reviews points at artifacts, and most tables at jobs.
_DROP: tuple[str, ...] = (
    "qa_checks",
    "reviews",
    "artifacts",
    "events",
    "chunks",
    "steps",
    "jobs",
    "workers",
    "breakers",
    "profiles",
)


def upgrade() -> None:
    """Create every queue table and index."""
    for statement in _CREATE:
        op.execute(statement)


def downgrade() -> None:
    """Drop every queue table. The Alembic version table stays."""
    for table in _DROP:
        op.execute(f"DROP TABLE IF EXISTS {table}")
