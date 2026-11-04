"""Profile model: validation, export, and property tests."""

from __future__ import annotations

import json
from typing import Any

import pytest
from hypothesis import given
from hypothesis import settings as hypothesis_settings
from hypothesis import strategies as st
from pydantic import ValidationError

from megila.config import (
    PROFILE_EXPORT_FIELDS,
    Profile,
    ProfileError,
    load_profile,
)
from megila.config.secret_names import is_secret_name

_CANARY = "sk-live-NEVER-PRINT-THIS"
_PROMPTS = st.text(
    alphabet=st.characters(exclude_categories=["Cs"], exclude_characters="\x00"),
    max_size=60,
)
_TERMS = st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=12)
_PROVIDERS = st.one_of(
    st.just("local"),
    st.just("openai-compatible"),
    st.from_regex(r"[a-z][a-z0-9]{0,8}(-[a-z0-9]{1,6}){0,2}", fullmatch=True),
).filter(lambda name: not is_secret_name(name))


def test_defaults_are_local_and_closed() -> None:
    profile = load_profile({})
    assert profile.provider == "local"
    assert profile.language == "pt-BR"
    assert profile.video_prompt == ""
    assert profile.summary_prompt == ""
    assert profile.glossary == {}
    assert profile.compress is False
    assert profile.audio_enhance is False
    assert profile.overlays is True
    assert profile.auto_approve is False


def test_invalid_language_is_readable() -> None:
    with pytest.raises(ProfileError, match="language") as caught:
        load_profile({"language": "123"})
    message = str(caught.value)
    assert "Invalid profile:" in message
    assert "BCP 47" in message
    assert "123" in message
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_provider_named_like_a_secret_is_rejected() -> None:
    with pytest.raises(ProfileError, match="credential") as caught:
        load_profile({"provider": "token"})
    assert "token" in str(caught.value)
    assert caught.value.__context__ is None


def test_export_refuses_an_unexpected_field(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = load_profile({})
    original = Profile.model_dump

    def dump(self: Profile, *args: object, **kwargs: object) -> dict[str, Any]:
        del args, kwargs
        data = original(self, mode="json")
        data["api_key"] = _CANARY
        return data

    monkeypatch.setattr(Profile, "model_dump", dump)
    with pytest.raises(ProfileError, match="api_key") as caught:
        profile.export()
    assert _CANARY not in str(caught.value)


def test_invalid_provider_names_the_field() -> None:
    with pytest.raises(ProfileError, match="provider") as caught:
        load_profile({"provider": "OpenAI"})
    assert "local" in str(caught.value)
    assert caught.value.__context__ is None


def test_secret_field_error_omits_the_value() -> None:
    with pytest.raises(ProfileError, match="api_key") as caught:
        load_profile({"api_key": _CANARY, "language": "pt-BR"})
    message = str(caught.value)
    assert "cannot store secrets" in message
    assert "keyring" in message
    assert _CANARY not in message
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_nested_secret_is_rejected_without_the_value() -> None:
    with pytest.raises(ProfileError, match="api_key") as caught:
        load_profile({"notes": {"api_key": _CANARY}})
    assert _CANARY not in str(caught.value)
    assert caught.value.__context__ is None


def test_unknown_field_does_not_echo_its_value() -> None:
    with pytest.raises(ProfileError, match="theme") as caught:
        load_profile({"theme": _CANARY})
    message = str(caught.value)
    assert "unknown field" in message
    assert _CANARY not in message
    assert caught.value.__context__ is None


def test_glossary_term_token_is_content() -> None:
    profile = load_profile({"glossary": {"token": "ficha"}})
    assert profile.glossary == {"token": "ficha"}
    assert profile.export()["glossary"] == {"token": "ficha"}


def test_glossary_rejects_blank_terms() -> None:
    with pytest.raises(ProfileError, match="glossary"):
        load_profile({"glossary": {"  ": "x"}})


def test_glossary_rejects_nul_and_duplicates() -> None:
    with pytest.raises(ProfileError, match="NUL"):
        load_profile({"glossary": {"termo": "a\x00b"}})
    with pytest.raises(ProfileError, match="duplicate"):
        load_profile({"glossary": {"termo": "a", "termo ": "b"}})


def test_prompt_rejects_nul() -> None:
    with pytest.raises(ProfileError, match="NUL"):
        load_profile({"video_prompt": "a\x00b"})


def test_long_invalid_language_is_truncated() -> None:
    value = "x" * 80
    with pytest.raises(ProfileError, match="language") as caught:
        load_profile({"language": value})
    message = str(caught.value)
    assert "..." in message
    assert value not in message


def test_renderer_redacts_a_secret_shaped_extra_field() -> None:
    from pydantic import BaseModel, ConfigDict

    from megila.config.errors import render_validation_error

    class Bare(BaseModel):
        model_config = ConfigDict(extra="forbid")
        language: str = "pt-BR"

    with pytest.raises(ValidationError) as caught:
        Bare.model_validate({"api_key": _CANARY})
    message = render_validation_error(caught.value, heading="Invalid profile:")
    assert "cannot store secrets" in message
    assert _CANARY not in message


def test_non_mapping_is_rejected() -> None:
    with pytest.raises(ProfileError, match="table"):
        load_profile([])  # type: ignore[arg-type]


def test_export_is_a_copy_of_public_fields_only() -> None:
    profile = load_profile(
        {
            "video_prompt": "mostre o termo",
            "summary_prompt": "resuma só o pedido",
            "glossary": {"Megila": "pipeline"},
            "language": "pt-BR",
            "compress": True,
            "provider": "openai-compatible",
        }
    )
    exported = profile.export()
    assert list(exported) == list(PROFILE_EXPORT_FIELDS)
    forbidden = {
        "api_key",
        "apikey",
        "secret",
        "token",
        "password",
        "authorization",
        "keyring_account",
        "base_url",
    }
    assert forbidden.isdisjoint(exported)
    encoded = json.dumps(exported)
    assert _CANARY not in encoded
    assert exported["provider"] == "openai-compatible"
    glossary = exported["glossary"]
    assert isinstance(glossary, dict)
    glossary["Megila"] = "changed"
    assert profile.glossary["Megila"] == "pipeline"


def test_profile_is_frozen() -> None:
    profile = Profile()
    with pytest.raises(ValidationError):
        profile.provider = "local"


def test_json_schema_has_no_secret_properties() -> None:
    properties = Profile.model_json_schema()["properties"]
    assert set(properties) == set(PROFILE_EXPORT_FIELDS)
    assert "api_key" not in properties


def test_repr_of_a_normal_profile_has_no_secret_field() -> None:
    profile = load_profile({"video_prompt": "olá", "provider": "local"})
    assert "api_key" not in repr(profile)
    assert "password" not in repr(profile)


@given(
    video_prompt=_PROMPTS,
    summary_prompt=_PROMPTS,
    glossary=st.dictionaries(_TERMS, _PROMPTS, max_size=6),
    language=st.sampled_from(["pt-BR", "en", "pt", "es-419", "zh-Hant"]),
    compress=st.booleans(),
    audio_enhance=st.booleans(),
    overlays=st.booleans(),
    auto_approve=st.booleans(),
    provider=_PROVIDERS,
)
@hypothesis_settings(max_examples=40, deadline=None)
def test_export_round_trip_has_no_secret_fields(
    video_prompt: str,
    summary_prompt: str,
    glossary: dict[str, str],
    language: str,
    compress: bool,
    audio_enhance: bool,
    overlays: bool,
    auto_approve: bool,
    provider: str,
) -> None:
    payload: dict[str, Any] = {
        "video_prompt": video_prompt,
        "summary_prompt": summary_prompt,
        "glossary": glossary,
        "language": language,
        "compress": compress,
        "audio_enhance": audio_enhance,
        "overlays": overlays,
        "auto_approve": auto_approve,
        "provider": provider,
    }
    profile = load_profile(payload)
    exported = profile.export()
    assert list(exported) == list(PROFILE_EXPORT_FIELDS)
    assert all(not is_secret_name(key) for key in exported)
    assert load_profile(exported) == profile
    json.dumps(exported)
    with pytest.raises(ValidationError):
        profile.language = "en"


@given(value=st.text(max_size=40))
@hypothesis_settings(max_examples=25, deadline=None)
def test_provider_names_match_the_validator(value: str) -> None:
    from megila.config.profile import validate_provider_name

    rejected = False
    try:
        validate_provider_name(value)
    except ValueError:
        rejected = True
    if not rejected:
        assert load_profile({"provider": value}).provider == value
        return
    with pytest.raises(ProfileError, match="provider") as caught:
        load_profile({"provider": value})
    assert caught.value.__context__ is None
