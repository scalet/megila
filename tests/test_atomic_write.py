"""Atomic writes, including a crash before the file is published."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest
from hypothesis import given
from hypothesis import settings as hypothesis_settings
from hypothesis import strategies as st

from megila.storage import atomic_write


def _names(directory: Path) -> list[str]:
    return sorted(path.name for path in directory.iterdir())


def test_replaces_previous_contents(tmp_path: Path) -> None:
    target = tmp_path / "payload.bin"
    target.write_bytes(b"old-complete")
    atomic_write(target, b"new-complete")
    assert target.read_bytes() == b"new-complete"
    assert _names(tmp_path) == ["payload.bin"]


def test_creates_parent_directories(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "c.bin"
    atomic_write(target, b"xyz")
    assert target.read_bytes() == b"xyz"


def test_new_file_mode_is_0644_and_existing_mode_is_kept(tmp_path: Path) -> None:
    created = tmp_path / "created.bin"
    atomic_write(created, b"abc")
    assert stat.S_IMODE(created.stat().st_mode) == 0o644

    existing = tmp_path / "existing.bin"
    existing.write_bytes(b"old")
    existing.chmod(0o600)
    atomic_write(existing, b"new")
    assert existing.read_bytes() == b"new"
    assert stat.S_IMODE(existing.stat().st_mode) == 0o600


def test_rejects_str_and_directories(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="bytes"):
        atomic_write(tmp_path / "out.bin", "text")  # type: ignore[arg-type]
    with pytest.raises(IsADirectoryError):
        atomic_write(tmp_path, b"nope")
    assert _names(tmp_path) == []


def test_replaces_a_symlink_without_following_it(tmp_path: Path) -> None:
    real = tmp_path / "real.bin"
    real.write_bytes(b"real")
    link = tmp_path / "link.bin"
    link.symlink_to(real)
    atomic_write(link, b"published")
    assert link.read_bytes() == b"published"
    assert not link.is_symlink()
    assert real.read_bytes() == b"real"


def test_temp_file_is_in_the_destination_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded: list[Path] = []
    real = tempfile.mkstemp

    def spy(
        suffix: str | None = None,
        prefix: str | None = None,
        dir: str | Path | None = None,
        text: bool = False,
    ) -> tuple[int, str]:
        assert isinstance(dir, Path)
        recorded.append(dir)
        fd, name = real(suffix=suffix, prefix=prefix, dir=dir, text=text)
        assert isinstance(name, str)
        assert Path(name).parent == dir
        return fd, name

    monkeypatch.setattr("megila.storage.atomic.tempfile.mkstemp", spy)
    target = tmp_path / "nested" / "out.bin"
    atomic_write(target, b"abc")
    assert recorded == [tmp_path / "nested"]


def test_directory_fsync_ignores_a_non_integer_o_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "O_DIRECTORY", "not-an-int", raising=False)
    target = tmp_path / "out.bin"
    atomic_write(target, b"abc")
    assert target.read_bytes() == b"abc"


def test_fsyncs_the_file_and_then_the_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kinds: list[str] = []
    real = os.fsync

    def spy(fd: int) -> None:
        mode = os.fstat(fd).st_mode
        if stat.S_ISDIR(mode):
            kinds.append("dir")
        elif stat.S_ISREG(mode):
            kinds.append("file")
        else:
            kinds.append("other")
        real(fd)

    monkeypatch.setattr("megila.storage.atomic.os.fsync", spy)
    atomic_write(tmp_path / "out.bin", b"abc")
    assert kinds == ["file", "dir"]


def test_long_names_still_use_a_same_directory_temp(tmp_path: Path) -> None:
    target = tmp_path / ("n" * 90)
    atomic_write(target, b"ok")
    assert target.read_bytes() == b"ok"
    assert _names(tmp_path) == ["n" * 90]


def test_zero_length_os_write_does_not_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "out.bin"
    target.write_bytes(b"old-complete")

    def zero(fd: int, data: bytes | memoryview) -> int:
        del fd, data
        return 0

    monkeypatch.setattr("megila.storage.atomic.os.write", zero)
    with pytest.raises(OSError, match="temporary file"):
        atomic_write(target, b"new-complete")
    assert target.read_bytes() == b"old-complete"
    assert _names(tmp_path) == ["out.bin"]


def test_short_writes_still_publish_the_full_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = os.write

    def short(fd: int, data: bytes | memoryview) -> int:
        return real(fd, bytes(data[:1]))

    monkeypatch.setattr("megila.storage.atomic.os.write", short)
    target = tmp_path / "out.bin"
    payload = b"abcdef"
    atomic_write(target, payload)
    assert target.read_bytes() == payload


def test_crash_before_replace_keeps_the_previous_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "out.bin"
    target.write_bytes(b"old-complete")

    def boom(src: str, dst: str) -> None:
        del src, dst
        raise OSError("simulated crash")

    monkeypatch.setattr("megila.storage.atomic.os.replace", boom)
    with pytest.raises(OSError, match="simulated crash"):
        atomic_write(target, b"new-complete-must-not-land")
    assert target.read_bytes() == b"old-complete"
    assert _names(tmp_path) == ["out.bin"]


def test_directory_fsync_failure_keeps_the_complete_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = os.fsync

    def spy(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("simulated directory fsync failure")
        real(fd)

    monkeypatch.setattr("megila.storage.atomic.os.fsync", spy)
    target = tmp_path / "out.bin"
    with pytest.raises(OSError, match="directory fsync"):
        atomic_write(target, b"complete-new")
    assert target.read_bytes() == b"complete-new"
    assert _names(tmp_path) == ["out.bin"]


def _crash_after_partial_temp_write(fd: int, data: bytes) -> None:
    if data:
        os.write(fd, data[:1])
    raise OSError("simulated crash")


@given(
    original=st.binary(max_size=1024),
    updated=st.binary(max_size=1024),
    existed=st.booleans(),
)
@hypothesis_settings(max_examples=30, deadline=None)
def test_crash_mid_write_never_leaves_a_partial_file(
    original: bytes, updated: bytes, existed: bool
) -> None:
    with TemporaryDirectory() as tmp:
        directory = Path(tmp)
        target = directory / "payload"
        if existed:
            target.write_bytes(original)
        with (
            patch(
                "megila.storage.atomic._write_all",
                _crash_after_partial_temp_write,
            ),
            pytest.raises(OSError, match="simulated crash"),
        ):
            atomic_write(target, updated)
        if existed:
            assert target.read_bytes() == original
        else:
            assert not target.exists()
        assert _names(directory) == (["payload"] if existed else [])


@given(payload=st.binary(max_size=2048))
@hypothesis_settings(max_examples=25, deadline=None)
def test_round_trip_bytes(payload: bytes) -> None:
    with TemporaryDirectory() as tmp:
        target = Path(tmp) / "payload"
        atomic_write(target, payload)
        assert target.read_bytes() == payload
        atomic_write(target, payload + b"!")
        assert target.read_bytes() == payload + b"!"
