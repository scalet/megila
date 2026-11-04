"""Recognize the filesystem that will hold the queue database.

ADR 0003: the database lives on a local disk. ``nfs``, ``cifs``, ``smb``,
``fuse.rclone`` and the same protocols under another name are refused.
An unrecognized type is not refused; only a positive match is.
"""

from __future__ import annotations

from pathlib import Path

# Names are compared after ``str.lower()``. ``nfs4`` is NFS. ``smb2`` and
# ``smb3`` are SMB. ``rclone`` is the same mount as ``fuse.rclone``.
REFUSED_FILESYSTEM_TYPES: frozenset[str] = frozenset(
    {
        "nfs",
        "nfs4",
        "cifs",
        "smb",
        "smb2",
        "smb3",
        "fuse.rclone",
        "rclone",
    }
)

_MOUNTINFO = Path("/proc/self/mountinfo")
_ESCAPES = {"040": " ", "011": "\t", "012": "\n", "134": "\\"}


def detect_filesystem_type(path: Path) -> str | None:
    """Return the fstype of the mount that contains ``path``.

    Linux exposes this in ``/proc/self/mountinfo``. Other platforms, and a
    missing mount table, return ``None`` (the type is not recognizable).
    """
    try:
        text = _MOUNTINFO.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return filesystem_type_from_mountinfo(path, text)


def filesystem_type_from_mountinfo(path: Path, mountinfo: str) -> str | None:
    """Return the fstype of the longest mount point that contains ``path``.

    ``mountinfo`` is the text of ``/proc/self/mountinfo``. The path does not
    have to exist; the match is lexical against the normalized absolute path.
    """
    candidate = path.expanduser().resolve()
    best_length = -1
    best_type: str | None = None
    for line in mountinfo.splitlines():
        parsed = _parse_mountinfo_line(line)
        if parsed is None:
            continue
        mount_point, fstype = parsed
        if not mount_point.startswith("/"):
            continue
        try:
            candidate.relative_to(mount_point)
        except ValueError:
            continue
        if len(mount_point) >= best_length:
            best_length = len(mount_point)
            best_type = fstype
    return best_type


def _parse_mountinfo_line(line: str) -> tuple[str, str] | None:
    """Return ``(mount point, fstype)`` or ``None`` when the line is short.

    Fields are space-separated. Optional fields sit between the mount options
    and a field that is exactly ``-``. The filesystem type is the next field.
    Spaces in the mount point are escaped as ``\\040``.
    """
    parts = line.split(" ")
    if len(parts) < 10:
        return None
    try:
        separator = parts.index("-")
    except ValueError:
        return None
    if separator < 6 or separator + 1 >= len(parts):
        return None
    return _unescape_mount_point(parts[4]), parts[separator + 1]


def _unescape_mount_point(value: str) -> str:
    pieces: list[str] = []
    index = 0
    while index < len(value):
        if value[index] == "\\" and index + 4 <= len(value):
            mapped = _ESCAPES.get(value[index + 1 : index + 4])
            if mapped is not None:
                pieces.append(mapped)
                index += 4
                continue
        pieces.append(value[index])
        index += 1
    return "".join(pieces)
