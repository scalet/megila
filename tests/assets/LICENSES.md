# Licenças da amostra sintética

Este arquivo registra a licença do texto, da voz e das ferramentas usadas por
`make_sample.py`. Nada aqui é vendorizado no repositório. O clipe gerado fica
em `cache/` e o `.gitignore` desta pasta impede o commit.

## Texto falado

| Item | Valor |
| --- | --- |
| Arquivo | `narracao_ptbr_v1.txt` |
| Versão | 1 |
| Idioma | pt-BR |
| Origem | Texto original escrito para o projeto Megila. Não é citação de livro, letra, roteiro ou outro material de terceiros. |
| Licença | [MIT](../../LICENSE), a mesma do repositório. Copyright (c) 2026 Renan Scalet. |
| SPDX | `MIT` |

O cabeçalho do arquivo (comentários, `version` e `language`) não é lido em voz.
Só o corpo depois da linha `---` entra no espeak-ng.

## Voz

| Item | Valor |
| --- | --- |
| Ferramenta | [eSpeak NG](https://github.com/espeak-ng/espeak-ng) (`espeak-ng`) |
| Voz | `pt-br+m3` — Portuguese (Brazil), variante masculina 3, dados que acompanham o pacote `espeak-ng-data` |
| Licença do programa e dos dados de voz | GPL-3.0-or-later |
| SPDX | `GPL-3.0-or-later` |

A voz do eSpeak NG não é um modelo baixado à parte e não é copiada para este
repositório. O gerador só chama o executável instalado no sistema. A variante
`+m3` é a voz Klatt do próprio eSpeak NG, não uma voz MBROLA (essas têm
licença própria e não são usadas aqui).

Piper não é usado. O eSpeak NG já traz a voz pt-BR, então não há download de
modelo nem custo de rede.

## Ferramentas de vídeo

| Item | Valor |
| --- | --- |
| Ferramenta | [FFmpeg](https://ffmpeg.org/) (`ffmpeg` e `ffprobe`) |
| Filtro de vídeo | `testsrc2`, padrão sintético gerado pelo FFmpeg. Não há filmagem, foto ou trilha de terceiros. |
| Codificador de vídeo | libx264 (GPL-2.0-or-later) |
| Áudio no clipe | `pcm_s16le` produzido pelo FFmpeg a partir do WAV do eSpeak NG |
| Licença típica do binário | A build do Ubuntu empacotada com `--enable-gpl` e libx264 é GPL-2.0-or-later. Builds do FFmpeg sem GPL são LGPL-2.1-or-later, mas este clipe precisa do libx264. |
| SPDX do binário usado para gerar o clipe | `GPL-2.0-or-later` |

O FFmpeg e o libx264 não são dependências Python nem entram no código do
Megila. São executáveis de sistema, usados só para gerar e conferir a amostra
de teste.

## O que isso significa para o repositório

- O que está versionado aqui (o texto e os scripts) permanece sob a licença MIT do Megila.
- Chamar um programa GPL na linha de comando não relicencia o Megila e não copia esse programa para o git.
- O WAV e o MKV gerados não são commitados. Quem precisar do clipe roda `make_sample.py` de novo.
- Nenhuma amostra com licença desconhecida, CC-BY sem registro, ou voz proprietária deve ser adicionada sem atualizar este arquivo. O critério da amostra real está em `docs/dev/amostras.md`.
