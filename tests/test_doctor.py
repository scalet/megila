"""Doctor unit tests with fake ffmpeg output and a fake host (psutil stand-in)."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from megila.cli import app
from megila.config import ConfigError, default_data_dir
from megila.doctor.collect import (
    classify_destination,
    collect_report,
    nvidia_smi_argv,
    parse_nvidia_smi,
    run_doctor,
)
from megila.doctor.command import CommandResult, run_command
from megila.doctor.facts import (
    BACKUP_SAME_DISK,
    CONFIG_INVALID,
    DISK_UNREADABLE,
    FFMPEG_MISSING,
    LEVE_MAX_RAM_BYTES,
    LIBASS_MISSING,
    LIBVMAF_MISSING,
    LIBX264_MISSING,
    MEMORY_UNREADABLE,
    QUALITY_NOTE,
    CpuFacts,
    DoctorReport,
    TemperatureReading,
    cpu_is_light,
    intel_core_generation,
)
from megila.doctor.ffmpeg import (
    ffmpeg_argv,
    parse_build_flags,
    parse_encoder_names,
    parse_filter_names,
    parse_version,
)
from megila.doctor.host import PsutilHost, brand_from_cpuinfo, read_cpu_brand
from megila.doctor.render import render_json, render_plain

runner = CliRunner()

_GIB = 1024**3
_FILTERS = """\
Filters:
  T.. = Timeline support
  .S. = Slice threading
  ..C = Command support
  A = Audio input/output
  V = Video input/output
  N = Dynamic number and/or type of input/output
  | = Source or sink filter
 ... asplit            A->N       Pass audio input to N outputs.
 ... ass               V->V       Render ASS subtitles.
 ... subtitles         V->V       Render text subtitles.
 ... vmafmotion        V->V       Calculate VMAF motion.
"""
_FILTERS_VMAF = (
    _FILTERS
    + " ... libvmaf           VV->V      Calculate the VMAF between two input videos.\n"
)
_BUILD = """\

  configuration:
    --enable-gpl
    --enable-libass
    --enable-libx264
"""
_BUILD_VMAF = _BUILD + "    --enable-libvmaf\n"
_ENCODERS = """\
Encoders:
 V....D libx264              libx264 H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10
"""
_ENCODERS_EMPTY = "Encoders:\n"
_VERSION = (
    "ffmpeg version 6.1.1-3ubuntu5 Copyright (c) 2000-2023 the FFmpeg developers\n"
)
_HASWELL = "Intel(R) Core(TM) i5-4258U CPU @ 2.40GHz"
_MODERN = "Intel(R) Core(TM) i5-12400"


class FakeHost:
    """Stand-in for psutil plus PATH lookups."""

    def __init__(
        self,
        *,
        logical: int | None = 8,
        physical: int | None = 4,
        brand: str | None = _MODERN,
        frequency: float | None = 4500.0,
        memory: tuple[int, int | None] | None = (32 * _GIB, 8 * _GIB),
        disk: tuple[str, int, int] | None = ("/data", 100 * _GIB, 40 * _GIB),
        device: int | None = 1,
        devices: dict[str, int] | None = None,
        temperatures: tuple[TemperatureReading, ...] | None = (),
        system: str = "Linux",
        machine: str = "x86_64",
        ffmpeg: str | None = "/usr/bin/ffmpeg",
        nvidia: str | None = None,
    ) -> None:
        self._logical = logical
        self._physical = physical
        self._brand = brand
        self._frequency = frequency
        self._memory = memory
        self._disk = disk
        self._device = device
        self._devices = devices
        self._temperatures = temperatures
        self._system = system
        self._machine = machine
        self._ffmpeg = ffmpeg
        self._nvidia = nvidia

    def logical_cpus(self) -> int | None:
        return self._logical

    def physical_cpus(self) -> int | None:
        return self._physical

    def cpu_brand(self) -> str | None:
        return self._brand

    def max_cpu_frequency_mhz(self) -> float | None:
        return self._frequency

    def memory_bytes(self) -> tuple[int, int | None] | None:
        return self._memory

    def disk_bytes(self, path: Path) -> tuple[str, int, int] | None:
        del path
        return self._disk

    def device_id(self, path: Path) -> int | None:
        if self._devices is None:
            return self._device
        current = path
        seen: set[Path] = set()
        while current not in seen:
            found = self._devices.get(str(current))
            if found is not None:
                return found
            seen.add(current)
            if current.parent == current:
                break
            current = current.parent
        return None

    def temperatures(self) -> tuple[TemperatureReading, ...] | None:
        return self._temperatures

    def system_name(self) -> str:
        return self._system

    def machine_name(self) -> str:
        return self._machine

    def which(self, name: str) -> str | None:
        if name == "ffmpeg":
            return self._ffmpeg
        if name == "nvidia-smi":
            return self._nvidia
        return None


class MapRunner:
    """Return scripted stdout for ffmpeg and nvidia-smi."""

    def __init__(self, mapping: dict[str, tuple[int, str, str]]) -> None:
        self.mapping = mapping
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv: Sequence[str], *, timeout: float) -> CommandResult:
        del timeout
        recorded = tuple(argv)
        self.calls.append(recorded)
        name = Path(argv[0]).name
        key = "nvidia-smi" if name == "nvidia-smi" else argv[-1]
        code, stdout, stderr = self.mapping[key]
        return CommandResult(
            argv=recorded,
            returncode=code,
            stdout=stdout,
            stderr=stderr,
        )


def _runner(
    *,
    filters: str = _FILTERS_VMAF,
    encoders: str = _ENCODERS,
    build: str = _BUILD_VMAF,
    version: str = _VERSION,
    version_code: int = 0,
    nvidia: str = "",
    nvidia_code: int = 0,
    build_stderr: str = "",
) -> MapRunner:
    return MapRunner(
        {
            "-version": (version_code, version, ""),
            "-filters": (0, filters, ""),
            "-encoders": (0, encoders, ""),
            "-buildconf": (0, build, build_stderr),
            "nvidia-smi": (nvidia_code, nvidia, ""),
        }
    )


def _report(**kwargs: object) -> tuple[DoctorReport, MapRunner]:
    host_kwargs = {
        key: kwargs.pop(key)
        for key in list(kwargs)
        if key
        in {
            "logical",
            "physical",
            "brand",
            "frequency",
            "memory",
            "disk",
            "device",
            "devices",
            "temperatures",
            "system",
            "machine",
            "ffmpeg",
            "nvidia",
        }
    }
    runner_kwargs = {
        key: kwargs.pop(key)
        for key in list(kwargs)
        if key
        in {
            "filters",
            "encoders",
            "build",
            "version",
            "version_code",
            "nvidia_stdout",
            "nvidia_code",
            "build_stderr",
        }
    }
    if "nvidia_stdout" in runner_kwargs:
        runner_kwargs["nvidia"] = runner_kwargs.pop("nvidia_stdout")
    source = kwargs.pop("source", Path("/data"))
    backup = kwargs.pop("backup", None)
    config_error = kwargs.pop("config_error", None)
    assert not kwargs
    assert isinstance(source, Path)
    assert backup is None or isinstance(backup, str)
    assert config_error is None or isinstance(config_error, str)
    scripted = _runner(**runner_kwargs)  # type: ignore[arg-type]
    report = collect_report(
        FakeHost(**host_kwargs),  # type: ignore[arg-type]
        scripted,
        source=source,
        backup=backup,
        config_error=config_error,
    )
    return report, scripted


def test_encoder_parser_finds_libx264() -> None:
    names = parse_encoder_names(_ENCODERS)
    assert names == {"libx264"}
    assert "libx264" not in parse_encoder_names(_ENCODERS_EMPTY)


def test_libx264_from_encoder_without_build_flag() -> None:
    report, _script = _report(
        filters=_FILTERS_VMAF,
        encoders=_ENCODERS,
        build="configuration:\n",
    )
    assert report.ffmpeg.libx264_encoder is True
    assert report.ffmpeg.libx264_build is False
    assert report.ffmpeg.libx264 is True
    assert LIBX264_MISSING not in report.warnings


def test_filter_parser_ignores_the_legend_and_vmafmotion() -> None:
    names = parse_filter_names(_FILTERS)
    assert names == {"asplit", "ass", "subtitles", "vmafmotion"}
    assert "libvmaf" not in names
    assert "ass" in parse_filter_names(_FILTERS_VMAF)
    assert "libvmaf" in parse_filter_names(_FILTERS_VMAF)


def test_build_flags_and_version_token() -> None:
    flags = parse_build_flags(_BUILD)
    assert "--enable-libass" in flags
    assert "--enable-libx264" in flags
    assert "--enable-libvmaf" not in flags
    assert "--enable-libvmaf" in parse_build_flags(_BUILD_VMAF)
    assert parse_version(_VERSION) == "6.1.1-3ubuntu5"
    assert parse_version("no version here") is None


def test_libass_from_the_filter_or_the_build_flag() -> None:
    by_filter, _script = _report(filters=_FILTERS, build="configuration:\n")
    assert by_filter.ffmpeg.libass is True
    assert by_filter.ffmpeg.libass_filter is True
    assert by_filter.ffmpeg.libass_build is False
    assert by_filter.ok is True

    by_flag, _script = _report(filters="Filters:\n", build=_BUILD)
    assert by_flag.ffmpeg.libass_build is True
    assert by_flag.ffmpeg.libass is True
    assert by_flag.ffmpeg.libvmaf is False
    assert LIBVMAF_MISSING in by_flag.warnings
    assert by_flag.exit_code == 0


def test_build_flag_on_stderr_still_counts() -> None:
    flags = ("--enable-libass", "--enable-libvmaf", "--enable-libx264")
    report, _script = _report(
        filters=_FILTERS_VMAF,
        build="",
        build_stderr="".join(f"    {flag}\n" for flag in flags),
    )
    assert report.ffmpeg.libass_build is True
    assert report.ffmpeg.libvmaf_build is True
    assert report.ffmpeg.libx264 is True
    assert report.warnings == ()


def test_missing_libass_is_a_hard_failure() -> None:
    report, script = _report(
        filters=_FILTERS.replace(" ass ", " crop "), build="configuration:\n"
    )
    assert report.ffmpeg.present is True
    assert report.ffmpeg.libass is False
    assert report.hard_failures == (LIBASS_MISSING,)
    assert report.exit_code == 1
    assert report.ok is False
    assert "missing" in render_plain(report)
    assert script.calls[:4] == list(ffmpeg_argv("/usr/bin/ffmpeg"))
    assert all("nvidia-smi" not in call[0] for call in script.calls)


def test_missing_ffmpeg_is_a_hard_failure_and_skips_library_warnings() -> None:
    report, script = _report(ffmpeg=None)
    assert report.hard_failures == (FFMPEG_MISSING,)
    assert report.exit_code == 1
    assert LIBVMAF_MISSING not in report.warnings
    assert LIBX264_MISSING not in report.warnings
    assert script.calls == []
    plain = render_plain(report)
    assert "ffmpeg" in plain
    assert "missing" in plain


def test_ffmpeg_nonzero_without_a_version_is_missing() -> None:
    report, _script = _report(version="boom\n", version_code=1)
    assert report.ffmpeg.present is False
    assert report.hard_failures == (FFMPEG_MISSING,)
    assert "boom" in (report.ffmpeg.error or "")


def test_vmafmotion_does_not_satisfy_libvmaf() -> None:
    report, _script = _report(filters=_FILTERS, build=_BUILD, encoders=_ENCODERS)
    assert report.ffmpeg.libvmaf is False
    assert report.ffmpeg.libx264 is True
    assert report.warnings == (LIBVMAF_MISSING,)
    assert report.exit_code == 0


@pytest.mark.parametrize(
    ("brand", "generation"),
    [
        (_HASWELL, 4),
        ("Intel(R) Core(TM) i7-4770 CPU @ 3.40GHz", 4),
        ("Intel(R) Core(TM) i7-3770 CPU @ 3.40GHz", 3),
        ("Intel(R) Core(TM) i5-2500", 2),
        ("Intel(R) Core(TM) i5-750", 1),
        ("Intel(R) Core(TM)2 Duo CPU P8600 @ 2.40GHz", 0),
        ("Intel(R) Core(TM) i5-8250U", 8),
        ("Intel(R) Core(TM) i5-1035G1", 10),
        ("Intel(R) Core(TM) i5-1135G7", 11),
        ("Intel(R) Core(TM) i7-11600K", 11),
        ("Intel(R) Core(TM) i5-12400", 12),
        ("Intel(R) Core(TM) i5-1340P", 13),
        ("Intel(R) Core(TM) i9-14900K", 14),
        ("Apple M1", None),
        ("", None),
        (None, None),
    ],
)
def test_intel_generation_parser(brand: str | None, generation: int | None) -> None:
    assert intel_core_generation(brand) == generation


def test_eight_gigabyte_2013_i5_suggests_leve() -> None:
    report, _script = _report(
        logical=4,
        physical=2,
        brand=_HASWELL,
        frequency=2900.0,
        memory=(8 * _GIB, 2 * _GIB),
    )
    assert report.suggested_profile == "leve"
    assert "8.0 GiB" in report.suggestion_reason
    assert "2013" in report.suggestion_reason
    assert "2 physical cores" in report.suggestion_reason
    assert "generation 4" in report.suggestion_reason
    assert QUALITY_NOTE in report.suggestion_reason
    assert cpu_is_light(report.cpu)


def test_ram_boundary_is_eight_gibibytes() -> None:
    at_limit, _script = _report(
        physical=8,
        brand=_MODERN,
        memory=(LEVE_MAX_RAM_BYTES, _GIB),
    )
    above, _script = _report(
        physical=8,
        brand=_MODERN,
        memory=(LEVE_MAX_RAM_BYTES + 1, _GIB),
    )
    assert at_limit.suggested_profile == "leve"
    assert above.suggested_profile == "padrao"
    assert "No CUDA or Apple Silicon GPU was detected." in above.suggestion_reason


def test_old_cpu_with_sixteen_gib_stays_leve() -> None:
    report, _script = _report(
        physical=4,
        brand="Intel(R) Core(TM) i7-4770 CPU @ 3.40GHz",
        memory=(16 * _GIB, 8 * _GIB),
    )
    assert report.suggested_profile == "leve"
    assert "generation 4" in report.suggestion_reason


def test_dual_core_modern_cpu_is_leve() -> None:
    report, _script = _report(
        physical=2,
        brand=_MODERN,
        memory=(16 * _GIB, 8 * _GIB),
    )
    assert report.suggested_profile == "leve"
    assert "2 physical cores" in report.suggestion_reason


def test_cuda_gpu_suggests_forte() -> None:
    report, script = _report(
        physical=8,
        brand=_MODERN,
        memory=(32 * _GIB, 16 * _GIB),
        nvidia="/usr/bin/nvidia-smi",
        nvidia_stdout="NVIDIA GeForce RTX 3060, 12288\n",
    )
    assert report.suggested_profile == "forte"
    assert report.gpu.kind == "cuda"
    assert report.gpu.name == "NVIDIA GeForce RTX 3060"
    assert report.gpu.memory_bytes == 12288 * 1024 * 1024
    assert "CUDA GPU NVIDIA GeForce RTX 3060" in report.suggestion_reason
    assert script.calls[-1] == nvidia_smi_argv("/usr/bin/nvidia-smi")


def test_nvidia_smi_picks_the_larger_gpu_and_accepts_unknown_memory() -> None:
    larger, recognized = parse_nvidia_smi("NVIDIA A, 1024\nNVIDIA B, 8192\n")
    assert recognized is True
    assert larger.count == 2
    assert larger.name == "NVIDIA B"
    assert larger.memory_bytes == 8192 * 1024 * 1024
    unknown, recognized = parse_nvidia_smi("NVIDIA C, [Not Supported]\n")
    assert recognized is True
    assert unknown.memory_bytes is None
    assert unknown.available is True
    empty, recognized = parse_nvidia_smi("no devices were found\n")
    assert recognized is False
    assert empty.available is False


def test_failed_nvidia_smi_is_not_a_gpu() -> None:
    report, _script = _report(
        physical=8,
        brand=_MODERN,
        memory=(32 * _GIB, _GIB),
        nvidia="/usr/bin/nvidia-smi",
        nvidia_stdout="NVIDIA GeForce RTX 3060, 12288\n",
        nvidia_code=1,
    )
    assert report.gpu.available is False
    assert report.suggested_profile == "padrao"


def test_apple_silicon_suggests_forte_without_nvidia_smi() -> None:
    report, script = _report(
        physical=8,
        brand="Apple M1",
        memory=(16 * _GIB, 8 * _GIB),
        system="Darwin",
        machine="arm64",
        nvidia=None,
    )
    assert report.gpu.kind == "videotoolbox"
    assert report.gpu.name == "Apple Silicon"
    assert report.suggested_profile == "forte"
    assert "VideoToolbox" in report.suggestion_reason
    assert script.calls == list(ffmpeg_argv("/usr/bin/ffmpeg"))


def test_eight_gigabyte_gpu_machine_stays_leve() -> None:
    report, _script = _report(
        physical=8,
        brand="Apple M1",
        memory=(8 * _GIB, _GIB),
        system="Darwin",
        machine="arm64",
    )
    assert report.gpu.available is True
    assert report.suggested_profile == "leve"
    assert "VideoToolbox" in report.suggestion_reason


def test_backup_on_the_same_disk_warns_without_failing() -> None:
    report, _script = _report(
        source=Path("/videos"),
        backup="/videos/copy",
        devices={"/videos": 9, "/videos/copy": 9},
    )
    assert report.backup.status == "same_disk"
    assert report.backup.same_disk is True
    assert BACKUP_SAME_DISK in report.warnings
    assert report.exit_code == 0
    assert "same disk" in render_plain(report)


def test_backup_on_another_disk_and_remote_and_omitted() -> None:
    distinct, _script = _report(
        source=Path("/videos"),
        backup="/mnt/cold",
        devices={"/videos": 1, "/mnt/cold": 2},
    )
    assert distinct.backup.status == "distinct"
    assert distinct.backup.same_disk is False
    assert BACKUP_SAME_DISK not in distinct.warnings

    remote, _script = _report(backup="gdrive:megila")
    assert remote.backup.status == "remote"
    assert remote.backup.same_disk is False
    assert remote.backup.destination == "gdrive:megila"

    omitted, _script = _report(backup=None)
    assert omitted.backup.status == "not_configured"
    assert omitted.backup.destination is None
    assert "no backup destination" in render_plain(omitted)

    unknown, _script = _report(
        source=Path("/videos"),
        backup="/mnt/missing",
        devices={},
    )
    assert unknown.backup.status == "unknown"
    assert BACKUP_SAME_DISK not in unknown.warnings


@pytest.mark.parametrize(
    ("value", "kind"),
    [
        (None, "not_configured"),
        ("  ", "not_configured"),
        ("gdrive:megila", "remote"),
        ("remote:", "remote"),
        ("/data/backup", "local"),
        ("backup", "local"),
        (r"C:\backup", "local"),
        ("C:/backup", "local"),
    ],
)
def test_destination_classification(value: str | None, kind: str) -> None:
    assert classify_destination(value) == kind


def test_temperatures_are_reported_and_absence_is_not_a_failure() -> None:
    readings = (
        TemperatureReading("coretemp", "Core 0", 61.0, 100.0),
        TemperatureReading("coretemp", "Package id 0", 70.5, 100.0),
    )
    report, _script = _report(temperatures=readings)
    assert report.temperatures_available is True
    assert report.temperatures == readings
    assert "70.5 C" in render_plain(report)
    assert report.exit_code == 0

    missing, _script = _report(temperatures=None)
    assert missing.temperatures_available is False
    assert missing.temperatures == ()
    assert "unavailable" in render_plain(missing)
    assert missing.warnings == ()


def test_unreadable_memory_and_disk_are_warnings() -> None:
    report, _script = _report(memory=None, disk=None, physical=8, brand=_MODERN)
    assert MEMORY_UNREADABLE in report.warnings
    assert DISK_UNREADABLE in report.warnings
    assert "could not read RAM" in render_plain(report)
    assert report.exit_code == 0
    assert report.suggested_profile == "padrao"


def test_plain_and_json_render_the_same_report() -> None:
    report, _script = _report(
        logical=4,
        physical=2,
        brand=_HASWELL,
        memory=(8 * _GIB, _GIB),
        filters=_FILTERS,
        build=_BUILD,
    )
    plain = render_plain(report)
    assert plain.startswith("megila doctor\n")
    assert "Check" in plain
    assert "suggested profile: leve" in plain
    assert "libvmaf_missing" in plain
    payload = json.loads(render_json(report))
    assert payload == report.to_dict()
    assert payload["ok"] is True
    assert payload["ffmpeg"]["libass"] is True
    assert payload["ffmpeg"]["libvmaf"] is False
    assert payload["cpu"]["brand"] == _HASWELL
    assert payload["memory"]["total_bytes"] == 8 * _GIB


def test_json_cli_exits_nonzero_when_libass_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report, _script = _report(filters="Filters:\n", build="configuration:\n")

    def fake(**_kwargs: object) -> object:
        return report

    monkeypatch.setattr("megila.cli.doctor.run_doctor", fake)
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["hard_failures"] == [LIBASS_MISSING]
    assert "megila doctor" not in result.stdout
    assert result.stdout.strip().startswith("{")


def test_plain_cli_and_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "doctor" in result.stdout
    help_result = runner.invoke(app, ["doctor", "--help"])
    assert help_result.exit_code == 0
    assert "--json" in help_result.stdout
    assert "--source" in help_result.stdout
    assert "--backup" in help_result.stdout


def test_source_flag_does_not_read_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def boom(_config_file: Path | None = None) -> object:
        raise AssertionError("settings should not load when --source is set")

    monkeypatch.setattr("megila.doctor.collect.load_settings", boom)
    report = run_doctor(
        source=tmp_path,
        backup=None,
        config_file=None,
        host=FakeHost(),
        runner=_runner(),
    )
    assert report.config_error is None
    assert report.disk.path == str(tmp_path)


def test_invalid_config_warns_and_uses_the_default_data_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(_config_file: Path | None = None) -> object:
        raise ConfigError(
            "Invalid configuration:\n- data_dir: must be an absolute path"
        )

    monkeypatch.setattr("megila.doctor.collect.load_settings", boom)
    report = run_doctor(
        source=None,
        backup="  ",
        config_file=None,
        host=FakeHost(disk=(str(default_data_dir()), 10, 5)),
        runner=_runner(),
    )
    assert CONFIG_INVALID in report.warnings
    assert report.config_error is not None
    assert "absolute path" in report.config_error
    assert report.disk.path == str(default_data_dir())
    assert report.exit_code == 0
    assert "config" in render_plain(report)


def test_doctor_sources_do_not_invoke_a_shell() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "megila"
    files = list((root / "doctor").rglob("*.py"))
    files.append(root / "cli" / "doctor.py")
    text = "\n".join(path.read_text(encoding="utf-8") for path in files)
    assert "shell=True" not in text
    assert "shell = True" not in text


def test_run_command_captures_text_and_a_missing_binary() -> None:
    completed = run_command(
        [sys.executable, "-c", "print('doctor-ok')"],
        timeout=10,
    )
    assert completed.returncode == 0
    assert "doctor-ok" in completed.stdout
    missing = run_command(["megila-missing-binary-xyz"], timeout=5)
    assert missing.returncode == 1
    assert missing.stderr


def test_run_command_times_out() -> None:
    completed = run_command(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        timeout=1,
    )
    assert completed.returncode == 1
    assert completed.stderr == "timed out"


def test_cpuinfo_brand_and_darwin_sysctl(tmp_path: Path) -> None:
    text = "processor\t: 0\nmodel name\t: Intel(R) Core(TM) i5-4258U CPU @ 2.40GHz\n"
    assert brand_from_cpuinfo(text) == _HASWELL
    cpuinfo = tmp_path / "cpuinfo"
    cpuinfo.write_text(text, encoding="utf-8")
    assert read_cpu_brand("Linux", cpuinfo=cpuinfo) == _HASWELL

    def sysctl(argv: Sequence[str], *, timeout: float) -> CommandResult:
        del timeout
        assert argv == ["sysctl", "-n", "machdep.cpu.brand_string"]
        return CommandResult(
            argv=tuple(argv), returncode=0, stdout="Apple M1\n", stderr=""
        )

    assert read_cpu_brand("Darwin", runner=sysctl) == "Apple M1"


def test_psutil_host_maps_a_fake_module(tmp_path: Path) -> None:
    class _Module:
        def cpu_count(self, logical: bool = True) -> int:
            return 8 if logical else 4

        def cpu_freq(self) -> SimpleNamespace:
            return SimpleNamespace(current=2000.0, min=800.0, max=3200.0)

        def virtual_memory(self) -> SimpleNamespace:
            return SimpleNamespace(total=16 * _GIB, available=3 * _GIB)

        def disk_usage(self, path: str) -> SimpleNamespace:
            del path
            return SimpleNamespace(total=50 * _GIB, free=12 * _GIB)

        def sensors_temperatures(self) -> dict[str, list[SimpleNamespace]]:
            return {
                "coretemp": [
                    SimpleNamespace(label="Package id 0", current=61.5, high=100.0),
                ]
            }

    host = PsutilHost(
        psutil_module=_Module(),
        system="Linux",
        machine="x86_64",
        brand=_MODERN,
        which_fn=lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None,
    )
    assert host.logical_cpus() == 8
    assert host.physical_cpus() == 4
    assert host.max_cpu_frequency_mhz() == 3200.0
    assert host.memory_bytes() == (16 * _GIB, 3 * _GIB)
    measured, total, free = host.disk_bytes(tmp_path / "missing" / "leaf") or ("", 0, 0)
    assert measured == str(tmp_path)
    assert total == 50 * _GIB
    assert free == 12 * _GIB
    assert host.device_id(tmp_path) == host.device_id(tmp_path / "missing")
    readings = host.temperatures()
    assert readings is not None
    assert readings[0].current_celsius == 61.5
    assert host.which("ffmpeg") == "/usr/bin/ffmpeg"
    assert host.which("nvidia-smi") is None

    class _NoSensors(_Module):
        def sensors_temperatures(self) -> dict[str, list[SimpleNamespace]]:
            raise NotImplementedError

    silent = PsutilHost(
        psutil_module=_NoSensors(),
        system="Linux",
        machine="x86_64",
        brand=None,
    )
    assert silent.temperatures() is None
    assert silent.cpu_brand() is None


def test_settings_supply_the_source_when_the_flag_is_omitted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "megila.doctor.collect.load_settings",
        lambda _config_file=None: SimpleNamespace(data_dir=tmp_path),
    )
    report = run_doctor(
        source=None,
        backup=None,
        config_file=tmp_path / "config.toml",
        host=FakeHost(),
        runner=_runner(),
    )
    assert report.config_error is None
    assert report.disk.path == str(tmp_path)


def test_relative_paths_are_resolved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    report = run_doctor(
        source=Path("clips"),
        backup="copies",
        config_file=None,
        host=FakeHost(devices={}),
        runner=_runner(),
    )
    assert report.disk.path == str(tmp_path / "clips")
    assert report.backup.destination == str(tmp_path / "copies")
    assert report.backup.status == "unknown"
    assert "could not compare devices" in render_plain(report)


def test_nvidia_parser_skips_noise_and_rejects_bad_memory() -> None:
    text = "\n".join(
        [
            "NVIDIA-SMI 550",
            "",
            "name, memory.total",
            "only-a-name",
            "NVIDIA C, [Not Supported]",
            "NVIDIA D, nope",
            "NVIDIA E, -5",
        ]
    )
    parsed, recognized = parse_nvidia_smi(text)
    assert recognized is True
    assert parsed.count == 3
    assert parsed.memory_bytes is None
    plain = render_plain(
        _report(
            nvidia="/usr/bin/nvidia-smi",
            nvidia_stdout="NVIDIA A, 100\nNVIDIA B, 4000\n",
            physical=8,
            memory=(32 * _GIB, _GIB),
        )[0]
    )
    assert "2 devices" in plain
    unknown = render_plain(
        _report(
            nvidia="/usr/bin/nvidia-smi",
            nvidia_stdout="NVIDIA C, [Not Supported]\n",
            physical=8,
            memory=(32 * _GIB, _GIB),
        )[0]
    )
    assert "CUDA NVIDIA C" in unknown


def test_light_cpu_phrases_and_forte_without_a_memory_reading() -> None:
    core_2, _script = _report(
        physical=4,
        brand="Intel(R) Core(TM)2 Duo CPU P8600 @ 2.40GHz",
        memory=(16 * _GIB, _GIB),
    )
    assert "Intel Core 2" in core_2.suggestion_reason
    single, _script = _report(physical=1, brand=None, memory=(16 * _GIB, _GIB))
    assert "1 physical core" in single.suggestion_reason
    forte, _script = _report(
        memory=None,
        physical=8,
        brand=_MODERN,
        nvidia="/usr/bin/nvidia-smi",
        nvidia_stdout="NVIDIA T, 2048\n",
    )
    assert forte.suggested_profile == "forte"
    assert "The CPU is outside the light class." in forte.suggestion_reason
    assert MEMORY_UNREADABLE in forte.warnings


def test_render_covers_missing_libraries_and_backup_rows() -> None:
    broken = "not a version " + ("x" * 400)
    missing, _script = _report(version=broken, version_code=1)
    assert missing.ffmpeg.error is not None
    assert missing.ffmpeg.error.endswith("...")
    assert len(missing.ffmpeg.error) == 300
    assert "ass" not in parse_filter_names(
        " ... ass               not-a-pad  ignored\n"
    )

    partial, _script = _report(
        filters=_FILTERS,
        build="configuration:\n",
        logical=None,
        physical=None,
        brand=None,
        frequency=None,
        memory=(16 * _GIB, None),
        disk=None,
        temperatures=(),
    )
    plain = render_plain(partial)
    assert "not built in" in plain
    assert "cpu information is not available" in plain
    assert "could not read RAM" not in plain
    assert "could not read free space" in plain
    assert "no readings" in plain

    distinct, _script = _report(
        source=Path("/videos"),
        backup="/mnt/cold",
        devices={"/videos": 1, "/mnt/cold": 2},
    )
    assert "different disk" in render_plain(distinct)
    apple, _script = _report(
        physical=8,
        brand="Apple M1",
        memory=(16 * _GIB, _GIB),
        system="Darwin",
        machine="arm64",
    )
    assert "Apple Silicon (VideoToolbox)" in render_plain(apple)


def test_cpu_facts_without_a_brand_can_still_be_light() -> None:
    assert cpu_is_light(
        CpuFacts(
            logical_cores=4,
            physical_cores=2,
            max_frequency_mhz=None,
            brand=None,
        )
    )
    assert not cpu_is_light(
        CpuFacts(
            logical_cores=8,
            physical_cores=4,
            max_frequency_mhz=None,
            brand=_MODERN,
        )
    )
