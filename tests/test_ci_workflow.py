"""The CI workflow and pre-commit config keep the checks this task promised."""

from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


def test_ci_workflow_runs_both_pythons_and_the_coverage_gate() -> None:
    text = (_REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for needle in (
        "ubuntu-latest",
        '"3.12"',
        '"3.13"',
        "python -m ruff check .",
        "python -m ruff format --check .",
        "python -m mypy",
        "python -m pytest",
        "pre-commit run --all-files",
        "ensure-media-tools.sh",
        "coverage_gate.py",
        "cache: pip",
        "actions/cache@",
        ".github/coverage-baseline.json",
        "libvmaf",
        "espeak-ng",
        "HF_HOME",
        "model_cache",
    ):
        assert needle in text, needle
    assert "name: ci" in text


def test_mkdocs_yaml_tags_are_checked_with_an_unsafe_hook() -> None:
    pre_commit = (_REPO / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    mkdocs = (_REPO / "mkdocs.yml").read_text(encoding="utf-8")
    assert "!!python/name:" in mkdocs
    assert "!!python/object/apply:" in mkdocs
    assert "exclude: ^mkdocs\\.yml$" in pre_commit
    assert "--unsafe" in pre_commit
    assert "pymdown-extensions==" in pre_commit
