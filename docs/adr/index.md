# Decisões arquiteturais

O Megila é um pipeline genérico de vídeo. Quem usa configura dois
prompts (ajustes e overlays; resumo), entrega um arquivo ou, se quiser,
uma URL, e recebe um diretório com os arquivos daquele job. O nome vem
de Jeremias 36:2. O programa é software livre, licença MIT, de Renan
Scalet.

Decisões duráveis ficam neste diretório, no formato
[MADR](https://adr.github.io/madr/) 4.0.0, em português. O campo
`status` do front matter usa o vocabulário do MADR, em inglês.
Nesta tabela, `accepted` aparece como **aceita**.

| ADR | Decisão | Status |
| --- | --- | --- |
| [0001](0001-python-nao-rust.md) | Python, e não Rust | aceita |
| [0002](0002-licenca-mit-sem-codigo-agpl.md) | Licença MIT e nenhum código AGPL | aceita |
| [0003](0003-fila-sqlite-wal.md) | Fila própria em SQLite com WAL | aceita |
| [0004](0004-qualidade-em-primeiro-lugar.md) | Qualidade antes da velocidade | aceita |
| [0005](0005-ia-plugavel-e-keyring.md) | IA plugável, local por padrão, segredo no keyring | aceita |
| [0006](0006-local-por-padrao.md) | Local por padrão | aceita |

Cada ADR traz contexto e problema, opções consideradas, decisão e
consequências. O índice acima lista todas as decisões aceitas.

Cortes curtos, no espírito de produtos como o SupoClip, ainda não têm
desenho. Quando tiverem, entram numa ADR nova. A [0002](0002-licenca-mit-sem-codigo-agpl.md)
já impede copiar código AGPL para chegar lá.

## Modelo

Uma ADR nova começa pelo [modelo](template.md). Copie o arquivo para
`NNNN-titulo-curto.md`, com o próximo número livre, quatro dígitos e
hífens no lugar de espaços. O título da opção escolhida tem de repetir,
letra por letra, uma das opções consideradas. Atualize esta tabela no
mesmo commit.

Valores de `status`:

- `proposed` (proposta), estado inicial do modelo
- `accepted` (aceita)
- `rejected` (rejeitada)
- `deprecated` (obsoleta)
- `superseded by ADR-NNNN` (substituída pela ADR indicada)

As chaves do front matter (`status`, `date`, `decision-makers`,
`consulted`, `informed`) ficam em inglês, como no MADR. O resto do
arquivo é em português.

## Conferência do Markdown

Na raiz do repositório:

```bash
npx --yes markdownlint-cli@0.50.0 \
  --config docs/adr/.markdownlint.yaml "docs/adr/**/*.md"
```

A configuração está em [`.markdownlint.yaml`](.markdownlint.yaml).
O comando deve terminar sem apontar erro nestes arquivos.
