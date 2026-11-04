"""Generator for docs/configuracao.md, and the check that it stays in sync."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from enum import Enum
from pathlib import Path
from typing import Annotated

import pytest
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from megila.config import Profile, Settings, TextModelSettings, load_settings
from megila.config.docgen import (
    REGENERATE_COMMAND,
    collect_env_vars,
    default_docs_path,
    main,
    out_of_date_message,
    render_config_docs,
    render_env_table,
)
from megila.config.docgen import (
    _env_rules as env_rules,
)
from megila.config.docgen import (
    _group_paragraph as group_paragraph,
)
from megila.config.paths import config_path

_TOML_FENCE = re.compile(r"```toml\n(.*?)```", re.DOTALL)


class Keyring(BaseModel):
    service: str = Field(default="megila", description="Serviço no chaveiro.")


class Mode(Enum):
    LOCAL = "local"


def _tags() -> list[str]:
    return ["a", "b"]


def _names() -> dict[str, str]:
    return {"b": "2", "a": "1"}


class ExtraSettings(BaseSettings):
    """Stand-in for fields another change might add to Settings."""

    model_config = SettingsConfigDict(
        env_prefix="MEGILA_",
        env_nested_delimiter="__",
    )

    db_path: Path = Field(
        default=Path("/var/megila.sqlite"),
        description="Caminho do banco.",
    )
    keyring: Keyring = Field(default_factory=Keyring, description="Chaveiro.")
    retries: int = Field(default=3, description="Tentativas.")
    ratio: float = Field(default=0.5, description="Razão.")
    note: str = Field(default="", description="Nota.")
    label: str | None = Field(default=None, description="Rótulo opcional.")
    tags: list[str] = Field(default_factory=_tags, description="Tags.")
    names: dict[str, str] = Field(default_factory=_names, description="Nomes.")
    enabled: Annotated[bool, "meta"] = Field(default=True, description="Ligado.")
    rel: Path = Field(default=Path("relative/file"), description="Relativo.")
    cfg: Path = Field(default_factory=config_path, description="Arquivo de config.")
    mode: Mode = Field(default=Mode.LOCAL, description="Modo.")
    choice: str = Field(default="a|b", description="esquerda | direita")


class Item(BaseModel):
    enabled: bool = Field(default=False, description="Ligado.")


def _items() -> dict[str, Item]:
    return {"default": Item(enabled=True), "aula": Item(enabled=False)}


class ItemsSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", env_nested_delimiter="__")

    items: dict[str, Item] = Field(default_factory=_items, description="Itens.")


class Step(BaseModel):
    name: str = Field(default="ingest", description="Nome do passo.")


class StepsSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", env_nested_delimiter="__")

    steps: list[Step] = Field(default_factory=list, description="Passos.")


class Child(BaseModel):
    name: str = Field(default="n", description="Nome.")


class OptionalParent(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="P_", env_nested_delimiter="__")

    child: Child | None = Field(default=None, description="Filho opcional.")


class NeedSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="X_")

    must: str = Field(description="Obrigatório.")


class SensitiveSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="Megila_", case_sensitive=True)

    data_dir: str = Field(default="x", description="Diretório.")


class AliasSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="M_")

    path: str = Field(
        default="x",
        validation_alias="db_path",
        description="Banco.",
    )


class BareSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="B_")

    note: str = "sem"


class Node(BaseModel):
    label: str = Field(default="n", description="Rótulo.")
    child: Node | None = Field(default=None, description="Filho.")


def _node() -> Node:
    return Node()


class WrapSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="N_", env_nested_delimiter="__")

    node: Node = Field(default_factory=_node, description="Nó.")


class DotChild(BaseModel):
    name: str = Field(default="a", description="Nome.")


class DotSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="p_", env_nested_delimiter=".")

    child: DotChild = Field(default_factory=DotChild, description="Filho.")


class EmptyMapSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="E_", env_nested_delimiter="__")

    items: dict[str, Item] = Field(default_factory=dict, description="")


class DotenvSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="D_", env_file=".env")

    name: str = Field(default="a", description="Nome.")


def _by_name(model: type[BaseModel]) -> dict[str, str]:
    return {item.name: item.default_text for item in collect_env_vars(model).variables}


def _code_span_end(text: str, start: int) -> int | None:
    width = 0
    while start + width < len(text) and text[start + width] == "`":
        width += 1
    fence = text[start : start + width]
    end = text.find(fence, start + width)
    if end == -1:
        return None
    return end + width


def _cells(row: str) -> list[str]:
    text = row.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|") and not text.endswith("\\|"):
        text = text[:-1]
    cells: list[str] = []
    current: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            current.append(text[index + 1])
            index += 2
            continue
        if char == "`":
            end = _code_span_end(text, index)
            if end is None:
                current.append(text[index:])
                break
            current.append(text[index:end])
            index = end
            continue
        if char == "|":
            cells.append("".join(current).strip())
            current = []
            index += 1
            continue
        current.append(char)
        index += 1
    cells.append("".join(current).strip())
    return cells


def test_future_fields_appear_without_a_generator_change() -> None:
    defaults = _by_name(ExtraSettings)
    assert defaults["MEGILA_DB_PATH"] == "/var/megila.sqlite"
    assert defaults["MEGILA_KEYRING__SERVICE"] == "megila"
    assert defaults["MEGILA_RETRIES"] == "3"
    assert defaults["MEGILA_RATIO"] == "0.5"
    assert defaults["MEGILA_NOTE"] == '""'
    assert defaults["MEGILA_LABEL"] == "None"
    assert defaults["MEGILA_TAGS"] == '["a", "b"]'
    assert defaults["MEGILA_NAMES"] == '{"a": "1", "b": "2"}'
    assert defaults["MEGILA_ENABLED"] == "true"
    assert defaults["MEGILA_REL"] == "relative/file"
    assert defaults["MEGILA_CFG"] == "~/.config/megila/config.toml"
    assert defaults["MEGILA_MODE"] == "local"
    assert defaults["MEGILA_CHOICE"] == "a|b"
    catalog = collect_env_vars(ExtraSettings)
    choice = next(item for item in catalog.variables if item.name == "MEGILA_CHOICE")
    assert choice.type_name == "str"
    assert choice.description == "esquerda | direita"
    label = next(item for item in catalog.variables if item.name == "MEGILA_LABEL")
    assert label.type_name == "Union[str, None]"
    enabled = next(item for item in catalog.variables if item.name == "MEGILA_ENABLED")
    assert enabled.type_name == "bool"
    table = render_env_table(catalog.variables)
    assert all(len(_cells(line)) == 4 for line in table.splitlines())
    assert "esquerda" in table
    assert "direita" in table


def test_mapping_sequence_optional_and_recursion() -> None:
    items = _by_name(ItemsSettings)
    assert items["APP_ITEMS__DEFAULT__ENABLED"] == "true"
    assert items["APP_ITEMS__AULA__ENABLED"] == "false"
    assert _by_name(StepsSettings) == {"APP_STEPS__0__NAME": "ingest"}
    assert _by_name(OptionalParent) == {"P_CHILD__NAME": "n"}
    assert _by_name(NeedSettings) == {"X_MUST": "obrigatório"}
    assert _by_name(SensitiveSettings) == {"Megila_data_dir": "x"}
    assert _by_name(AliasSettings) == {"M_DB_PATH": "x"}
    bare = collect_env_vars(BareSettings).variables
    assert bare[0].description == "Sem descrição."
    wrapped = {item.name for item in collect_env_vars(WrapSettings).variables}
    assert wrapped == {"N_NODE__LABEL", "N_NODE__CHILD"}
    assert _by_name(DotSettings) == {"P_CHILD.NAME": "a"}
    empty = collect_env_vars(EmptyMapSettings)
    assert empty.variables[0].name == "E_ITEMS__NOME__ENABLED"
    assert "NOME" in group_paragraph(empty.groups[0], empty.variables)
    assert "MEGILA_PROFILES__AULA__" in render_config_docs()


def test_env_rules_follow_the_model() -> None:
    settings_rules = env_rules(Settings).replace("\n", " ")
    assert "Arquivos `.env` não são lidos." in settings_rules
    assert "não distingue maiúsculas" in settings_rules
    assert "Arquivos `.env` não são lidos." not in env_rules(DotenvSettings)
    sensitive = env_rules(SensitiveSettings).replace("\n", " ")
    assert "distingue maiúsculas" in sensitive
    assert "não distingue" not in sensitive


def test_settings_fields_have_pt_br_descriptions() -> None:
    for model in (Settings, TextModelSettings, Profile):
        for name, field in model.model_fields.items():
            description = field.description
            assert isinstance(description, str) and description.strip(), name
    active = Settings.model_fields["active_profile"].description or ""
    text_model = Settings.model_fields["text_model"].description or ""
    profiles = Settings.model_fields["profiles"].description or ""
    assert "perfil" in active
    assert "texto" in text_model
    assert "perfil" in profiles
    provider = TextModelSettings.model_fields["provider"].description or ""
    assert "provedor" in provider
    assert "network connection" not in provider
    catalog = collect_env_vars(Settings)
    missing = [
        item.name for item in catalog.variables if item.description == "Sem descrição."
    ]
    assert missing == [], (
        "Add a pt-BR Field(description=...) so the generated page can "
        f"describe: {', '.join(missing)}"
    )
    undescribed = [
        group.field_path
        for group in catalog.groups
        if group.description == "Sem descrição."
    ]
    assert undescribed == []


def test_page_lists_every_variable_with_type_default_and_description() -> None:
    catalog = collect_env_vars(Settings)
    text = render_config_docs()
    names = [item.name for item in catalog.variables]
    assert names[0] == "MEGILA_DATA_DIR"
    assert "MEGILA_ACTIVE_PROFILE" in names
    assert "MEGILA_TEXT_MODEL__PROVIDER" in names
    assert "MEGILA_PROFILES__DEFAULT__LANGUAGE" in names
    assert names.index("MEGILA_DATA_DIR") < names.index("MEGILA_ACTIVE_PROFILE")
    assert names.index("MEGILA_ACTIVE_PROFILE") < names.index(
        "MEGILA_TEXT_MODEL__PROVIDER"
    )
    assert names.index("MEGILA_TEXT_MODEL__BASE_URL") < names.index(
        "MEGILA_PROFILES__DEFAULT__LANGUAGE"
    )
    by_name = {item.name: item for item in catalog.variables}
    assert by_name["MEGILA_DATA_DIR"].type_name == "Path"
    assert by_name["MEGILA_DATA_DIR"].default_text == "~/.local/share/megila"
    assert by_name["MEGILA_ACTIVE_PROFILE"].default_text == "default"
    assert by_name["MEGILA_TEXT_MODEL__PROVIDER"].default_text == "local"
    assert by_name["MEGILA_TEXT_MODEL__MODEL"].default_text == '""'
    assert by_name["MEGILA_TEXT_MODEL__BASE_URL"].type_name == "Union[str, None]"
    assert by_name["MEGILA_TEXT_MODEL__BASE_URL"].default_text == "None"
    assert by_name["MEGILA_PROFILES__DEFAULT__COMPRESS"].default_text == "false"
    assert by_name["MEGILA_PROFILES__DEFAULT__OVERLAYS"].default_text == "true"
    assert by_name["MEGILA_PROFILES__DEFAULT__GLOSSARY"].type_name == "dict[str, str]"
    assert by_name["MEGILA_PROFILES__DEFAULT__GLOSSARY"].default_text == "{}"
    for item in catalog.variables:
        assert f"`{item.name}`" in text
        assert item.description in text
        assert f"`{item.type_name}`" in text
    rows = [line for line in text.splitlines() if line.startswith("|")]
    assert rows
    assert all(len(_cells(row)) == 4 for row in rows)


def test_page_documents_precedence_and_xdg_layout() -> None:
    text = render_config_docs()
    assert text.index("kwargs") < text.index("`env`") < text.index("config.toml")
    assert "~/.config/megila/" in text
    assert "XDG_CONFIG_HOME" in text
    assert "config.toml" in text
    assert "~/.local/share/megila" in text
    assert "XDG_DATA_HOME" in text
    assert REGENERATE_COMMAND in text
    assert "Um valor vazio ou relativo" in text


def test_render_ignores_the_process_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MEGILA_DATA_DIR", "/from/env")
    monkeypatch.setenv("MEGILA_ACTIVE_PROFILE", "aula")
    monkeypatch.setenv("XDG_CONFIG_HOME", "/from/xdg-config")
    monkeypatch.setenv("XDG_DATA_HOME", "/from/xdg-data")
    first = render_config_docs()
    second = render_config_docs()
    assert first == second
    assert "/from/env" not in first
    assert "/from/xdg-config" not in first
    assert "/from/xdg-data" not in first
    assert "/tmp-megila-docgen" not in first
    assert str(Path.home()) not in first
    assert "~/.local/share/megila" in first
    assert "~/.config/megila/" in first


def test_documented_examples_load(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    blocks = _TOML_FENCE.findall(render_config_docs())
    assert len(blocks) == 2
    for key in list(os.environ):
        if key.lower().startswith("megila_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    path = tmp_path / "config.toml"
    for block in blocks:
        path.write_text(block, encoding="utf-8")
        settings = load_settings(config_file=path)
        assert settings.active_profile == "default"
    path.write_text(blocks[1], encoding="utf-8")
    external = load_settings(config_file=path)
    assert external.text_model.provider == "openai-compatible"
    assert external.text_model.base_url == "https://exemplo-do-provedor/v1"


def test_configuracao_md_matches_the_model() -> None:
    path = default_docs_path()
    expected = render_config_docs()
    actual = path.read_text(encoding="utf-8")
    assert actual == expected, out_of_date_message(path)


def test_out_of_date_message_tells_how_to_regenerate() -> None:
    message = out_of_date_message(default_docs_path())
    assert "docs/configuracao.md" in message
    assert "out of date" in message
    assert REGENERATE_COMMAND in message


def test_check_fails_with_regenerate_instructions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "configuracao.md"
    target.write_text("# velho\n", encoding="utf-8")
    assert main(["--check", "-o", str(target)]) == 1
    error = capsys.readouterr().err
    assert "out of date" in error
    assert REGENERATE_COMMAND in error
    assert target.read_text(encoding="utf-8") == "# velho\n"


def test_check_passes_when_the_file_matches(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "configuracao.md"
    target.write_text(render_config_docs(), encoding="utf-8")
    assert main(["--check", "-o", str(target)]) == 0
    assert capsys.readouterr().err == ""


def test_main_writes_the_page(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "nested" / "configuracao.md"
    assert main(["-o", str(target)]) == 0
    assert target.read_text(encoding="utf-8") == render_config_docs()
    assert "Wrote" in capsys.readouterr().out


def test_module_entrypoint(tmp_path: Path) -> None:
    target = tmp_path / "configuracao.md"
    completed = subprocess.run(
        [sys.executable, "-m", "megila.config.docgen", "-o", str(target)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert target.read_text(encoding="utf-8") == render_config_docs()


def test_missing_file_is_out_of_date(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "missing" / "configuracao.md"
    assert main(["--check", "-o", str(target)]) == 1
    assert REGENERATE_COMMAND in capsys.readouterr().err
