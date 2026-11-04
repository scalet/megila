"""Typer application for the Megila command line."""

from typing import Annotated

import typer

from megila import __version__

app = typer.Typer(
    name="megila",
    help="Generic local-first video pipeline.",
    no_args_is_help=True,
    add_completion=False,
)


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"megila {__version__}")
        raise typer.Exit


@app.callback()
def cli(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            "-V",
            help="Show the version and exit.",
            callback=_print_version,
            is_eager=True,
        ),
    ] = False,
) -> None:
    """Generic local-first video pipeline."""


def main() -> None:
    """Run the Megila CLI."""
    app()
