"""Store provider API keys in the OS keyring, or in a mode-0600 file.

The service name comes from ``Settings.text_model.keyring_service`` (default
``megila``). The account name is the provider passed to ``megila keys``, which
is the same string as ``keyring_account`` when the text model looks the key up.

The key itself is never a setting, never an environment variable, and never a
command-line argument. When ``keyring`` has no usable backend, the value is
written to ``secrets.json`` under the Megila config directory. That file is
created with mode ``0600`` and is not ``config.toml``.
"""

from __future__ import annotations

import contextlib
import json
import os
import stat
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

import keyring
from keyring.backend import KeyringBackend

from megila.config.paths import secrets_path
from megila.config.profile import validate_provider_name
from megila.log import get_logger, register_secret
from megila.secrets.errors import SecretError, SecretNotFoundError

if TYPE_CHECKING:
    from megila.config.settings import Settings

_INDEX_ACCOUNT = "megila.index"
_MAX_SECRET_LENGTH = 4096
_MAX_FILE_BYTES = 1_000_000
_FILE_MODE = 0o600

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
    settings. The returned string is the secret: callers must not log it.
    """
    text = settings.text_model
    if text.provider == "local" or text.keyring_account is None:
        return None
    store = SecretStore(service=text.keyring_service)
    return store.get(text.keyring_account)


class SecretStore:
    """Provider keys for one keyring service.

    ``backend_kind`` is ``"keyring"`` or ``"file"``. It is chosen once, the
    first time the store is used, so a process does not split a key across
    the two places.
    """

    def __init__(self, service: str = "megila") -> None:
        self.service = _validate_service(service)
        self._kind: str | None = None

    def __repr__(self) -> str:
        return f"SecretStore(service={self.service!r})"

    @property
    def backend_kind(self) -> str:
        """Return ``"keyring"`` or ``"file"``."""
        if self._kind is None:
            self._kind = "keyring" if os_keyring_available() else "file"
            _log_backend_once(self._kind)
        return self._kind

    def set(self, account: str, secret: str) -> None:
        """Store ``secret`` for ``account``.

        Raises:
            SecretError: The account or the key is rejected, or the backend
                could not save it. The message does not include ``secret``.
        """
        name = _validate_account(account)
        _validate_secret(secret)
        register_secret(secret)
        try:
            if self.backend_kind == "keyring":
                _set_keyring(self.service, name, secret)
            else:
                _set_file(self.service, name, secret)
        except SecretError:
            raise
        except Exception:
            raise SecretError(
                f"Could not store the key for provider {name!r}."
            ) from None
        get_logger().info(
            "secret_stored",
            provider=name,
            service=self.service,
            backend=self.backend_kind,
        )

    def get(self, account: str) -> str | None:
        """Return the stored key, or ``None`` when this provider has none.

        The return value is the secret. It is registered for log masking and
        must not be written to a log, a job file, or an error message.
        """
        name = _validate_account(account)
        try:
            if self.backend_kind == "keyring":
                value = _get_keyring(self.service, name)
            else:
                value = _get_file(self.service, name)
        except SecretError:
            raise
        except Exception:
            raise SecretError(
                f"Could not read the key for provider {name!r}."
            ) from None
        if value is not None:
            register_secret(value)
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
            if self.backend_kind == "keyring":
                _delete_keyring(self.service, name)
            else:
                _delete_file(self.service, name)
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
            backend=self.backend_kind,
        )

    def list_accounts(self) -> list[str]:
        """Return provider names that have a key. Values are not included."""
        try:
            if self.backend_kind == "keyring":
                names = _list_keyring(self.service)
            else:
                names = sorted(_file_service(self.service))
        except SecretError:
            raise
        except Exception:
            raise SecretError("Could not list stored provider names.") from None
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
        raise SecretError(
            f"The key must be at most {_MAX_SECRET_LENGTH} characters."
        )


def _log_backend_once(kind: str) -> None:
    global _logged_backend
    if _logged_backend:
        return
    _logged_backend = True
    if kind == "file":
        get_logger().info(
            "secret_backend",
            backend="file",
            path=str(secrets_path()),
        )
        return
    get_logger().info("secret_backend", backend="keyring")


def _backend() -> KeyringBackend:
    return keyring.get_keyring()


def _set_keyring(service: str, account: str, secret: str) -> None:
    backend = _backend()
    try:
        backend.set_password(service, account, secret)
    except keyring.errors.KeyringLocked:
        raise SecretError(
            "The OS keyring is locked. Unlock it and try again."
        ) from None
    except keyring.errors.NoKeyringError:
        raise SecretError("No OS keyring backend is available.") from None
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
    backend = _backend()
    try:
        return backend.get_password(service, account)
    except keyring.errors.KeyringLocked:
        raise SecretError(
            "The OS keyring is locked. Unlock it and try again."
        ) from None
    except keyring.errors.NoKeyringError:
        raise SecretError("No OS keyring backend is available.") from None
    except Exception:
        raise SecretError(
            f"Could not read the key for provider {account!r} from the OS keyring."
        ) from None


def _delete_keyring(service: str, account: str) -> None:
    backend = _backend()
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
    return _read_index(_backend(), service)


def _read_index(backend: KeyringBackend, service: str) -> list[str]:
    try:
        raw = backend.get_password(service, _INDEX_ACCOUNT)
    except keyring.errors.NoKeyringError:
        raise SecretError("No OS keyring backend is available.") from None
    except keyring.errors.KeyringLocked:
        raise SecretError(
            "The OS keyring is locked. Unlock it and try again."
        ) from None
    except Exception:
        return []
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


def _set_file(service: str, account: str, secret: str) -> None:
    services = _load_file_for_update()
    accounts = dict(services.get(service, {}))
    accounts[account] = secret
    services[service] = accounts
    _save_file(services)


def _get_file(service: str, account: str) -> str | None:
    return _file_service(service).get(account)


def _delete_file(service: str, account: str) -> None:
    services = _load_file_for_update()
    accounts = dict(services.get(service, {}))
    if account not in accounts:
        raise SecretNotFoundError(f"No key is stored for provider {account!r}.")
    del accounts[account]
    if accounts:
        services[service] = accounts
    else:
        services.pop(service, None)
    _save_file(services)


def _file_service(service: str) -> dict[str, str]:
    services = _read_services(secrets_path())
    for stored in services.values():
        for secret in stored.values():
            register_secret(secret)
    return dict(services.get(service, {}))


def _load_file_for_update() -> dict[str, dict[str, str]]:
    path = secrets_path()
    if path.is_symlink():
        path.unlink()
        return {}
    services = _read_services(path)
    for stored in services.values():
        for secret in stored.values():
            register_secret(secret)
    return services


def _save_file(services: Mapping[str, Mapping[str, str]]) -> None:
    remaining = {
        service: dict(accounts)
        for service, accounts in services.items()
        if accounts
    }
    path = secrets_path()
    if not remaining:
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            path.unlink()
        return
    _write_exclusive(path, remaining)


def _read_services(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    if path.is_symlink():
        raise SecretError(f"Refusing to follow a symlink at {path}.")
    if not path.is_file():
        raise SecretError(f"The secret path {path} is not a file.")
    _tighten(path)
    raw = _read_bytes(path)
    if raw.strip() == b"":
        return {}
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise SecretError(
            f"Cannot read the secret file {path}: it is not UTF-8 text."
        ) from None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise SecretError(
            f"Cannot read the secret file {path}: it is not valid JSON. "
            "The contents were not shown."
        ) from None
    return _parse_services(data, path)


def _parse_services(data: object, path: Path) -> dict[str, dict[str, str]]:
    if not isinstance(data, dict):
        raise SecretError(f"The secret file {path} has an unexpected shape.")
    version = data.get("version", 1)
    if version != 1:
        raise SecretError(f"The secret file {path} version is not supported.")
    services = data.get("services", {})
    if not isinstance(services, dict):
        raise SecretError(f"The secret file {path} has an unexpected shape.")
    parsed: dict[str, dict[str, str]] = {}
    for service, accounts in services.items():
        if not isinstance(service, str) or not isinstance(accounts, dict):
            raise SecretError(f"The secret file {path} has an unexpected shape.")
        parsed[service] = {}
        for account, secret in accounts.items():
            if not isinstance(account, str) or not isinstance(secret, str):
                raise SecretError(
                    f"The secret file {path} has an unexpected shape."
                )
            parsed[service][account] = secret
    return parsed


def _read_bytes(path: Path) -> bytes:
    flags = os.O_RDONLY
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if isinstance(nofollow, int):
        flags |= nofollow
    try:
        fd = os.open(path, flags)
    except OSError:
        raise SecretError(f"Cannot read the secret file {path}.") from None
    chunks: list[bytes] = []
    total = 0
    try:
        while True:
            block = os.read(fd, 65536)
            if not block:
                break
            total += len(block)
            if total > _MAX_FILE_BYTES:
                raise SecretError(f"The secret file {path} is too large.")
            chunks.append(block)
    except SecretError:
        raise
    except OSError:
        raise SecretError(f"Cannot read the secret file {path}.") from None
    finally:
        os.close(fd)
    return b"".join(chunks)


def _write_exclusive(
    path: Path,
    services: Mapping[str, Mapping[str, str]],
) -> None:
    if path.is_symlink():
        path.unlink()
    if path.exists() and not path.is_file():
        raise SecretError(f"The secret path {path} is not a file.")
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    payload = _encode(services)
    tmp_path: Path | None = None
    published = False
    fd = -1
    try:
        fd, tmp_name = tempfile.mkstemp(
            prefix=".secrets.",
            suffix=".tmp",
            dir=directory,
        )
        tmp_path = Path(tmp_name)
        os.fchmod(fd, _FILE_MODE)
        _write_all(fd, payload)
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.chmod(tmp_path, _FILE_MODE)
        os.replace(tmp_path, path)
        published = True
        os.chmod(path, _FILE_MODE)
        _fsync_directory(directory)
    except SecretError:
        raise
    except OSError:
        raise SecretError(f"Could not write the secret file {path}.") from None
    finally:
        if fd >= 0:
            os.close(fd)
        if tmp_path is not None and not published:
            tmp_path.unlink(missing_ok=True)
    _tighten(path)


def _encode(services: Mapping[str, Mapping[str, str]]) -> bytes:
    body = {
        "version": 1,
        "services": {
            service: dict(sorted(accounts.items()))
            for service, accounts in sorted(services.items())
        },
    }
    return json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True).encode(
        "utf-8"
    ) + b"\n"


def _tighten(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        return
    try:
        os.chmod(path, _FILE_MODE)
    except OSError:
        raise SecretError(
            f"Could not set mode 0600 on the secret file {path}."
        ) from None
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != _FILE_MODE:
        raise SecretError(f"The secret file {path} is not mode 0600.")


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    offset = 0
    while offset < len(view):
        written = os.write(fd, view[offset:])
        if written <= 0:
            raise SecretError("Could not write the secret file.")
        offset += written


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    if isinstance(directory_flag, int):
        flags |= directory_flag
    try:
        fd = os.open(directory, flags)
    except OSError:
        raise SecretError(
            f"Could not record the secret file in {directory}."
        ) from None
    try:
        os.fsync(fd)
    except OSError:
        raise SecretError(
            f"Could not record the secret file in {directory}."
        ) from None
    finally:
        os.close(fd)
