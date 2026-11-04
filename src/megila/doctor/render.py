"""Plain-text and JSON renderings of a doctor report.

Rich is not a runtime dependency, so the human report is aligned text.
``--json`` prints one object and nothing else.
"""

from __future__ import annotations

import json

from megila.doctor.facts import DoctorReport, format_gib

_HEADERS = ("Check", "Status", "Detail")


def render_plain(report: DoctorReport) -> str:
    """Return the human-readable report, without a trailing newline."""
    rows = [_HEADERS, *report_rows(report)]
    widths = [max(len(row[index]) for row in rows) for index in range(3)]
    lines = ["megila doctor", ""]
    for name, status, detail in rows:
        lines.append(f"{name:<{widths[0]}}  {status:<{widths[1]}}  {detail}")
    lines.append("")
    lines.append(f"suggested profile: {report.suggested_profile}")
    lines.append(report.suggestion_reason)
    lines.append("")
    lines.append(f"hard failures: {_codes(report.hard_failures)}")
    lines.append(f"warnings: {_codes(report.warnings)}")
    return "\n".join(lines)


def render_json(report: DoctorReport) -> str:
    """Return pretty-printed JSON, without a trailing newline."""
    return json.dumps(report.to_dict(), indent=2, ensure_ascii=False)


def report_rows(report: DoctorReport) -> list[tuple[str, str, str]]:
    """Return table rows shared by the plain renderer."""
    rows: list[tuple[str, str, str]] = []
    ffmpeg = report.ffmpeg
    if not ffmpeg.present:
        rows.append(("ffmpeg", "missing", ffmpeg.error or "not found on PATH"))
        rows.append(("libass", "missing", "requires ffmpeg"))
        rows.append(("libvmaf", "missing", "requires ffmpeg"))
        rows.append(("libx264", "missing", "requires ffmpeg"))
    else:
        version = ffmpeg.version or "unknown version"
        location = f"{version} ({ffmpeg.path})" if ffmpeg.path else version
        rows.append(("ffmpeg", "ok", location))
        rows.append(
            (
                "libass",
                _library_status(ffmpeg.libass, hard=True),
                _libass_detail(report),
            )
        )
        rows.append(
            (
                "libvmaf",
                _library_status(ffmpeg.libvmaf, hard=False),
                _libvmaf_detail(report),
            )
        )
        rows.append(
            (
                "libx264",
                _library_status(ffmpeg.libx264, hard=False),
                _libx264_detail(report),
            )
        )
    rows.append(("cpu", _cpu_status(report), _cpu_detail(report)))
    rows.append(
        (
            "memory",
            "ok" if report.memory.total_bytes is not None else "unavailable",
            _memory_detail(report),
        )
    )
    rows.append(
        (
            "disk",
            "ok" if report.disk.free_bytes is not None else "unavailable",
            _disk_detail(report),
        )
    )
    rows.append(("gpu", _gpu_status(report), _gpu_detail(report)))
    rows.append(
        ("temperature", _temperature_status(report), _temperature_detail(report))
    )
    rows.append(("backup", _backup_status(report), _backup_detail(report)))
    if report.config_error:
        rows.append(("config", "warn", " ".join(report.config_error.split())))
    return rows


def _codes(codes: tuple[str, ...]) -> str:
    if not codes:
        return "none"
    return ", ".join(codes)


def _library_status(present: bool, *, hard: bool) -> str:
    if present:
        return "ok"
    if hard:
        return "missing"
    return "warn"


def _evidence(*parts: str) -> str:
    found = [part for part in parts if part]
    if not found:
        return "not built in"
    return ", ".join(found)


def _libass_detail(report: DoctorReport) -> str:
    ffmpeg = report.ffmpeg
    return _evidence(
        "filter ass" if ffmpeg.libass_filter else "",
        "--enable-libass" if ffmpeg.libass_build else "",
    )


def _libvmaf_detail(report: DoctorReport) -> str:
    ffmpeg = report.ffmpeg
    return _evidence(
        "filter libvmaf" if ffmpeg.libvmaf_filter else "",
        "--enable-libvmaf" if ffmpeg.libvmaf_build else "",
    )


def _libx264_detail(report: DoctorReport) -> str:
    if report.ffmpeg.libx264_build:
        return "--enable-libx264"
    return "not built in"


def _cpu_status(report: DoctorReport) -> str:
    cpu = report.cpu
    if (
        cpu.logical_cores is None
        and cpu.physical_cores is None
        and cpu.brand is None
        and cpu.max_frequency_mhz is None
    ):
        return "unavailable"
    return "ok"


def _cpu_detail(report: DoctorReport) -> str:
    cpu = report.cpu
    parts: list[str] = []
    if cpu.logical_cores is not None:
        parts.append(f"{cpu.logical_cores} logical")
    if cpu.physical_cores is not None:
        parts.append(f"{cpu.physical_cores} physical")
    if cpu.max_frequency_mhz is not None:
        parts.append(f"up to {cpu.max_frequency_mhz:.0f} MHz")
    if cpu.brand:
        parts.append(cpu.brand)
    if not parts:
        return "cpu information is not available"
    return ", ".join(parts)


def _memory_detail(report: DoctorReport) -> str:
    memory = report.memory
    if memory.total_bytes is None:
        return "could not read RAM"
    total = f"{format_gib(memory.total_bytes)} total"
    if memory.available_bytes is None:
        return total
    return f"{total}, {format_gib(memory.available_bytes)} available"


def _disk_detail(report: DoctorReport) -> str:
    disk = report.disk
    if disk.free_bytes is None or disk.total_bytes is None:
        return f"could not read free space for {disk.path}"
    where = disk.measured_path or disk.path
    free = format_gib(disk.free_bytes)
    total = format_gib(disk.total_bytes)
    return f"{free} free of {total} on {where}"


def _gpu_status(report: DoctorReport) -> str:
    if report.gpu.available:
        return "ok"
    return "none"


def _gpu_detail(report: DoctorReport) -> str:
    gpu = report.gpu
    if gpu.kind == "cuda":
        name = gpu.name or "CUDA device"
        if gpu.count > 1:
            name = f"{gpu.count} devices, using {name}"
        if gpu.memory_bytes is None:
            return f"CUDA {name}"
        return f"CUDA {name}, {format_gib(gpu.memory_bytes)}"
    if gpu.kind == "videotoolbox":
        return "Apple Silicon (VideoToolbox)"
    return "no CUDA device and not Apple Silicon"


def _temperature_status(report: DoctorReport) -> str:
    if not report.temperatures_available:
        return "unavailable"
    return "ok"


def _temperature_detail(report: DoctorReport) -> str:
    if not report.temperatures_available:
        return "the OS does not expose sensors"
    if not report.temperatures:
        return "no readings"
    hottest = max(report.temperatures, key=lambda item: item.current_celsius)
    count = len(report.temperatures)
    noun = "reading" if count == 1 else "readings"
    return (
        f"{count} {noun}, hottest {hottest.current_celsius:.1f} C "
        f"({hottest.sensor} {hottest.label})"
    )


def _backup_status(report: DoctorReport) -> str:
    status = report.backup.status
    if status == "same_disk":
        return "warn"
    if status == "not_configured":
        return "skip"
    if status == "unknown":
        return "unavailable"
    return "ok"


def _backup_detail(report: DoctorReport) -> str:
    backup = report.backup
    if backup.status == "not_configured":
        return "no backup destination (pass --backup)"
    if backup.status == "remote":
        return f"rclone remote {backup.destination}"
    if backup.status == "same_disk":
        return f"same disk as the source ({backup.destination})"
    if backup.status == "distinct":
        return f"different disk from the source ({backup.destination})"
    return "could not compare devices"
