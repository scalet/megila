"""Keyring store, file fallback permissions, and secret masking."""

from __future__ import annotations

import io
import json
import logging
import os
import stat
import traceback
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import keyring
import pytest
from keyring.backend import KeyringBackend
from typer.testing import CliRunner

from megila.cli.app import app
from megila.config import load_settings, secrets_path
from megila.log import (
    clear_registered_secrets,
    configure_logging,
    get_logger,
    mask_text,
    reset_logging,
)
from megila.secrets import SecretError, SecretStore, secret_for_text_model
from megila.secrets.store import reset_backend_log

_CANARY = "megila-FAKE-KEY-DO-NOT-LEAK-9f3c1a7b"
_PATTERN = "sk-megilaPATTERNdonotleak123456"
runner = CliRunner()


def _fail_keyring() -> KeyringBackend:
    backend = keyring.backends.fail.Keyring()  # type: ignore[no-untyped-call]
    return cast(KeyringBackend, backend)


class MemoryKeyring(KeyringBackend):
    """In-memory keyring backend for unit tests."""

    priority = 1.0

    def __init__(self) -> None:
        super().__init__()  # type: ignore[no-untyped-call]
        self.passwords: dict[tuple[str, str], str] = {}
        self.fail_message: str | None = None

    def get_password(self, service: str, username: str) -> str | None:
        return self.passwords.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        if self.fail_message is not None:
            raise RuntimeError(self.fail_message)
        self.passwords[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        try:
            del self.passwords[(service, username)]
        except KeyError:
            raise keyring.errors.PasswordDeleteError(service) from None


@pytest.fixture
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    for key in list(os.environ):
        if key.lower().startswith("megila_"):
            monkeypatch.delenv(key, raising=False)
    home = tmp_path / "home"
    config_home = tmp_path / "xdg-config"
    data_home = tmp_path / "xdg-data"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    reset_logging()
    reset_backend_log()
    clear_registered_secrets()
    previous = keyring.get_keyring()
    yield tmp_path
    keyring.set_keyring(previous)
    reset_logging()
    reset_backend_log()
    clear_registered_secrets()


@pytest.fixture
def memory(isolated: Path) -> MemoryKeyring:
    del isolated
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    return backend


def _snapshot(root: Path) -> dict[Path, bytes]:
    found: dict[Path, bytes] = {}
    if not root.exists():
        return found
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            found[path] = path.read_bytes()
    return found


def _changed(before: dict[Path, bytes], root: Path) -> dict[Path, bytes]:
    changed: dict[Path, bytes] = {}
    for path, content in _snapshot(root).items():
        if before.get(path) != content:
            changed[path] = content
    return changed


def test_memory_keyring_round_trip_lists_names_only(
    memory: MemoryKeyring, isolated: Path
) -> None:
    store = SecretStore(service="megila")
    assert store.backend_kind == "keyring"
    store.set("openai", "first-value-not-shown")
    store.set("anthropic", "second-value-not-shown")
    assert store.get("openai") == "first-value-not-shown"
    assert store.list_accounts() == ["anthropic", "openai"]
    assert "first-value-not-shown" not in store.list_accounts()
    assert "second-value-not-shown" not in store.list_accounts()
    store.set("openai", "replaced-value-not-shown")
    assert store.get("openai") == "replaced-value-not-shown"
    store.delete("openai")
    assert store.get("openai") is None
    assert store.list_accounts() == ["anthropic"]
    other = SecretStore(service="other-service")
    assert other.get("anthropic") is None
    assert not (isolated / "xdg-config" / "megila" / "secrets.json").exists()
    assert "first-value-not-shown" not in repr(store)


def test_services_do_not_share_keys(memory: MemoryKeyring) -> None:
    SecretStore(service="megila").set("openai", "value-for-megila-service")
    assert SecretStore(service="other").get("openai") is None
    assert SecretStore(service="megila").get("openai") == "value-for-megila-service"


def test_text_model_lookup_uses_config_names(
    memory: MemoryKeyring, isolated: Path
) -> None:
    del memory
    config = isolated / "xdg-config" / "megila" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "\n".join(
            [
                "[text_model]",
                'provider = "openai-compatible"',
                'model = "nome"',
                'base_url = "https://example.test/v1"',
                'keyring_service = "custom-svc"',
                'keyring_account = "openai"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    settings = load_settings()
    SecretStore(service="custom-svc").set("openai", "looked-up-value")
    assert secret_for_text_model(settings) == "looked-up-value"
    assert SecretStore(service="megila").get("openai") is None

    config.write_text(
        "\n".join(
            [
                "[text_model]",
                'provider = "local"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    assert secret_for_text_model(load_settings()) is None
    assert not (isolated / "xdg-config" / "megila" / "secrets.json").exists()
    config.write_text(
        "\n".join(
            [
                "[text_model]",
                'provider = "openai-compatible"',
                'base_url = "https://example.test/v1"',
                'keyring_service = "custom-svc"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    assert secret_for_text_model(load_settings()) is None


def test_rejected_names_and_empty_keys_omit_the_value(memory: MemoryKeyring) -> None:
    store = SecretStore()
    with pytest.raises(SecretError, match="openai") as bad_name:
        store.set(_CANARY, "ignored-value")
    assert _CANARY not in str(bad_name.value)
    with pytest.raises(SecretError, match="empty") as empty:
        store.set("openai", "")
    assert "ignored-value" not in str(empty.value)
    with pytest.raises(SecretError, match="4096"):
        store.set("openai", "x" * 4097)
    with pytest.raises(SecretError, match="reserved"):
        store.set("megila.index", "ignored-value")
    with pytest.raises(SecretError, match="service"):
        SecretStore(service="bad service")


def test_keyring_error_does_not_include_the_secret(memory: MemoryKeyring) -> None:
    memory.fail_message = _CANARY
    store = SecretStore()
    with pytest.raises(SecretError) as caught:
        store.set("openai", _CANARY)
    rendered = "".join(traceback.format_exception(caught.value))
    assert _CANARY not in str(caught.value)
    assert _CANARY not in rendered
    assert caught.value.__cause__ is None
    assert "openai" not in memory.passwords.get(("megila", "openai"), "")


def test_file_fallback_is_mode_0600(isolated: Path) -> None:
    keyring.set_keyring(_fail_keyring())
    buffer = io.StringIO()
    configure_logging(buffer, force=True)
    secret = "file-fallback-canary-mode-0600"
    store = SecretStore(service="megila")
    assert store.backend_kind == "file"
    old_umask = os.umask(0)
    try:
        store.set("openai", secret)
        store.set("anthropic", "second-file-value")
    finally:
        os.umask(old_umask)
    path = isolated / "xdg-config" / "megila" / "secrets.json"
    assert path.is_file()
    assert not path.is_symlink()
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600
    assert mode & 0o077 == 0
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["services"]["megila"]["openai"] == secret
    assert store.list_accounts() == ["anthropic", "openai"]
    assert secret not in store.list_accounts()
    assert secret not in buffer.getvalue()
    assert "second-file-value" not in buffer.getvalue()
    assert not list(path.parent.glob(".secrets.*.tmp"))
    assert store.get("openai") == secret
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    config = isolated / "xdg-config" / "megila" / "config.toml"
    if config.exists():
        assert secret not in config.read_text(encoding="utf-8")
    store.delete("openai")
    store.delete("anthropic")
    assert not path.exists()


def test_file_fallback_respects_xdg_and_rejects_relative(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    keyring.set_keyring(_fail_keyring())
    home = isolated / "home"
    monkeypatch.setenv("XDG_CONFIG_HOME", "relative/config")
    assert secrets_path() == home / ".config" / "megila" / "secrets.json"
    SecretStore().set("openai", "relative-xdg-value")
    path = secrets_path()
    assert path.is_file()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "relative-xdg-value" in path.read_text(encoding="utf-8")
    assert not (isolated / "xdg-config" / "megila" / "secrets.json").exists()


def test_loose_file_is_tightened_and_symlink_is_replaced(isolated: Path) -> None:
    keyring.set_keyring(_fail_keyring())
    path = secrets_path()
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"version": 1, "services": {"megila": {"openai": "kept"}}}),
        encoding="utf-8",
    )
    os.chmod(path, 0o644)
    store = SecretStore()
    assert store.list_accounts() == ["openai"]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600

    target = isolated / "world-readable.txt"
    target.write_text("do-not-overwrite-target", encoding="utf-8")
    os.chmod(target, 0o644)
    path.unlink()
    path.symlink_to(target)
    store.set("anthropic", "symlink-value")
    assert path.is_file()
    assert not path.is_symlink()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert target.read_text(encoding="utf-8") == "do-not-overwrite-target"
    assert "symlink-value" in path.read_text(encoding="utf-8")


def test_invalid_secret_file_is_not_echoed(isolated: Path) -> None:
    keyring.set_keyring(_fail_keyring())
    path = secrets_path()
    path.parent.mkdir(parents=True)
    path.write_text('{"broken": ' + _CANARY, encoding="utf-8")
    os.chmod(path, 0o600)
    with pytest.raises(SecretError) as caught:
        SecretStore().list_accounts()
    message = str(caught.value)
    rendered = "".join(traceback.format_exception(caught.value))
    assert _CANARY not in message
    assert _CANARY not in rendered
    assert "not shown" in message or "not valid JSON" in message


def test_known_fake_key_never_appears_in_logs_files_or_errors(
    memory: MemoryKeyring, isolated: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Fail if the canary shows up in a log, a file this code writes, or an error."""
    buffer = io.StringIO()
    configure_logging(buffer, force=True)
    before = _snapshot(isolated)
    store = SecretStore(service="megila")
    store.set("openai", _CANARY)
    store.set("openai", _CANARY + "-rotated")
    get_logger().info(
        "probe",
        provider="openai",
        note=f"see {_CANARY} and {_CANARY}-rotated",
        api_key=_CANARY,
        header=f"Authorization: Bearer {_CANARY}",
        url=f"https://example.test/v1?api_key={_CANARY}&x=1",
        assignment=f"token={_CANARY}",
        quoted=json.dumps({"api_key": _CANARY}),
        pattern=_PATTERN,
        bearer=f"Bearer {_PATTERN}",
    )
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(logging.Formatter("%(message)s"))
    stdlib = logging.getLogger("megila.known-key-test")
    stdlib.handlers.clear()
    stdlib.setLevel(logging.INFO)
    stdlib.propagate = False
    stdlib.addHandler(handler)
    stdlib.info("stdlib %s", _CANARY)
    stdlib.info("Authorization: Bearer %s", _PATTERN)
    handler.flush()

    logs = buffer.getvalue()
    assert _CANARY not in logs
    assert _CANARY + "-rotated" not in logs
    assert _PATTERN not in logs
    assert "openai" in logs
    for line in logs.splitlines():
        if line.startswith("{"):
            json.loads(line)
    assert "***" in logs

    with pytest.raises(SecretError) as missing:
        store.delete("missing-provider")
    assert _CANARY not in str(missing.value)

    memory.fail_message = _CANARY
    with pytest.raises(SecretError) as exploded:
        store.set("anthropic", _CANARY)
    exploded_text = "".join(traceback.format_exception(exploded.value))
    assert _CANARY not in str(exploded.value)
    assert _CANARY not in exploded_text

    memory.fail_message = None
    listed = runner.invoke(app, ["keys", "list"])
    stored = runner.invoke(app, ["keys", "set", "anthropic"], input=_CANARY + "\n")
    leaked_argv = runner.invoke(app, ["keys", "set", "openai", _CANARY])
    leaked_option = runner.invoke(app, ["keys", "set", "openai", "--api-key", _CANARY])
    leaked_name = runner.invoke(app, ["keys", "set", _CANARY])
    names = runner.invoke(app, ["keys", "list"])
    cli_blobs = [
        listed.stdout,
        listed.stderr or "",
        listed.output,
        stored.stdout,
        stored.stderr or "",
        stored.output,
        leaked_argv.stdout,
        leaked_argv.stderr or "",
        leaked_argv.output,
        leaked_option.stdout,
        leaked_option.stderr or "",
        leaked_option.output,
        leaked_name.stdout,
        leaked_name.stderr or "",
        leaked_name.output,
        names.stdout,
        names.stderr or "",
        names.output,
    ]
    for blob in cli_blobs:
        assert _CANARY not in blob
        assert _PATTERN not in blob
    assert stored.exit_code == 0
    assert "anthropic" in names.stdout
    assert _CANARY not in names.stdout
    assert leaked_argv.exit_code == 2
    assert leaked_option.exit_code == 2
    assert leaked_name.exit_code == 2
    for result in (leaked_argv, leaked_option, leaked_name):
        if result.exception is not None:
            rendered = "".join(traceback.format_exception(result.exception))
            assert _CANARY not in rendered

    captured = capsys.readouterr()
    assert _CANARY not in captured.out
    assert _CANARY not in captured.err

    for content in _changed(before, isolated).values():
        assert _CANARY.encode() not in content
        assert _PATTERN.encode() not in content
        assert (_CANARY + "-rotated").encode() not in content

    logs_after = buffer.getvalue()
    assert _CANARY not in logs_after
    assert _CANARY + "-rotated" not in logs_after
    assert _PATTERN not in logs_after
    assert mask_text(f"prefix {_CANARY} suffix") == "prefix *** suffix"
    assert _PATTERN not in mask_text(f"Bearer {_PATTERN}")
