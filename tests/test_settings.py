"""Settings precedence, XDG paths, and secret rejection."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import settings as hypothesis_settings
from hypothesis import strategies as st

from megila.config import (
    PROFILE_EXPORT_FIELDS,
    ConfigError,
    Settings,
    TextModelSettings,
    config_path,
    load_settings,
)
from megila.config.secret_names import is_secret_name

_CANARY = "sk-live-NEVER-PRINT-THIS"


def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for key in list(os.environ):
        if key.lower().startswith("megila_"):
            monkeypatch.delenv(key, raising=False)
    config_home = tmp_path / "xdg-config"
    data_home = tmp_path / "xdg-data"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    return config_home / "megila" / "config.toml"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@contextmanager
def _scratch_env(config_home: Path, data_home: Path) -> Iterator[None]:
    saved = dict(os.environ)
    try:
        for key in list(os.environ):
            if key.lower().startswith("megila_"):
                del os.environ[key]
        os.environ["XDG_CONFIG_HOME"] = str(config_home)
        os.environ["XDG_DATA_HOME"] = str(data_home)
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


def test_model_fields_have_no_secret_or_remote_worker() -> None:
    assert set(Settings.model_fields) == {
        "data_dir",
        "active_profile",
        "text_model",
        "profiles",
    }
    assert set(TextModelSettings.model_fields) == {
        "provider",
        "model",
        "base_url",
        "keyring_service",
        "keyring_account",
    }
    assert all(not is_secret_name(name) for name in Settings.model_fields)
    assert all(not is_secret_name(name) for name in TextModelSettings.model_fields)


def test_missing_file_uses_defaults_and_creates_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = _isolate(monkeypatch, tmp_path)
    settings = load_settings()
    assert not path.exists()
    assert settings.data_dir == tmp_path / "xdg-data" / "megila"
    assert settings.active_profile == "default"
    assert settings.text_model.provider == "local"
    assert settings.text_model.model == ""
    assert settings.text_model.base_url is None
    assert settings.text_model.keyring_service == "megila"
    assert settings.text_model.keyring_account is None
    profile = settings.profiles["default"]
    assert profile.provider == "local"
    assert profile.language == "pt-BR"
    assert profile.compress is False
    assert profile.audio_enhance is False
    assert profile.overlays is True
    assert profile.auto_approve is False


def test_file_overrides_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = _isolate(monkeypatch, tmp_path)
    _write(
        path,
        """
data_dir = "/from/file"
active_profile = "default"

[text_model]
provider = "openai-compatible"
model = "from-file"
base_url = "https://example.test/v1"
keyring_account = "openai"

[profiles.default]
language = "en"
video_prompt = "from file"
provider = "local"
""",
    )
    settings = load_settings()
    assert settings.data_dir == Path("/from/file")
    assert settings.text_model.provider == "openai-compatible"
    assert settings.text_model.model == "from-file"
    assert settings.text_model.base_url == "https://example.test/v1"
    assert settings.text_model.keyring_account == "openai"
    assert settings.profiles["default"].language == "en"
    assert settings.profiles["default"].video_prompt == "from file"
    assert settings.profiles["default"].provider == "local"
    assert settings.profiles["default"].compress is False
    assert settings.profiles["default"].overlays is True


def test_env_overrides_file_and_keeps_other_file_fields(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = _isolate(monkeypatch, tmp_path)
    _write(
        path,
        """
data_dir = "/from/file"
active_profile = "default"

[text_model]
provider = "openai-compatible"
model = "from-file"
base_url = "https://example.test/v1"
keyring_account = "openai"

[profiles.default]
language = "en"
video_prompt = "from file"
compress = true
provider = "openai-compatible"
""",
    )
    monkeypatch.setenv("MEGILA_DATA_DIR", "/from/env")
    monkeypatch.setenv("MEGILA_TEXT_MODEL__PROVIDER", "local")
    monkeypatch.setenv("MEGILA_PROFILES__DEFAULT__LANGUAGE", "pt-BR")
    monkeypatch.setenv("MEGILA_PROFILES__DEFAULT__COMPRESS", "false")
    settings = load_settings()
    assert settings.data_dir == Path("/from/env")
    assert settings.text_model.provider == "local"
    assert settings.text_model.model == "from-file"
    assert settings.text_model.base_url == "https://example.test/v1"
    assert settings.text_model.keyring_account == "openai"
    profile = settings.profiles["default"]
    assert profile.language == "pt-BR"
    assert profile.compress is False
    assert profile.video_prompt == "from file"
    assert profile.provider == "openai-compatible"


def test_arguments_override_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = _isolate(monkeypatch, tmp_path)
    _write(path, 'data_dir = "/from/file"\n')
    monkeypatch.setenv("MEGILA_DATA_DIR", "/from/env")
    settings = load_settings(data_dir=Path("/from/init"))
    assert settings.data_dir == Path("/from/init")
    assert settings.text_model.provider == "local"


def test_tilde_in_file_expands(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = _isolate(monkeypatch, tmp_path)
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    _write(path, 'data_dir = "~/library"\n')
    settings = load_settings()
    assert settings.data_dir == home / "library"


def test_relative_data_dir_is_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = _isolate(monkeypatch, tmp_path)
    _write(path, 'data_dir = "relative"\n')
    with pytest.raises(ConfigError, match="absolute") as caught:
        load_settings()
    assert caught.value.__context__ is None


def test_invalid_profile_in_the_file_is_readable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = _isolate(monkeypatch, tmp_path)
    _write(
        path,
        """
[profiles.default]
language = "nope!"
""",
    )
    with pytest.raises(ConfigError, match="Invalid profile 'default'") as caught:
        load_settings()
    message = str(caught.value)
    assert "language" in message
    assert "BCP 47" in message
    assert caught.value.__context__ is None


def test_toml_secret_is_rejected_without_the_value(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = _isolate(monkeypatch, tmp_path)
    _write(
        path,
        f"""
[text_model]
api_key = "{_CANARY}"
provider = "openai-compatible"
""",
    )
    with pytest.raises(ConfigError, match="api_key") as caught:
        load_settings()
    message = str(caught.value)
    assert "keyring" in message
    assert _CANARY not in message
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_env_secret_is_rejected_without_the_value(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv("MEGILA_API_KEY", _CANARY)
    monkeypatch.setenv("megila_text_model__token", _CANARY)
    with pytest.raises(ConfigError, match="keyring") as caught:
        load_settings()
    message = str(caught.value)
    assert "MEGILA_API_KEY" in message
    assert "megila_text_model__token" in message
    assert _CANARY not in message
    assert caught.value.__context__ is None


def test_argument_secret_is_rejected_without_the_value(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate(monkeypatch, tmp_path)
    with pytest.raises(ConfigError, match="api_key") as caught:
        load_settings(text_model={"provider": "local", "api_key": _CANARY})
    assert _CANARY not in str(caught.value)
    assert caught.value.__context__ is None


def test_base_url_userinfo_and_query_omit_the_secret(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = _isolate(monkeypatch, tmp_path)
    _write(
        path,
        """
[text_model]
base_url = "https://sk-live-NEVER-PRINT-THIS@example.test/v1"
""",
    )
    with pytest.raises(ConfigError, match="password") as caught:
        load_settings()
    assert _CANARY not in str(caught.value)

    _write(
        path,
        """
[text_model]
base_url = "https://example.test/v1?api_key=sk-live-NEVER-PRINT-THIS"
""",
    )
    with pytest.raises(ConfigError, match="query") as caught:
        load_settings()
    assert _CANARY not in str(caught.value)
    assert caught.value.__context__ is None


def test_invalid_toml_names_the_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = _isolate(monkeypatch, tmp_path)
    _write(path, "=\n")
    with pytest.raises(ConfigError, match="invalid TOML") as caught:
        load_settings()
    assert str(path) in str(caught.value)
    assert caught.value.__context__ is None


def test_config_path_must_be_a_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = _isolate(monkeypatch, tmp_path)
    path.mkdir(parents=True)
    with pytest.raises(ConfigError, match="expected a file"):
        load_settings()


def test_missing_active_profile_is_readable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = _isolate(monkeypatch, tmp_path)
    _write(path, 'active_profile = "aula"\n')
    with pytest.raises(ConfigError, match="aula") as caught:
        load_settings()
    assert "not defined" in str(caught.value)


def test_dotenv_file_is_not_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate(monkeypatch, tmp_path)
    dotenv = tmp_path / ".env"
    dotenv.write_text("MEGILA_DATA_DIR=/from/dotenv\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    settings = load_settings()
    assert settings.data_dir == tmp_path / "xdg-data" / "megila"


def test_exported_profile_drops_connection_details(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = _isolate(monkeypatch, tmp_path)
    _write(
        path,
        """
[text_model]
provider = "openai-compatible"
model = "demo"
base_url = "https://example.test/v1"
keyring_service = "megila"
keyring_account = "openai"

[profiles.default]
provider = "local"
language = "pt-BR"
""",
    )
    settings = load_settings()
    exported = settings.exported_profiles()["default"]
    assert list(exported) == list(PROFILE_EXPORT_FIELDS)
    encoded = json.dumps(exported)
    assert "example.test" not in encoded
    assert "openai" not in encoded
    assert "api_key" not in encoded
    assert exported["provider"] == "local"


def test_config_path_respects_xdg_and_ignores_empty_or_relative(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    assert config_path() == tmp_path / "cfg" / "megila" / "config.toml"

    monkeypatch.setenv("HOME", "/home/person")
    monkeypatch.setenv("XDG_CONFIG_HOME", "   ")
    assert config_path() == Path("/home/person/.config/megila/config.toml")

    monkeypatch.setenv("XDG_CONFIG_HOME", "relative/config")
    assert config_path() == Path("/home/person/.config/megila/config.toml")

    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert config_path() == Path("/home/person/.config/megila/config.toml")


def test_text_model_rejects_bad_urls_and_accounts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = _isolate(monkeypatch, tmp_path)
    cases = (
        ('model = "line\\nbreak"\n', "control"),
        (f'model = "{"m" * 257}"\n', "256"),
        ('base_url = "ftp://example.test/v1"\n', "http or https"),
        ('base_url = "https://example.test/v1#part"\n', "fragment"),
        (f'base_url = "https://example.test/{"a" * 2100}"\n', "2048"),
        ('keyring_service = ""\n', "empty"),
        ('keyring_service = "my service"\n', "token"),
        ('keyring_account = "has space"\n', "token"),
    )
    for body, match in cases:
        _write(path, "[text_model]\n" + body)
        with pytest.raises(ConfigError, match=match):
            load_settings()


def test_empty_optional_text_fields_become_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = _isolate(monkeypatch, tmp_path)
    _write(
        path,
        """
[text_model]
base_url = ""
keyring_account = ""
""",
    )
    settings = load_settings()
    assert settings.text_model.base_url is None
    assert settings.text_model.keyring_account is None


def test_data_dir_must_be_a_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate(monkeypatch, tmp_path)
    with pytest.raises(ConfigError, match="path"):
        load_settings(data_dir=12)


def test_secret_inside_a_list_is_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate(monkeypatch, tmp_path)
    with pytest.raises(ConfigError, match="api_key") as caught:
        load_settings(notes=[{"api_key": _CANARY}])
    assert _CANARY not in str(caught.value)


def test_two_invalid_profiles_share_one_heading(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = _isolate(monkeypatch, tmp_path)
    _write(
        path,
        """
active_profile = "aula"

[profiles.default]
language = "!!"

[profiles.aula]
language = "??"
""",
    )
    with pytest.raises(ConfigError, match="Invalid profile:") as caught:
        load_settings()
    message = str(caught.value)
    assert "Invalid profile 'default'" not in message
    assert "profiles.default.language" in message
    assert "profiles.aula.language" in message


def test_profile_name_must_be_a_lowercase_identifier(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = _isolate(monkeypatch, tmp_path)
    _write(path, 'active_profile = "Aula"\n')
    with pytest.raises(ConfigError, match="lowercase") as caught:
        load_settings()
    assert caught.value.__context__ is None


def test_bad_profile_name_and_direct_constructor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = _isolate(monkeypatch, tmp_path)
    _write(path, 'active_profile = "Token"\n')
    with pytest.raises(ConfigError, match="credential"):
        load_settings()
    _write(path, 'data_dir = "/from/constructor"\n')
    settings = Settings()
    assert settings.data_dir == Path("/from/constructor")
    assert settings.active_profile == "default"


def test_non_bool_toggle_is_a_type_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = _isolate(monkeypatch, tmp_path)
    _write(
        path,
        """
[profiles.default]
compress = 2
""",
    )
    with pytest.raises(ConfigError, match="boolean"):
        load_settings()


def test_explicit_config_file_argument(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate(monkeypatch, tmp_path)
    chosen = tmp_path / "elsewhere" / "config.toml"
    _write(chosen, 'data_dir = "/from/explicit"\n')
    settings = load_settings(chosen)
    assert settings.data_dir == Path("/from/explicit")


@given(leaf=st.text(alphabet="abcdefghijklmnop", min_size=1, max_size=8))
@hypothesis_settings(max_examples=20, deadline=None)
def test_env_data_dir_beats_file_for_any_leaf(leaf: str) -> None:
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        config_home = root / "cfg"
        data_home = root / "data"
        config = config_home / "megila" / "config.toml"
        config.parent.mkdir(parents=True)
        config.write_text('data_dir = "/from/file"\n', encoding="utf-8")
        env_dir = f"/from/env/{leaf}"
        with _scratch_env(config_home, data_home):
            os.environ["MEGILA_DATA_DIR"] = env_dir
            settings = load_settings()
        assert settings.data_dir == Path(env_dir)
        assert settings.text_model.provider == "local"
