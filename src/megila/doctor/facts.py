"""Facts gathered by ``megila doctor`` and the machine-profile suggestion.

``leve``, ``padrao``, and ``forte`` describe headroom on the computer. They
are not content profiles (prompts, glossary, provider) and they do not change
the quality profile from ADR 0004.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

LEVE_MAX_RAM_BYTES: int = 8 * 1024**3
LIGHT_MAX_PHYSICAL_CORES: int = 2
# Haswell (4th generation) is the 2013 i5 class used as the light reference.
HASWELL_GENERATION: int = 4

QUALITY_NOTE: str = (
    "The quality profile stays large-v3 int8 and libx264 preset slow CRF 19. "
    "This name describes machine headroom."
)

MachineProfileName = Literal["leve", "padrao", "forte"]
GpuKind = Literal["none", "cuda", "videotoolbox"]
BackupStatus = Literal["not_configured", "remote", "same_disk", "distinct", "unknown"]

FFMPEG_MISSING = "ffmpeg_missing"
LIBASS_MISSING = "libass_missing"
LIBVMAF_MISSING = "libvmaf_missing"
LIBX264_MISSING = "libx264_missing"
BACKUP_SAME_DISK = "backup_same_disk"
CONFIG_INVALID = "config_invalid"
DISK_UNREADABLE = "disk_unreadable"
MEMORY_UNREADABLE = "memory_unreadable"

_CORE_I = re.compile(r"\bi[3579]-(\d{3,5})[a-z0-9]*\b", re.IGNORECASE)
_CORE_2 = re.compile(r"core(?:\(tm\))?\s*2\b", re.IGNORECASE)


def format_gib(num_bytes: int) -> str:
    """Format ``num_bytes`` as gibibytes with one decimal place."""
    return f"{num_bytes / (1024**3):.1f} GiB"


def intel_core_generation(brand: str | None) -> int | None:
    """Return an Intel Core generation, or None when ``brand`` is not one.

    Core 2 is reported as ``0``. A 4-digit model whose first digit is ``1``
    is a 10th-generation-or-later part (``i5-1035G1`` is 10, ``i5-4258U`` is
    4). Five-digit models use the first two digits (``i5-12400`` is 12).
    """
    if brand is None or brand.strip() == "":
        return None
    if _CORE_2.search(brand):
        return 0
    match = _CORE_I.search(brand)
    if match is None:
        return None
    digits = match.group(1)
    if len(digits) == 3:
        return 1
    if len(digits) == 5:
        return int(digits[:2])
    if digits[0] == "1":
        return int(digits[:2])
    return int(digits[0])


def cpu_is_light(cpu: CpuFacts) -> bool:
    """Return whether the CPU matches the light-machine class.

    That class is a dual-core (or smaller) chip, or an Intel Core from the
    Core 2 era through Haswell. The reference is a 2013 i5.
    """
    if (
        cpu.physical_cores is not None
        and 0 < cpu.physical_cores <= LIGHT_MAX_PHYSICAL_CORES
    ):
        return True
    generation = intel_core_generation(cpu.brand)
    return generation is not None and generation <= HASWELL_GENERATION


@dataclass(frozen=True)
class CpuFacts:
    """CPU counts, peak frequency, and the brand string when one is known."""

    logical_cores: int | None
    physical_cores: int | None
    max_frequency_mhz: float | None
    brand: str | None


@dataclass(frozen=True)
class MemoryFacts:
    """Installed RAM and the amount the OS currently reports as available."""

    total_bytes: int | None
    available_bytes: int | None


@dataclass(frozen=True)
class DiskFacts:
    """Free space for ``path``. ``measured_path`` is the existing ancestor."""

    path: str
    measured_path: str | None
    total_bytes: int | None
    free_bytes: int | None


@dataclass(frozen=True)
class GpuFacts:
    """A CUDA device or Apple Silicon VideoToolbox, when one was detected."""

    available: bool
    kind: GpuKind
    name: str | None
    memory_bytes: int | None
    count: int


@dataclass(frozen=True)
class TemperatureReading:
    """One sensor reading in degrees Celsius."""

    sensor: str
    label: str
    current_celsius: float
    high_celsius: float | None


@dataclass(frozen=True)
class FfmpegFacts:
    """What ``ffmpeg -filters`` and ``ffmpeg -buildconf`` said about the build."""

    present: bool
    path: str | None
    version: str | None
    libass_filter: bool
    libass_build: bool
    libvmaf_filter: bool
    libvmaf_build: bool
    libx264_build: bool
    error: str | None

    @property
    def libass(self) -> bool:
        """True when the ``ass`` filter or ``--enable-libass`` was seen."""
        return self.libass_filter or self.libass_build

    @property
    def libvmaf(self) -> bool:
        """True when the ``libvmaf`` filter or ``--enable-libvmaf`` was seen."""
        return self.libvmaf_filter or self.libvmaf_build

    @property
    def libx264(self) -> bool:
        """True when ``--enable-libx264`` was seen."""
        return self.libx264_build


@dataclass(frozen=True)
class BackupFacts:
    """Whether the backup destination shares a filesystem with the source."""

    source: str
    destination: str | None
    same_disk: bool | None
    status: BackupStatus


@dataclass(frozen=True)
class DoctorReport:
    """Full doctor result. ``ok`` is false when a hard requirement is missing."""

    ffmpeg: FfmpegFacts
    cpu: CpuFacts
    memory: MemoryFacts
    disk: DiskFacts
    gpu: GpuFacts
    temperatures: tuple[TemperatureReading, ...]
    temperatures_available: bool
    backup: BackupFacts
    suggested_profile: MachineProfileName
    suggestion_reason: str
    hard_failures: tuple[str, ...]
    warnings: tuple[str, ...]
    config_error: str | None = None

    @property
    def ok(self) -> bool:
        """True when ffmpeg is usable and the build includes libass."""
        return len(self.hard_failures) == 0

    @property
    def exit_code(self) -> int:
        """Process status: ``0`` when :attr:`ok`, otherwise ``1``."""
        if self.ok:
            return 0
        return 1

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready mapping. Paths are strings. Bytes are integers."""
        return {
            "ok": self.ok,
            "suggested_profile": self.suggested_profile,
            "suggestion_reason": self.suggestion_reason,
            "hard_failures": list(self.hard_failures),
            "warnings": list(self.warnings),
            "config_error": self.config_error,
            "ffmpeg": {
                "present": self.ffmpeg.present,
                "path": self.ffmpeg.path,
                "version": self.ffmpeg.version,
                "libass": self.ffmpeg.libass,
                "libvmaf": self.ffmpeg.libvmaf,
                "libx264": self.ffmpeg.libx264,
                "libass_filter": self.ffmpeg.libass_filter,
                "libass_build": self.ffmpeg.libass_build,
                "libvmaf_filter": self.ffmpeg.libvmaf_filter,
                "libvmaf_build": self.ffmpeg.libvmaf_build,
                "libx264_build": self.ffmpeg.libx264_build,
                "error": self.ffmpeg.error,
            },
            "cpu": {
                "logical_cores": self.cpu.logical_cores,
                "physical_cores": self.cpu.physical_cores,
                "max_frequency_mhz": self.cpu.max_frequency_mhz,
                "brand": self.cpu.brand,
            },
            "memory": {
                "total_bytes": self.memory.total_bytes,
                "available_bytes": self.memory.available_bytes,
            },
            "disk": {
                "path": self.disk.path,
                "measured_path": self.disk.measured_path,
                "total_bytes": self.disk.total_bytes,
                "free_bytes": self.disk.free_bytes,
            },
            "gpu": {
                "available": self.gpu.available,
                "kind": self.gpu.kind,
                "name": self.gpu.name,
                "memory_bytes": self.gpu.memory_bytes,
                "count": self.gpu.count,
            },
            "temperatures_available": self.temperatures_available,
            "temperatures": [
                {
                    "sensor": reading.sensor,
                    "label": reading.label,
                    "current_celsius": reading.current_celsius,
                    "high_celsius": reading.high_celsius,
                }
                for reading in self.temperatures
            ],
            "backup": {
                "source": self.backup.source,
                "destination": self.backup.destination,
                "same_disk": self.backup.same_disk,
                "status": self.backup.status,
            },
        }


def absent_ffmpeg(error: str, *, path: str | None = None) -> FfmpegFacts:
    """Build facts for an ffmpeg binary that cannot be used."""
    return FfmpegFacts(
        present=False,
        path=path,
        version=None,
        libass_filter=False,
        libass_build=False,
        libvmaf_filter=False,
        libvmaf_build=False,
        libx264_build=False,
        error=error,
    )


def suggest_profile(
    *,
    memory_total: int | None,
    cpu: CpuFacts,
    gpu: GpuFacts,
) -> tuple[MachineProfileName, str]:
    """Choose ``leve``, ``padrao``, or ``forte`` and explain the choice.

    ``leve`` wins when RAM is at most 8 GiB or the CPU is in the light class,
    including when a GPU is also present. Otherwise a CUDA or Apple Silicon
    GPU selects ``forte``. The remaining machines select ``padrao``.
    """
    light = _light_reasons(memory_total, cpu, gpu)
    if light:
        reason = (
            "Suggested machine profile 'leve'. "
            f"{'; '.join(light)}. "
            "Reference machine: an 8 GB 2013 i5 MacBook. "
            f"{QUALITY_NOTE}"
        )
        return "leve", reason
    if gpu.available:
        if memory_total is None:
            room = "The CPU is outside the light class."
        else:
            room = "RAM is above 8 GiB and the CPU is outside the light class."
        reason = (
            "Suggested machine profile 'forte'. "
            f"{_gpu_phrase(gpu)}. "
            f"{room} "
            f"{QUALITY_NOTE}"
        )
        return "forte", reason
    if memory_total is None:
        headroom = "No light-machine limit was detected"
    else:
        headroom = f"RAM is {format_gib(memory_total)}, above 8 GiB"
    reason = (
        "Suggested machine profile 'padrao'. "
        f"{headroom}, and the CPU is outside the light class. "
        "No CUDA or Apple Silicon GPU was detected. "
        f"{QUALITY_NOTE}"
    )
    return "padrao", reason


def _light_reasons(
    memory_total: int | None,
    cpu: CpuFacts,
    gpu: GpuFacts,
) -> list[str]:
    reasons: list[str] = []
    if memory_total is not None and memory_total <= LEVE_MAX_RAM_BYTES:
        reasons.append(f"{format_gib(memory_total)} RAM is at or below 8 GiB")
    if cpu_is_light(cpu):
        reasons.append(_cpu_light_phrase(cpu))
    if reasons and gpu.available:
        reasons.append(f"{_gpu_phrase(gpu)} remains visible in the report")
    return reasons


def _cpu_light_phrase(cpu: CpuFacts) -> str:
    parts: list[str] = []
    cores = cpu.physical_cores
    if cores is not None and 0 < cores <= LIGHT_MAX_PHYSICAL_CORES:
        noun = "core" if cores == 1 else "cores"
        parts.append(f"{cores} physical {noun}")
    generation = intel_core_generation(cpu.brand)
    if generation == 0:
        parts.append("Intel Core 2")
    elif generation is not None and generation <= HASWELL_GENERATION:
        parts.append(f"Intel Core generation {generation}")
    if not parts:
        parts.append("a light CPU")
    phrase = " and ".join(parts)
    if cpu.brand:
        return f"CPU has {phrase} ({cpu.brand})"
    return f"CPU has {phrase}"


def _gpu_phrase(gpu: GpuFacts) -> str:
    if gpu.kind == "cuda":
        if gpu.name:
            return f"CUDA GPU {gpu.name}"
        return "CUDA GPU"
    if gpu.kind == "videotoolbox":
        return "Apple Silicon VideoToolbox"
    return "GPU"
