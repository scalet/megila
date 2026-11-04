# Como contribuir

O Megila é um pipeline genérico de vídeo em Python, publicado sob a licença
MIT. Este guia descreve o ambiente, os testes, o estilo, os commits e o que
um pull request precisa trazer.

Quem participa segue o [Código de Conduta](CODE_OF_CONDUCT.md).

## Segurança

Uma vulnerabilidade segue o relato privado da
[política de segurança](SECURITY.md). O texto do problema fica fora de
issue, pull request, discussão e commit público.

## Ambiente

O passo a passo está em
[Ambiente de desenvolvimento](docs/dev/ambiente.md). É preciso Python 3.12
ou superior, `pip` e Git. Na raiz do repositório:

```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
pre-commit install
```

`pre-commit install` vale uma vez por clone. Os comandos seguintes usam
esse ambiente ativo, na raiz do repositório.

## Testes e estilo

```bash
megila --version
python -m megila --version
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m mypy
pre-commit run --all-files
```

`megila --version` encerra com código 0 e escreve `megila 0.1.0`.

`python -m pytest` é a suíte. Comportamento novo ou corrigido chega com
teste. O clipe sintético está em [Amostras de teste](docs/dev/amostras.md).
O teste de integração que gera o clipe roda quando ffmpeg e espeak-ng
estão no `PATH`. Sem essas ferramentas, o pytest ignora esse teste e
emite um aviso.

O ruff faz o lint e a formatação. A configuração está no `pyproject.toml`.
O mypy roda em modo estrito (`strict = true`) sobre `src` e `tests`.
`pre-commit run --all-files` repete o ruff e o mypy e aplica as checagens
de higiene (espaço no fim da linha, YAML, TOML, chaves privadas).

## Markdown

Com Node.js instalado, na raiz do repositório:

```bash
npx --yes markdownlint-cli2@0.24.0
```

O comando é o mesmo do job `markdownlint` em
[`.github/workflows/markdown.yml`](.github/workflows/markdown.yml). O job
`link check` desse workflow roda o lychee na versão fixada lá, com
[`lychee.toml`](lychee.toml).

A conferência específica das ADRs está no
[índice](docs/adr/index.md).

## Commits

As mensagens de commit seguem
[Conventional Commits 1.0.0](https://www.conventionalcommits.org/pt-br/v1.0.0/),
em inglês:

```text
tipo(escopo): descrição
```

O escopo é opcional. A descrição usa o imperativo, em minúscula, como nos
exemplos abaixo. O corpo, quando existe, explica o motivo. Uma quebra de
compatibilidade leva o rodapé `BREAKING CHANGE:`.

| Tipo | Uso |
| --- | --- |
| `feat` | Comportamento novo |
| `fix` | Correção |
| `docs` | Documentação |
| `test` | Testes |
| `refactor` | Mudança interna, com o mesmo comportamento |
| `perf` | Desempenho |
| `build` | Empacotamento |
| `ci` | Integração contínua |
| `chore` | Manutenção do repositório |

Exemplos:

```text
feat: add the subtitle burn stage
fix(queue): renew the sqlite lease before it expires
docs: describe how to add an ADR
```

O título do pull request usa o mesmo formato, em inglês. A branch parte de
`main` atualizada. Quem contribui de fora usa um fork.

## Pull request

O GitHub preenche o corpo com
[`.github/pull_request_template.md`](.github/pull_request_template.md).
O checklist pede testes, documentação, changelog e licenças.

- A documentação que a mudança toca é atualizada no mesmo pull request.
  Código novo ou comportamento diferente ganha a página ou a seção
  correspondente.
- [`CHANGELOG.md`](CHANGELOG.md) ganha uma entrada em `## [Unreleased]`, em
  português, na categoria que descreve a mudança (`Added`, `Changed`,
  `Deprecated`, `Removed`, `Fixed` ou `Security`). O formato é
  [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/). O link do
  rodapé permanece.
- `README.md` e `README.en.md`, na raiz, são atualizados juntos quando a
  mudança os alcança. Os dois dizem o mesmo: um em português e outro em
  inglês.
- A licença segue a seção abaixo.

## Licenças

O arquivo [`LICENSE`](LICENSE) é MIT, copyright Renan Scalet. A política
está na [ADR 0002](docs/adr/0002-licenca-mit-sem-codigo-agpl.md).

O repositório permanece MIT. Código sob GPL, AGPL ou SSPL fica de fora,
em qualquer versão. Isso inclui tradução, adaptação, teste, prompt,
esquema, asset, Dockerfile e workflow copiados de um projeto com essas
licenças. Ler o código alheio para reproduzir a estrutura ainda conta
como derivação: a implementação nasce de requisitos escritos no Megila.

O SupoClip ilustra o problema de produto (cortes curtos). O código, os
prompts, os esquemas e os textos daquele repositório ficam de fora.

Dependência Python de runtime entra com uma destas licenças: MIT,
BSD-2-Clause, BSD-3-Clause, Apache-2.0, ISC, PSF-2.0, Unlicense e
CC0-1.0. Qualquer outra, inclusive MPL-2.0 e LGPL, só entra se uma ADR
citar o pacote pelo nome.

ffmpeg, ffprobe, yt-dlp e rclone são programas externos, chamados por
subprocesso. O binário fica na máquina de quem o instalou.

## Decisões arquiteturais

Uma decisão durável vira uma ADR no formato
[MADR](https://adr.github.io/madr/) 4.0.0. O texto é em português. As
chaves do front matter ficam em inglês, como no MADR.

1. Copie [`docs/adr/template.md`](docs/adr/template.md) para
   `docs/adr/NNNN-titulo-curto.md`. `NNNN` é o próximo número livre, com
   quatro dígitos. O nome do arquivo usa hífens no lugar de espaços.
2. Preencha `status`, `date` e `decision-makers`. Apague as linhas
   `consulted` e `informed` quando não houver quem ouvir ou quem só
   precise saber.
3. O título da opção escolhida repete, letra por letra, uma das opções
   consideradas.
4. Atualize a tabela em [`docs/adr/index.md`](docs/adr/index.md) no mesmo
   commit.

Valores de `status`:

- `proposed` (proposta), estado inicial do modelo
- `accepted` (aceita)
- `rejected` (rejeitada)
- `deprecated` (obsoleta)
- `superseded by ADR-NNNN` (substituída pela ADR indicada)

## Documentação do site

Páginas em `docs/` seguem
[Como escrever a documentação](docs/dev/docs.md). Com o ambiente ativo,
na raiz do repositório:

```bash
python -m pip install -r docs/requirements.txt
mkdocs build --strict
```

O endereço local de pré-visualização (`mkdocs serve`) está naquela página.
A pasta `site/` é gerada na máquina e fica fora do Git.

## Issues

Ao abrir uma issue, o GitHub mostra dois formulários:

- [relato de erro](.github/ISSUE_TEMPLATE/bug.yml), para algo que não
  funciona como o esperado;
- [pedido de funcionalidade](.github/ISSUE_TEMPLATE/feature.yml), para
  uma capacidade nova.

[`.github/ISSUE_TEMPLATE/config.yml`](.github/ISSUE_TEMPLATE/config.yml)
desliga a abertura de issue em branco e aponta vulnerabilidade para o
relato privado. Os rótulos `bug` e `enhancement` já existem no repositório.
