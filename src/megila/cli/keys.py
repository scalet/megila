"""``megila keys`` stores provider API keys outside argv, config, and logs.

``set`` reads the key from a hidden prompt. The value is never a command-line
argument. ``list`` prints provider names only.
"""

from __future__ import annotations

from typing import Annotated

import typer

from megila.config.errors import ConfigError
from megila.config.paths import secrets_path
from megila.config.profile import validate_provider_name
from megila.config.settings import load_settings
from megila.log import configure_logging
from megila.secrets import SecretError, SecretNotFoundError, SecretStore

keys_app = typer.Typer(
    name="keys",
    help="Store provider API keys in the OS keyring.",
    no_args_is_help=True,
    add_completion=False,
)

# Unknown tokens stay in the context instead of being echoed by usage errors.
# A key passed on the command line is rejected without printing it.
_NO_VALUE_ON_ARGV: dict[str, bool] = {
    "allow_extra_args": True,
    "ignore_unknown_options": True,
}


@keys_app.callback()
def _keys() -> None:
    """Store provider API keys outside config files and logs."""
    configure_logging()


def read_hidden_key() -> str:
    """Read one API key from a hidden prompt.

    The prompt uses ``hide_input``, which reads through ``getpass`` and does
    not echo the value. The key is not taken from argv.
    """
    try:
        value = typer.prompt("API key", hide_input=True)
    except typer.Abort:
        typer.echo("No key was entered.", err=True)
        raise typer.Exit(code=1) from None
    if not isinstance(value, str) or value == "":
        typer.echo("The key must not be empty.", err=True)
        raise typer.Exit(code=1)
    return value


@keys_app.command("set", context_settings=_NO_VALUE_ON_ARGV)
def set_key(
    ctx: typer.Context,
    provedor: Annotated[
        str,
        typer.Argument(
            metavar="PROVEDOR",
            help="Provider name, such as 'openai'. The key is typed at the prompt.",
        ),
    ],
) -> None:
    """Save a provider API key. The key is not a command-line argument."""
    _reject_extra(ctx)
    name = _require_provider(provedor)
    store = _open_store()
    secret = read_hidden_key()
    try:
        store.set(name, secret)
    except SecretError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None
    if store.backend_kind == "keyring":
        typer.echo(
            f"Stored the key for provider {name!r} "
            f"in the OS keyring (service {store.service!r})."
        )
        return
    typer.echo(
        f"Stored the key for provider {name!r} in {secrets_path()} "
        "with mode 0600 (no OS keyring backend is available)."
    )


@keys_app.command("list", context_settings=_NO_VALUE_ON_ARGV)
def list_keys(ctx: typer.Context) -> None:
    """List provider names that have a stored key. Values are not shown."""
    _reject_extra(ctx)
    store = _open_store()
    try:
        names = store.list_accounts()
    except SecretError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None
    for name in names:
        typer.echo(name)


@keys_app.command("delete", context_settings=_NO_VALUE_ON_ARGV)
def delete_key(
    ctx: typer.Context,
    provedor: Annotated[
        str,
        typer.Argument(metavar="PROVEDOR", help="Provider name whose key is removed."),
    ],
) -> None:
    """Delete the stored key for a provider."""
    _reject_extra(ctx)
    name = _require_provider(provedor)
    store = _open_store()
    try:
        store.delete(name)
    except SecretNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None
    except SecretError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None
    typer.echo(f"Deleted the key for provider {name!r}.")


def _reject_extra(ctx: typer.Context) -> None:
    if not ctx.args:
        return
    typer.echo(
        "Unexpected argument. Megila never reads an API key from the command line.",
        err=True,
    )
    raise typer.Exit(code=2)


def _require_provider(value: str) -> str:
    try:
        return validate_provider_name(value)
    except ValueError:
        typer.echo(
            "Provider name must look like 'openai'. The API key is not an argument.",
            err=True,
        )
        raise typer.Exit(code=2) from None


def _open_store() -> SecretStore:
    try:
        settings = load_settings()
    except ConfigError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None
    return SecretStore(service=settings.text_model.keyring_service)
