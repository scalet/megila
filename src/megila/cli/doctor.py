"""``megila doctor`` subcommand."""

from pathlib import Path
from typing import Annotated

import typer

from megila.doctor import render_json, render_plain, run_doctor


def doctor(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print the report as one JSON object."),
    ] = False,
    source: Annotated[
        Path | None,
        typer.Option(
            "--source",
            help=(
                "Directory whose disk is checked. "
                "Defaults to the configured data directory."
            ),
        ),
    ] = None,
    backup: Annotated[
        str | None,
        typer.Option(
            "--backup",
            help=(
                "Backup destination. A local path on the same disk as "
                "--source is a warning. An rclone remote (name:prefix) is not."
            ),
        ),
    ] = None,
    config_file: Annotated[
        Path | None,
        typer.Option(
            "--config",
            help="Settings TOML used when --source is omitted.",
        ),
    ] = None,
) -> None:
    """Check ffmpeg, the machine, and whether backup shares a disk."""
    report = run_doctor(source=source, backup=backup, config_file=config_file)
    if json_output:
        typer.echo(render_json(report))
    else:
        typer.echo(render_plain(report))
    if report.exit_code != 0:
        raise typer.Exit(code=report.exit_code)
