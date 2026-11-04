# Megila

[Português](README.md) | English

Megila is a generic video pipeline, written in Python by
[Renan Scalet](https://github.com/scalet). The code lives in
[scalet/megila](https://github.com/scalet/megila), under the MIT license.
Processing is local by default, and the project does not require a paid
API.

## What Megila does

You configure two prompts: one for the video and one for the summary.
The input is a video file or, if you want, a URL. A URL is downloaded
with yt-dlp. A local file does not go through that download.

This is the pipeline design. In phase 0, the code does not run these
steps yet.

1. It transcribes the speech in the video.
2. It adds overlays driven by the video prompt. There is no fixed
   caption template.
3. It optionally compresses the video and improves the audio, when the
   job asks for that treatment. Without that request, the program does
   not re-encode out of habit. The encode profile already decided is in
   [ADR 0004](docs/adr/0004-qualidade-em-primeiro-lugar.md).
4. It writes a summary that follows the summary prompt exactly. The
   program does not add a title, a table of contents, topics, or a
   footer. The approved file exists only when the text fulfills the
   prompt.
5. It produces an output directory with the files for that job.

The directory is the delivery. The design includes, among other files,
`transcript.json`, `overlays.ass` when there is an overlay, the video,
`summary.txt` only when the summary passes, `qa.json`, and
`manifest.json`.

Short clips, cut from a long video, come in a later phase and have no
design yet. The idea may recall SupoClip. The code does not come from
there. See the License section.

## Name origin

The name comes from Jeremiah 36:2 ("Take a scroll of a book and write
on it..."): a scroll where what must remain is written down. A video
comes in, passes through explicit stages, and leaves as a result that
can be repeated.

## Principles

### Quality over speed

The output is the product. The default profile favors the quality of
the transcription, the video, and the summary. If the result falls
short of the bar, the job does not proceed as a success. There is no
fast preset on the default path. On a machine without a GPU this takes
time. That wait is the decision. The detail is in
[ADR 0004](docs/adr/0004-qualidade-em-primeiro-lugar.md).

### Local by default and zero cost

The job runs on the computer where Megila is installed. There is no
project cloud account, no telemetry, and no required paid API. Backup
with rclone and a remote worker, including a Colab on your own account,
exist only if you turn them on. Any spend is yours. The project stays
at zero cost. The detail is in
[ADR 0006](docs/adr/0006-local-por-padrao.md).

### Pluggable AI

The text model that plans overlays and writes the summary is pluggable.
The default provider is local: no key and no external call. An external
provider is opt-in, with your own key in the operating system keyring,
not in the repository, the log, or the job directory. Transcription
does not go through that port. It stays local. The detail is in
[ADR 0005](docs/adr/0005-ia-plugavel-e-keyring.md).

### Resilience

A job can run for hours. The queue is a local SQLite database with WAL:
temporary ownership of the job, a heartbeat, and a checkpoint per
chunk. A crash resumes from the last confirmed chunk, instead of
starting over. A job that fails too many times stays visible, with the
request intact, until someone asks to try again. The detail is in
[ADR 0003](docs/adr/0003-fila-sqlite-wal.md).

## Current status

Phase 0, pre-alpha. The package classifier is
`Development Status :: 2 - Pre-Alpha`. Version `0.1.0` identifies the
package, not a usable release. Megila is not usable for processing
video yet.

What is already in the tree:

- The package in `src/megila/` and the Typer CLI, which answers
  `megila --version` and `megila doctor`.
- The development tools: hatchling, ruff, strict mypy, pytest, and
  pre-commit.
- The MkDocs site, ADRs 0001 through 0006, and the synthetic pt-BR test
  clip.
- The code of conduct, the security policy, and the changelog.

The CLI reports the version and, with `megila doctor`, checks ffmpeg,
the machine, and disk. There are no pipeline subcommands yet. The inner
packages mark each component's boundary. This tree cannot transcribe,
overlay, compress, summarize, or cut clips.

## Development install

Python 3.12 or newer, `pip`, and Git. ffmpeg, speech models, and a
local AI runtime arrive in the phases that use them. For this skeleton,
the interpreter is enough.

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Check the CLI:

```bash
megila --version
python -m megila --version
```

Both commands exit with code 0 and print `megila 0.1.0`. `megila doctor`
checks ffmpeg and the machine; the guide is
[Install](docs/instalacao.md). The full environment guide, with pytest,
ruff, mypy, and pre-commit, is in
[Development environment](docs/dev/ambiente.md).

## Documentation

The site is built with MkDocs Material. The public address, once GitHub
Pages uses GitHub Actions as the source, is
`https://scalet.github.io/megila/`. Until that address answers, the
pages are in the repository:

- [Home](docs/index.md)
- [Install](docs/instalacao.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Development environment](docs/dev/ambiente.md)
- [Test samples](docs/dev/amostras.md)
- [How to write the docs](docs/dev/docs.md)
- [Architectural decisions](docs/adr/index.md)

The ADRs are written in Portuguese, in MADR form:

- [0001 — Python, not Rust](docs/adr/0001-python-nao-rust.md)
- [0002 — MIT license and no AGPL code](docs/adr/0002-licenca-mit-sem-codigo-agpl.md)
- [0003 — A SQLite queue with WAL](docs/adr/0003-fila-sqlite-wal.md)
- [0004 — Quality before speed](docs/adr/0004-qualidade-em-primeiro-lugar.md)
- [0005 — Pluggable AI, local by default, secret in the keyring](docs/adr/0005-ia-plugavel-e-keyring.md)
- [0006 — Local by default](docs/adr/0006-local-por-padrao.md)

Also in the repository, in Portuguese:
[code of conduct](CODE_OF_CONDUCT.md),
[security policy](SECURITY.md), and
[changelog](CHANGELOG.md).

## License

Megila is free software under the [MIT license](LICENSE).
Copyright (c) 2026 Renan Scalet.

[SupoClip](https://github.com/FujiwaraChoki/supoclip) is published under
the [GNU AGPL-3.0](https://www.gnu.org/licenses/agpl-3.0.html). It only
inspires the idea of short clips from a long video. No code, prompt,
schema, test, or text from that repository is copied. Reading that code
in order to reproduce its structure is out of bounds too: the
implementation comes from the requirements written here. The full policy
is in [ADR 0002](docs/adr/0002-licenca-mit-sem-codigo-agpl.md).
