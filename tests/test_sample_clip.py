"""Integration test: generate the synthetic clip and probe it.

Skipped with a warning when ffmpeg, ffprobe, or espeak-ng is not on PATH.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import pytest

_ASSETS = Path(__file__).resolve().parent / "assets"
if str(_ASSETS) not in sys.path:
    sys.path.insert(0, str(_ASSETS))

import make_sample  # noqa: E402


def skip_unless_sample_tools() -> None:
    missing = make_sample.missing_tools()
    if not missing:
        return
    message = (
        "synthetic sample integration test skipped; missing tools: "
        + ", ".join(missing)
        + ". Install ffmpeg (with libx264) and espeak-ng."
    )
    warnings.warn(message, make_sample.SampleToolWarning, stacklevel=2)
    pytest.skip(message)


def test_skip_warns_when_ffmpeg_or_espeak_is_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(make_sample.shutil, "which", lambda _name: None)
    with pytest.warns(make_sample.SampleToolWarning, match="espeak-ng"):
        with pytest.raises(pytest.skip.Exception, match="espeak-ng"):
            skip_unless_sample_tools()


def test_generated_clip_is_deterministic_and_matches_probe(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    skip_unless_sample_tools()
    spec = make_sample.DEFAULT_SPEC
    first = make_sample.generate_sample(cache_dir=tmp_path / "a", force=True)
    second = make_sample.generate_sample(cache_dir=tmp_path / "b", force=True)
    digest_first = make_sample.sha256_file(first)
    digest_second = make_sample.sha256_file(second)
    assert digest_first == digest_second

    stamp = first.stat().st_mtime_ns
    cached = make_sample.generate_sample(cache_dir=tmp_path / "a", force=False)
    assert cached == first
    assert cached.stat().st_mtime_ns == stamp
    assert make_sample.sha256_file(cached) == digest_first

    info = make_sample.probe_media(first)
    assert make_sample.media_mismatches(info, spec) == []
    assert info.duration_s is not None
    assert abs(info.duration_s - spec.duration_s) <= 1.5 / spec.frame_rate
    assert info.width == spec.width
    assert info.height == spec.height
    assert info.video_codec == "h264"
    assert info.frame_rate == f"{spec.frame_rate}/1"
    assert info.audio_codec == spec.audio_codec
    assert info.sample_rate == spec.sample_rate
    assert info.channels == spec.channels

    manifest = make_sample.manifest_path_for(first)
    recorded = manifest.read_text(encoding="utf-8")
    assert digest_first in recorded
    assert '"speech_duration_s"' in recorded

    assert make_sample.main(
        ["--cache-dir", str(tmp_path / "a"), "--check", "--print-hash"]
    ) == 0
    assert capsys.readouterr().out.strip() == digest_first
