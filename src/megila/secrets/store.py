"""Store provider API keys in the OS keyring.

The service name comes from ``Settings.text_model.keyring_service`` (default
``megila``). The account name is the provider passed to ``megila keys``, which
is the same string as ``keyring_account`` when the text model looks the key up,
or the provider name when ``keyring_account`` is unset.

The key itself is never a setting, never an environment variable, never a
command-line argument, and never a file under the config directory. ADR 0005:
without a usable OS keyring backend, an external provider does not start. The
process explains what is missing and does not fall back to a file, an
environment variable, or SQLite.
"""

from __future__ import annotations

import contextlib
import json
from typing import TYPE_CHECKING

import keyring
from keyring.backend import KeyringBackend

from megila.config.profile import validate_provider_name
from megila.log import get_logger, register_secret
from megila.secrets.errors import SecretError, SecretNotFoundError

if TYPE_CHECKING:
    from megila.config.settings import Settings

_INDEX_ACCOUNT = "megila.index"
_MAX_SECRET_LENGTH = 4096
_NO_KEYRING = (
    "No OS keyring backend is available. Unlock or install the system "
    "keyring (Keychain, Credential Manager, or Secret Service). Megila "
    "does not store provider keys in a file."
)

_logged_backend = False


def reset_backend_log() -> None:
    """Allow the next store to log its backend again. Tests use this."""
    global _logged_backend
    _logged_backend = False


def os_keyring_available() -> bool:
    """Return whether the process has a usable OS keyring backend.

    The fail and null backends count as unavailable. A positive-priority
    backend, including a backend installed for tests, counts as available.
    """
    backend = keyring.get_keyring()
    module_tail = type(backend).__module__.rsplit(".", 1)[-1]
    if module_tail in {"fail", "null"}:
        return False
    priority = getattr(backend, "priority", None)
    if isinstance(priority, bool) or not isinstance(priority, int | float):
        return False
    return priority > 0


def secret_for_text_model(settings: Settings) -> str | None:
    """Return the text-model key, or ``None`` when that provider needs none.

    ``provider == "local"`` does not consult the keyring. Otherwise the lookup
    uses ``keyring_service`` and ``keyring_account`` from the text-model
    settings. When ``keyring_account`` is unset the account is the provider
    name, which is what ``megila keys set <provider>`` stores. The returned
    string is the secret: callers must not log it.
    """
    text = settings.text_model
    if text.provider == "local":
        return None
    store = SecretStore(service=text.keyring_service)
    return store.get(text.keyring_account or text.provider)


class SecretStore:
    """Provider keys for one keyring service."""

    def __init__(self, service: str = "megila") -> None:
        self.service = _validate_service(service)

    def __repr__(self) -> str:
        return f"SecretStore(service={self.service!r})"

    def set(self, account: str, secret: str) -> None:
        """Store ``secret`` for ``account``.

        Raises:
            SecretError: The account or the key is rejected, no OS keyring is
                available, or the backend could not save it. The message does
                not include ``secret``.
        """
        name = _validate_account(account)
        _validate_secret(secret)
        register_secret(secret)
        try:
            _set_keyring(self.service, name, secret)
        except SecretError:
            raise
        except Exception:
            raise SecretError(
                f"Could not store the key for provider {name!r}."
            ) from None
        _log_backend_once()
        get_logger().info(
            "secret_stored",
            provider=name,
            service=self.service,
            backend="keyring",
        )

    def get(self, account: str) -> str | None:
        """Return the stored key, or ``None`` when this provider has none.

        The return value is the secret. It is registered for log masking and
        must not be written to a log, a job file, or an error message.
        """
        name = _validate_account(account)
        try:
            value = _get_keyring(self.service, name)
        except SecretError:
            raise
        except Exception:
            raise SecretError(
                f"Could not read the key for provider {name!r}."
            ) from None
        if value is not None:
            register_secret(value)
        _log_backend_once()
        return value

    def delete(self, account: str) -> None:
        """Delete the key for ``account``.

        Raises:
            SecretNotFoundError: Nothing is stored for this provider.
            SecretError: The backend could not delete it.
        """
        name = _validate_account(account)
        if self.get(name) is None:
            raise SecretNotFoundError(f"No key is stored for provider {name!r}.")
        try:
            _delete_keyring(self.service, name)
        except SecretError:
            raise
        except Exception:
            raise SecretError(
                f"Could not delete the key for provider {name!r}."
            ) from None
        get_logger().info(
            "secret_deleted",
            provider=name,
            service=self.service,
            backend="keyring",
        )

    def list_accounts(self) -> list[str]:
        """Return provider names that have a key. Values are not included."""
        try:
            names = _list_keyring(self.service)
        except SecretError:
            raise
        except Exception:
            raise SecretError("Could not list stored provider names.") from None
        _log_backend_once()
        return [name for name in names if name != _INDEX_ACCOUNT]


def _validate_service(service: str) -> str:
    if (
        service == ""
        or len(service) > 128
        or any(character.isspace() or ord(character) < 32 for character in service)
    ):
        raise SecretError("The keyring service name is invalid.")
    return service


def _validate_account(account: str) -> str:
    if account == _INDEX_ACCOUNT or account.startswith("megila."):
        raise SecretError("That provider name is reserved.")
    try:
        return validate_provider_name(account)
    except ValueError:
        raise SecretError(
            "Provider name must look like 'openai' "
            "(lowercase letters, digits, hyphens, or underscores)."
        ) from None


def _validate_secret(secret: str) -> None:
    if not isinstance(secret, str):
        raise SecretError("The key must be text.")
    if secret == "":
        raise SecretError("The key must not be empty.")
    if "\x00" in secret:
        raise SecretError("The key contains a character that cannot be stored.")
    if len(secret) > _MAX_SECRET_LENGTH:
        raise SecretError(f"The key must be at most {_MAX_SECRET_LENGTH} characters.")


def _log_backend_once() -> None:
    global _logged_backend
    if _logged_backend:
        return
    _logged_backend = True
    get_logger().info("secret_backend", backend="keyring")


def _require_keyring() -> KeyringBackend:
    if not os_keyring_available():
        raise SecretError(_NO_KEYRING)
    return keyring.get_keyring()


def _set_keyring(service: str, account: str, secret: str) -> None:
    backend = _require_keyring()
    try:
        backend.set_password(service, account, secret)
    except keyring.errors.KeyringLocked:
        raise SecretError(
            "The OS keyring is locked. Unlock it and try again."
        ) from None
    except keyring.errors.NoKeyringError:
        raise SecretError(_NO_KEYRING) from None
    except Exception:
        raise SecretError(
            f"Could not store the key for provider {account!r} in the OS keyring."
        ) from None
    try:
        names = set(_read_index(backend, service))
        names.add(account)
        backend.set_password(
            service,
            _INDEX_ACCOUNT,
            json.dumps(sorted(names), separators=(",", ":")),
        )
    except Exception:
        try:
            backend.delete_password(service, account)
        except Exception:
            get_logger().error(
                "secret_index_rollback_failed",
                provider=account,
                service=service,
            )
        raise SecretError(
            f"Could not record provider {account!r} in the OS keyring."
        ) from None


def _get_keyring(service: str, account: str) -> str | None:
    backend = _require_keyring()
    try:
        return backend.get_password(service, account)
    except keyring.errors.KeyringLocked:
        raise SecretError(
            "The OS keyring is locked. Unlock it and try again."
        ) from None
    except keyring.errors.NoKeyringError:
        raise SecretError(_NO_KEYRING) from None
    except Exception:
        raise SecretError(
            f"Could not read the key for provider {account!r} from the OS keyring."
        ) from None


def _delete_keyring(service: str, account: str) -> None:
    backend = _require_keyring()
    try:
        backend.delete_password(service, account)
    except keyring.errors.PasswordDeleteError:
        raise SecretNotFoundError(
            f"No key is stored for provider {account!r}."
        ) from None
    except keyring.errors.KeyringLocked:
        raise SecretError(
            "The OS keyring is locked. Unlock it and try again."
        ) from None
    except Exception:
        raise SecretError(
            f"Could not delete the key for provider {account!r} from the OS keyring."
        ) from None
    try:
        names = [item for item in _read_index(backend, service) if item != account]
        if names:
            backend.set_password(
                service,
                _INDEX_ACCOUNT,
                json.dumps(sorted(names), separators=(",", ":")),
            )
        else:
            with contextlib.suppress(keyring.errors.PasswordDeleteError):
                backend.delete_password(service, _INDEX_ACCOUNT)
    except SecretError:
        raise
    except Exception:
        raise SecretError(
            f"Could not update the provider list after deleting {account!r}."
        ) from None


def _list_keyring(service: str) -> list[str]:
    return _read_index(_require_keyring(), service)


def _read_index(backend: KeyringBackend, service: str) -> list[str]:
    try:
        raw = backend.get_password(service, _INDEX_ACCOUNT)
    except keyring.errors.NoKeyringError:
        raise SecretError(_NO_KEYRING) from None
    except keyring.errors.KeyringLocked:
        raise SecretError(
            "The OS keyring is locked. Unlock it and try again."
        ) from None
    except Exception:
        # An unreadable index is an error, not an empty list: set() would
        # rewrite the index from [] and forget every other provider.
        raise SecretError("Could not read the stored provider list.") from None
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    names: list[str] = []
    for item in parsed:
        if isinstance(item, str) and item != _INDEX_ACCOUNT:
            names.append(item)
    return sorted(names)
