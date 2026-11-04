"""Errors raised while opening the queue database."""


class QueueError(Exception):
    """The queue database could not be opened or migrated."""


class DatabaseLocationError(QueueError):
    """The database path is on a filesystem SQLite must not use.

    Network and cloud-sync mounts can corrupt a SQLite file. ADR 0003
    refuses those filesystem types when they can be recognized.
    """
