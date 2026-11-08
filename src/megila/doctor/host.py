"""Read CPU, memory, disk, sensors, and CPU brand from the local machine.

psutil is BSD-3-Clause. Doctor uses it for counts and sensors. Filesystem
identity uses ``st_dev`` so two paths can be compared without guessing a
mount table.
"""

from __future__ import annotations

import math
import platform
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import psutil

from megila.doctor.command import CommandRunner, run_command
from megila.doctor.facts import TemperatureReading

_MISSING: object = object()


class HostStats(Protocol):
    """The slice of the machine doctor knows how to read."""

    def logical_cpus(self) -> int | None:
        """Return logical CPU count, or None when the OS does not say."""
        ...

    def physical_cpus(self) -> int | None:
        """Return physical CPU count, or None when the OS does not say."""
        ...

    def cpu_brand(self) -> str | None:
        """Return the CPU brand string, or None."""
        ...

    def max_cpu_frequency_mhz(self) -> float | None:
        """Return the highest advertised frequency in MHz, or None."""
        ...

    def memory_bytes(self) -> tuple[int, int | None] | None:
        """Return ``(total, available)`` bytes, or None when unread."""
        ...

    def disk_bytes(self, path: Path) -> tuple[str, int, int] | None:
        """Return ``(measured path, total bytes, free bytes)``, or None."""
        ...

    def device_id(self, path: Path) -> int | None:
        """Return ``st_dev`` of ``path`` or its nearest existing ancestor."""
        ...

    def temperatures(self) -> tuple[TemperatureReading, ...] | None:
        """Return readings, an empty tuple, or None when unsupported."""
        ...

    def system_name(self) -> str:
        """Return ``platform.system()`` (``Linux``, ``Darwin``, ``Windows``)."""
        ...

    def machine_name(self) -> str:
        """Return ``platform.machine()`` (``x86_64``, ``arm64``, ...)."""
        ...

    def which(self, name: str) -> str | None:
        """Return an executable path for ``name``, or None."""
        ...


def brand_from_cpuinfo(text: str) -> str | None:
    """Return the first ``model name`` value from Linux ``/proc/cpuinfo``."""
    for line in text.splitlines():
        if line.lower().startswith("model name"):
            _label, separator, value = line.partition(":")
            if separator == "":
                continue
            brand = value.strip()
            if brand:
                return brand
    return None


def read_cpu_brand(
    system: str,
    *,
    cpuinfo: Path = Path("/proc/cpuinfo"),
    runner: CommandRunner = run_command,
) -> str | None:
    """Read a CPU brand from the OS, then fall back to ``platform.processor``."""
    if system == "Linux":
        try:
            text = cpuinfo.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        brand = brand_from_cpuinfo(text)
        if brand:
            return brand
    elif system == "Darwin":
        result = runner(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            timeout=2.0,
        )
        if result.returncode == 0:
            brand = result.stdout.strip()
            if brand:
                return brand
    processor = platform.processor().strip()
    if processor:
        return processor
    return None


def existing_ancestor(path: Path) -> Path | None:
    """Return ``path`` or the closest parent that exists."""
    current = path
    seen: set[Path] = set()
    while current not in seen:
        seen.add(current)
        if current.exists():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent
    return None


def device_id_of(path: Path) -> int | None:
    """Return ``st_dev`` for ``path`` or its nearest existing ancestor."""
    current = existing_ancestor(path)
    if current is None:
        return None
    try:
        return current.stat().st_dev
    except OSError:
        return None


class PsutilHost:
    """:class:`HostStats` backed by psutil, ``/proc``, and ``shutil.which``."""

    def __init__(
        self,
        *,
        psutil_module: Any = None,
        system: str | None = None,
        machine: str | None = None,
        brand: object = _MISSING,
        which_fn: Callable[[str], str | None] | None = None,
        brand_reader: Callable[[str], str | None] | None = None,
    ) -> None:
        self._psutil: Any = psutil if psutil_module is None else psutil_module
        self._system = platform.system() if system is None else system
        self._machine = platform.machine() if machine is None else machine
        self._brand = brand
        self._which = shutil.which if which_fn is None else which_fn
        self._brand_reader = read_cpu_brand if brand_reader is None else brand_reader

    def logical_cpus(self) -> int | None:
        return _positive_int(_call(self._psutil.cpu_count, logical=True))

    def physical_cpus(self) -> int | None:
        return _positive_int(_call(self._psutil.cpu_count, logical=False))

    def cpu_brand(self) -> str | None:
        if self._brand is not _MISSING:
            if isinstance(self._brand, str):
                stripped = self._brand.strip()
                return stripped or None
            return None
        return self._brand_reader(self._system)

    def max_cpu_frequency_mhz(self) -> float | None:
        try:
            freq = self._psutil.cpu_freq()
        except (AttributeError, NotImplementedError, OSError, RuntimeError):
            return None
        if freq is None:
            return None
        samples = freq if isinstance(freq, list) else [freq]
        maxima: list[float] = []
        for sample in samples:
            maximum = getattr(sample, "max", None)
            current = getattr(sample, "current", None)
            chosen = maximum if isinstance(maximum, (int, float)) else current
            if (
                isinstance(chosen, (int, float))
                and math.isfinite(chosen)
                and chosen > 0
            ):
                maxima.append(float(chosen))
        if not maxima:
            return None
        return max(maxima)

    def memory_bytes(self) -> tuple[int, int | None] | None:
        try:
            memory = self._psutil.virtual_memory()
        except (AttributeError, NotImplementedError, OSError, RuntimeError):
            return None
        total = getattr(memory, "total", None)
        if not isinstance(total, int) or total <= 0:
            return None
        available = getattr(memory, "available", None)
        if isinstance(available, int) and available >= 0:
            return (total, available)
        return (total, None)

    def disk_bytes(self, path: Path) -> tuple[str, int, int] | None:
        measured = existing_ancestor(path)
        if measured is None:
            return None
        try:
            usage = self._psutil.disk_usage(str(measured))
        except (AttributeError, NotImplementedError, OSError, RuntimeError):
            return None
        total = getattr(usage, "total", None)
        free = getattr(usage, "free", None)
        if not isinstance(total, int) or not isinstance(free, int):
            return None
        if total < 0 or free < 0:
            return None
        return (str(measured), total, free)

    def device_id(self, path: Path) -> int | None:
        return device_id_of(path)

    def temperatures(self) -> tuple[TemperatureReading, ...] | None:
        try:
            raw = self._psutil.sensors_temperatures()
        except (AttributeError, NotImplementedError, OSError, RuntimeError):
            return None
        if not isinstance(raw, dict):
            return None
        readings: list[TemperatureReading] = []
        for sensor, entries in raw.items():
            if not isinstance(entries, list):
                continue
            sensor_name = str(sensor)
            for entry in entries:
                reading = _temperature(sensor_name, entry)
                if reading is not None:
                    readings.append(reading)
        readings.sort(key=lambda item: (item.sensor, item.label, item.current_celsius))
        return tuple(readings)

    def system_name(self) -> str:
        return self._system

    def machine_name(self) -> str:
        return self._machine

    def which(self, name: str) -> str | None:
        found = self._which(name)
        if found is None or found == "":
            return None
        return found


def _call(function: Any, **kwargs: Any) -> Any:
    try:
        return function(**kwargs)
    except (AttributeError, NotImplementedError, OSError, RuntimeError):
        return None


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value <= 0:
        return None
    return value


def _temperature(sensor: str, entry: object) -> TemperatureReading | None:
    current = getattr(entry, "current", None)
    if isinstance(current, bool) or not isinstance(current, (int, float)):
        return None
    if not math.isfinite(current):
        return None
    label = str(getattr(entry, "label", "") or "").strip()
    if label == "":
        label = sensor
    high = getattr(entry, "high", None)
    high_celsius: float | None = None
    if (
        isinstance(high, (int, float))
        and not isinstance(high, bool)
        and math.isfinite(high)
    ):
        high_celsius = float(high)
    return TemperatureReading(
        sensor=sensor,
        label=label,
        current_celsius=float(current),
        high_celsius=high_celsius,
    )
