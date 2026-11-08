"""Queue database path, pragmas, and filesystem refusal."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from megila.config import load_settings
from megila.jobs.queue import (
    BUSY_TIMEOUT_MS,
    DATABASE_FILENAME,
    DatabaseLocationError,
    create_db_engine,
    database_path,
    prepare_database_path,
    sqlite_url,
    utc_now,
)
from megila.jobs.queue.filesystem import (
    REFUSED_FILESYSTEM_TYPES,
    detect_filesystem_type,
    filesystem_type_from_mountinfo,
)

_INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
_MOUNTINFO = "\n".join(
    (
        "36 35 98:0 / / rw,noatime - ext4 /dev/root rw",
        "40 36 0:40 / /mnt/nfs rw - nfs 10.0.0.2:/export rw",
        "41 36 0:41 / /mnt/cloud rw - fuse.rclone rclone rw",
        "42 36 0:42 / /mnt/my\\040disk rw - ext4 /dev/sdb1 rw",
        "not a mount line",
        "1 2 3 4",
    )
)


def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for key in list(os.environ):
        if key.lower().startswith("megila_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))


def _pragma(engine: Engine, name: str) -> object:
    with engine.connect() as connection:
        return connection.execute(text(f"PRAGMA {name}")).scalar_one()


def test_utc_now_is_fixed_width_iso8601() -> None:
    assert _INSTANT.fullmatch(utc_now())


def test_database_path_uses_the_configured_data_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate(monkeypatch, tmp_path)
    data_dir = tmp_path / "library"
    settings = load_settings(config_file=tmp_path / "missing.toml", data_dir=data_dir)
    assert database_path(settings) == data_dir / DATABASE_FILENAME
    assert database_path(settings).name == "megila.sqlite3"


def test_sqlite_url_is_absolute(tmp_path: Path) -> None:
    path = tmp_path / "megila.sqlite3"
    url = sqlite_url(path)
    assert url.startswith("sqlite:///")
    assert url.endswith(path.resolve().as_posix())


def test_every_connection_sets_the_adr_pragmas(tmp_path: Path) -> None:
    engine = create_db_engine(tmp_path / "megila.sqlite3")
    try:
        for _ in range(2):
            assert _pragma(engine, "journal_mode") == "wal"
            assert _pragma(engine, "synchronous") == 2
            assert _pragma(engine, "foreign_keys") == 1
            assert _pragma(engine, "busy_timeout") == BUSY_TIMEOUT_MS
    finally:
        engine.dispose()


def test_filesystem_type_is_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    prepare_database_path(tmp_path / "nested" / "megila.sqlite3")
    assert "filesystem type:" in caplog.text
    assert (tmp_path / "nested").is_dir()


@pytest.mark.parametrize("fstype", sorted(REFUSED_FILESYSTEM_TYPES))
def test_network_filesystem_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fstype: str
) -> None:
    monkeypatch.setattr(
        "megila.jobs.queue.engine.detect_filesystem_type",
        lambda path: fstype.upper(),
    )
    target = tmp_path / "blocked" / "megila.sqlite3"
    with pytest.raises(DatabaseLocationError, match=fstype.upper()):
        prepare_database_path(target)
    assert not target.parent.exists()


def test_unknown_filesystem_is_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "megila.jobs.queue.engine.detect_filesystem_type",
        lambda path: None,
    )
    target = tmp_path / "local" / "megila.sqlite3"
    assert prepare_database_path(target) == target.resolve()
    assert target.parent.is_dir()


def test_temp_directory_is_not_a_refused_filesystem(tmp_path: Path) -> None:
    detected = detect_filesystem_type(tmp_path)
    if detected is not None:
        assert detected.strip().lower() not in REFUSED_FILESYSTEM_TYPES


def test_mountinfo_picks_the_longest_matching_mount() -> None:
    assert filesystem_type_from_mountinfo(Path("/var/lib"), _MOUNTINFO) == "ext4"
    assert filesystem_type_from_mountinfo(Path("/mnt/nfs/megila"), _MOUNTINFO) == "nfs"
    assert (
        filesystem_type_from_mountinfo(Path("/mnt/cloud/db"), _MOUNTINFO)
        == "fuse.rclone"
    )
    assert (
        filesystem_type_from_mountinfo(Path("/mnt/my disk/file"), _MOUNTINFO) == "ext4"
    )
    assert filesystem_type_from_mountinfo(Path("/"), _MOUNTINFO) == "ext4"


def test_mountinfo_ignores_unparseable_lines() -> None:
    assert filesystem_type_from_mountinfo(Path("/tmp/a"), "garbage\n") is None
    relative = "36 35 98:0 / relative rw,noatime - ext4 /dev/root rw\n"
    assert filesystem_type_from_mountinfo(Path("/tmp/a"), relative) is None
    no_separator = "36 35 98:0 / / rw,noatime shared:1 extra extra extra extra\n"
    assert filesystem_type_from_mountinfo(Path("/"), no_separator) is None
    early_separator = "36 35 98:0 / - ext4 /dev/root rw a b c\n"
    assert filesystem_type_from_mountinfo(Path("/"), early_separator) is None
    trailing_separator = "36 35 98:0 / / rw extra extra extra -\n"
    assert filesystem_type_from_mountinfo(Path("/"), trailing_separator) is None


def test_shorter_mount_does_not_replace_a_longer_one() -> None:
    mountinfo = "\n".join(
        (
            "40 36 0:40 / /mnt/nfs rw - nfs 10.0.0.2:/export rw",
            "36 35 98:0 / / rw,noatime - ext4 /dev/root rw",
        )
    )
    assert filesystem_type_from_mountinfo(Path("/mnt/nfs/megila"), mountinfo) == "nfs"


def test_unknown_mount_escape_is_kept_literally() -> None:
    mountinfo = "36 35 98:0 / /mnt/foo\\999 rw,noatime - ext4 /dev/sdb1 rw\n"
    assert filesystem_type_from_mountinfo(Path("/mnt/foo\\999"), mountinfo) == "ext4"


def test_detect_returns_none_when_mountinfo_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "megila.jobs.queue.filesystem._MOUNTINFO",
        tmp_path / "missing-mountinfo",
    )
    assert detect_filesystem_type(tmp_path) is None
