"""CLI unit tests."""

import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from megila import __version__
from megila.cli import app

runner = CliRunner()


def _console_script() -> Path:
    bindir = Path(sys.executable).parent
    for name in ("megila", "megila.exe"):
        candidate = bindir / name
        if candidate.is_file():
            return candidate
    message = f"megila console script not found in {bindir}"
    raise AssertionError(message)


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"megila {__version__}"


def test_short_version_flag() -> None:
    result = runner.invoke(app, ["-V"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"megila {__version__}"


def test_help_lists_version_flag() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "--version" in result.stdout


def test_module_entrypoint_version() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "megila", "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert completed.stdout.strip() == f"megila {__version__}"


def test_installed_script_version() -> None:
    completed = subprocess.run(
        [_console_script(), "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert completed.stdout.strip() == f"megila {__version__}"
