# CI

O workflow fica em `.github/workflows/ci.yml`. Ele roda no Ubuntu
(`ubuntu-latest`), em Python 3.12 e 3.13, a cada pull request, a cada push
na `main` e quando alguém dispara o workflow à mão. O runner é o gratuito
do GitHub Actions. Não há segredo nem serviço pago.

O pacote declara `requires-python >= 3.12`. O mypy do `pyproject.toml` usa
`python_version = 3.12` nos dois jobs. O job de 3.13 executa o mesmo código
no interpretador 3.13.

## Jobs

| Job | O que confere |
| --- | --- |
| `Python 3.12` | ruff, mypy estrito, pre-commit, pytest com cobertura |
| `Python 3.13` | ruff, mypy estrito e pytest com cobertura |
| `ci` | falha se 3.12 ou 3.13 falhar |

O check que a proteção da `main` deve exigir é `CI / ci`. Ele só passa
quando as duas versões passam. `pre-commit run --all-files` roda no job
3.12, porque repete o ruff e o mypy e ainda confere YAML, TOML e higiene.
Rodar isso duas vezes não muda o resultado.

O ambiente do hook de mypy não instala o Megila. O que esse mypy precisa
importar fica em `additional_dependencies`, com o mesmo piso do
`pyproject.toml`: as dependências de runtime (typer, pydantic,
pydantic-settings) e as que os testes importam (pytest e hypothesis).
`python -m mypy` no job usa o pacote instalado em modo editável, então vê
as mesmas bibliotecas.

Cada versão executa, com o pacote instalado em modo editável (`pip install -e ".[dev]"`):

```bash
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pytest \
  --cov-report=json:"${TMPDIR:-/tmp}/megila-coverage.json" \
  --junitxml:"${TMPDIR:-/tmp}/megila-pytest.xml"
python .github/ci/coverage_gate.py \
  --coverage "${TMPDIR:-/tmp}/megila-coverage.json" \
  --baseline .github/coverage-baseline.json \
  --reference /caminho/da/linha-de-base-da-main.json \
  --junit "${TMPDIR:-/tmp}/megila-pytest.xml"
```

No pull request, a referência é o `.github/coverage-baseline.json` da branch
de base. Se a `main` ainda não tem esse arquivo, a referência é o arquivo
deste commit. Num push na `main`, a referência é o arquivo do próprio commit.

## ffmpeg, libass, libvmaf e espeak-ng

O clipe sintético precisa de `ffmpeg`, `ffprobe` e `espeak-ng` com a voz
`pt-br`. Sem isso o pytest pula o teste de integração e o restante fica
verde. O gate lê o JUnit e falha se
`test_generated_clip_is_deterministic_and_matches_probe` não rodou.

O ffmpeg do apt no Ubuntu 24.04 traz `libx264` e libass (filtro `ass`) e
não traz libvmaf. O script `.github/ci/ensure-media-tools.sh` instala
`ffmpeg` e `espeak-ng` pelo apt, confere o encoder `libx264`, os filtros
`ass` e `libvmaf`, e a voz `pt-br`. Se faltar libx264, libass ou libvmaf,
baixa uma build estática GPL do
[BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds), release
`autobuild-2026-11-04-12-51`, arquivo da linha 8.1 (`linux64` ou
`linuxarm64`, conforme a arquitetura). O SHA-256 está no script. A build
`x86_64` foi conferida: tem `libx264`, o filtro `ass` e o filtro `libvmaf`.
A de `aarch64` é o par GPL da mesma release; o script sonda o binário
depois de extrair e falha se a sonda não passar.

O tarball não entra no Git. A
[ADR 0002](../adr/0002-licenca-mit-sem-codigo-agpl.md) trata ffmpeg como
programa externo, chamado por subprocesso. A build é GPL por causa do
libx264 e de outros componentes; quem roda o job aceita a licença daquele
binário. O Megila não a redistribui. O passo seguinte do workflow repete a
sonda, para confirmar que o `PATH` do runner ficou com essa build e não com
o ffmpeg do apt.

Para trocar o pino: atualize a tag, os dois nomes de arquivo e os dois
SHA-256 no script, extraia a build e confira de novo `libx264`, `ass` e
`libvmaf`.

O espeak-ng continua o do apt, com os dados de voz que já trazem `pt-br`.
O detalhe do clipe está em [Amostras de teste](amostras.md). O motivo do
libvmaf está na [ADR 0004](../adr/0004-qualidade-em-primeiro-lugar.md).

## Cache

O token do workflow pede `contents: read` e, no job de Python,
`actions: write`. A escrita serve só ao cache de Actions. Não há secret.

| Cache | Onde | Chave |
| --- | --- | --- |
| pip | cache do `actions/setup-python` | `pyproject.toml` e a versão do Python |
| modelos | `.cache/huggingface`, `.cache/whisper`, `model_cache/` | `pyproject.toml` |
| ffmpeg estático | `~/.cache/megila/ffmpeg` | o script de instalação e a arquitetura |
| pre-commit | `~/.cache/pre-commit` | `.pre-commit-config.yaml`, só no Python 3.12 |

Os pesos não entram no Git. O job aponta `HF_HOME`,
`HUGGINGFACE_HUB_CACHE` e `XDG_CACHE_HOME` para `.cache/` no workspace, para
um download futuro cair no cache em vez de ir para o diretório do runner.
Nesta fase a suíte não baixa modelo. O diretório fica preparado.

Se um passo de cache falhar com permissão negada no log, em
**Settings → Actions → General → Workflow permissions** a opção precisa ser
**Read and write permissions**. Com o padrão antigo de leitura e escrita,
o `permissions:` do workflow basta e essa tela não muda.

## Cobertura

O percentual é o de linhas e ramos juntos, o mesmo `percent_covered` do
coverage.py, arredondado a duas casas decimais. O gate está em
`.github/ci/coverage_gate.py`.

Pisos, sempre:

- total ≥ 80%
- cada pacote de núcleo com linha executável ≥ 90%
- o agregado desses pacotes ≥ 90%, quando houver linha executável

Núcleo: `megila.config`, `megila.jobs` (inclui `megila.jobs.queue`),
`megila.plugins` e `megila.stages`. As bordas (`cli`, `api`, `notify`,
`storage`, `providers`) entram só no total. Pacote sem linha executável não
tem percentual: não derruba o piso de 90%, e a linha de base grava `null`.
Quando a primeira linha executável aparecer, o pull request precisa gravar
o número novo. A diferença entre o arquivo commitado e a medida não pode
passar de 1 ponto.

Queda contra a `main`: a referência é o
`.github/coverage-baseline.json` da branch de base, não a cópia editada no
pull request. Queda de mais de 1,00 ponto no total, no agregado do núcleo
ou num pacote de núcleo falha o job. Queda de exatamente 1,00 ponto não
falha. Editar o arquivo para baixo não esconde essa comparação.

O arquivo deste commit também tem de ficar a no máximo 1 ponto da medida.
Subir a cobertura em mais de 1 ponto sem atualizar o arquivo falha, para a
linha de base acompanhar. Aí o comando abaixo imprime o JSON:

```bash
python .github/ci/coverage_gate.py \
  --coverage "${TMPDIR:-/tmp}/megila-coverage.json" \
  --print-baseline > .github/coverage-baseline.json
```

Revise o diff antes de commitar. O arquivo é a linha de base da `main`
depois do merge.

## O mesmo fluxo na máquina local

O ambiente de pytest, ruff e mypy está em
[Ambiente de desenvolvimento](ambiente.md). Na raiz do repositório, com o
virtualenv ativo:

```bash
path_file="${TMPDIR:-/tmp}/megila-ffmpeg-path"
rm -f "${path_file}"
if ! bash .github/ci/ensure-media-tools.sh --check; then
  GITHUB_PATH="${path_file}" bash .github/ci/ensure-media-tools.sh
  export PATH="$(cat "${path_file}"):${PATH}"
fi
python -m ruff check .
python -m ruff format --check .
python -m mypy
pre-commit run --all-files
python -m pytest \
  --cov-report=json:"${TMPDIR:-/tmp}/megila-coverage.json" \
  --junitxml:"${TMPDIR:-/tmp}/megila-pytest.xml"
git fetch origin main
git show origin/main:.github/coverage-baseline.json \
  > "${TMPDIR:-/tmp}/coverage-baseline-main.json"
python .github/ci/coverage_gate.py \
  --coverage "${TMPDIR:-/tmp}/megila-coverage.json" \
  --baseline .github/coverage-baseline.json \
  --reference "${TMPDIR:-/tmp}/coverage-baseline-main.json" \
  --junit "${TMPDIR:-/tmp}/megila-pytest.xml"
```

`--check` só sonda o `PATH`. Se faltar libvmaf, o comando sem `--check`
pede `sudo` para o apt e, ainda assim, baixa a build estática. O arquivo
apontado por `GITHUB_PATH` recebe o diretório do binário que o job usa.
Os relatórios ficam fora do repositório. Um nome que começa com
`.coverage.` some quando o coverage.py começa outra execução: ele trata
esse padrão como dado paralelo.

O `mkdocs.yml` usa tags `!!python/name` e `!!python/object/apply`. O
`check-yaml` seguro recusa essas tags. O pre-commit deixa esse arquivo de
fora do hook seguro e o confere de novo com `--unsafe` e
`pymdown-extensions`, que é o que resolve as tags. Os outros YAML continuam
no carregamento seguro.

Python 3.13, quando estiver instalado, repete ruff, mypy e pytest. O gate
de cobertura no CI roda nas duas versões, contra a mesma linha de base.

## Proteção da branch main

Isto não dá para ligar pelo pull request. Em **Settings → Branches → Add
branch protection rule** (ou **Settings → Rules → Rulesets**, se o
repositório usa rulesets), a regra da `main` precisa de **Require status
checks to pass before merging** com estes checks:

| Check na lista | Workflow |
| --- | --- |
| `CI / ci` | `.github/workflows/ci.yml` |
| `Markdown / markdownlint` | `.github/workflows/markdown.yml` |
| `Markdown / link check` | `.github/workflows/markdown.yml` |
| `Docs / Strict build` | `.github/workflows/docs.yml` |

Não marque `Docs / Deploy GitHub Pages`. Esse job não roda em pull request.
Check obrigatório que fica skipped segura o merge.

Os nomes só aparecem na busca depois que cada workflow rodou pelo menos uma
vez. Dá para marcar a regra quando os checks deste pull request estiverem
visíveis.

A descrição dessa tela está em
[About protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).

Para a comparação de cobertura contra a `main` valer também para quem pode
fazer push direto, a mesma regra deve exigir pull request antes do merge.
Sem isso, um push direto pode trocar a linha de base no mesmo commit em que
a cobertura cai.
