---
status: accepted
date: 2026-11-04
decision-makers: Renan Scalet
---

# ADR 0001: Python, e não Rust

## Contexto e problema

O Megila orquestra um pipeline de vídeo. Quem usa configura dois
prompts, um para ajustes e overlays e outro para o resumo, entrega um
arquivo ou uma URL e recebe um diretório de saída. O tempo do job está
na transcrição e no encode. Esses trechos já são código nativo: o
faster-whisper roda sobre o CTranslate2, em C++, e o ffmpeg entrega o
vídeo ao libx264, em C. A máquina alvo não tem GPU, o projeto não tem
orçamento e o código tem um mantenedor.

A pergunta é qual linguagem implementa a orquestração.

## Motivadores da decisão

- O caminho que consome CPU já está em C/C++. Trocar a linguagem do
  programa não acelera o Whisper nem o x264.
- yt-dlp, faster-whisper, o keyring do sistema e um worker opcional em
  Colab já vivem no ecossistema Python.
- A qualidade da saída e a retomada depois de uma queda pesam mais do
  que o tempo gasto coordenando passos.
- Uma pessoa precisa conseguir evoluir o pipeline inteiro.

## Opções consideradas

- Python 3 na orquestração
- Rust no programa inteiro
- Go no programa inteiro
- Núcleo em Rust e borda em Python

## Decisão

Opção escolhida: "Python 3 na orquestração", porque o Rust ganharia
pouco onde o tempo é gasto e afastaria o ecossistema de que o pipeline
depende.

A linguagem do repositório, dos testes, dos exemplos e de um worker
opcional em Colab é Python 3, na implementação CPython. A versão mínima
fica no `pyproject.toml`, fora desta ADR, desde que continue sendo
CPython 3.

ffmpeg, ffprobe, yt-dlp e rclone são executáveis externos. O processo
Python os chama com lista de argumentos, sem shell. A inferência do
faster-whisper entra por uma fronteira Python e roda no código nativo
do CTranslate2, que solta o GIL durante o cálculo.

Anotações de tipo cobrem a fronteira de cada passo. A ferramenta que
confere esses tipos fica com o empacotamento do projeto.

### Consequências

- Bom, porque a transcrição e o encode continuam nos binários que já
  definem a qualidade, como na [ADR 0004](0004-qualidade-em-primeiro-lugar.md).
- Bom, porque yt-dlp, a biblioteca `keyring` e um notebook de Colab
  encaixam sem FFI.
- Bom, porque um mantenedor percorre o fluxo num único ecossistema.
- Ruim, porque Python sem fronteira vira script frágil. Cada passo
  precisa de contrato tipado, e a chamada de processo externo não pode
  passar por shell.
- Ruim, porque o GIL existe. Ele não segura o job: o CTranslate2 solta
  o GIL na inferência e o ffmpeg roda noutro processo. Um job já satura
  a máquina modesta dentro dessas bibliotecas. Na máquina padrão, a
  fila da [ADR 0003](0003-fila-sqlite-wal.md) mantém um job pesado por
  vez.
- Neutro, porque o arquivo de pacote, a ferramenta de tipos e o
  comando de entrada ficam fora desta ADR. Ela só fixa a linguagem.

### Confirmação

- O código de orquestração importa em Python. O repositório não ganha
  crate Rust nem módulo Go.
- Um teste de arquitetura, quando o pacote existir, falha se aparecer
  `Cargo.toml` ou `go.mod` na raiz.
- As chamadas a ffmpeg, ffprobe, yt-dlp e rclone usam lista de
  argumentos. Um teste recusa `shell=True` nesses pontos.
- A transcrição entra pelo faster-whisper, sem reimplementar o modelo
  em Python puro nem em Rust.

## Prós e contras das opções

### Python 3 na orquestração

CPython coordena os passos. A inferência e o encode continuam nativos.

- Bom, porque reescrever a orquestração não encurta o large-v3 nem o
  preset `slow` do x264. Esses dois já são C/C++.
- Bom, porque o faster-whisper, o yt-dlp e a biblioteca `keyring` são
  a forma direta de cumprir as ADR
  [0004](0004-qualidade-em-primeiro-lugar.md),
  [0005](0005-ia-plugavel-e-keyring.md) e
  [0006](0006-local-por-padrao.md).
- Bom, porque o worker opcional de Colab é um runtime Python. A mesma
  linguagem serve na máquina local e nesse worker.
- Ruim, porque disciplina de tipos, de subprocesso e de teste fica por
  conta do projeto. A linguagem não impõe isso sozinha.
- Neutro, porque o custo de subir o interpretador é irrelevante ao
  lado de uma transcrição e de um encode em preset `slow`.

### Rust no programa inteiro

O programa, a fila e a chamada das ferramentas seriam um binário Rust.

- Bom, porque o compilador segura memória e concorrência na
  orquestração, e o binário sobe rápido.
- Ruim, porque o tempo do job continua no CTranslate2 e no libx264. O
  Rust não substitui esses núcleos.
- Ruim, porque o yt-dlp é Python. Embutir um interpretador, ou
  reescrever o download, é custo sem ganho de qualidade.
- Ruim, porque o keyring e o Colab deixam de ser uma biblioteca e um
  notebook e passam a ser integração à parte.
- Ruim, porque um mantenedor passa a cuidar de uma segunda linguagem
  cujo ganho não aparece na saída de vídeo.

### Go no programa inteiro

A orquestração seria um binário Go, com ffmpeg em subprocesso.

- Bom, porque o binário é simples de copiar e o runtime tem concorrência
  pronta.
- Ruim, porque o caminho quente também não muda: Whisper e x264 seguem
  nativos, fora do Go.
- Ruim, porque o faster-whisper não tem uma porta Go equivalente e
  madura. Chamar Python por baixo, ou usar cgo contra o CTranslate2,
  recria a fronteira que o Go deveria evitar.
- Ruim, porque yt-dlp, keyring e Colab continuam do lado de fora.

### Núcleo em Rust e borda em Python

Um biblioteca Rust faria a fila, os checkpoints ou o empacotamento do
ASS, e o Python manteria Whisper, yt-dlp e keyring.

- Bom, porque a borda continua no ecossistema que já resolve o
  pipeline.
- Ruim, porque o núcleo proposto não é o caminho quente. A fila SQLite
  e o compilador de ASS são trabalho pequeno ao lado do encode.
- Ruim, porque o repositório passa a ter duas linguagens, FFI e um
  passo de build a mais, antes de existir um gargalo medido em Python.
- Neutro, porque um trecho que um perfil mostre quente, e que não seja
  o CTranslate2 nem o libx264, pode justificar Rust no futuro. Isso
  pede outra ADR, com o perfil anexo.

## Mais informações

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) publica o
  modelo que a [ADR 0004](0004-qualidade-em-primeiro-lugar.md) torna
  padrão. A inferência é CTranslate2.
- [CTranslate2](https://github.com/OpenNMT/CTranslate2) implementa os
  kernels, inclusive `int8` em CPU, e solta o GIL.
- [ffmpeg](https://ffmpeg.org/) é o processo externo de encode, de
  overlay ASS e de VMAF.
- Vale reabrir esta ADR se um perfil mostrar tempo relevante dentro do
  Python, fora do modelo e do ffmpeg. Até lá, a orquestração permanece
  Python.
