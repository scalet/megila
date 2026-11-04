"""Provider API keys.

Keys live in the operating-system keyring, under the service and account
names from the text-model settings. They stay out of ``config.toml``, the
environment, files under the config directory, and the job directory.
Without a usable keyring backend, Megila does not store the key.
"""

from megila.secrets.errors import SecretError, SecretNotFoundError
from megila.secrets.store import (
    SecretStore,
    os_keyring_available,
    secret_for_text_model,
)

__all__ = [
    "SecretError",
    "SecretNotFoundError",
    "SecretStore",
    "os_keyring_available",
    "secret_for_text_model",
]
