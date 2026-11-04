"""Cover the console entrypoint in-process.

``python -m megila`` in a subprocess is invisible to pytest-cov. Running the
module here keeps that code in the coverage total the CI gate enforces.
"""

from __future__ import annotations

import runpy
import sys

import pytest

from megila import __version__
from megila.cli.app import _print_version


def test_importing_main_module_does_not_run_the_cli() -> None:
    import megila.__main__ as entry

    assert entry.__name__ == "megila.__main__"


def test_module_entrypoint_prints_version(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A previous test imports this module. runpy warns if it is already loaded.
    sys.modules.pop("megila.__main__", None)
    monkeypatch.setattr(sys, "argv", ["megila", "--version"])
    with pytest.raises(SystemExit) as caught:
        runpy.run_module("megila", run_name="__main__")
    assert caught.value.code in (0, None)
    assert capsys.readouterr().out.strip() == f"megila {__version__}"


def test_version_callback_returns_when_the_flag_is_absent() -> None:
    _print_version(False)
