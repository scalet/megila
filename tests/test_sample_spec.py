"""Unit tests for the synthetic sample contract. No ffmpeg or espeak-ng."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

_ASSETS = Path(__file__).resolve().parent / "assets"
if str(_ASSETS) not in sys.path:
    sys.path.insert(0, str(_ASSETS))

import make_sample  # noqa: E402

# Bytes of narracao_ptbr_v1.txt. Bump the narration version instead of editing v1.
NARRATION_V1_SHA256 = "0c3609691f9cb3d8ee441815f3fd084b170b0ea122b59d6d0e5b8850f4be6475"


def test_default_spec_is_inside_the_contract():
    spec = make_sample.DEFAULT_SPEC
    spec.validate()
    assert spec.text_version == 1
    assert make_sample.MIN_DURATION_S <= spec.duration_s <= make_sample.MAX_DURATION_S
    assert spec.duration_s == 48
    assert spec.width == 320
    assert spec.height == 240
    assert spec.frame_rate == 25
    assert spec.frame_count == 1200
    assert spec.sample_rate == 22050
    assert spec.channels == 1
    assert spec.voice == "pt-br+m3"
    assert spec.espeak_speed == 160
    assert spec.video_codec == "libx264"
    assert spec.audio_codec == "pcm_s16le"
    assert spec.container == "mkv"
    assert make_sample.TEXT_PATH.name == f"narracao_ptbr_v{spec.text_version}.txt"


@pytest.mark.parametrize("duration_s", [30, 60])
def test_duration_bounds_are_accepted(duration_s: int):
    spec = replace(make_sample.DEFAULT_SPEC, duration_s=duration_s)
    spec.validate()


@pytest.mark.parametrize("duration_s", [0, 29, 61, 120])
def test_duration_outside_30_to_60_is_rejected(duration_s: int):
    spec = replace(make_sample.DEFAULT_SPEC, duration_s=duration_s)
    with pytest.raises(ValueError, match="duration_s"):
        spec.validate()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"width": 321},
        {"height": 241},
        {"width": 0},
        {"channels": 2},
        {"video_codec": "mpeg4"},
        {"audio_codec": "aac"},
        {"container": "mp4"},
        {"voice": ""},
        {"espeak_speed": 10},
        {"text_version": 0},
        {"frame_rate": 0},
    ],
)
def test_spec_rejects_values_that_would_break_the_recipe(kwargs: dict):
    spec = replace(make_sample.DEFAULT_SPEC, **kwargs)
    with pytest.raises(ValueError):
        spec.validate()


def test_narration_v1_is_pinned_pt_br_text():
    raw = make_sample.TEXT_PATH.read_bytes()
    assert make_sample.sha256_file(make_sample.TEXT_PATH) == NARRATION_V1_SHA256
    assert b"\r" not in raw
    assert not raw.startswith(b"\xef\xbb\xbf")
    narration = make_sample.load_narration()
    assert narration.version == 1
    assert narration.language == "pt-BR"
    assert "amostra sintética" in narration.text
    assert "português do Brasil" in narration.text
    assert "Fim da narração sintética." in narration.text
    assert "version:" not in narration.text
    assert "SPDX" not in narration.text
    assert narration.text.endswith("\n")


def test_narration_parser_rejects_bad_files(tmp_path: Path):
    cases = {
        "version: 1\nlanguage: pt-BR\nOlá.\n": "separator",
        "version: 1\nlanguage: en\n---\nOlá.\n": "pt-BR",
        "language: pt-BR\n---\nOlá.\n": "version",
        "version: 1\nlanguage: pt-BR\n---\n": "empty",
        "version: um\nlanguage: pt-BR\n---\nOlá.\n": "integer",
    }
    for body, match in cases.items():
        path = tmp_path / "bad.txt"
        path.write_bytes(body.encode("utf-8"))
        with pytest.raises(make_sample.NarrationError, match=match):
            make_sample.load_narration(path)

    crlf = tmp_path / "crlf.txt"
    crlf.write_bytes(b"version: 1\r\nlanguage: pt-BR\r\n---\r\nOl\xc3\xa1.\r\n")
    with pytest.raises(make_sample.NarrationError, match="LF"):
        make_sample.load_narration(crlf)

    bom = tmp_path / "bom.txt"
    bom.write_bytes(b"\xef\xbb\xbfversion: 1\nlanguage: pt-BR\n---\nOl\xc3\xa1.\n")
    with pytest.raises(make_sample.NarrationError, match="BOM"):
        make_sample.load_narration(bom)


def test_commands_pin_bitexact_testsrc_and_voice():
    spec = make_sample.DEFAULT_SPEC
    espeak = make_sample.build_espeak_command(Path("narration.txt"), Path("speech.wav"), spec)
    ffmpeg = make_sample.build_ffmpeg_command(Path("speech.wav"), Path("clip.mkv"), spec)
    assert espeak[:6] == ["espeak-ng", "-v", "pt-br+m3", "-s", "160", "-w"]
    assert espeak[-2:] == ["-f", "narration.txt"]
    assert ffmpeg[0] == "ffmpeg"
    assert ffmpeg.count("+bitexact") >= 2
    assert "-map_metadata" in ffmpeg and ffmpeg[ffmpeg.index("-map_metadata") + 1] == "-1"
    assert any(part.startswith("testsrc2=size=320x240:rate=25:duration=48:") for part in ffmpeg)
    assert "threads=1" in ffmpeg[ffmpeg.index("-x264-params") + 1]
    assert "pcm_s16le" in ffmpeg
    assert ffmpeg[-2:] == ["matroska", "clip.mkv"]
    assert all(isinstance(part, str) for part in espeak + ffmpeg)
    joined = " ".join(espeak + ffmpeg)
    assert "&&" not in joined and ";" not in joined


def test_recipe_hash_is_stable_and_tracks_the_spec():
    first = make_sample.recipe_sha256(make_sample.DEFAULT_SPEC)
    second = make_sample.recipe_sha256(make_sample.DEFAULT_SPEC)
    assert first == second
    assert len(first) == 64
    other = replace(make_sample.DEFAULT_SPEC, duration_s=36)
    assert make_sample.recipe_sha256(other) != first


def test_cache_path_stays_inside_the_cache_and_is_gitignored(tmp_path: Path):
    path = make_sample.output_path(tmp_path, make_sample.DEFAULT_SPEC)
    assert path.parent == tmp_path.resolve()
    assert path.name == "megila_sintetico_v1_320x240_48s.mkv"
    gitignore = (_ASSETS / ".gitignore").read_text(encoding="utf-8")
    assert "cache/" in gitignore
    default_output = make_sample.output_path(make_sample.CACHE_DIR, make_sample.DEFAULT_SPEC)
    assert default_output.parent == make_sample.CACHE_DIR.resolve()


def test_licenses_cover_text_voice_and_tools():
    text = (_ASSETS / "LICENSES.md").read_text(encoding="utf-8")
    for needle in (
        "narracao_ptbr_v1.txt",
        "MIT",
        "espeak-ng",
        "pt-br+m3",
        "GPL-3.0-or-later",
        "ffmpeg",
        "libx264",
        "GPL-2.0-or-later",
        "testsrc2",
    ):
        assert needle in text


def test_media_mismatches_accept_a_matching_probe_and_flag_drift():
    spec = make_sample.DEFAULT_SPEC
    good = make_sample.MediaInfo(
        duration_s=48.0,
        width=320,
        height=240,
        frame_rate="25/1",
        video_codec="h264",
        audio_codec="pcm_s16le",
        sample_rate=22050,
        channels=1,
    )
    assert make_sample.media_mismatches(good, spec) == []
    bad = replace(good, width=16, audio_codec=None, duration_s=10.0)
    problems = make_sample.media_mismatches(bad, spec)
    assert any("resolution" in item for item in problems)
    assert any("audio codec" in item for item in problems)
    assert any("duration" in item for item in problems)


def test_print_spec_does_not_need_external_tools(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setattr(make_sample.shutil, "which", lambda _name: None)
    assert make_sample.main(["--print-spec"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["duration_s"] == 48
    assert payload["width"] == 320
    assert payload["height"] == 240
    assert payload["voice"] == "pt-br+m3"


def test_generate_reports_missing_tools(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(make_sample.shutil, "which", lambda _name: None)
    with pytest.raises(make_sample.MissingToolsError, match="espeak-ng"):
        make_sample.generate_sample(cache_dir=tmp_path)
