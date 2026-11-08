#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Fail a run when Megila coverage misses a floor or falls against main.

The percentage is the statement-plus-branch ratio coverage.py reports as
``percent_covered``. Core packages with no executable lines have no
percentage: an empty package does not fail the 90% floor. Comparison
against main uses a committed baseline, rounded to two decimal places.
A drop of more than 1.00 point fails. A drop of exactly 1.00 does not.
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

FLOOR_TOTAL = 80.0
FLOOR_CORE = 90.0
MAX_DROP = 1.0
BASELINE_VERSION = 1
SAMPLE_TEST_NAME = "test_generated_clip_is_deterministic_and_matches_probe"
CORE_PACKAGES: tuple[str, ...] = (
    "megila.config",
    "megila.jobs",
    "megila.plugins",
    "megila.stages",
)
_PATH_MARKERS = frozenset({"src", "site-packages"})


class CoverageDataError(ValueError):
    """Raised when a coverage report or baseline cannot be read."""


@dataclass(frozen=True)
class _Counts:
    statements: int = 0
    covered_statements: int = 0
    branches: int = 0
    covered_branches: int = 0

    def add(self, other: _Counts) -> _Counts:
        return _Counts(
            self.statements + other.statements,
            self.covered_statements + other.covered_statements,
            self.branches + other.branches,
            self.covered_branches + other.covered_branches,
        )

    def percent(self) -> float | None:
        denominator = self.statements + self.branches
        if denominator == 0:
            return None
        covered = self.covered_statements + self.covered_branches
        return 100.0 * covered / denominator


@dataclass(frozen=True)
class Measurement:
    """Coverage measured from one pytest-cov JSON report."""

    total: float
    core: float | None
    packages: dict[str, float | None]


@dataclass(frozen=True)
class Baseline:
    """Numbers stored in ``.github/coverage-baseline.json``."""

    version: int
    total: float
    core: float | None
    packages: dict[str, float | None]


def points(value: float) -> float:
    """Round a percentage to the two decimals the gate compares."""

    return round(value, 2)


def _rounded(value: float | None) -> float | None:
    if value is None:
        return None
    return points(value)


def format_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{points(value):.2f}%"


def normalize_package_path(path: str) -> str | None:
    """Return ``megila/...`` for a coverage path, ignoring the repo checkout."""

    parts = tuple(
        part for part in path.replace("\\", "/").split("/") if part not in ("", ".")
    )
    marker_at: int | None = None
    for index, part in enumerate(parts):
        if part in _PATH_MARKERS:
            marker_at = index
    if (
        marker_at is not None
        and marker_at + 1 < len(parts)
        and parts[marker_at + 1] == "megila"
    ):
        return "/".join(parts[marker_at + 1 :])
    if "megila" in parts:
        index = len(parts) - 1 - parts[::-1].index("megila")
        return "/".join(parts[index:])
    return None


def core_package_for(normalized: str) -> str | None:
    """Map a package path to one core package. ``jobs.queue`` counts as jobs."""

    parts = normalized.split("/")
    if len(parts) < 2 or parts[0] != "megila":
        return None
    if len(parts) == 2:
        module = parts[1].removesuffix(".py")
        dotted = "megila" if module == "__init__" else f"megila.{module}"
    else:
        dotted = "megila." + ".".join(parts[1:-1])
    match: str | None = None
    for name in CORE_PACKAGES:
        if (dotted == name or dotted.startswith(name + ".")) and (
            match is None or len(name) > len(match)
        ):
            match = name
    return match


def _object_dict(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise CoverageDataError(f"{label} is not a JSON object")
    typed: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise CoverageDataError(f"{label} has a non-string key")
        typed[key] = item
    return typed


def _count(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise CoverageDataError(f"{label} is not a count")
    if isinstance(value, float) and not value.is_integer():
        raise CoverageDataError(f"{label} is not a whole number")
    return int(value)


def _counts_from_summary(summary: dict[str, object], label: str) -> _Counts:
    return _Counts(
        statements=_count(summary.get("num_statements"), f"{label} num_statements"),
        covered_statements=_count(
            summary.get("covered_lines"), f"{label} covered_lines"
        ),
        branches=_count(summary.get("num_branches"), f"{label} num_branches"),
        covered_branches=_count(
            summary.get("covered_branches"), f"{label} covered_branches"
        ),
    )


def measurement_from_json(document: dict[str, object]) -> Measurement:
    files = _object_dict(document.get("files"), "coverage files")
    total = _Counts()
    buckets = {name: _Counts() for name in CORE_PACKAGES}
    for path, info in files.items():
        normalized = normalize_package_path(path)
        if normalized is None:
            continue
        summary = _object_dict(
            _object_dict(info, path).get("summary"), f"{path} summary"
        )
        counts = _counts_from_summary(summary, path)
        total = total.add(counts)
        package = core_package_for(normalized)
        if package is not None:
            buckets[package] = buckets[package].add(counts)
    measured_total = total.percent()
    if measured_total is None:
        raise CoverageDataError("coverage report has no measured statements")
    core_counts = _Counts()
    packages: dict[str, float | None] = {}
    for name in CORE_PACKAGES:
        packages[name] = buckets[name].percent()
        core_counts = core_counts.add(buckets[name])
    return Measurement(
        total=measured_total,
        core=core_counts.percent(),
        packages=packages,
    )


def load_coverage(path: Path) -> Measurement:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CoverageDataError(f"cannot read coverage report {path}: {exc}") from exc
    return measurement_from_json(_object_dict(raw, "coverage report"))


def _percent_value(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise CoverageDataError(f"{label} is not a percentage")
    number = float(value)
    if number < 0 or number > 100:
        raise CoverageDataError(f"{label} is outside 0..100")
    return number


def _optional_percent(value: object, label: str) -> float | None:
    if value is None:
        return None
    return _percent_value(value, label)


def baseline_from_measurement(measured: Measurement) -> Baseline:
    return Baseline(
        version=BASELINE_VERSION,
        total=points(measured.total),
        core=_rounded(measured.core),
        packages={name: _rounded(value) for name, value in measured.packages.items()},
    )


def dump_baseline(baseline: Baseline) -> str:
    payload: dict[str, object] = {
        "version": baseline.version,
        "total": points(baseline.total),
        "core": _rounded(baseline.core),
        "packages": {name: _rounded(baseline.packages[name]) for name in CORE_PACKAGES},
    }
    return json.dumps(payload, indent=2) + "\n"


def load_baseline(path: Path) -> Baseline:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CoverageDataError(f"cannot read baseline {path}: {exc}") from exc
    document = _object_dict(raw, f"baseline {path}")
    allowed = {"version", "total", "core", "packages"}
    unknown = sorted(set(document) - allowed)
    if unknown:
        raise CoverageDataError(f"baseline {path} has unknown keys: {unknown}")
    version = document.get("version")
    if version != BASELINE_VERSION:
        raise CoverageDataError(f"baseline {path} version must be {BASELINE_VERSION}")
    packages = _object_dict(document.get("packages"), f"baseline {path} packages")
    if set(packages) != set(CORE_PACKAGES):
        raise CoverageDataError(
            f"baseline {path} packages must be {list(CORE_PACKAGES)}"
        )
    return Baseline(
        version=BASELINE_VERSION,
        total=_percent_value(document.get("total"), f"baseline {path} total"),
        core=_optional_percent(document.get("core"), f"baseline {path} core"),
        packages={
            name: _optional_percent(packages[name], f"baseline {path} {name}")
            for name in CORE_PACKAGES
        },
    )


def _floor_failures(measured: Measurement) -> list[str]:
    failures: list[str] = []
    if points(measured.total) < FLOOR_TOTAL:
        failures.append(
            f"total coverage {format_percent(measured.total)} is below "
            f"the {FLOOR_TOTAL:.0f}% floor"
        )
    if measured.core is not None and points(measured.core) < FLOOR_CORE:
        failures.append(
            f"core coverage {format_percent(measured.core)} is below "
            f"the {FLOOR_CORE:.0f}% floor"
        )
    for name in CORE_PACKAGES:
        value = measured.packages[name]
        if value is not None and points(value) < FLOOR_CORE:
            failures.append(
                f"{name} coverage {format_percent(value)} is below "
                f"the {FLOOR_CORE:.0f}% floor"
            )
    return failures


def _drop_failure(
    reference: float | None, measured: float | None, label: str
) -> str | None:
    if reference is None or measured is None:
        return None
    delta = points(reference) - points(measured)
    if delta <= MAX_DROP:
        return None
    return (
        f"{label} dropped {delta:.2f} points from the main baseline "
        f"({format_percent(reference)} -> {format_percent(measured)}); "
        f"a drop of more than {MAX_DROP:.0f} point blocks the change"
    )


def _drift_failure(
    committed: float | None, measured: float | None, label: str
) -> str | None:
    if committed is None and measured is None:
        return None
    if committed is None or measured is None:
        return (
            f"{label} baseline is {format_percent(committed)} but the "
            f"measurement is {format_percent(measured)}; update "
            ".github/coverage-baseline.json"
        )
    delta = abs(points(committed) - points(measured))
    if delta <= MAX_DROP:
        return None
    return (
        f"{label} baseline {format_percent(committed)} differs from the "
        f"measurement {format_percent(measured)} by {delta:.2f} points; "
        "update .github/coverage-baseline.json"
    )


def evaluate(
    measured: Measurement, committed: Baseline, reference: Baseline
) -> list[str]:
    """Return human-readable failures. An empty list means the run passes."""

    failures = _floor_failures(measured)
    for label, ref, current, recorded in (
        ("total", reference.total, measured.total, committed.total),
        ("core", reference.core, measured.core, committed.core),
    ):
        dropped = _drop_failure(ref, current, label)
        if dropped is not None:
            failures.append(dropped)
        drifted = _drift_failure(recorded, current, label)
        if drifted is not None:
            failures.append(drifted)
    for name in CORE_PACKAGES:
        dropped = _drop_failure(reference.packages[name], measured.packages[name], name)
        if dropped is not None:
            failures.append(dropped)
        drifted = _drift_failure(
            committed.packages[name], measured.packages[name], name
        )
        if drifted is not None:
            failures.append(drifted)
    return failures


def junit_sample_problem(path: Path) -> str | None:
    """Fail when the synthetic-clip integration test did not actually run."""

    if not path.is_file():
        return f"junit report not found: {path}"
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        return f"junit report {path} is not XML: {exc}"
    found = False
    for case in tree.iter("testcase"):
        if case.get("name") != SAMPLE_TEST_NAME:
            continue
        found = True
        if case.find("skipped") is not None:
            return (
                f"{SAMPLE_TEST_NAME} was skipped; install ffmpeg and espeak-ng "
                "so the synthetic clip integration test runs"
            )
    if not found:
        return f"junit report has no {SAMPLE_TEST_NAME}"
    return None


def format_summary(
    measured: Measurement, committed: Baseline, reference: Baseline
) -> str:
    lines = [
        "total "
        f"{format_percent(measured.total)} "
        f"(floor {FLOOR_TOTAL:.0f}%, "
        f"main {format_percent(reference.total)}, "
        f"baseline {format_percent(committed.total)})",
        "core "
        f"{format_percent(measured.core)} "
        f"(floor {FLOOR_CORE:.0f}%, "
        f"main {format_percent(reference.core)}, "
        f"baseline {format_percent(committed.core)})",
    ]
    for name in CORE_PACKAGES:
        lines.append(
            f"{name} {format_percent(measured.packages[name])} "
            f"(main {format_percent(reference.packages[name])}, "
            f"baseline {format_percent(committed.packages[name])})"
        )
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Check Megila coverage floors and the drop against the main baseline."
        )
    )
    parser.add_argument(
        "--coverage",
        type=Path,
        required=True,
        help="pytest-cov JSON report (coverage json / --cov-report=json)",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        help="baseline committed in this revision",
    )
    parser.add_argument(
        "--reference",
        type=Path,
        help="baseline from main; defaults to --baseline (local runs)",
    )
    parser.add_argument(
        "--junit",
        type=Path,
        help="pytest junit XML; when set, the synthetic clip test must have run",
    )
    parser.add_argument(
        "--print-baseline",
        action="store_true",
        help="print a baseline JSON for this measurement and exit",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        measured = load_coverage(args.coverage)
        if args.print_baseline:
            sys.stdout.write(dump_baseline(baseline_from_measurement(measured)))
            return 0
        if args.baseline is None:
            print("error: --baseline is required", file=sys.stderr)
            return 2
        committed = load_baseline(args.baseline)
        reference_path = args.baseline if args.reference is None else args.reference
        reference = load_baseline(reference_path)
        failures = evaluate(measured, committed, reference)
        if args.junit is not None:
            problem = junit_sample_problem(args.junit)
            if problem is not None:
                failures.append(problem)
    except CoverageDataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(format_summary(measured, committed, reference))
    if failures:
        print("coverage gate failed:", file=sys.stderr)
        for item in failures:
            print(f"- {item}", file=sys.stderr)
        return 1
    print("coverage gate passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
