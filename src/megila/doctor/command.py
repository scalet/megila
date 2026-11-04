"""Run an external program from an argument list.

ffmpeg, nvidia-smi, and sysctl are separate processes. The call never uses
a shell, as ADR 0001 requires.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CommandResult:
    """Captured result of one argv invocation."""

    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    """Callable used by doctor so tests can supply fake program output."""

    def __call__(self, argv: Sequence[str], *, timeout: float) -> CommandResult:
        """Run ``argv`` and return the captured result."""
        ...


def run_command(argv: Sequence[str], *, timeout: float) -> CommandResult:
    """Run ``argv`` without a shell and capture both streams as text.

    A missing binary or a timeout becomes ``returncode`` 1 and a short
    ``stderr``. The caller decides whether that is a hard failure.
    """
    arguments = list(argv)
    try:
        completed = subprocess.run(
            arguments,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return CommandResult(
            argv=tuple(arguments),
            returncode=1,
            stdout="",
            stderr="timed out",
        )
    except OSError as exc:
        return CommandResult(
            argv=tuple(arguments),
            returncode=1,
            stdout="",
            stderr=str(exc),
        )
    stdout = completed.stdout if isinstance(completed.stdout, str) else ""
    stderr = completed.stderr if isinstance(completed.stderr, str) else ""
    return CommandResult(
        argv=tuple(arguments),
        returncode=completed.returncode,
        stdout=stdout,
        stderr=stderr,
    )


def combined_output(result: CommandResult) -> str:
    """Return stdout and stderr as one string for parsers.

    With ``-hide_banner``, current ffmpeg writes these reports to stdout.
    Combining the streams still accepts a build that uses stderr.
    """
    if result.stderr:
        return f"{result.stdout}\n{result.stderr}"
    return result.stdout
