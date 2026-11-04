# Ambiente de desenvolvimento

Como preparar o computador para desenvolver o Megila. Este guia cobre o esqueleto do pacote: instalação editável, CLI e as ferramentas de verificação.

## Requisitos

- Python 3.12 ou superior
- `pip`
- Git

ffmpeg, modelos de fala e um runtime de IA local entram nas fases que os utilizam. Para o esqueleto, o interpretador basta.

## Criar o ambiente

Na raiz do repositório:

```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

O extra `dev` instala pytest, pytest-cov, ruff, mypy, pre-commit e hypothesis. As dependências de runtime são o Typer, o keyring e o structlog.

Ative os ganchos do Git uma vez por clone:

```bash
pre-commit install
```

## Conferir

```bash
megila --version
python -m megila --version
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m mypy
pre-commit run --all-files
```

`megila --version` encerra com código 0 e escreve `megila 0.1.0`. A versão fica em `src/megila/__init__.py`; o hatchling lê esse valor na hora do build.

## Ferramentas

A configuração fica no `pyproject.toml`.

- **ruff** faz o lint e a formatação.
- **mypy** roda em modo estrito (`strict = true`) sobre `src` e `tests`.
- **pre-commit** aplica checagens de higiene (espaço no fim da linha, YAML, TOML, chaves privadas), o ruff e o mypy.
- **pytest** executa a suíte. **pytest-cov** gera o relatório de cobertura. **hypothesis** fica disponível para testes de propriedade nas próximas fases.

## Layout do código

O pacote usa layout `src` (`src/megila/`). Os testes importam o código instalado em modo editável.

| Pacote | Função |
| --- | --- |
| `megila.cli` | Borda de linha de comando (Typer). Responde `--version`, `-V` e `megila keys`. |
| `megila.config` | Configuração de execução: caminhos, modelo e provedor. A chave de API não entra no arquivo. |
| `megila.secrets` | Chave do provedor no keyring do sistema. Sem backend, `megila keys` recusa gravar. |
| `megila.jobs` | Ciclo de vida dos trabalhos. |
| `megila.jobs.queue` | Fila durável em SQLite (WAL), com lease (reserva temporária) e heartbeat (sinal de vida). Pacote separado para a implementação ficar junto da interface. |
| `megila.stages` | Etapas do pipeline: ingerir, transcrever, sobrepor legendas, codificar e medir qualidade. |
| `megila.providers` | Provedores de IA plugáveis. O caminho padrão é Ollama ou llama.cpp na máquina; uma API externa usa a mesma interface. |
| `megila.plugins` | Pontos de extensão para registrar etapas, provedores e notificadores. |
| `megila.api` | Superfície HTTP (FastAPI), ao lado do CLI, chamando o mesmo núcleo. |
| `megila.notify` | Notificações de saída, a começar pelo Telegram. |
| `megila.storage` | Arquivos locais, com backup opcional via rclone na mesma fronteira. |

Nesta fase os pacotes declaram a fronteira de cada componente. As bordas (`cli`, `api`, `notify`, `storage`, `providers`, `secrets`) ficam separadas do núcleo (`jobs`, `stages`, `config`, `plugins`).

## Arquivos fora do Git

O `.gitignore` cobre `.env`, `keys/`, `secrets/`, caches de modelo (`models/`, `model_cache/`, `huggingface/`, `whisper/`, `whisper_models/`) e saídas de mídia (`output/`, `outputs/`, `renders/`, `media_out/`). Clipes de teste em `tests/assets/` permanecem no repositório.

A chave de API fica no keyring do sistema operacional. O comando e a política sem fallback em arquivo estão em [Segurança](../seguranca.md).
