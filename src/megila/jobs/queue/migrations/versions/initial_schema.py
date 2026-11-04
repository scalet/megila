"""Create the queue tables.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-04

Tables: jobs, steps, chunks, events, artifacts, reviews, qa_checks, profiles,
breakers, workers. The columns live on the SQLAlchemy models in
``megila.jobs.queue.models``. This revision creates that metadata and, on
downgrade, drops it.

The revision has not shipped. Until a second revision exists, a schema
change updates the models and the column contract in
``tests/test_queue_migration.py`` together with this file. After it ships,
a schema change is a new revision, not an edit here.
"""

from __future__ import annotations

from alembic import op

from megila.jobs.queue.models import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create every queue table."""
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    """Drop every queue table. The Alembic version table stays."""
    Base.metadata.drop_all(bind=op.get_bind())
