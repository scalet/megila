"""Error paths of the keyring store, the log masker, and ``megila keys``."""

from __future__ import annotations

import io
import logging
import os
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import keyring
import keyring.errors
import pytest
from keyring.backend import KeyringBackend
from typer.testing import CliRunner

import megila.log as megila_log
import megila.secrets.store as store_module
from megila.cli.app import app
from megila.log import (
    clear_registered_secrets,
    configure_logging,
    mask_event,
    mask_text,
    register_secret,
    reset_logging,
)
from megila.secrets import SecretError, SecretNotFoundError, SecretStore
from megila.secrets.store import os_keyring_available, reset_backend_log

runner = CliRunner()
_VALUE = "scripted-secret-value-1234"
_INDEX = "megila.index"


class ScriptedKeyring(KeyringBackend):
    """In-memory backend that raises on demand.

    ``failures`` maps ``(operation, username)`` to the exception to raise.
    The username ``"*"`` matches every account.
    """

    priority = 1.0

    def __init__(self) -> None:
        super().__init__()  # type: ignore[no-untyped-call]
        self.passwords: dict[tuple[str, str], str] = {}
        self.failures: dict[tuple[str, str], Exception] = {}

    def _maybe_fail(self, operation: str, username: str) -> None:
        for key in ((operation, username), (operation, "*")):
            failure = self.failures.get(key)
            if failure is not None:
                raise failure

    def get_password(self, service: str, username: str) -> str | None:
        self._maybe_fail("get", username)
        return self.passwords.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self._maybe_fail("set", username)
        self.passwords[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self._maybe_fail("delete", username)
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
    factory = logging.getLogRecordFactory()
    reset_logging()
    reset_backend_log()
    clear_registered_secrets()
    previous = keyring.get_keyring()
    yield tmp_path
    keyring.set_keyring(previous)
    reset_logging()
    logging.setLogRecordFactory(factory)
    reset_backend_log()
    clear_registered_secrets()


@pytest.fixture
def scripted(isolated: Path) -> ScriptedKeyring:
    del isolated
    backend = ScriptedKeyring()
    keyring.set_keyring(backend)
    return backend


def _locked() -> Exception:
    return keyring.errors.KeyringLocked("locked")


def _no_backend() -> Exception:
    return keyring.errors.NoKeyringError("none")


def test_backend_with_a_non_numeric_priority_is_unavailable(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated
    # Not a KeyringBackend subclass: keyring would discover it and compare
    # its priority in every later test.
    monkeypatch.setattr(
        keyring,
        "get_keyring",
        lambda: SimpleNamespace(priority="high"),
    )
    assert os_keyring_available() is False


def test_invalid_secrets_are_rejected_without_echo(scripted: ScriptedKeyring) -> None:
    store = SecretStore()
    with pytest.raises(SecretError, match="must be text"):
        store.set("openai", cast(str, 123))
    with pytest.raises(SecretError, match="cannot be stored"):
        store.set("openai", "has\x00nul")
    with pytest.raises(SecretError, match="at most") as excinfo:
        store.set("openai", "x" * 5000)
    assert "xxxx" not in str(excinfo.value)
    assert scripted.passwords == {}


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (_locked, "locked"),
        (_no_backend, "No OS keyring backend"),
        (lambda: RuntimeError(_VALUE), "Could not store the key"),
    ],
)
def test_set_maps_backend_failures(
    scripted: ScriptedKeyring, failure: Callable[[], Exception], message: str
) -> None:
    scripted.failures[("set", "openai")] = failure()
    with pytest.raises(SecretError, match=message) as excinfo:
        SecretStore().set("openai", _VALUE)
    assert _VALUE not in str(excinfo.value)


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (_locked, "locked"),
        (_no_backend, "No OS keyring backend"),
        (lambda: RuntimeError(_VALUE), "Could not read the key"),
    ],
)
def test_get_maps_backend_failures(
    scripted: ScriptedKeyring, failure: Callable[[], Exception], message: str
) -> None:
    scripted.failures[("get", "openai")] = failure()
    with pytest.raises(SecretError, match=message):
        SecretStore().get("openai")


def test_a_failed_index_write_rolls_the_key_back(scripted: ScriptedKeyring) -> None:
    scripted.failures[("set", _INDEX)] = RuntimeError("index down")
    store = SecretStore()
    with pytest.raises(SecretError, match="Could not record"):
        store.set("openai", _VALUE)
    assert ("megila", "openai") not in scripted.passwords


def test_a_failed_rollback_is_logged_and_still_raises(
    scripted: ScriptedKeyring,
) -> None:
    stream = io.StringIO()
    configure_logging(stream, force=True)
    scripted.failures[("set", _INDEX)] = RuntimeError("index down")
    scripted.failures[("delete", "openai")] = RuntimeError("delete down")
    with pytest.raises(SecretError, match="Could not record"):
        SecretStore().set("openai", _VALUE)
    assert "secret_index_rollback_failed" in stream.getvalue()
    assert _VALUE not in stream.getvalue()


@pytest.mark.parametrize(
    ("operation", "message"),
    [
        ("_set_keyring", "Could not store"),
        ("_get_keyring", "Could not read"),
        ("_delete_keyring", "Could not delete"),
        ("_list_keyring", "Could not list"),
    ],
)
def test_unexpected_errors_become_secret_errors(
    scripted: ScriptedKeyring,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    message: str,
) -> None:
    store = SecretStore()
    store.set("openai", _VALUE)

    def boom(*_args: object) -> None:
        raise ValueError(_VALUE)

    monkeypatch.setattr(store_module, operation, boom)
    with pytest.raises(SecretError, match=message) as excinfo:
        if operation == "_set_keyring":
            store.set("openai", _VALUE)
        elif operation == "_get_keyring":
            store.get("openai")
        elif operation == "_delete_keyring":
            store.delete("openai")
        else:
            store.list_accounts()
    assert _VALUE not in str(excinfo.value)


def test_delete_reports_a_key_that_disappears_first(
    scripted: ScriptedKeyring,
) -> None:
    store = SecretStore()
    store.set("openai", _VALUE)
    scripted.failures[("delete", "openai")] = keyring.errors.PasswordDeleteError("x")
    with pytest.raises(SecretNotFoundError):
        store.delete("openai")


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (_locked, "locked"),
        (lambda: RuntimeError(_VALUE), "Could not delete the key"),
    ],
)
def test_delete_maps_backend_failures(
    scripted: ScriptedKeyring, failure: Callable[[], Exception], message: str
) -> None:
    store = SecretStore()
    store.set("openai", _VALUE)
    scripted.failures[("delete", "openai")] = failure()
    with pytest.raises(SecretError, match=message):
        store.delete("openai")


def test_delete_fails_loudly_when_the_index_cannot_be_updated(
    scripted: ScriptedKeyring,
) -> None:
    store = SecretStore()
    store.set("openai", _VALUE)
    store.set("anthropic", _VALUE + "-b")
    scripted.failures[("set", _INDEX)] = RuntimeError("index down")
    with pytest.raises(SecretError, match="provider list"):
        store.delete("openai")


def test_deleting_the_last_key_removes_the_index(scripted: ScriptedKeyring) -> None:
    store = SecretStore()
    store.set("openai", _VALUE)
    store.delete("openai")
    assert ("megila", _INDEX) not in scripted.passwords
    assert store.list_accounts() == []


@pytest.mark.parametrize(
    ("failure", "message"),
    [(_no_backend, "No OS keyring backend"), (_locked, "locked")],
)
def test_list_maps_index_read_failures(
    scripted: ScriptedKeyring, failure: Callable[[], Exception], message: str
) -> None:
    scripted.failures[("get", _INDEX)] = failure()
    with pytest.raises(SecretError, match=message):
        SecretStore().list_accounts()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("{not json", []),
        ('{"openai": 1}', []),
        ('["openai", 3, "megila.index", "anthropic"]', ["anthropic", "openai"]),
        ("", []),
    ],
)
def test_list_tolerates_a_damaged_index(
    scripted: ScriptedKeyring, raw: str, expected: list[str]
) -> None:
    scripted.passwords[("megila", _INDEX)] = raw
    assert SecretStore().list_accounts() == expected


def test_a_damaged_index_is_repaired_by_the_next_set(
    scripted: ScriptedKeyring,
) -> None:
    scripted.passwords[("megila", _INDEX)] = "{not json"
    store = SecretStore()
    store.set("openai", _VALUE)
    assert store.list_accounts() == ["openai"]


def test_service_names_are_validated() -> None:
    for bad in ("", "has space", "x" * 129, "tab\tname"):
        with pytest.raises(SecretError, match="service name"):
            SecretStore(service=bad)


def test_account_names_are_validated(scripted: ScriptedKeyring) -> None:
    store = SecretStore()
    for bad in ("megila.index", "megila.other", "Has Space", ""):
        with pytest.raises(SecretError):
            store.get(bad)
    assert repr(store) == "SecretStore(service='megila')"


def test_masking_ignores_empty_and_placeholder_values(isolated: Path) -> None:
    del isolated
    register_secret("")
    register_secret("***")
    assert mask_text("") == ""
    assert mask_text("plain text") == "plain text"


def test_short_secrets_match_only_the_whole_text(isolated: Path) -> None:
    del isolated
    register_secret("abc")
    assert mask_text("abc") == "***"
    assert mask_text("xabcx") == "xabcx"


def test_long_secrets_are_replaced_inside_text(isolated: Path) -> None:
    del isolated
    register_secret(_VALUE)
    assert mask_text(f"before {_VALUE} after") == "before *** after"


def test_mask_event_handles_every_value_type(isolated: Path) -> None:
    del isolated
    register_secret(_VALUE)

    class Stringy:
        def __str__(self) -> str:
            return _VALUE

    event = {
        "flag": True,
        "none": None,
        "count": 3,
        "ratio": 1.5,
        "items": [_VALUE, 1],
        "pair": (_VALUE,),
        "blob": _VALUE.encode(),
        "object": Stringy(),
        "api_key": "whatever",
        "nested": {"inner": _VALUE},
    }
    masked = mask_event(None, "info", event)
    assert masked["flag"] is True
    assert masked["none"] is None
    assert masked["count"] == 3
    assert masked["ratio"] == 1.5
    assert masked["items"] == ["***", 1]
    assert masked["pair"] == ("***",)
    assert _VALUE not in str(masked)
    assert masked["api_key"] == "***"


def test_mask_event_falls_back_when_masking_returns_a_non_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(megila_log, "_mask_object", lambda _value: "oops")
    assert mask_event(None, "info", {"event": "x"}) == {"event": "***"}


def test_configuring_twice_does_not_stack_the_record_factory(
    isolated: Path,
) -> None:
    del isolated
    configure_logging(io.StringIO(), force=True)
    first = logging.getLogRecordFactory()
    configure_logging(io.StringIO(), force=True)
    assert logging.getLogRecordFactory() is first


def test_record_factory_masks_messages_that_fail_to_format(isolated: Path) -> None:
    del isolated
    register_secret(_VALUE)
    configure_logging(io.StringIO(), force=True)
    factory = logging.getLogRecordFactory()
    record = factory("n", logging.INFO, "f", 1, f"{_VALUE} %d", ("x",), None)
    assert _VALUE not in record.msg
    assert record.args is None


def test_record_factory_masks_existing_exception_text(isolated: Path) -> None:
    del isolated
    register_secret(_VALUE)

    def original(*args: object, **kwargs: object) -> logging.LogRecord:
        record = logging.LogRecord(*args, **kwargs)  # type: ignore[arg-type]
        record.exc_text = f"Traceback: {_VALUE}"
        return record

    logging.setLogRecordFactory(original)
    configure_logging(io.StringIO(), force=True)
    record = logging.getLogRecordFactory()("n", logging.INFO, "f", 1, "m", (), None)
    assert record.exc_text == "Traceback: ***"


def test_keys_list_and_delete_report_a_missing_keyring(isolated: Path) -> None:
    del isolated
    keyring.set_keyring(cast(KeyringBackend, keyring.backends.fail.Keyring()))  # type: ignore[no-untyped-call]
    listed = runner.invoke(app, ["keys", "list"])
    assert listed.exit_code == 1
    assert "No OS keyring backend" in listed.output
    deleted = runner.invoke(app, ["keys", "delete", "openai"])
    assert deleted.exit_code == 1
    assert "No OS keyring backend" in deleted.output


def test_keys_set_rejects_an_empty_key(
    scripted: ScriptedKeyring, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("megila.cli.keys.typer.prompt", lambda *_a, **_k: "")
    result = runner.invoke(app, ["keys", "set", "openai"])
    assert result.exit_code == 1
    assert "must not be empty" in result.output
    assert scripted.passwords == {}


def test_keys_commands_report_an_invalid_configuration(
    scripted: ScriptedKeyring, monkeypatch: pytest.MonkeyPatch
) -> None:
    del scripted
    monkeypatch.setenv("MEGILA_ACTIVE_PROFILE", "missing")
    result = runner.invoke(app, ["keys", "list"])
    assert result.exit_code == 1
    assert "active_profile" in result.output
