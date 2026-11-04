# Megila

Português | [English](README.en.md)

Megila é um pipeline genérico de vídeo, escrito em Python por
[Renan Scalet](https://github.com/scalet). O código está em
[scalet/megila](https://github.com/scalet/megila), sob a licença MIT.
O processamento é local por padrão e o projeto não exige API paga.

## O que o Megila faz

Quem usa configura dois prompts: um de vídeo e um de resumo. A entrada é
um arquivo de vídeo ou, se a pessoa quiser, uma URL. A URL é baixada com
o yt-dlp. Um arquivo local não passa por esse download.

O desenho do pipeline é este. Na fase 0, o código ainda não executa
esses passos.

1. Transcreve a fala do vídeo.
2. Acrescenta overlays guiados pelo prompt de vídeo. Não há um molde
   fixo de legendas.
3. Opcionalmente comprime o vídeo e melhora o áudio, quando o job pede
   esse tratamento. Sem pedido, o programa não reencoda por hábito. O
   perfil concreto do encode que já está decidido fica na
   [ADR 0004](docs/adr/0004-qualidade-em-primeiro-lugar.md).
4. Escreve um resumo que segue o prompt de resumo à letra. O programa
   não acrescenta título, sumário, tópicos nem rodapé. O arquivo
   aprovado só existe quando o texto cumpre o prompt.
5. Entrega um diretório de saída com os arquivos daquele job.

O diretório é a entrega. O desenho prevê, entre outros,
`transcript.json`, `overlays.ass` quando há overlay, o vídeo,
`summary.txt` só quando o resumo passa, `qa.json` e `manifest.json`.

Cortes curtos, a partir de um vídeo longo, entram numa fase posterior e
ainda não têm desenho. A ideia pode lembrar o SupoClip. O código não vem
de lá. Veja a seção Licença.

## Origem do nome

O nome vem de Jeremias 36:2 («Toma um rolo de livro e escreve nele...»):
um rolo em que se escreve o que precisa permanecer. Um vídeo entra,
atravessa etapas explícitas e sai como um resultado que dá para repetir.

## Princípios

### Qualidade antes da velocidade

A saída é o produto. O perfil padrão privilegia a qualidade da
transcrição, do vídeo e do resumo. Se o resultado fica abaixo do
critério, o job não segue como sucesso. Não há preset rápido no caminho
padrão. Numa máquina sem GPU isso demora. Essa demora é a decisão. O
detalhe está na
[ADR 0004](docs/adr/0004-qualidade-em-primeiro-lugar.md).

### Local por padrão e custo zero

O job roda no computador em que o Megila está instalado. Não há conta do
projeto na nuvem, nem telemetria, nem API paga obrigatória. Backup com
rclone e um worker remoto, inclusive um Colab da conta de quem usa, só
existem se a pessoa os ligar. O gasto, quando existe, é dela. O projeto
permanece com custo zero. O detalhe está na
[ADR 0006](docs/adr/0006-local-por-padrao.md).

### IA plugável

O modelo de texto que planeja os overlays e escreve o resumo é plugável.
O provedor padrão é local: sem chave e sem chamada externa. Um provedor
externo é opt-in, com a chave da própria pessoa no keyring do sistema
operacional, não no repositório, no log nem no diretório do job. A
transcrição não passa por essa porta. Continua local. O detalhe está na
[ADR 0005](docs/adr/0005-ia-plugavel-e-keyring.md).

### Resiliência

Um job pode durar horas. A fila fica num SQLite local com WAL: posse
temporária do job, sinal de vida e checkpoint por pedaço. Uma queda
retoma do último pedaço confirmado, em vez de recomeçar do zero. Quem
falha vezes demais permanece visível, com o pedido intacto, até alguém
pedir para tentar de novo. O detalhe está na
[ADR 0003](docs/adr/0003-fila-sqlite-wal.md).

## Estado atual

Fase 0, pré-alfa. O classificador do pacote é
`Development Status :: 2 - Pre-Alpha`. A versão `0.1.0` identifica o
pacote, não um lançamento utilizável. O Megila ainda não está utilizável
para processar vídeo.

O que já está na árvore:

- O pacote em `src/megila/` e a CLI Typer, que responde a
  `megila --version`.
- As ferramentas de desenvolvimento: hatchling, ruff, mypy estrito,
  pytest e pre-commit.
- O site MkDocs, as ADRs 0001 a 0006 e o clipe sintético de teste em
  pt-BR.
- O Código de Conduta, a política de segurança e o changelog.

A CLI hoje informa a versão. Ainda não há subcomandos de pipeline. Os
pacotes internos marcam a fronteira de cada componente. Não dá para
transcrever, sobrepor, comprimir, resumir nem gerar cortes com esta
árvore.

## Instalação para desenvolvimento

Python 3.12 ou superior, `pip` e Git. ffmpeg, modelos de fala e um
runtime de IA local entram nas fases que os utilizam. Para este
esqueleto, o interpretador basta.

Na raiz do repositório:

```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Conferir a CLI:

```bash
megila --version
python -m megila --version
```

Os dois comandos encerram com código 0 e escrevem `megila 0.1.0`. O
guia completo, com pytest, ruff, mypy e pre-commit, está em
[Ambiente de desenvolvimento](docs/dev/ambiente.md).

## Documentação

O site é gerado com MkDocs Material. O endereço público, quando o
GitHub Pages estiver ligado à origem GitHub Actions, é
`https://scalet.github.io/megila/`. Enquanto esse endereço não
responde, as páginas estão no repositório:

- [Início](docs/index.md)
- [Ambiente de desenvolvimento](docs/dev/ambiente.md)
- [Amostras de teste](docs/dev/amostras.md)
- [Como escrever a documentação](docs/dev/docs.md)
- [Decisões arquiteturais](docs/adr/index.md)

As ADRs estão em português, no formato MADR:

- [0001 — Python, e não Rust](docs/adr/0001-python-nao-rust.md)
- [0002 — Licença MIT e nenhum código AGPL](docs/adr/0002-licenca-mit-sem-codigo-agpl.md)
- [0003 — Fila própria em SQLite com WAL](docs/adr/0003-fila-sqlite-wal.md)
- [0004 — Qualidade antes da velocidade](docs/adr/0004-qualidade-em-primeiro-lugar.md)
- [0005 — IA plugável, local por padrão, segredo no keyring](docs/adr/0005-ia-plugavel-e-keyring.md)
- [0006 — Local por padrão](docs/adr/0006-local-por-padrao.md)

Também no repositório, em português:
[Código de Conduta](CODE_OF_CONDUCT.md),
[política de segurança](SECURITY.md) e
[changelog](CHANGELOG.md).

## Licença

O Megila é software livre sob a [licença MIT](LICENSE).
Copyright (c) 2026 Renan Scalet.

O [SupoClip](https://github.com/FujiwaraChoki/supoclip) é publicado sob
a [GNU AGPL-3.0](https://www.gnu.org/licenses/agpl-3.0.html). Ele só
inspira a ideia de cortes curtos a partir de um vídeo longo. Nenhum
código, prompt, esquema, teste ou texto daquele repositório é copiado.
Ler o código alheio para reproduzir a estrutura também fica de fora: a
implementação nasce dos requisitos escritos aqui. A política completa
está na [ADR 0002](docs/adr/0002-licenca-mit-sem-codigo-agpl.md).
