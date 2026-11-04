"""Durable SQLite queue.

The database file is ``<data_dir>/megila.sqlite3``. Every connection uses
WAL, ``synchronous=FULL``, foreign keys and a 5000 ms busy timeout.
:func:`open_database` migrates the file to the current revision.

Lease claim, heartbeat and the move to ``dead`` are not in this package yet.
The columns they need are on :class:`~megila.jobs.queue.models.Job`.
"""

from megila.jobs.queue.engine import (
    BUSY_TIMEOUT_MS,
    DATABASE_FILENAME,
    create_db_engine,
    database_path,
    prepare_database_path,
    session_factory,
    sqlite_url,
)
from megila.jobs.queue.errors import DatabaseLocationError, QueueError
from megila.jobs.queue.filesystem import REFUSED_FILESYSTEM_TYPES
from megila.jobs.queue.migrate import (
    current_revision,
    downgrade_database,
    open_database,
    upgrade_database,
)
from megila.jobs.queue.models import (
    BREAKER_STATES,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_PRIORITY,
    JOB_STATUSES,
    QA_STATUSES,
    REVIEW_STATUSES,
    STEP_STATUSES,
    Artifact,
    Base,
    Breaker,
    Chunk,
    Event,
    Job,
    ProfileRecord,
    QaCheck,
    Review,
    Step,
    Worker,
    new_id,
    utc_now,
)

__all__ = [
    "BREAKER_STATES",
    "BUSY_TIMEOUT_MS",
    "DATABASE_FILENAME",
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_PRIORITY",
    "JOB_STATUSES",
    "QA_STATUSES",
    "REFUSED_FILESYSTEM_TYPES",
    "REVIEW_STATUSES",
    "STEP_STATUSES",
    "Artifact",
    "Base",
    "Breaker",
    "Chunk",
    "DatabaseLocationError",
    "Event",
    "Job",
    "ProfileRecord",
    "QaCheck",
    "QueueError",
    "Review",
    "Step",
    "Worker",
    "create_db_engine",
    "current_revision",
    "database_path",
    "downgrade_database",
    "new_id",
    "open_database",
    "prepare_database_path",
    "session_factory",
    "sqlite_url",
    "upgrade_database",
    "utc_now",
]
