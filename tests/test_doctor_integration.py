"""Doctor against the machine running the tests.

Skipped when ffmpeg is not on PATH, so a CI runner without ffmpeg stays green.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from megila.cli import app
from megila.doctor.ffmpeg import (
    parse_build_flags,
    parse_encoder_names,
    parse_filter_names,
    parse_version,
)

runner = CliRunner()


def _require_ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    pytest.skip("ffmpeg is not on PATH; megila doctor integration test skipped")


def test_doctor_matches_this_ffmpeg(tmp_path: Path) -> None:
    ffmpeg = _require_ffmpeg()
    version = _run(ffmpeg, "-version")
    filters = _run(ffmpeg, "-filters")
    encoders = _run(ffmpeg, "-encoders")
    build = _run(ffmpeg, "-buildconf")
    names = parse_filter_names(filters)
    encoder_names = parse_encoder_names(encoders)
    flags = parse_build_flags(build) | parse_build_flags(version)
    libass = ("ass" in names) or ("--enable-libass" in flags)
    libvmaf = ("libvmaf" in names) or ("--enable-libvmaf" in flags)
    libx264 = ("libx264" in encoder_names) or ("--enable-libx264" in flags)

    source = tmp_path / "source"
    source.mkdir()
    json_result = runner.invoke(
        app,
        [
            "doctor",
            "--json",
            "--source",
            str(source),
            "--backup",
            "gdrive:megila",
        ],
    )
    payload = json.loads(json_result.stdout)
    assert payload["ffmpeg"]["present"] is True
    assert payload["ffmpeg"]["version"] == parse_version(version)
    assert payload["ffmpeg"]["libass"] is libass
    assert payload["ffmpeg"]["libvmaf"] is libvmaf
    assert payload["ffmpeg"]["libx264"] is libx264
    assert payload["backup"]["status"] == "remote"
    assert payload["backup"]["same_disk"] is False
    assert isinstance(payload["cpu"]["logical_cores"], int)
    assert payload["cpu"]["logical_cores"] >= 1
    assert payload["memory"]["total_bytes"] > 0
    assert payload["disk"]["free_bytes"] >= 0
    assert payload["suggested_profile"] in {"leve", "padrao", "forte"}
    assert isinstance(payload["temperatures"], list)
    if libass:
        assert json_result.exit_code == 0
        assert payload["ok"] is True
        assert "libass_missing" not in payload["hard_failures"]
    else:
        assert json_result.exit_code == 1
        assert payload["ok"] is False
        assert "libass_missing" in payload["hard_failures"]
    if not libvmaf:
        assert "libvmaf_missing" in payload["warnings"]

    plain = runner.invoke(app, ["doctor", "--source", str(source)])
    assert plain.exit_code == json_result.exit_code
    assert "suggested profile:" in plain.stdout
    assert payload["suggested_profile"] in plain.stdout


def _run(ffmpeg: str, flag: str) -> str:
    completed = subprocess.run(
        [ffmpeg, "-hide_banner", flag],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert completed.returncode == 0
    return f"{completed.stdout}\n{completed.stderr}"
