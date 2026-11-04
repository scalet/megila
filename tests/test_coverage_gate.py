"""Unit tests for the coverage gate used by GitHub Actions."""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

_CI = Path(__file__).resolve().parents[1] / ".github" / "ci"
if str(_CI) not in sys.path:
    sys.path.insert(0, str(_CI))

import coverage_gate  # noqa: E402

_REPO = Path(__file__).resolve().parents[1]
_BASELINE = _REPO / ".github" / "coverage-baseline.json"


def _summary(
    statements: int,
    covered: int,
    branches: int = 0,
    covered_branches: int = 0,
) -> dict[str, object]:
    return {
        "summary": {
            "num_statements": statements,
            "covered_lines": covered,
            "num_branches": branches,
            "covered_branches": covered_branches,
        }
    }


def _measure(files: dict[str, dict[str, object]]) -> coverage_gate.Measurement:
    document: dict[str, object] = {"files": files, "totals": {"percent_covered": 0}}
    return coverage_gate.measurement_from_json(document)


def _baseline(
    total: float,
    core: float | None = None,
    **packages: float | None,
) -> coverage_gate.Baseline:
    stored = {name: packages.get(name) for name in coverage_gate.CORE_PACKAGES}
    return coverage_gate.Baseline(version=1, total=total, core=core, packages=stored)


def test_paths_ignore_the_repository_directory() -> None:
    checkout = "/agent/repos/megila/src/megila/jobs/queue/job.py"
    assert coverage_gate.normalize_package_path(checkout) == (
        "megila/jobs/queue/job.py"
    )
    assert coverage_gate.core_package_for("megila/jobs/queue/job.py") == ("megila.jobs")
    cli = "lib/python3.12/site-packages/megila/cli/app.py"
    assert coverage_gate.normalize_package_path(cli) == "megila/cli/app.py"
    assert coverage_gate.core_package_for("megila/cli/app.py") is None
    assert coverage_gate.core_package_for("megila/config/model.py") == "megila.config"


def test_core_percentage_is_weighted_and_empty_packages_are_absent() -> None:
    measured = _measure(
        {
            "src/megila/jobs/a.py": _summary(1, 1),
            "src/megila/jobs/queue/b.py": _summary(3, 1),
            "src/megila/cli/app.py": _summary(10, 10),
            "src/megila/config/__init__.py": _summary(0, 0),
        }
    )
    assert measured.packages["megila.jobs"] == pytest.approx(50.0)
    assert measured.packages["megila.config"] is None
    assert measured.packages["megila.plugins"] is None
    assert measured.core == pytest.approx(50.0)
    assert measured.total == pytest.approx(100.0 * 12 / 14)


def test_floors_and_exact_one_point_drop() -> None:
    measured = _measure(
        {
            "src/megila/cli/app.py": _summary(10, 8),
            "src/megila/jobs/work.py": _summary(10, 9),
            "src/megila/stages/encode.py": _summary(10, 9),
            "src/megila/plugins/hook.py": _summary(10, 9),
            "src/megila/config/model.py": _summary(10, 9),
        }
    )
    assert coverage_gate.points(measured.total) == 88.0
    core_names = {name: 90.0 for name in coverage_gate.CORE_PACKAGES}
    matching = _baseline(88.0, 90.0, **core_names)
    assert coverage_gate.evaluate(measured, matching, matching) == []

    low_total = _measure({"src/megila/cli/app.py": _summary(100, 79)})
    low_failures = coverage_gate.evaluate(low_total, _baseline(79.0), _baseline(79.0))
    assert any("floor" in item for item in low_failures)

    low_core = _measure(
        {
            "src/megila/cli/app.py": _summary(10, 10),
            "src/megila/jobs/work.py": _summary(10, 8),
        }
    )
    committed = _baseline(90.0, 80.0, **{"megila.jobs": 80.0})
    failures = coverage_gate.evaluate(low_core, committed, committed)
    assert any("megila.jobs" in item and "floor" in item for item in failures)

    exact = _measure({"src/megila/cli/app.py": _summary(100, 94)})
    assert coverage_gate.points(exact.total) == 94.0
    assert coverage_gate.evaluate(exact, _baseline(94.0), _baseline(95.0)) == []

    just_over = _measure({"src/megila/cli/app.py": _summary(10000, 9399)})
    assert coverage_gate.points(just_over.total) == 93.99
    dropped = coverage_gate.evaluate(just_over, _baseline(93.99), _baseline(95.0))
    assert any("dropped" in item for item in dropped)
    assert not any("differs" in item for item in dropped)


def test_editing_the_baseline_does_not_hide_a_drop_against_main() -> None:
    measured = _measure({"src/megila/cli/app.py": _summary(100, 90)})
    committed = _baseline(90.0)
    reference = _baseline(95.0)
    failures = coverage_gate.evaluate(measured, committed, reference)
    assert any("main baseline" in item for item in failures)
    assert not any("differs" in item for item in failures)


def test_a_rise_of_more_than_one_point_must_update_the_baseline() -> None:
    measured = _measure({"src/megila/cli/app.py": _summary(100, 97)})
    failures = coverage_gate.evaluate(measured, _baseline(95.0), _baseline(95.0))
    assert any("update .github/coverage-baseline.json" in item for item in failures)
    assert coverage_gate.evaluate(measured, _baseline(97.0), _baseline(95.0)) == []


def test_new_core_code_must_be_recorded_when_the_baseline_was_empty() -> None:
    measured = _measure(
        {
            "src/megila/cli/app.py": _summary(10, 10),
            "src/megila/config/model.py": _summary(10, 10),
        }
    )
    empty = _baseline(100.0)
    recorded = _baseline(100.0, 100.0, **{"megila.config": 100.0})
    assert coverage_gate.evaluate(measured, empty, empty)
    assert coverage_gate.evaluate(measured, recorded, empty) == []


def test_junit_requires_the_synthetic_clip_test_to_run(tmp_path: Path) -> None:
    passed = tmp_path / "passed.xml"
    ET.ElementTree(
        ET.Element(
            "testsuite",
            {
                "tests": "1",
            },
        )
    )
    suite = ET.Element("testsuite")
    ET.SubElement(suite, "testcase", {"name": coverage_gate.SAMPLE_TEST_NAME})
    ET.ElementTree(suite).write(passed, encoding="unicode")
    assert coverage_gate.junit_sample_problem(passed) is None

    skipped = tmp_path / "skipped.xml"
    skipped_suite = ET.Element("testsuite")
    case = ET.SubElement(
        skipped_suite, "testcase", {"name": coverage_gate.SAMPLE_TEST_NAME}
    )
    ET.SubElement(case, "skipped", {"message": "missing ffmpeg"})
    ET.ElementTree(skipped_suite).write(skipped, encoding="unicode")
    problem = coverage_gate.junit_sample_problem(skipped)
    assert problem is not None and "skipped" in problem
    assert coverage_gate.junit_sample_problem(tmp_path / "missing.xml")


def test_cli_print_baseline_and_gate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = tmp_path / "coverage.json"
    report.write_text(
        json.dumps({"files": {"src/megila/cli/app.py": _summary(10, 9)}}),
        encoding="utf-8",
    )
    assert coverage_gate.main(["--coverage", str(report), "--print-baseline"]) == 0
    printed_text = capsys.readouterr().out
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(printed_text, encoding="utf-8")
    assert coverage_gate.load_baseline(baseline_path).total == pytest.approx(90.0)
    assert (
        coverage_gate.main(
            [
                "--coverage",
                str(report),
                "--baseline",
                str(baseline_path),
                "--reference",
                str(baseline_path),
            ]
        )
        == 0
    )
    assert "coverage gate passed" in capsys.readouterr().out


def test_committed_baseline_meets_the_floors() -> None:
    baseline = coverage_gate.load_baseline(_BASELINE)
    assert baseline.version == 1
    assert baseline.total >= coverage_gate.FLOOR_TOTAL
    assert set(baseline.packages) == set(coverage_gate.CORE_PACKAGES)
    if baseline.core is not None:
        assert baseline.core >= coverage_gate.FLOOR_CORE
    for value in baseline.packages.values():
        if value is not None:
            assert value >= coverage_gate.FLOOR_CORE
