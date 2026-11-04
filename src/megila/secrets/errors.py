"""Errors raised while storing or reading a provider key.

Messages name the provider and the problem. They never include the key.
"""

from __future__ import annotations


class SecretError(Exception):
    """A provider key could not be stored, read, or deleted.

    The message never includes the secret value.
    """


class SecretNotFoundError(SecretError):
    """No key is stored for this provider."""
