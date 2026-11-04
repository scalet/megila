"""Content profiles.

A profile chooses prompts, language, glossary, stage toggles, and the AI
provider by name. It has no field for an API key. Exporting a profile
returns only the public fields.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from megila.config.errors import ProfileError, display_value, render_validation_error
from megila.config.secret_names import is_secret_name, secret_field_paths

PROFILE_EXPORT_FIELDS: tuple[str, ...] = (
    "video_prompt",
    "summary_prompt",
    "glossary",
    "language",
    "compress",
    "audio_enhance",
    "overlays",
    "auto_approve",
    "provider",
)

_LANGUAGE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
_PROVIDER = re.compile(r"^[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*$")
_MAX_PROVIDER_LENGTH = 64


def validate_provider_name(value: str) -> str:
    """Return ``value`` when it is a provider name, not a credential."""
    if is_secret_name(value):
        raise ValueError(
            "must be a provider name such as 'local', not a credential field "
            f"(got {display_value(value)})"
        )
    if len(value) > _MAX_PROVIDER_LENGTH or _PROVIDER.fullmatch(value) is None:
        raise ValueError(
            "must be a provider name such as 'local' "
            "(1-64 characters: lowercase letters, digits, hyphens, or "
            f"underscores; got {display_value(value)})"
        )
    return value


def validate_profile_name(value: str) -> str:
    """Return ``value`` when it can be used as a profile id."""
    if is_secret_name(value):
        raise ValueError(
            "must be a lowercase identifier such as 'default', "
            f"not a credential field (got {display_value(value)})"
        )
    if len(value) > _MAX_PROVIDER_LENGTH or _PROVIDER.fullmatch(value) is None:
        raise ValueError(
            "must be a lowercase identifier such as 'default' "
            f"(got {display_value(value)})"
        )
    return value


class Profile(BaseModel):
    """Frozen job profile. Secrets are not part of the model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    video_prompt: str = Field(
        default="",
        description="Instruções do plano de overlay. Não é segredo.",
    )
    summary_prompt: str = Field(
        default="",
        description="Instruções que o resumo deve seguir, e nada além delas.",
    )
    glossary: dict[str, str] = Field(
        default_factory=dict,
        description="Termo mapeado para a forma preferida.",
    )
    language: str = Field(
        default="pt-BR",
        description="Etiqueta BCP 47 fixa para os jobs que usam este perfil.",
    )
    compress: bool = Field(
        default=False,
        description="Pede um arquivo de entrega menor. Não autoriza subir o CRF.",
    )
    audio_enhance: bool = Field(
        default=False,
        description="Pede tratamento de áudio. Desligado, o áudio permanece intacto.",
    )
    overlays: bool = Field(
        default=True,
        description="Permite queimar overlays quando o prompt de vídeo os pede.",
    )
    auto_approve: bool = Field(
        default=False,
        description=(
            "Reserva um futuro pulo da aprovação humana. "
            "Não desliga a checagem de qualidade."
        ),
    )
    provider: str = Field(
        default="local",
        description="Nome do provedor de IA. A chave de API não fica aqui.",
    )

    @field_validator("video_prompt", "summary_prompt")
    @classmethod
    def _prompts(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("must not contain NUL")
        return value

    @field_validator("language")
    @classmethod
    def _language(cls, value: str) -> str:
        if _LANGUAGE.fullmatch(value) is None:
            raise ValueError(
                "must be a BCP 47 tag such as 'pt-BR' or 'en' "
                f"(got {display_value(value)})"
            )
        return value

    @field_validator("provider")
    @classmethod
    def _provider(cls, value: str) -> str:
        return validate_provider_name(value)

    @field_validator("glossary")
    @classmethod
    def _glossary(cls, value: dict[str, str]) -> dict[str, str]:
        cleaned: dict[str, str] = {}
        for term, preferred in value.items():
            stripped = term.strip()
            if stripped == "":
                raise ValueError("terms must not be empty")
            if "\x00" in stripped or "\x00" in preferred:
                raise ValueError("entries must not contain NUL")
            if stripped in cleaned:
                raise ValueError(f"duplicate term {stripped!r}")
            cleaned[stripped] = preferred
        return cleaned

    def export(self) -> dict[str, Any]:
        """Return a JSON-ready copy that contains only public fields."""
        raw = self.model_dump(mode="json")
        unexpected = set(raw) - set(PROFILE_EXPORT_FIELDS)
        if unexpected or any(is_secret_name(key) for key in raw):
            names = ", ".join(sorted(unexpected))
            raise ProfileError(f"Exported profile contains unexpected fields: {names}")
        exported: dict[str, Any] = {}
        for key in PROFILE_EXPORT_FIELDS:
            value = raw[key]
            if key == "glossary" and isinstance(value, dict):
                exported[key] = dict(value)
            else:
                exported[key] = value
        return exported


def load_profile(data: Mapping[str, Any]) -> Profile:
    """Validate ``data`` as a profile.

    Raises:
        ProfileError: ``data`` is not a profile. Secret values are omitted
            from the message.
    """
    if not isinstance(data, Mapping):
        raise ProfileError(
            "Invalid profile:\n- configuration: expected a table of fields"
        )
    secret_paths = secret_field_paths(data)
    if secret_paths:
        names = ", ".join(secret_paths)
        raise ProfileError(
            "Invalid profile:\n"
            f"- {names} cannot store secrets. Put the key in the OS keyring "
            "(service 'megila'), not in the profile."
        )
    failure: str | None = None
    try:
        return Profile.model_validate(dict(data))
    except ValidationError as exc:
        failure = render_validation_error(exc, heading="Invalid profile:")
    raise ProfileError(failure or "Invalid profile.")
