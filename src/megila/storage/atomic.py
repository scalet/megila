"""Replace one file without publishing a partial write.

The write lands in a temporary file in the same directory, that file is
fsynced, ``os.replace`` publishes it, and the directory is fsynced. A crash
before the rename leaves the destination unchanged. ``os.replace`` is atomic
on the same filesystem, which the same-directory temporary file guarantees.
"""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path


def atomic_write(path: str | Path, data: bytes) -> None:
    """Atomically replace ``path`` with ``data``.

    Args:
        path: Destination. A symlink is replaced; the write does not follow it.
        data: Complete contents. Strings are rejected so a partial encode
            cannot be confused with the payload.

    Raises:
        TypeError: ``data`` is not ``bytes``.
        IsADirectoryError: ``path`` is an existing directory.
        OSError: The temporary file could not be written or published.
    """
    if not isinstance(data, bytes):
        message = "data must be bytes"
        raise TypeError(message)
    destination = Path(path)
    if (
        destination.exists()
        and not destination.is_file()
        and not destination.is_symlink()
    ):
        raise IsADirectoryError(destination)
    directory = destination.parent
    directory.mkdir(parents=True, exist_ok=True)
    mode = _mode_for(destination)
    prefix = f".{destination.name}."
    if len(prefix) > 80:
        prefix = ".megila."

    tmp_path: Path | None = None
    published = False
    try:
        fd, tmp_name = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=directory)
        tmp_path = Path(tmp_name)
        try:
            _write_all(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, destination)
        published = True
        _fsync_directory(directory)
    finally:
        if tmp_path is not None and not published:
            tmp_path.unlink(missing_ok=True)


def _mode_for(destination: Path) -> int:
    if destination.is_symlink() or not destination.is_file():
        return 0o644
    return stat.S_IMODE(destination.stat().st_mode)


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    offset = 0
    while offset < len(view):
        written = os.write(fd, view[offset:])
        if written <= 0:
            message = "failed to write the temporary file"
            raise OSError(message)
        offset += written


def _fsync_directory(directory: Path) -> None:
    """Record the directory entry created by ``os.replace``.

    On POSIX, a successful rename is not durable until the parent directory
    itself is fsynced.
    """
    flags = os.O_RDONLY
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    if isinstance(directory_flag, int):
        flags |= directory_flag
    fd = os.open(directory, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
