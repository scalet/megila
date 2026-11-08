#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Generate a deterministic synthetic sample clip for Megila tests.

The clip is ffmpeg's ``testsrc2`` pattern plus Brazilian Portuguese speech
from espeak-ng. Bitexact mux flags, a single x264 thread, and PCM audio make
two runs with the same tool versions produce the same SHA-256. The media is
written under ``tests/assets/cache/`` and is not meant to be committed.

Requires the ``ffmpeg`` (with libx264), ``ffprobe``, and ``espeak-ng``
executables. No Python dependency beyond the standard library.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import warnings
from dataclasses import asdict, dataclass
from pathlib import Path

ASSETS_DIR = Path(__file__).resolve().parent
TEXT_PATH = ASSETS_DIR / "narracao_ptbr_v1.txt"
CACHE_DIR = ASSETS_DIR / "cache"

MIN_DURATION_S = 30
MAX_DURATION_S = 60
MIN_SPEECH_S = 5.0
REQUIRED_TOOLS = ("ffmpeg", "ffprobe", "espeak-ng")
_ENV_PASSTHROUGH = ("PATH", "HOME", "LD_LIBRARY_PATH", "TMPDIR", "TMP", "TEMP")


class SampleToolWarning(UserWarning):
    """Emitted when ffmpeg or espeak-ng is missing and a test is skipped."""


class MissingToolsError(RuntimeError):
    """Raised when a required external executable is not on PATH."""

    def __init__(self, missing: list[str]) -> None:
        self.missing = list(missing)
        joined = ", ".join(self.missing)
        super().__init__(
            "missing required tools on PATH: "
            f"{joined}. Install ffmpeg (with libx264) and espeak-ng."
        )


class NarrationError(ValueError):
    """Raised when the versioned narration file cannot be parsed."""


class SampleBuildError(RuntimeError):
    """Raised when espeak-ng, ffmpeg, or ffprobe fails while building the clip."""


@dataclass(frozen=True)
class SampleSpec:
    """Parameters of the synthetic clip. Defaults are the committed contract."""

    text_version: int = 1
    duration_s: int = 48
    width: int = 320
    height: int = 240
    frame_rate: int = 25
    sample_rate: int = 22050
    channels: int = 1
    voice: str = "pt-br+m3"
    espeak_speed: int = 160
    video_codec: str = "libx264"
    audio_codec: str = "pcm_s16le"
    crf: int = 32
    preset: str = "ultrafast"
    container: str = "mkv"
    pix_fmt: str = "yuv420p"

    @property
    def frame_count(self) -> int:
        return self.duration_s * self.frame_rate

    def validate(self) -> None:
        if isinstance(self.duration_s, bool) or not isinstance(self.duration_s, int):
            raise ValueError("duration_s must be an integer number of seconds")
        if self.duration_s < MIN_DURATION_S or self.duration_s > MAX_DURATION_S:
            raise ValueError(
                "duration_s must be between "
                f"{MIN_DURATION_S} and {MAX_DURATION_S} seconds"
            )
        if self.width <= 0 or self.height <= 0 or self.width % 2 or self.height % 2:
            raise ValueError("width and height must be positive even integers")
        if self.frame_rate <= 0:
            raise ValueError("frame_rate must be positive")
        if self.sample_rate <= 0 or self.channels != 1:
            raise ValueError("audio must be mono with a positive sample rate")
        if self.video_codec != "libx264" or self.audio_codec != "pcm_s16le":
            raise ValueError("sample clip must use libx264 video and pcm_s16le audio")
        if self.container != "mkv":
            raise ValueError("sample clip container must be mkv")
        if self.pix_fmt != "yuv420p":
            raise ValueError("pix_fmt must be yuv420p")
        if not self.voice:
            raise ValueError("voice must be set")
        if not 80 <= self.espeak_speed <= 450:
            raise ValueError("espeak_speed is outside the espeak-ng range 80..450")
        if not 0 <= self.crf <= 51:
            raise ValueError("crf must be between 0 and 51")
        allowed_presets = {
            "ultrafast",
            "superfast",
            "veryfast",
            "faster",
            "fast",
            "medium",
        }
        if self.preset not in allowed_presets:
            raise ValueError(f"unsupported x264 preset: {self.preset}")
        if self.text_version < 1:
            raise ValueError("text_version must be >= 1")


DEFAULT_SPEC = SampleSpec()


@dataclass(frozen=True)
class Narration:
    version: int
    language: str
    text: str
    source: Path


@dataclass(frozen=True)
class MediaInfo:
    duration_s: float | None
    width: int | None
    height: int | None
    frame_rate: str | None
    video_codec: str | None
    audio_codec: str | None
    sample_rate: int | None
    channels: int | None


def missing_tools() -> list[str]:
    return [name for name in REQUIRED_TOOLS if shutil.which(name) is None]


def tool_env() -> dict[str, str]:
    """Environment for ffmpeg and espeak-ng.

    The child environment is intentionally small. ``SOURCE_DATE_EPOCH`` and
    ``TZ`` are pinned, and espeak/ffmpeg data-path overrides are dropped so a
    developer's shell cannot change the bytes.
    """

    env = {key: os.environ[key] for key in _ENV_PASSTHROUGH if os.environ.get(key)}
    env["LANG"] = "C.UTF-8"
    env["LC_ALL"] = "C.UTF-8"
    env["TZ"] = "UTC"
    env["SOURCE_DATE_EPOCH"] = "0"
    return env


def load_narration(path: Path = TEXT_PATH) -> Narration:
    """Read the versioned pt-BR script. The header is not spoken."""

    if not path.is_file():
        raise NarrationError(f"narration file not found: {path}")
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise NarrationError("narration file must be UTF-8 without a BOM")
    if b"\r" in raw:
        raise NarrationError("narration file must use LF line endings")
    if not raw.endswith(b"\n"):
        raise NarrationError("narration file must end with a newline")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise NarrationError("narration file must be UTF-8") from exc

    lines = text.split("\n")[:-1]
    try:
        separator = lines.index("---")
    except ValueError as exc:
        raise NarrationError("narration file is missing a '---' separator") from exc

    meta: dict[str, str] = {}
    for line in lines[:separator]:
        if line == "" or line.startswith("#"):
            continue
        if ":" not in line:
            raise NarrationError(f"invalid narration header line: {line!r}")
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip()

    if "version" not in meta:
        raise NarrationError("narration header is missing version")
    try:
        version = int(meta["version"])
    except ValueError as exc:
        raise NarrationError(
            f"narration version is not an integer: {meta['version']!r}"
        ) from exc
    language = meta.get("language")
    if language != "pt-BR":
        raise NarrationError(f"narration language must be pt-BR, got {language!r}")

    spoken = "\n".join(lines[separator + 1 :])
    if spoken:
        spoken += "\n"
    if not spoken.strip():
        raise NarrationError("narration body is empty")
    return Narration(version=version, language=language, text=spoken, source=path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def output_filename(spec: SampleSpec) -> str:
    return (
        f"megila_sintetico_v{spec.text_version}_"
        f"{spec.width}x{spec.height}_{spec.duration_s}s.mkv"
    )


def output_path(cache_dir: Path, spec: SampleSpec) -> Path:
    path = (cache_dir / output_filename(spec)).resolve()
    root = cache_dir.resolve()
    if path.parent != root:
        raise ValueError(f"refusing to write outside the cache directory: {path}")
    return path


def manifest_path_for(media: Path) -> Path:
    return media.with_suffix(".manifest.json")


def build_espeak_command(
    text_path: Path, wav_path: Path, spec: SampleSpec
) -> list[str]:
    return [
        "espeak-ng",
        "-v",
        spec.voice,
        "-s",
        str(spec.espeak_speed),
        "-w",
        str(wav_path),
        "-f",
        str(text_path),
    ]


def build_ffmpeg_command(wav_path: Path, out_path: Path, spec: SampleSpec) -> list[str]:
    """argv for a bitexact Matroska file. Paths are the only varying parts."""

    duration = str(spec.duration_s)
    video = (
        f"testsrc2=size={spec.width}x{spec.height}:rate={spec.frame_rate}:"
        f"duration={duration}:sar=1/1"
    )
    audio_filter = (
        f"[1:a]aresample={spec.sample_rate},"
        "aformat=sample_fmts=s16:channel_layouts=mono,"
        f"atrim=end={duration},apad=whole_dur={duration},asetpts=PTS-STARTPTS[a]"
    )
    x264_params = ":".join(
        [
            "threads=1",
            "sliced-threads=0",
            "sync-lookahead=0",
            "bframes=0",
            f"keyint={spec.frame_rate}",
            f"keyint_min={spec.frame_rate}",
            "scenecut=0",
            "nal-hrd=none",
            "force-cfr=1",
        ]
    )
    return [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-y",
        "-fflags",
        "+bitexact",
        "-f",
        "lavfi",
        "-i",
        video,
        "-i",
        str(wav_path),
        "-filter_complex",
        audio_filter,
        "-map",
        "0:v:0",
        "-map",
        "[a]",
        "-frames:v",
        str(spec.frame_count),
        "-c:v",
        spec.video_codec,
        "-preset",
        spec.preset,
        "-pix_fmt",
        spec.pix_fmt,
        "-crf",
        str(spec.crf),
        "-x264-params",
        x264_params,
        "-c:a",
        spec.audio_codec,
        "-ar",
        str(spec.sample_rate),
        "-ac",
        str(spec.channels),
        "-flags",
        "+bitexact",
        "-fflags",
        "+bitexact",
        "-map_metadata",
        "-1",
        "-muxpreload",
        "0",
        "-muxdelay",
        "0",
        "-f",
        "matroska",
        str(out_path),
    ]


def recipe_sha256(spec: SampleSpec) -> str:
    """Hash of the command shape. Placeholder paths keep it machine-independent."""

    spec.validate()
    argv = build_espeak_command(Path("narration.txt"), Path("speech.wav"), spec)
    argv.extend(build_ffmpeg_command(Path("speech.wav"), Path("clip.mkv"), spec))
    return hashlib.sha256("\n".join(argv).encode("utf-8")).hexdigest()


def run_tool(argv: list[str]) -> subprocess.CompletedProcess[str]:
    if not argv:
        raise ValueError("empty command")
    binary = argv[0]
    if shutil.which(binary) is None:
        raise MissingToolsError([binary])
    completed = subprocess.run(
        argv,
        check=False,
        capture_output=True,
        text=True,
        env=tool_env(),
        stdin=subprocess.DEVNULL,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise SampleBuildError(
            f"{binary} exited with status {completed.returncode}: {detail}"
        )
    return completed


def tool_version_line(binary: str, *args: str) -> str:
    completed = run_tool([binary, *args])
    text = completed.stdout.strip() or completed.stderr.strip()
    if not text:
        raise SampleBuildError(f"{binary} did not report a version")
    return text.splitlines()[0].strip()


def _string_key_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    typed: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            return None
        typed[key] = item
    return typed


def _optional_int(value: object) -> int | None:
    """Best-effort int from ffprobe JSON. Booleans stay numeric, as ``int`` did."""

    if value is None or value == "N/A":
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _optional_str(value: object) -> str | None:
    if isinstance(value, str):
        return value
    return None


def probe_media(path: Path) -> MediaInfo:
    if not path.is_file():
        raise FileNotFoundError(path)
    completed = run_tool(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ]
    )
    try:
        payload_raw = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SampleBuildError(f"ffprobe returned invalid JSON for {path}") from exc
    payload = _string_key_dict(payload_raw)
    if payload is None:
        raise SampleBuildError(f"ffprobe JSON for {path} is not an object")

    video: dict[str, object] | None = None
    audio: dict[str, object] | None = None
    streams = payload.get("streams", [])
    if isinstance(streams, list):
        for stream in streams:
            parsed = _string_key_dict(stream)
            if parsed is None:
                continue
            kind = parsed.get("codec_type")
            if kind == "video" and video is None:
                video = parsed
            elif kind == "audio" and audio is None:
                audio = parsed
    video_info = video or {}
    audio_info = audio or {}

    channels = _optional_int(audio_info.get("channels"))
    if channels is None and audio_info.get("channel_layout") == "mono":
        channels = 1
    format_info = _string_key_dict(payload.get("format"))
    duration_raw = None if format_info is None else format_info.get("duration")
    duration_s = _optional_float(duration_raw)

    frame_rate_raw = video_info.get("r_frame_rate") or video_info.get("avg_frame_rate")
    frame_rate = str(frame_rate_raw) if frame_rate_raw else None
    return MediaInfo(
        duration_s=duration_s,
        width=_optional_int(video_info.get("width")),
        height=_optional_int(video_info.get("height")),
        frame_rate=frame_rate,
        video_codec=_optional_str(video_info.get("codec_name")),
        audio_codec=_optional_str(audio_info.get("codec_name")),
        sample_rate=_optional_int(audio_info.get("sample_rate")),
        channels=channels,
    )


def media_mismatches(info: MediaInfo, spec: SampleSpec) -> list[str]:
    """Describe how probed media differs from ``spec``. Empty means it matches."""

    spec.validate()
    problems: list[str] = []
    expected_video = "h264" if spec.video_codec == "libx264" else spec.video_codec
    if info.video_codec != expected_video:
        problems.append(
            f"video codec is {info.video_codec!r}, expected {expected_video!r}"
        )
    if info.width != spec.width or info.height != spec.height:
        problems.append(
            "resolution is "
            f"{info.width}x{info.height}, expected {spec.width}x{spec.height}"
        )
    expected_rates = {f"{spec.frame_rate}/1", str(spec.frame_rate)}
    if info.frame_rate not in expected_rates:
        problems.append(
            f"frame rate is {info.frame_rate!r}, expected {spec.frame_rate}"
        )
    if info.audio_codec != spec.audio_codec:
        problems.append(
            f"audio codec is {info.audio_codec!r}, expected {spec.audio_codec!r}"
        )
    if info.sample_rate != spec.sample_rate:
        problems.append(
            f"sample rate is {info.sample_rate!r}, expected {spec.sample_rate}"
        )
    if info.channels != spec.channels:
        problems.append(
            f"audio channels are {info.channels!r}, expected {spec.channels}"
        )
    if info.duration_s is None:
        problems.append("duration is missing")
    else:
        tolerance = 1.5 / spec.frame_rate
        if abs(info.duration_s - spec.duration_s) > tolerance:
            problems.append(
                f"duration is {info.duration_s:.3f}s, expected {spec.duration_s}s"
            )
    return problems


def _input_fingerprint(
    spec: SampleSpec,
    text_sha256: str,
    ffmpeg_version: str,
    espeak_version: str,
) -> dict[str, object]:
    return {
        "espeak_version": espeak_version,
        "ffmpeg_version": ffmpeg_version,
        "recipe_sha256": recipe_sha256(spec),
        "spec": asdict(spec),
        "text_sha256": text_sha256,
    }


def _read_manifest(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return _string_key_dict(data)


def _manifest_matches(path: Path, fingerprint: dict[str, object]) -> bool:
    manifest = _read_manifest(path)
    if manifest is None:
        return False
    return all(manifest.get(key) == value for key, value in fingerprint.items())


def _write_json(path: Path, payload: dict[str, object]) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def generate_sample(
    spec: SampleSpec | None = None,
    *,
    cache_dir: Path | None = None,
    text_path: Path | None = None,
    force: bool = False,
) -> Path:
    """Create the clip (or reuse a cache entry) and return its path.

    Cache hits require the same narration bytes, the same command recipe, and
    the same ffmpeg and espeak-ng version strings.
    """

    spec = DEFAULT_SPEC if spec is None else spec
    spec.validate()
    cache_dir = CACHE_DIR if cache_dir is None else cache_dir
    text_path = TEXT_PATH if text_path is None else text_path
    narration = load_narration(text_path)
    if narration.version != spec.text_version:
        raise NarrationError(
            f"spec text_version {spec.text_version} does not match "
            f"{text_path.name} version {narration.version}"
        )

    cache_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_path(cache_dir, spec)
    manifest_path = manifest_path_for(out_path)

    absent = missing_tools()
    if absent:
        raise MissingToolsError(absent)

    fingerprint = _input_fingerprint(
        spec,
        sha256_file(text_path),
        tool_version_line("ffmpeg", "-version"),
        tool_version_line("espeak-ng", "--version"),
    )
    if (
        not force
        and out_path.is_file()
        and _manifest_matches(manifest_path, fingerprint)
    ):
        recorded = (_read_manifest(manifest_path) or {}).get("output_sha256")
        if isinstance(recorded, str) and recorded == sha256_file(out_path):
            return out_path

    with tempfile.TemporaryDirectory(prefix="megila-sample-") as tmp:
        tmp_dir = Path(tmp)
        spoken_path = tmp_dir / "narration.txt"
        spoken_path.write_text(narration.text, encoding="utf-8", newline="\n")
        wav_path = tmp_dir / "speech.wav"
        run_tool(build_espeak_command(spoken_path, wav_path, spec))
        speech = probe_media(wav_path)
        if speech.duration_s is None or speech.duration_s < MIN_SPEECH_S:
            raise SampleBuildError(
                f"synthesized speech is too short ({speech.duration_s}s); "
                "espeak-ng did not render the narration"
            )
        if speech.duration_s > spec.duration_s + (1.5 / spec.frame_rate):
            warnings.warn(
                "synthesized speech is "
                f"{speech.duration_s:.2f}s and will be trimmed to {spec.duration_s}s",
                SampleToolWarning,
                stacklevel=2,
            )
        partial = out_path.with_name(out_path.name + ".partial")
        try:
            run_tool(build_ffmpeg_command(wav_path, partial, spec))
            os.replace(partial, out_path)
        except Exception:
            partial.unlink(missing_ok=True)
            raise

    manifest: dict[str, object] = {
        **fingerprint,
        "generator": "tests/assets/make_sample.py",
        "output_name": out_path.name,
        "output_sha256": sha256_file(out_path),
        "speech_duration_s": speech.duration_s,
    }
    _write_json(manifest_path, manifest)
    return out_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate the deterministic Megila synthetic sample clip "
            "(ffmpeg testsrc2 + espeak-ng pt-BR)."
        )
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help=f"directory for the clip and manifest (default: {CACHE_DIR})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="regenerate even when the cache fingerprint matches",
    )
    parser.add_argument(
        "--print-spec",
        action="store_true",
        help="print the default SampleSpec as JSON and exit",
    )
    parser.add_argument(
        "--print-hash",
        action="store_true",
        help="print only the SHA-256 of the clip",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="probe the clip with ffprobe and exit 1 if it disagrees with the spec",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.print_spec:
        json.dump(asdict(DEFAULT_SPEC), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    cache_dir = CACHE_DIR if args.cache_dir is None else args.cache_dir
    try:
        if args.check and not args.force:
            path = output_path(cache_dir, DEFAULT_SPEC)
            if not path.is_file():
                print(f"error: cached clip not found: {path}", file=sys.stderr)
                print(
                    "generate it with: python tests/assets/make_sample.py",
                    file=sys.stderr,
                )
                return 1
            mismatches = media_mismatches(probe_media(path), DEFAULT_SPEC)
            if mismatches:
                for item in mismatches:
                    print(f"error: {item}", file=sys.stderr)
                return 1
            digest = sha256_file(path)
        else:
            path = generate_sample(cache_dir=cache_dir, force=args.force)
            if args.check:
                mismatches = media_mismatches(probe_media(path), DEFAULT_SPEC)
                if mismatches:
                    for item in mismatches:
                        print(f"error: {item}", file=sys.stderr)
                    return 1
            digest = sha256_file(path)
    except (
        MissingToolsError,
        SampleBuildError,
        NarrationError,
        ValueError,
        OSError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.print_hash:
        print(digest)
    else:
        print(path)
        print(f"sha256:{digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
