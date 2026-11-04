"""Detect credential-shaped names.

Megila stores API keys in the operating-system keyring. A field or
environment variable with one of these names is rejected before the value
is validated, so the value never appears in an error.
"""

from __future__ import annotations

from collections.abc import Mapping

_SECRET_NAMES = frozenset(
    {
        "api_key",
        "apikey",
        "api_secret",
        "secret",
        "secret_key",
        "client_secret",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "password",
        "passwd",
        "authorization",
        "auth",
        "auth_token",
        "credential",
        "credentials",
        "private_key",
        "bearer",
    }
)
_SECRET_SUFFIXES = (
    "_api_key",
    "_secret",
    "_token",
    "_password",
    "_private_key",
)


def is_secret_name(name: str) -> bool:
    """Return whether ``name`` is a credential field, not profile content."""
    normalized = name.strip().lower().replace("-", "_")
    if normalized in _SECRET_NAMES:
        return True
    return normalized.endswith(_SECRET_SUFFIXES)


def secret_field_paths(data: object) -> list[str]:
    """Return dotted paths of secret-shaped keys.

    Glossary entries are profile content, so keys under a ``glossary`` table
    are not inspected. A term such as ``token`` can be a word in the glossary.
    """
    found: list[str] = []
    _collect(data, (), found)
    return found


def _collect(data: object, prefix: tuple[str, ...], found: list[str]) -> None:
    if isinstance(data, list):
        for index, item in enumerate(data):
            _collect(item, (*prefix, str(index)), found)
        return
    if not isinstance(data, Mapping):
        return
    for key, value in data.items():
        name = str(key)
        path = (*prefix, name)
        if name == "glossary":
            continue
        if is_secret_name(name):
            found.append(".".join(path))
            continue
        _collect(value, path, found)
