"""Provider API keys.

Keys live in the operating-system keyring, under the service and account
names from the text-model settings. When no keyring backend is available,
they live in a mode-0600 file under the Megila config directory. Either way
they stay out of ``config.toml``, the environment, and the job directory.
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
