"""CLI for provider keys: hidden prompt, names only, no value on argv."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import keyring
import pytest
from keyring.backend import KeyringBackend
from typer.testing import CliRunner

from megila.cli.app import app
from megila.cli.keys import read_hidden_key
from megila.log import clear_registered_secrets, reset_logging
from megila.secrets import SecretStore
from megila.secrets.store import reset_backend_log

runner = CliRunner()


class MemoryKeyring(KeyringBackend):
    """In-memory keyring backend for CLI tests."""

    priority = 1.0

    def __init__(self) -> None:
        super().__init__()  # type: ignore[no-untyped-call]
        self.passwords: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.passwords.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
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
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    reset_logging()
    reset_backend_log()
    clear_registered_secrets()
    previous = keyring.get_keyring()
    keyring.set_keyring(MemoryKeyring())
    yield tmp_path
    keyring.set_keyring(previous)
    reset_logging()
    reset_backend_log()
    clear_registered_secrets()


def test_help_has_no_key_option(isolated: Path) -> None:
    del isolated
    root = runner.invoke(app, ["--help"])
    assert root.exit_code == 0
    assert "keys" in root.stdout
    group = runner.invoke(app, ["keys", "--help"])
    assert group.exit_code == 0
    for name in ("set", "list", "delete"):
        assert name in group.stdout
    set_help = runner.invoke(app, ["keys", "set", "--help"])
    assert set_help.exit_code == 0
    assert "PROVEDOR" in set_help.stdout
    lowered = set_help.stdout.lower()
    assert "--api-key" not in lowered
    assert "--password" not in lowered
    assert "--secret" not in lowered
    assert "--key" not in lowered


def test_hidden_prompt_uses_getpass(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}

    def fake_getpass(prompt: str = "Password: ", stream: object = None) -> str:
        del stream
        seen["prompt"] = prompt
        return "typed-secret-not-an-argument"

    monkeypatch.setattr("getpass.getpass", fake_getpass)
    assert read_hidden_key() == "typed-secret-not-an-argument"
    assert seen["prompt"]


def test_set_list_delete_hides_the_value(isolated: Path) -> None:
    secret = "cli-keyring-value-not-on-argv"
    stored = runner.invoke(app, ["keys", "set", "openai"], input=secret + "\n")
    assert stored.exit_code == 0, stored.output
    assert secret not in stored.stdout
    assert secret not in (stored.stderr or "")
    assert "OS keyring" in stored.stdout

    listed = runner.invoke(app, ["keys", "list"])
    assert listed.exit_code == 0
    assert listed.stdout.strip() == "openai"
    assert secret not in listed.stdout
    assert secret not in (listed.stderr or "")

    empty = runner.invoke(app, ["keys", "set", "anthropic"], input="\n")
    assert empty.exit_code == 1
    assert secret not in empty.output

    deleted = runner.invoke(app, ["keys", "delete", "openai"])
    assert deleted.exit_code == 0
    assert secret not in deleted.output
    assert SecretStore().get("openai") is None
    missing = runner.invoke(app, ["keys", "delete", "openai"])
    assert missing.exit_code == 1
    assert "openai" in missing.stderr or "openai" in missing.output
    del isolated


def test_set_without_keyring_fails(isolated: Path) -> None:
    del isolated
    backend = keyring.backends.fail.Keyring()  # type: ignore[no-untyped-call]
    keyring.set_keyring(cast(KeyringBackend, backend))
    result = runner.invoke(app, ["keys", "set", "openai"], input="secret\n")
    assert result.exit_code == 1
    assert "secret" not in result.output
    assert "does not store provider keys in a file" in (result.stderr or result.output)
