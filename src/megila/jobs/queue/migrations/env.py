"""Alembic environment for the Megila queue database.

Alembic loads this file by path. The migration body lives in
:func:`megila.jobs.queue.migrate.run_migrations` so the same pragmas used by
:func:`megila.jobs.queue.engine.create_db_engine` apply here.
"""

from megila.jobs.queue.migrate import run_migrations

run_migrations()
