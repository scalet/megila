"""The media-tool installer probes ffmpeg and can fall back to a local archive."""

from __future__ import annotations

import hashlib
import subprocess
import tarfile
from pathlib import Path

_SCRIPT = (
    Path(__file__).resolve().parents[1] / ".github" / "ci" / "ensure-media-tools.sh"
)
_AMD64_SHA = "0fc51331600b02730e6d63485ac7e3cd203bdeeb13216cd78c8844aeb9277fb8"
_ARM64_SHA = "e4d93d4b858a341cf29cbcd0ce2e31271bba67018b27ff4ef3c2e1683f76b810"


def _write_script(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)


def _ffmpeg_body(*, vmaf: bool) -> str:
    vmaf_line = ""
    if vmaf:
        vmaf_line = '    echo " .. libvmaf           VV->V      Calculate"\n'
    return (
        'for arg in "$@"; do\n'
        '  if [ "$arg" = "-encoders" ]; then\n'
        '    echo " V..... libx264              H.264"\n'
        "    exit 0\n"
        "  fi\n"
        '  if [ "$arg" = "-filters" ]; then\n'
        '    echo " .. ass               V->V       Render"\n'
        f"{vmaf_line}"
        "    exit 0\n"
        "  fi\n"
        "done\n"
        "exit 0\n"
    )


def _espeak_body(*, voice: bool) -> str:
    voice_line = ""
    if voice:
        voice_line = '    echo " 5  pt-br           --/M      Portuguese_(Brazil)"\n'
    return (
        'for arg in "$@"; do\n'
        '  if [ "$arg" = "--voices" ]; then\n'
        f"{voice_line}"
        "    exit 0\n"
        "  fi\n"
        "done\n"
        "exit 0\n"
    )


def _bindir(tmp_path: Path, *, vmaf: bool, voice: bool) -> Path:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _write_script(bindir / "ffmpeg", _ffmpeg_body(vmaf=vmaf))
    _write_script(bindir / "ffprobe", "exit 0\n")
    _write_script(bindir / "espeak-ng", _espeak_body(voice=voice))
    return bindir


def _env(bindir: Path, home: Path, **extra: str) -> dict[str, str]:
    env = {
        "PATH": f"{bindir}:/usr/bin:/bin",
        "HOME": str(home),
        "MEGILA_FFMPEG_CACHE": str(home / "ffmpeg-cache"),
    }
    env.update(extra)
    return env


def _run(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(_SCRIPT), *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _archive(tmp_path: Path) -> tuple[Path, str]:
    bundle = tmp_path / "bundle" / "bin"
    bundle.mkdir(parents=True)
    _write_script(bundle / "ffmpeg", _ffmpeg_body(vmaf=True))
    _write_script(bundle / "ffprobe", "exit 0\n")
    archive = tmp_path / "ffmpeg.tar.xz"
    with tarfile.open(archive, "w:xz") as tar:
        tar.add(tmp_path / "bundle", arcname="bundle")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    return archive, digest


def test_pinned_static_build_is_recorded() -> None:
    text = _SCRIPT.read_text(encoding="utf-8")
    assert _AMD64_SHA in text
    assert _ARM64_SHA in text
    assert "autobuild-2026-11-04-12-51" in text
    assert "libvmaf" in text
    assert "libx264" in text
    assert "flock -w 180" in text
    assert "--max-time 300" in text


def test_check_accepts_a_complete_tool_set(tmp_path: Path) -> None:
    env = _env(_bindir(tmp_path, vmaf=True, voice=True), tmp_path / "home")
    result = _run(["--check"], env)
    assert result.returncode == 0, result.stderr
    assert "libvmaf: present" in result.stdout


def test_check_rejects_ffmpeg_without_libvmaf(tmp_path: Path) -> None:
    env = _env(_bindir(tmp_path, vmaf=False, voice=True), tmp_path / "home")
    result = _run(["--check"], env)
    assert result.returncode == 1
    assert "libvmaf" in result.stderr


def test_check_rejects_espeak_without_pt_br(tmp_path: Path) -> None:
    env = _env(_bindir(tmp_path, vmaf=True, voice=False), tmp_path / "home")
    result = _run(["--check"], env)
    assert result.returncode == 1
    assert "pt-br" in result.stderr


def test_static_only_uses_a_local_archive_and_records_path(tmp_path: Path) -> None:
    archive, digest = _archive(tmp_path)
    github_path = tmp_path / "github-path"
    env = _env(
        _bindir(tmp_path, vmaf=False, voice=True),
        tmp_path / "home",
        MEGILA_FFMPEG_URL=archive.as_uri(),
        MEGILA_FFMPEG_SHA256=digest,
        GITHUB_PATH=str(github_path),
    )
    result = _run(["--static-only"], env)
    assert result.returncode == 0, result.stderr + result.stdout
    recorded = github_path.read_text(encoding="utf-8").strip().splitlines()
    assert recorded
    static_ffmpeg = Path(recorded[-1]) / "ffmpeg"
    assert static_ffmpeg.is_file()
    probed = subprocess.run(
        [str(static_ffmpeg), "-filters"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert "libvmaf" in probed.stdout


def test_wrong_sha256_rejects_the_archive(tmp_path: Path) -> None:
    archive, _digest = _archive(tmp_path)
    env = _env(
        _bindir(tmp_path, vmaf=False, voice=True),
        tmp_path / "home",
        MEGILA_FFMPEG_URL=archive.as_uri(),
        MEGILA_FFMPEG_SHA256="0" * 64,
    )
    result = _run(["--static-only"], env)
    assert result.returncode != 0


def test_cached_static_build_is_reused(tmp_path: Path) -> None:
    _archive_path, digest = _archive(tmp_path)
    assert _archive_path.is_file()
    home = tmp_path / "home"
    cache_bin = home / "ffmpeg-cache" / digest / "bin"
    cache_bin.mkdir(parents=True)
    _write_script(cache_bin / "ffmpeg", _ffmpeg_body(vmaf=True))
    _write_script(cache_bin / "ffprobe", "exit 0\n")
    env = _env(
        _bindir(tmp_path, vmaf=False, voice=True),
        home,
        MEGILA_FFMPEG_URL="file:///missing/ffmpeg.tar.xz",
        MEGILA_FFMPEG_SHA256=digest,
    )
    result = _run(["--static-only"], env)
    assert result.returncode == 0, result.stderr + result.stdout
    assert str(cache_bin) in result.stdout
