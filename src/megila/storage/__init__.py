"""Media storage.

Local files are the default. An optional rclone backup can plug in behind the
same boundary. ``atomic_write`` replaces a file without leaving a partial write.
"""

from megila.storage.atomic import atomic_write

__all__ = ["atomic_write"]
