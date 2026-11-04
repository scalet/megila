"""Generate the Portuguese settings reference from the settings model.

The page lists every environment variable of a settings model, so a field
added later shows up after ``python -m megila.config.docgen`` without a
change to this module's field list.

Run ``python -m megila.config.docgen`` from the repository root.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import UnionType
from typing import Annotated, Any, TypeGuard, Union, cast, get_args, get_origin
from unittest.mock import patch

from pydantic import BaseModel
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined

from megila.config.paths import config_path, default_data_dir
from megila.config.settings import Settings

REGENERATE_COMMAND = "python -m megila.config.docgen"
_MISSING_DESCRIPTION = "Sem descrição."
_REQUIRED = "obrigatório"
_FAKE_CONFIG = Path("/tmp-megila-docgen-config")
_FAKE_DATA = Path("/tmp-megila-docgen-data")
_REPO_ROOT = Path(__file__).resolve().parents[3]

_TAIL_BEFORE_ERROR = """\
## Exemplo

```toml
data_dir = "~/.local/share/megila"
active_profile = "default"

[text_model]
provider = "local"

[profiles.default]
language = "pt-BR"
video_prompt = "Descreva só os overlays pedidos."
summary_prompt = "Escreva o resumo pedido, e só isso."
compress = false
audio_enhance = false
overlays = true
auto_approve = false
provider = "local"

[profiles.default.glossary]
Megila = "pipeline de vídeo"
```

O provedor padrão é `local`: sem URL, sem conta e sem rede de
inferência. Um provedor externo é opt-in e continua sem o segredo no
arquivo:

```toml
[text_model]
provider = "openai-compatible"
model = "nome-do-modelo"
base_url = "https://exemplo-do-provedor/v1"
keyring_service = "megila"
keyring_account = "openai"
```

A URL não pode carregar usuário, senha, query ou fragmento. Isso evita
`https://chave@host` e `?api_key=...`. O perfil que escolhe o provedor
está em [Perfis](perfis.md). Enquanto o perfil ativo disser `local`, o
job não usa o provedor externo, mesmo que `text_model` já descreva uma
URL.

## Segredos

Estes nomes são recusados no arquivo, no ambiente e nos argumentos:
`api_key`, `token`, `password`, `secret`, `authorization` e os
equivalentes com hífen ou sufixo (`client_secret`, `access_token`).
O erro é legível e não repete o valor:

```text
"""

_SECRET_ERROR = (
    "/home/pessoa/.config/megila/config.toml cannot contain secrets "
    "(text_model.api_key). Remove those fields and store the key in "
    "the OS keyring (service 'megila')."
)

_TAIL_AFTER_ERROR = """\
```

O glossário é texto do perfil. Um termo chamado `token` é uma palavra,
não um campo de credencial. Ver [Perfis](perfis.md).

## Escrita atômica

`megila.storage.atomic_write` substitui um arquivo sem publicar um
conteúdo pela metade. O helper grava um temporário no mesmo diretório,
chama `fsync` nesse temporário, troca o nome com `os.replace` e chama
`fsync` no diretório. A troca no mesmo diretório é atômica no sistema
de arquivos. Uma falha antes do `replace` deixa o destino como estava,
ou ausente se ele ainda não existia, e apaga o temporário. Um crash do
processo no meio do temporário pode deixar um irmão `*.tmp`; o destino
não fica pela metade.

O modo de um arquivo novo é `0644`. Se o destino já existe, o modo
dele é preservado. Um link simbólico é substituído; a escrita não o
segue.

## Erros

TOML inválido, perfil desconhecido, caminho relativo e campo fora do
modelo viram `ConfigError`. A mensagem diz o arquivo ou o campo. Ela
não inclui o valor de um segredo rejeitado. Um perfil inválido dentro
do arquivo usa o mesmo texto de [Perfis](perfis.md), com o nome do
perfil.
"""


class _Missing:
    """Sentinel for a field that has neither a default nor a factory."""


_MISSING = _Missing()


@dataclass(frozen=True)
class EnvVar:
    """One environment variable derived from a settings field."""

    name: str
    type_name: str
    default_text: str
    description: str


@dataclass(frozen=True)
class FieldGroup:
    """A nested model or a mapping of models, documented above the table."""

    field_path: str
    description: str
    kind: str
    env_name: str
    delimiter: str
    case_sensitive: bool
    keys: tuple[str, ...]


@dataclass(frozen=True)
class EnvCatalog:
    """Variables and the container fields that introduce them."""

    variables: tuple[EnvVar, ...]
    groups: tuple[FieldGroup, ...]


@dataclass(frozen=True)
class Layout:
    """Config and data paths relative to the XDG homes."""

    config_relative: str
    data_relative: str


def default_docs_path() -> Path:
    """Return the committed path of ``docs/configuracao.md``."""
    return _REPO_ROOT / "docs" / "configuracao.md"


def out_of_date_message(path: Path) -> str:
    """Return the failure text that tells the reader how to regenerate."""
    return (
        f"{_display_path(path)} is out of date with the settings model.\n"
        "Regenerate it with:\n"
        f"    {REGENERATE_COMMAND}\n"
        "and commit the result."
    )


def collect_env_vars(model: type[BaseModel]) -> EnvCatalog:
    """Walk ``model`` and return one variable per leaf field.

    Nested models expand with the configured delimiter. A ``dict`` whose
    values are models expands once per default key. A model that contains
    itself is listed once, so the walk cannot recurse forever.
    """
    variables: list[EnvVar] = []
    groups: list[FieldGroup] = []
    with _stable_xdg():
        _walk(
            model,
            prefix=_displayed_prefix(model),
            delimiter=_delimiter(model),
            case_sensitive=_case_sensitive(model),
            instance=None,
            field_path=(),
            stack=(model,),
            variables=variables,
            groups=groups,
        )
    return EnvCatalog(tuple(variables), tuple(groups))


def render_env_table(variables: Sequence[EnvVar]) -> str:
    """Render the variable table. Pipes inside cells are escaped."""
    header = "| Variável | Tipo | Padrão | Descrição |"
    separator = "| --- | --- | --- | --- |"
    rows = [_table_row(item) for item in variables]
    return "\n".join([header, separator, *rows])


def render_config_docs() -> str:
    """Return the full ``docs/configuracao.md`` page for :class:`Settings`."""
    catalog = collect_env_vars(Settings)
    layout = discover_layout()
    blocks = [
        _preamble(Settings),
        _regenerate_block(),
        _config_section(layout),
        _data_section(layout),
        _variables_section(Settings, catalog),
        _tail(),
    ]
    return _join_blocks(blocks)


def main(argv: list[str] | None = None) -> int:
    """Write the page, or fail if ``--check`` finds it stale."""
    parser = argparse.ArgumentParser(
        prog=REGENERATE_COMMAND,
        description="Generate docs/configuracao.md from the settings model.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=default_docs_path(),
        help="Markdown file to write (default: docs/configuracao.md).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit with status 1 if the file is out of date, without writing.",
    )
    args = parser.parse_args(argv)
    destination = Path(str(args.output))
    rendered = render_config_docs()
    if bool(args.check):
        current = (
            destination.read_text(encoding="utf-8") if destination.is_file() else ""
        )
        if current != rendered:
            print(out_of_date_message(destination), file=sys.stderr)
            return 1
        return 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(rendered, encoding="utf-8")
    print(f"Wrote {_display_path(destination)}")
    return 0


def discover_layout() -> Layout:
    """Read the config and data paths without using this machine's home."""
    with _stable_xdg():
        config_relative = config_path().relative_to(_FAKE_CONFIG).as_posix()
        data_relative = default_data_dir().relative_to(_FAKE_DATA).as_posix()
    return Layout(config_relative, data_relative)


@contextmanager
def _stable_xdg() -> Iterator[None]:
    """Point XDG homes at fixed absolute paths for the duration of the block."""
    with patch.dict(
        os.environ,
        {
            "XDG_CONFIG_HOME": str(_FAKE_CONFIG),
            "XDG_DATA_HOME": str(_FAKE_DATA),
        },
    ):
        yield


def _walk(
    model: type[BaseModel],
    *,
    prefix: str,
    delimiter: str,
    case_sensitive: bool,
    instance: BaseModel | None,
    field_path: tuple[str, ...],
    stack: tuple[type[BaseModel], ...],
    variables: list[EnvVar],
    groups: list[FieldGroup],
) -> None:
    for name, field in model.model_fields.items():
        label = _field_label(field, name)
        env_name = f"{prefix}{_token(label, case_sensitive=case_sensitive)}"
        path = (*field_path, name)
        value = _field_value(field, instance, name)
        nested = _model_type(field.annotation)
        if nested is not None and nested not in stack:
            _append_group(
                groups,
                path=path,
                field=field,
                kind="model",
                env_name=env_name,
                delimiter=delimiter,
                case_sensitive=case_sensitive,
                keys=(),
            )
            child = value if isinstance(value, nested) else None
            _walk(
                nested,
                prefix=f"{env_name}{delimiter}",
                delimiter=delimiter,
                case_sensitive=case_sensitive,
                instance=child,
                field_path=path,
                stack=(*stack, nested),
                variables=variables,
                groups=groups,
            )
            continue
        mapped = _mapping_model(field.annotation)
        if mapped is not None and mapped not in stack:
            keys = _mapping_keys(value)
            _append_group(
                groups,
                path=path,
                field=field,
                kind="mapping",
                env_name=env_name,
                delimiter=delimiter,
                case_sensitive=case_sensitive,
                keys=keys,
            )
            _walk_mapping(
                mapped,
                value=value,
                keys=keys,
                env_name=env_name,
                delimiter=delimiter,
                case_sensitive=case_sensitive,
                field_path=path,
                stack=stack,
                variables=variables,
                groups=groups,
            )
            continue
        sequenced = _sequence_model(field.annotation)
        if sequenced is not None and sequenced not in stack:
            _append_group(
                groups,
                path=path,
                field=field,
                kind="sequence",
                env_name=env_name,
                delimiter=delimiter,
                case_sensitive=case_sensitive,
                keys=(),
            )
            _walk_sequence(
                sequenced,
                value=value,
                env_name=env_name,
                delimiter=delimiter,
                case_sensitive=case_sensitive,
                field_path=path,
                stack=stack,
                variables=variables,
                groups=groups,
            )
            continue
        variables.append(
            EnvVar(
                name=env_name,
                type_name=format_type(field.annotation),
                default_text=_render_default(value),
                description=_description(field),
            )
        )


def _walk_mapping(
    model: type[BaseModel],
    *,
    value: object,
    keys: tuple[str, ...],
    env_name: str,
    delimiter: str,
    case_sensitive: bool,
    field_path: tuple[str, ...],
    stack: tuple[type[BaseModel], ...],
    variables: list[EnvVar],
    groups: list[FieldGroup],
) -> None:
    mapping = value if isinstance(value, Mapping) else {}
    chosen = keys or ("NOME",)
    for key in chosen:
        token = _token(key, case_sensitive=case_sensitive)
        item = mapping.get(key) if isinstance(mapping, Mapping) else None
        child = item if isinstance(item, model) else None
        _walk(
            model,
            prefix=f"{env_name}{delimiter}{token}{delimiter}",
            delimiter=delimiter,
            case_sensitive=case_sensitive,
            instance=child,
            field_path=(*field_path, key),
            stack=(*stack, model),
            variables=variables,
            groups=groups,
        )


def _walk_sequence(
    model: type[BaseModel],
    *,
    value: object,
    env_name: str,
    delimiter: str,
    case_sensitive: bool,
    field_path: tuple[str, ...],
    stack: tuple[type[BaseModel], ...],
    variables: list[EnvVar],
    groups: list[FieldGroup],
) -> None:
    items: Sequence[object]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        items = value
    else:
        items = ()
    indexed = items or (None,)
    for index, item in enumerate(indexed):
        child = item if isinstance(item, model) else None
        _walk(
            model,
            prefix=f"{env_name}{delimiter}{index}{delimiter}",
            delimiter=delimiter,
            case_sensitive=case_sensitive,
            instance=child,
            field_path=(*field_path, str(index)),
            stack=(*stack, model),
            variables=variables,
            groups=groups,
        )


def _append_group(
    groups: list[FieldGroup],
    *,
    path: tuple[str, ...],
    field: FieldInfo,
    kind: str,
    env_name: str,
    delimiter: str,
    case_sensitive: bool,
    keys: tuple[str, ...],
) -> None:
    groups.append(
        FieldGroup(
            field_path=".".join(path),
            description=_description(field),
            kind=kind,
            env_name=env_name,
            delimiter=delimiter,
            case_sensitive=case_sensitive,
            keys=keys,
        )
    )


def _mapping_keys(value: object) -> tuple[str, ...]:
    if not isinstance(value, Mapping):
        return ()
    return tuple(str(key) for key in value)


def _field_value(field: FieldInfo, instance: BaseModel | None, name: str) -> object:
    if instance is not None:
        return getattr(instance, name)
    value = field.get_default(call_default_factory=True)
    if value is PydanticUndefined:
        return _MISSING
    return cast(object, value)


def _field_label(field: FieldInfo, name: str) -> str:
    alias = field.validation_alias
    if isinstance(alias, str) and alias != "":
        return alias
    return name


def _description(field: FieldInfo) -> str:
    raw = field.description
    if not isinstance(raw, str):
        return _MISSING_DESCRIPTION
    text = " ".join(raw.split())
    if text == "":
        return _MISSING_DESCRIPTION
    return text


def _render_default(value: object) -> str:
    if value is _MISSING:
        return _REQUIRED
    if isinstance(value, Enum):
        return _render_default(value.value)
    if isinstance(value, BaseModel):
        return "objeto"
    if isinstance(value, Path):
        return _display_xdg_path(value)
    if isinstance(value, str):
        return '""' if value == "" else value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(value)
    if value is None:
        return "None"
    if isinstance(value, Mapping):
        return json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            default=_json_default,
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return json.dumps(list(value), ensure_ascii=False, default=_json_default)
    return str(value)


def _json_default(value: object) -> str:
    if isinstance(value, Path):
        return _display_xdg_path(value)
    return str(value)


def _display_xdg_path(path: Path) -> str:
    if not path.is_absolute():
        return path.as_posix()
    homes = (
        (_FAKE_DATA, "~/.local/share"),
        (_FAKE_CONFIG, "~/.config"),
    )
    for root, prefix in homes:
        if path == root:
            return prefix
        if path.is_relative_to(root):
            return f"{prefix}/{path.relative_to(root).as_posix()}"
    return path.as_posix()


def format_type(annotation: Any) -> str:
    """Return a short Python spelling of ``annotation``."""
    annotation = _unwrap(annotation)
    if annotation is type(None):
        return "None"
    if annotation is Path:
        return "Path"
    if annotation is Any:
        return "Any"
    union_args = _union_args(annotation)
    if union_args is not None:
        # `str | None` contains a pipe, which markdownlint counts as a
        # table column. `Union[...]` is the same type and stays one cell.
        inner = ", ".join(format_type(arg) for arg in union_args)
        return f"Union[{inner}]"
    origin = get_origin(annotation)
    if origin is not None:
        args = tuple(arg for arg in get_args(annotation) if arg is not Ellipsis)
        name = getattr(origin, "__name__", None)
        label = name if isinstance(name, str) else str(origin)
        if not args:
            return label
        inner = ", ".join(format_type(arg) for arg in args)
        return f"{label}[{inner}]"
    if isinstance(annotation, type):
        return annotation.__name__
    return str(annotation).replace("typing.", "")


def _unwrap(annotation: Any) -> Any:
    seen: set[int] = set()
    current = annotation
    while True:
        if get_origin(current) is not Annotated:
            return current
        marker = id(current)
        if marker in seen:
            return current
        seen.add(marker)
        args = get_args(current)
        if not args:
            return current
        current = args[0]


def _union_args(annotation: Any) -> tuple[Any, ...] | None:
    origin = get_origin(annotation)
    if origin is Union or origin is UnionType:
        return get_args(annotation)
    return None


def _model_type(annotation: Any) -> type[BaseModel] | None:
    annotation = _unwrap(annotation)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    args = _union_args(annotation)
    if not args:
        return None
    models = [arg for arg in args if arg is not type(None) and _is_model_class(arg)]
    others = [arg for arg in args if arg is not type(None) and not _is_model_class(arg)]
    if len(models) == 1 and not others:
        found = models[0]
        if _is_model_class(found):
            return found
    return None


def _is_model_class(annotation: Any) -> TypeGuard[type[BaseModel]]:
    return isinstance(annotation, type) and issubclass(annotation, BaseModel)


def _mapping_model(annotation: Any) -> type[BaseModel] | None:
    annotation = _unwrap(annotation)
    if get_origin(annotation) is not dict:
        return None
    args = get_args(annotation)
    if len(args) != 2:
        return None
    return _model_type(args[1])


def _sequence_model(annotation: Any) -> type[BaseModel] | None:
    annotation = _unwrap(annotation)
    origin = get_origin(annotation)
    if origin not in {list, tuple}:
        return None
    args = tuple(arg for arg in get_args(annotation) if arg is not Ellipsis)
    if len(args) != 1:
        return None
    return _model_type(args[0])


def _model_config(model: type[BaseModel]) -> Mapping[str, Any]:
    return cast(Mapping[str, Any], model.model_config)


def _raw_prefix(model: type[BaseModel]) -> str:
    raw = _model_config(model).get("env_prefix", "")
    if isinstance(raw, str):
        return raw
    return ""


def _displayed_prefix(model: type[BaseModel]) -> str:
    prefix = _raw_prefix(model)
    if _case_sensitive(model):
        return prefix
    return prefix.upper()


def _delimiter(model: type[BaseModel]) -> str:
    raw = _model_config(model).get("env_nested_delimiter", "__")
    if isinstance(raw, str) and raw:
        return raw
    return "__"


def _case_sensitive(model: type[BaseModel]) -> bool:
    return _model_config(model).get("case_sensitive", False) is True


def _token(name: str, *, case_sensitive: bool) -> str:
    if case_sensitive:
        return name
    return name.upper()


def _reads_dotenv(model: type[BaseModel]) -> bool:
    raw = _model_config(model).get("env_file")
    return raw not in (None, "", [], ())


def _preamble(model: type[BaseModel]) -> str:
    prefix = _displayed_prefix(model) or "(sem prefixo)"
    lines = [
        "# Configuração",
        "",
        "O Megila lê a configuração em camadas. A mais específica vence.",
        "",
        "1. Argumentos nomeados (`kwargs`) de `load_settings` e do",
        "   construtor `Settings`.",
        f"2. Variáveis de ambiente (`env`) com o prefixo `{prefix}`.",
        "3. O arquivo `config.toml`.",
        "4. Os padrões embutidos no programa.",
        "",
        "Um valor passado em `kwargs` substitui o ambiente. Um valor no",
        "ambiente substitui o mesmo campo no `config.toml`. Um valor",
        "definido só no arquivo substitui o padrão. Os outros campos do",
        "arquivo permanecem.",
        "",
        "A chave de API não entra em nenhuma camada. Ela fica no chaveiro",
        "do sistema operacional, no serviço `megila`, como na",
        "[ADR 0005](adr/0005-ia-plugavel-e-keyring.md). O modelo guarda o",
        "nome do serviço e o da conta, não o segredo. Se o segredo",
        "aparecer na configuração, o programa recusa o arquivo, a",
        "variável ou o argumento e não repete o valor.",
    ]
    return "\n".join(lines)


def _regenerate_block() -> str:
    lines = [
        "Esta página é gerada a partir do modelo `Settings`. Não edite o",
        "arquivo à mão. Para atualizar depois de mudar um campo:",
        "",
        "```bash",
        REGENERATE_COMMAND,
        "```",
    ]
    return "\n".join(lines)


def _config_section(layout: Layout) -> str:
    relative = Path(layout.config_relative)
    parent = relative.parent.as_posix()
    name = relative.name
    if parent == ".":
        folder = "~/.config/"
        xdg = f"$XDG_CONFIG_HOME/{name}"
        fallback = f"~/.config/{name}"
    else:
        folder = f"~/.config/{parent}/"
        xdg = f"$XDG_CONFIG_HOME/{layout.config_relative}"
        fallback = f"~/.config/{layout.config_relative}"
    intro = _wrap(
        "O diretório de configuração respeita `XDG_CONFIG_HOME`. "
        f"O caminho do arquivo é `{xdg}` quando essa variável é um "
        f"caminho absoluto e não está vazio. Caso contrário, o arquivo é `{fallback}`."
    )
    lines = [
        "## Onde fica o arquivo",
        "",
        intro,
        "",
        "```text",
        folder,
        f"└── {name}",
        "```",
        "",
        "Um valor vazio ou relativo em `XDG_CONFIG_HOME` é ignorado, como",
        "pede a especificação XDG Base Directory. Um arquivo ausente não",
        "é erro: valem os padrões. O Megila não cria o arquivo sozinho.",
    ]
    return "\n".join(lines)


def _data_section(layout: Layout) -> str:
    relative = layout.data_relative
    lines = [
        "## Diretório de dados",
        "",
        "O padrão de `data_dir` é",
        f"`$XDG_DATA_HOME/{relative}`, ou `~/.local/share/{relative}`",
        "quando `XDG_DATA_HOME` não é um caminho absoluto. A fila e o",
        "diretório de cada job ficam aí, em disco local, como na",
        "[ADR 0006](adr/0006-local-por-padrao.md).",
        "",
        "`data_dir` tem de ser absoluto. `~` é expandido. Um caminho",
        "relativo é erro. `MEGILA_DATA_DIR` vence o arquivo, e o arquivo",
        "vence esse padrão. `XDG_DATA_HOME` só entra no cálculo do",
        "padrão; não é uma variável `MEGILA_`.",
    ]
    return "\n".join(lines)


def _variables_section(model: type[BaseModel], catalog: EnvCatalog) -> str:
    lines = ["## Variáveis de ambiente", "", _env_rules(model), ""]
    for group in catalog.groups:
        lines.append(_group_paragraph(group, catalog.variables))
        lines.append("")
    lines.append(render_env_table(catalog.variables))
    lines.extend(["", _unknown_variables()])
    return "\n".join(lines)


def _env_rules(model: type[BaseModel]) -> str:
    prefix = _displayed_prefix(model) or "(sem prefixo)"
    delimiter = _delimiter(model)
    if _case_sensitive(model):
        case = "A comparação distingue maiúsculas de minúsculas."
    else:
        case = "A comparação não distingue maiúsculas de minúsculas."
    sentences = [
        f"O prefixo é `{prefix}`. Campos aninhados usam `{delimiter}`.",
        case,
    ]
    if not _reads_dotenv(model):
        sentences.append("Arquivos `.env` não são lidos.")
    return _wrap(" ".join(sentences))


def _group_paragraph(group: FieldGroup, variables: Sequence[EnvVar]) -> str:
    if group.kind == "mapping":
        return _mapping_paragraph(group, variables)
    if group.kind == "sequence":
        head = (
            f"O campo `{group.field_path}` é uma lista. O índice começa em "
            f"`0` e entra em `{group.env_name}{group.delimiter}0"
            f"{group.delimiter}`."
        )
    else:
        head = (
            f"O campo `{group.field_path}` corresponde às variáveis que "
            f"começam com `{group.env_name}{group.delimiter}`."
        )
    if group.description == _MISSING_DESCRIPTION:
        return _wrap(head)
    return _wrap(f"{head} {group.description}")


def _mapping_paragraph(group: FieldGroup, variables: Sequence[EnvVar]) -> str:
    sentences = [
        (
            f"O campo `{group.field_path}` é uma tabela. Cada chave entra "
            f"na variável, entre `{group.env_name}{group.delimiter}` e o "
            "nome do campo."
        )
    ]
    if not group.case_sensitive:
        sentences.append("A chave é escrita em maiúsculas.")
    if group.description != _MISSING_DESCRIPTION:
        sentences.append(group.description)
    if not group.keys:
        sentences.append(
            "O padrão não traz chaves. O trecho `NOME` representa o identificador."
        )
    if group.keys:
        shown = ", ".join(
            f"`{key}` (`{_token(key, case_sensitive=group.case_sensitive)}` "
            "na variável)"
            for key in group.keys
        )
        if len(group.keys) == 1:
            sentences.append(f"A chave do padrão é {shown}.")
        else:
            sentences.append(f"As chaves do padrão são {shown}.")
    sibling = _sibling_example(group, variables)
    if sibling:
        sentences.append(sibling)
    return _wrap(" ".join(sentences))


def _sibling_example(group: FieldGroup, variables: Sequence[EnvVar]) -> str:
    if not group.keys:
        return ""
    key = group.keys[0]
    token = _token(key, case_sensitive=group.case_sensitive)
    prefix = f"{group.env_name}{group.delimiter}{token}{group.delimiter}"
    sample = next((item for item in variables if item.name.startswith(prefix)), None)
    if sample is None:
        return ""
    suffix = sample.name[len(prefix) :]
    fictional = "aula"
    fictional_token = _token(fictional, case_sensitive=group.case_sensitive)
    example = (
        f"{group.env_name}{group.delimiter}{fictional_token}{group.delimiter}{suffix}"
    )
    field_name = suffix if group.case_sensitive else suffix.lower()
    return (
        "Outra chave segue o mesmo formato. O campo "
        f"`{field_name}` da chave `{fictional}` é `{example}`."
    )


def _unknown_variables() -> str:
    return "\n".join(
        [
            "Uma variável desconhecida com o prefixo `MEGILA_` é ignorada,",
            "exceto quando o nome parece um segredo (`API_KEY`, `TOKEN`,",
            "`PASSWORD` e equivalentes). Nesse caso o programa para e pede",
            "para apagar a variável. A mensagem cita o nome da variável e",
            "não o valor.",
        ]
    )


def _tail() -> str:
    return f"{_TAIL_BEFORE_ERROR}{_SECRET_ERROR}\n{_TAIL_AFTER_ERROR}"


def _table_row(var: EnvVar) -> str:
    cells = [
        _cell(_code(var.name)),
        _cell(_code(var.type_name)),
        _cell(_code(var.default_text)),
        _cell(var.description),
    ]
    return "| " + " | ".join(cells) + " |"


def _code(text: str) -> str:
    if "`" in text:
        return f"`` {text} ``"
    return f"`{text}`"


def _cell(text: str) -> str:
    """Escape table separators that sit outside inline code.

    A pipe inside `` `...` `` is not a column break for the Markdown parser,
    and escaping it would show a backslash in the rendered type.
    """
    flat = text.replace("\n", " ")
    parts: list[str] = []
    index = 0
    while index < len(flat):
        if flat[index] == "`":
            end = _code_span_end(flat, index)
            if end is None:
                parts.append(flat[index:].replace("|", "\\|"))
                break
            parts.append(flat[index:end])
            index = end
            continue
        if flat[index] == "|":
            parts.append("\\|")
            index += 1
            continue
        parts.append(flat[index])
        index += 1
    return "".join(parts)


def _code_span_end(text: str, start: int) -> int | None:
    width = 0
    while start + width < len(text) and text[start + width] == "`":
        width += 1
    fence = text[start : start + width]
    end = text.find(fence, start + width)
    if end == -1:
        return None
    return end + width


def _wrap(text: str) -> str:
    return textwrap.fill(
        text,
        width=72,
        break_long_words=False,
        break_on_hyphens=False,
    )


def _join_blocks(blocks: Sequence[str]) -> str:
    cleaned = [block.strip("\n") for block in blocks if block.strip("\n")]
    return "\n\n".join(cleaned) + "\n"


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(_REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
