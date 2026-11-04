"""Collect a :class:`~megila.doctor.facts.DoctorReport` from a host and programs."""

from __future__ import annotations

import re
from pathlib import Path

from megila.config import ConfigError, default_data_dir, load_settings
from megila.doctor.command import CommandRunner, combined_output, run_command
from megila.doctor.facts import (
    BACKUP_SAME_DISK,
    CONFIG_INVALID,
    DISK_UNREADABLE,
    FFMPEG_MISSING,
    LIBASS_MISSING,
    LIBVMAF_MISSING,
    LIBX264_MISSING,
    MEMORY_UNREADABLE,
    BackupFacts,
    BackupStatus,
    CpuFacts,
    DiskFacts,
    DoctorReport,
    FfmpegFacts,
    GpuFacts,
    MemoryFacts,
    suggest_profile,
)
from megila.doctor.ffmpeg import inspect_ffmpeg
from megila.doctor.host import HostStats, PsutilHost

NVIDIA_SMI_TIMEOUT_SECONDS = 5.0
NVIDIA_SMI_ARGV: tuple[str, ...] = (
    "--query-gpu=name,memory.total",
    "--format=csv,noheader,nounits",
)
_REMOTE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}:")
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")
_MIB = 1024**2


def classify_destination(value: str | None) -> str:
    """Return ``not_configured``, ``remote``, or ``local``.

    An rclone remote looks like ``gdrive:megila``. A Windows drive
    (``C:\\data``) stays local. An empty value is not configured.
    """
    if value is None:
        return "not_configured"
    stripped = value.strip()
    if stripped == "":
        return "not_configured"
    if _WINDOWS_DRIVE.match(stripped):
        return "local"
    if _REMOTE.match(stripped):
        return "remote"
    return "local"


def parse_nvidia_smi(text: str) -> tuple[GpuFacts, bool]:
    """Parse ``nvidia-smi --query-gpu=name,memory.total`` CSV.

    The bool is False when no GPU row was recognized. Memory is MiB in the
    query; this function stores bytes. ``[Not Supported]`` keeps the GPU and
    leaves memory empty.
    """
    found: list[tuple[str, int | None]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if line == "" or line.lower().startswith("nvidia-smi"):
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 2:
            continue
        name = ",".join(parts[:-1]).strip()
        if name == "" or name.lower() == "name":
            continue
        found.append((name, _mib_to_bytes(parts[-1])))
    if not found:
        return _no_gpu(), False
    named = [item for item in found if item[1] is not None]
    pool = named or found
    best = max(pool, key=lambda item: item[1] or 0)
    return (
        GpuFacts(
            available=True,
            kind="cuda",
            name=best[0],
            memory_bytes=best[1],
            count=len(found),
        ),
        True,
    )


def collect_report(
    host: HostStats,
    runner: CommandRunner,
    *,
    source: Path,
    backup: str | None,
    config_error: str | None = None,
) -> DoctorReport:
    """Build a report. ``host`` and ``runner`` are the simulated-system seam."""
    cpu = CpuFacts(
        logical_cores=host.logical_cpus(),
        physical_cores=host.physical_cpus(),
        max_frequency_mhz=host.max_cpu_frequency_mhz(),
        brand=host.cpu_brand(),
    )
    memory, memory_ok = _memory(host)
    disk, disk_ok = _disk(host, source)
    temperatures = host.temperatures()
    temperatures_available = temperatures is not None
    ffmpeg = inspect_ffmpeg(host.which("ffmpeg"), runner)
    gpu = _gpu(host, runner)
    backup_facts = _backup(host, source, backup)
    profile, reason = suggest_profile(
        memory_total=memory.total_bytes,
        cpu=cpu,
        gpu=gpu,
    )
    hard = _hard_failures(ffmpeg)
    warnings = _warnings(
        ffmpeg=ffmpeg,
        memory_ok=memory_ok,
        disk_ok=disk_ok,
        backup_facts=backup_facts,
        config_error=config_error,
    )
    return DoctorReport(
        ffmpeg=ffmpeg,
        cpu=cpu,
        memory=memory,
        disk=disk,
        gpu=gpu,
        temperatures=() if temperatures is None else temperatures,
        temperatures_available=temperatures_available,
        backup=backup_facts,
        suggested_profile=profile,
        suggestion_reason=reason,
        hard_failures=hard,
        warnings=warnings,
        config_error=config_error,
    )


def run_doctor(
    *,
    source: Path | None,
    backup: str | None,
    config_file: Path | None,
    host: HostStats | None = None,
    runner: CommandRunner | None = None,
) -> DoctorReport:
    """Resolve the source directory, then collect a report from the machine.

    ``--source`` wins. Otherwise settings supply ``data_dir``. An invalid
    configuration file does not stop the hardware checks: the default data
    directory is used and the report carries ``config_invalid``.
    """
    resolved, config_error = resolve_source(source, config_file)
    return collect_report(
        PsutilHost() if host is None else host,
        run_command if runner is None else runner,
        source=resolved,
        backup=backup,
        config_error=config_error,
    )


def resolve_source(
    source: Path | None,
    config_file: Path | None,
) -> tuple[Path, str | None]:
    """Return the directory to measure and a config error, if loading failed."""
    if source is not None:
        return _absolute(source), None
    try:
        settings = load_settings(config_file)
    except ConfigError as exc:
        return default_data_dir(), str(exc)
    return settings.data_dir, None


def _absolute(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_absolute():
        return expanded
    return Path.cwd() / expanded


def _memory(host: HostStats) -> tuple[MemoryFacts, bool]:
    raw = host.memory_bytes()
    if raw is None:
        return MemoryFacts(total_bytes=None, available_bytes=None), False
    return MemoryFacts(total_bytes=raw[0], available_bytes=raw[1]), True


def _disk(host: HostStats, source: Path) -> tuple[DiskFacts, bool]:
    raw = host.disk_bytes(source)
    if raw is None:
        return (
            DiskFacts(
                path=str(source),
                measured_path=None,
                total_bytes=None,
                free_bytes=None,
            ),
            False,
        )
    measured, total, free = raw
    return (
        DiskFacts(
            path=str(source),
            measured_path=measured,
            total_bytes=total,
            free_bytes=free,
        ),
        True,
    )


def _gpu(host: HostStats, runner: CommandRunner) -> GpuFacts:
    nvidia = host.which("nvidia-smi")
    if nvidia is not None:
        result = runner(
            [nvidia, *NVIDIA_SMI_ARGV],
            timeout=NVIDIA_SMI_TIMEOUT_SECONDS,
        )
        parsed, recognized = parse_nvidia_smi(combined_output(result))
        if result.returncode == 0 and recognized:
            return parsed
    if _apple_silicon(host):
        return GpuFacts(
            available=True,
            kind="videotoolbox",
            name="Apple Silicon",
            memory_bytes=None,
            count=1,
        )
    return _no_gpu()


def _apple_silicon(host: HostStats) -> bool:
    if host.system_name().casefold() != "darwin":
        return False
    machine = host.machine_name().casefold()
    return machine in {"arm64", "aarch64"}


def _backup(host: HostStats, source: Path, backup: str | None) -> BackupFacts:
    kind = classify_destination(backup)
    source_text = str(source)
    if kind == "not_configured" or backup is None:
        return BackupFacts(
            source=source_text,
            destination=None,
            same_disk=None,
            status="not_configured",
        )
    destination = backup.strip()
    if kind == "remote":
        return BackupFacts(
            source=source_text,
            destination=destination,
            same_disk=False,
            status="remote",
        )
    dest_path = _absolute(Path(destination))
    source_id = host.device_id(source)
    dest_id = host.device_id(dest_path)
    status: BackupStatus
    same: bool | None
    if source_id is None or dest_id is None:
        status = "unknown"
        same = None
    elif source_id == dest_id:
        status = "same_disk"
        same = True
    else:
        status = "distinct"
        same = False
    return BackupFacts(
        source=source_text,
        destination=str(dest_path),
        same_disk=same,
        status=status,
    )


def _hard_failures(ffmpeg: FfmpegFacts) -> tuple[str, ...]:
    if not ffmpeg.present:
        return (FFMPEG_MISSING,)
    if not ffmpeg.libass:
        return (LIBASS_MISSING,)
    return ()


def _warnings(
    *,
    ffmpeg: FfmpegFacts,
    memory_ok: bool,
    disk_ok: bool,
    backup_facts: BackupFacts,
    config_error: str | None,
) -> tuple[str, ...]:
    found: list[str] = []
    if config_error is not None:
        found.append(CONFIG_INVALID)
    if not memory_ok:
        found.append(MEMORY_UNREADABLE)
    if not disk_ok:
        found.append(DISK_UNREADABLE)
    if ffmpeg.present and not ffmpeg.libvmaf:
        found.append(LIBVMAF_MISSING)
    if ffmpeg.present and not ffmpeg.libx264:
        found.append(LIBX264_MISSING)
    if backup_facts.status == "same_disk":
        found.append(BACKUP_SAME_DISK)
    return tuple(found)


def _no_gpu() -> GpuFacts:
    return GpuFacts(
        available=False,
        kind="none",
        name=None,
        memory_bytes=None,
        count=0,
    )


def _mib_to_bytes(field: str) -> int | None:
    if field.startswith("["):
        return None
    try:
        mib = float(field)
    except ValueError:
        return None
    if mib < 0:
        return None
    return int(mib * _MIB)


def nvidia_smi_argv(path: str) -> tuple[str, ...]:
    """Return the nvidia-smi argv doctor uses."""
    return (path, *NVIDIA_SMI_ARGV)
