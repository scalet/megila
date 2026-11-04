"""Errors raised while reading configuration or a profile."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError
from pydantic_core import ErrorDetails

from megila.config.secret_names import is_secret_name


class ConfigError(ValueError):
    """Settings could not be loaded.

    The message names the field and the problem. It never includes a secret
    value that was rejected.
    """


class ProfileError(ValueError):
    """A profile is invalid.

    The message names the field and the problem. It never includes a secret
    value that was rejected.
    """


def render_validation_error(exc: ValidationError, *, heading: str) -> str:
    """Turn a pydantic error into a readable message without input values."""
    lines = [heading]
    for error in exc.errors():
        loc = error.get("loc", ())
        path = _format_loc(loc)
        lines.append(f"- {path}: {_public_message(error)}")
    return "\n".join(lines)


def display_value(value: str, *, limit: int = 40) -> str:
    """Quote a non-secret value, truncating it when it is long."""
    if len(value) > limit:
        return repr(value[:limit] + "...")
    return repr(value)


def _format_loc(loc: Any) -> str:
    if not isinstance(loc, tuple) or not loc:
        return "configuration"
    return ".".join(str(part) for part in loc)


def _public_message(error: ErrorDetails) -> str:
    loc = error.get("loc", ())
    leaf = str(loc[-1]) if isinstance(loc, tuple) and loc else ""
    if is_secret_name(leaf):
        return (
            "cannot store secrets; use the OS keyring "
            "(service 'megila') and do not put the value in the config"
        )
    if error.get("type") == "extra_forbidden":
        return "unknown field; remove it"
    message = str(error.get("msg", "invalid value"))
    prefix = "Value error, "
    if message.startswith(prefix):
        message = message[len(prefix) :]
    return message
