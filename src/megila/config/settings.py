"""Process settings.

Precedence, from highest to lowest:

1. Keyword arguments of :func:`load_settings` (and the ``Settings`` constructor).
2. Environment variables prefixed with ``MEGILA_``. Nested fields use ``__``.
3. The TOML file at :func:`megila.config.paths.config_path`.
4. Built-in defaults.

Dotenv files are not read. API keys are not settings; they belong in the
operating-system keyring.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from contextvars import ContextVar
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from megila.config.errors import ConfigError, display_value, render_validation_error
from megila.config.paths import config_path, default_data_dir
from megila.config.profile import Profile, validate_profile_name, validate_provider_name
from megila.config.secret_names import is_secret_name, secret_field_paths

_toml_path: ContextVar[Path | None] = ContextVar("megila_toml_path", default=None)


class TextModelSettings(BaseModel):
    """How to reach the text model. The secret itself is not here."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(
        default="local",
        description="Nome do provedor. `local` não abre conexão de rede.",
    )
    model: str = Field(
        default="",
        description="Identificador do modelo escolhido por quem opera.",
    )
    base_url: str | None = Field(
        default=None,
        description=(
            "URL base compatível com a API OpenAI, sem usuário, senha, "
            "query ou fragmento."
        ),
    )
    keyring_service: str = Field(
        default="megila",
        description="Nome do serviço no chaveiro do sistema. Não é o segredo.",
    )
    keyring_account: str | None = Field(
        default=None,
        description="Nome da conta no chaveiro do sistema. Não é o segredo.",
    )

    @field_validator("provider")
    @classmethod
    def _provider(cls, value: str) -> str:
        return validate_provider_name(value)

    @field_validator("model")
    @classmethod
    def _model(cls, value: str) -> str:
        if len(value) > 256:
            raise ValueError("must be at most 256 characters")
        if any(ord(character) < 32 for character in value):
            raise ValueError("must not contain control characters")
        return value

    @field_validator("base_url")
    @classmethod
    def _base_url(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if len(value) > 2048:
            raise ValueError("must be at most 2048 characters")
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or parsed.netloc == "":
            raise ValueError("must be an absolute http or https URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError(
                "must not include a username or password; "
                "store the key in the OS keyring"
            )
        if parsed.query or parsed.fragment:
            raise ValueError("must not include a query or fragment")
        return parsed.geturl()

    @field_validator("keyring_service")
    @classmethod
    def _keyring_service(cls, value: str) -> str:
        if len(value) > 128 or any(character.isspace() for character in value):
            raise ValueError(
                "must be a single token of at most 128 characters "
                f"(got {display_value(value)})"
            )
        if value == "":
            raise ValueError("must not be empty")
        return value

    @field_validator("keyring_account")
    @classmethod
    def _keyring_account(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if len(value) > 256 or any(character.isspace() for character in value):
            raise ValueError("must be a single token of at most 256 characters")
        return value


def _default_profiles() -> dict[str, Profile]:
    return {"default": Profile()}


class Settings(BaseSettings):
    """Effective Megila settings after precedence is applied."""

    model_config = SettingsConfigDict(
        env_prefix="MEGILA_",
        env_nested_delimiter="__",
        env_file=None,
        extra="forbid",
        case_sensitive=False,
        validate_default=True,
        nested_model_default_partial_update=True,
        secrets_dir=None,
    )

    data_dir: Path = Field(
        default_factory=default_data_dir,
        description=(
            "Diretório local da fila e das saídas de cada job. "
            "O padrão é `$XDG_DATA_HOME/megila`, ou `~/.local/share/megila` "
            "quando `XDG_DATA_HOME` não é um caminho absoluto."
        ),
    )
    active_profile: str = Field(
        default="default",
        description="Nome do perfil ativo. Precisa existir em `profiles`.",
    )
    text_model: TextModelSettings = Field(
        default_factory=TextModelSettings,
        description="Como alcançar o modelo de texto. O segredo não fica aqui.",
    )
    profiles: dict[str, Profile] = Field(
        default_factory=_default_profiles,
        description=(
            "Perfis nomeados. A chave é o identificador do perfil, como `default`."
        ),
    )

    @field_validator("data_dir", mode="before")
    @classmethod
    def _absolute_data_dir(cls, value: object) -> Path:
        if isinstance(value, str):
            path = Path(value).expanduser()
        elif isinstance(value, Path):
            path = value.expanduser()
        else:
            raise ValueError("must be a path")
        if not path.is_absolute():
            raise ValueError(
                f"must be an absolute path (got {display_value(str(path))})"
            )
        return path

    @field_validator("active_profile")
    @classmethod
    def _active_profile_name(cls, value: str) -> str:
        return validate_profile_name(value)

    @model_validator(mode="after")
    def _known_profiles(self) -> Settings:
        for name in self.profiles:
            validate_profile_name(name)
        if self.active_profile not in self.profiles:
            known = ", ".join(sorted(self.profiles)) or "(none)"
            raise ValueError(
                f"active_profile {self.active_profile!r} is not defined "
                f"(known profiles: {known})"
            )
        return self

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Use init, then the environment, then TOML. Never dotenv or a secret file."""
        del dotenv_settings, file_secret_settings
        _reject_secret_env(os.environ)
        return (
            init_settings,
            env_settings,
            MegilaTomlSource(settings_cls, _active_toml_path()),
        )

    def exported_profiles(self) -> dict[str, dict[str, Any]]:
        """Export every profile. The result has no secret fields."""
        return {name: profile.export() for name, profile in self.profiles.items()}


class MegilaTomlSource(TomlConfigSettingsSource):
    """TOML source that refuses secret fields and an unreadable file."""

    def __init__(self, settings_cls: type[BaseSettings], toml_file: Path) -> None:
        if toml_file.exists() and not toml_file.is_file():
            raise ConfigError(f"Cannot read {toml_file}: expected a file.")
        if toml_file.is_file():
            _read_toml(toml_file)
        super().__init__(settings_cls, toml_file=toml_file)


def load_settings(
    config_file: Path | None = None,
    **overrides: Any,
) -> Settings:
    """Load settings from arguments, ``MEGILA_`` variables, and TOML.

    Args:
        config_file: TOML file to read. Defaults to :func:`config_path`.
            A path that does not exist is not an error.
        **overrides: Field values. These beat the environment and the file.

    Raises:
        ConfigError: The file, the environment, or a field is invalid.
            Secret values are omitted from the message.
    """
    if overrides:
        _reject_secret_table(dict(overrides), source="settings arguments")
    path = config_path() if config_file is None else Path(config_file).expanduser()
    token = _toml_path.set(path)
    failure: str | None = None
    try:
        try:
            return Settings(**overrides)
        except ValidationError as exc:
            failure = _render_settings_error(exc)
    finally:
        _toml_path.reset(token)
    raise ConfigError(failure or "Invalid configuration.")


def _active_toml_path() -> Path:
    configured = _toml_path.get()
    if configured is None:
        return config_path()
    return configured


def _read_toml(path: Path) -> None:
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        message = f"Cannot read {path}: invalid TOML ({exc})."
    else:
        _reject_secret_table(data, source=str(path))
        return
    raise ConfigError(message)


def _reject_secret_env(environ: Mapping[str, str]) -> None:
    found: list[str] = []
    prefix = "megila_"
    for key in environ:
        normalized = key.lower()
        if not normalized.startswith(prefix):
            continue
        parts = normalized[len(prefix) :].split("__")
        for index, part in enumerate(parts):
            # The second segment of MEGILA_PROFILES__<name>__... is the
            # profile id, which is content, not a credential field.
            if parts and parts[0] == "profiles" and index == 1:
                continue
            if is_secret_name(part):
                found.append(key)
                break
    if not found:
        return
    names = ", ".join(sorted(found))
    raise ConfigError(
        "Megila does not read secrets from the environment. "
        f"Unset {names} and store the key in the OS keyring (service 'megila')."
    )


def _reject_secret_table(data: object, *, source: str) -> None:
    paths = secret_field_paths(data)
    if not paths:
        return
    rendered = ", ".join(paths)
    raise ConfigError(
        f"{source} cannot contain secrets ({rendered}). "
        "Remove those fields and store the key in the OS keyring "
        "(service 'megila')."
    )


def _render_settings_error(exc: ValidationError) -> str:
    profile_names: list[str] = []
    errors = exc.errors()
    for error in errors:
        loc = error.get("loc", ())
        if isinstance(loc, tuple) and len(loc) >= 2 and loc[0] == "profiles":
            profile_names.append(str(loc[1]))
    if profile_names and len(profile_names) == len(errors):
        unique = sorted(set(profile_names))
        if len(unique) == 1:
            heading = f"Invalid profile {unique[0]!r}:"
        else:
            heading = "Invalid profile:"
    else:
        heading = "Invalid configuration:"
    return render_validation_error(exc, heading=heading)
