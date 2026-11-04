"""Parse ``ffmpeg -filters`` and ``ffmpeg -buildconf``."""

from __future__ import annotations

import re

from megila.doctor.command import CommandResult, CommandRunner, combined_output
from megila.doctor.facts import FfmpegFacts, absent_ffmpeg

FFMPEG_TIMEOUT_SECONDS = 15.0

_VERSION = re.compile(r"ffmpeg version\s+(\S+)")
_FLAG = re.compile(r"(?<!\S)(--[A-Za-z0-9][A-Za-z0-9._+-]*)(?:=\S+)?")
_FILTER_LINE = re.compile(r"^\s*([.TSC|]{3})\s+([A-Za-z0-9_]+)\s+(\S+)\s+.+$")
_PAD = re.compile(r"^[AVN|]+->[AVN|]+$")
_ERROR_LIMIT = 300


def parse_version(text: str) -> str | None:
    """Return the token after ``ffmpeg version``, or None."""
    match = _VERSION.search(text)
    if match is None:
        return None
    return match.group(1)


def parse_build_flags(text: str) -> frozenset[str]:
    """Return ``--enable-*`` / ``--disable-*`` tokens from a buildconf dump."""
    return frozenset(match.group(1) for match in _FLAG.finditer(text))


def parse_filter_names(text: str) -> frozenset[str]:
    """Return filter names from ``ffmpeg -filters``.

    Legend lines (``T.. = Timeline support``) are skipped. The pad column
    has to look like ``V->V`` so a prose mention of ``ass`` is not a filter.
    ``vmafmotion`` stays a distinct name from ``libvmaf``.
    """
    names: set[str] = set()
    for line in text.splitlines():
        match = _FILTER_LINE.match(line)
        if match is None:
            continue
        pad = match.group(3)
        if _PAD.fullmatch(pad) is None:
            continue
        names.add(match.group(2))
    return frozenset(names)


def inspect_ffmpeg(path: str | None, runner: CommandRunner) -> FfmpegFacts:
    """Probe ``path`` with ``-version``, ``-filters``, and ``-buildconf``.

    ``path`` None means the binary is not on ``PATH``. A non-zero ``-version``
    without a version string means the binary cannot be used. Library flags
    are read from ``-buildconf`` and from the configuration line of
    ``-version``. The ``ass`` and ``libvmaf`` filters are read from
    ``-filters``.
    """
    if path is None:
        return absent_ffmpeg("ffmpeg was not found on PATH")
    version = runner(
        [path, "-hide_banner", "-version"],
        timeout=FFMPEG_TIMEOUT_SECONDS,
    )
    filters = runner(
        [path, "-hide_banner", "-filters"],
        timeout=FFMPEG_TIMEOUT_SECONDS,
    )
    build = runner(
        [path, "-hide_banner", "-buildconf"],
        timeout=FFMPEG_TIMEOUT_SECONDS,
    )
    version_text = combined_output(version)
    parsed = parse_version(version_text)
    if version.returncode != 0 and parsed is None:
        detail = _failure_detail(version)
        return absent_ffmpeg(detail, path=path)
    flags = parse_build_flags(combined_output(build)) | parse_build_flags(version_text)
    names = parse_filter_names(combined_output(filters))
    return FfmpegFacts(
        present=True,
        path=path,
        version=parsed,
        libass_filter="ass" in names,
        libass_build="--enable-libass" in flags,
        libvmaf_filter="libvmaf" in names,
        libvmaf_build="--enable-libvmaf" in flags,
        libx264_build="--enable-libx264" in flags,
        error=None,
    )


def _failure_detail(result: CommandResult) -> str:
    text = result.stderr.strip() or result.stdout.strip() or "ffmpeg failed"
    collapsed = " ".join(text.split())
    if len(collapsed) <= _ERROR_LIMIT:
        return collapsed
    return collapsed[: _ERROR_LIMIT - 3] + "..."


def ffmpeg_argv(path: str) -> tuple[tuple[str, ...], ...]:
    """Return the three ffmpeg invocations doctor always makes."""
    return (
        (path, "-hide_banner", "-version"),
        (path, "-hide_banner", "-filters"),
        (path, "-hide_banner", "-buildconf"),
    )
