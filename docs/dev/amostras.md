# Amostras de teste

O pipeline ainda não tem um vídeo real com licença clara. Até isso existir, os
testes usam um clipe sintético de 48 segundos, gerado na máquina de quem roda
o teste e guardado só em cache local.

## Por que a amostra é sintética

Um padrão `testsrc2` mais fala sintetizada em pt-BR resolve três coisas ao
mesmo tempo:

- não traz imagem, voz nem música de terceiros, então não há dúvida de licença no git;
- não usa rede, modelo baixado nem API paga;
- com as mesmas versões de ffmpeg e espeak-ng, o arquivo sai com o mesmo SHA-256.

A amostra sintética serve para testar transcrição, queima de legenda ASS e uma
medição de VMAF. Ela não substitui fala humana gravada. Quando houver um clipe
real com licença compatível, ele entra como complemento. O clipe sintético
continua sendo o padrão do CI, porque é reproduzível e rápido de gerar.

## O que o clipe contém

O contrato está em `SampleSpec`, em `tests/assets/make_sample.py`.

| Parâmetro | Valor |
| --- | --- |
| Duração | 48 s (dentro da faixa de 30 a 60 s) |
| Vídeo | `testsrc2`, 320×240, 25 fps, H.264 via libx264 |
| Codificação | CRF 32, preset `ultrafast`, uma thread, sem B-frames |
| Áudio | espeak-ng, voz `pt-br+m3`, velocidade 160, PCM 16-bit, 22050 Hz, mono |
| Texto | `tests/assets/narracao_ptbr_v1.txt`, versão 1 |
| Contêiner | Matroska (`.mkv`) |

320×240 é o tamanho padrão do `testsrc2`. É pequeno de propósito: o teste de
integração gera o clipe do zero e precisa terminar rápido. Não serve como
referência de qualidade visual.

A narração desta versão do espeak-ng dura cerca de 42 s. O gerador completa com
silêncio até 48 s. Se uma versão futura da voz passar de 48 s, o áudio é
cortado e o gerador emite um aviso. A duração do arquivo continua 48 s.

## Como gerar

Pacotes de sistema, não são dependências Python:

- `ffmpeg` e `ffprobe`, compilados com libx264;
- `espeak-ng`, com os dados de voz pt-BR que já vêm em `espeak-ng-data`.

Na raiz do repositório:

```bash
python tests/assets/make_sample.py
python tests/assets/make_sample.py --print-hash
python tests/assets/make_sample.py --force --print-hash
python tests/assets/make_sample.py --check
pytest tests/test_sample_spec.py tests/test_sample_clip.py
```

O arquivo cai em `tests/assets/cache/`. O `.gitignore` dessa pasta deixa o
binário e o manifesto de fora do git. Dois `--force --print-hash` seguidos, na
mesma instalação, imprimem o mesmo hash.

`--print-spec` mostra os parâmetros em JSON e não precisa das ferramentas.
`--check` lê o clipe com ffprobe e falha se a duração, a resolução ou a faixa
de áudio não baterem com o contrato.

Os testes de unidade cobrem os parâmetros, o texto versionado e os argumentos
bitexact. O teste de integração gera o clipe duas vezes, compara o SHA-256 e
confere o ffprobe. Se `ffmpeg`, `ffprobe` ou `espeak-ng` não estiverem no
`PATH`, só esse teste de integração é pulado, com um aviso. O restante roda.

## Determinismo

O gerador fixa o que mudaria o arquivo entre uma execução e outra:

- o texto é UTF-8, fim de linha LF, sem BOM, com versão no cabeçalho;
- o espeak-ng recebe voz e velocidade fixas e grava WAV, sem tocar dispositivo de áudio;
- o vídeo é o `testsrc2` do ffmpeg, não um arquivo externo;
- o x264 roda com `threads=1` e GOP fixo;
- `-flags +bitexact`, `-fflags +bitexact` e `-map_metadata -1` tiram data de criação e versão variável do contêiner;
- o processo filho usa `SOURCE_DATE_EPOCH=0` e `TZ=UTC`, e ignora `ESPEAK_DATA_PATH` e variáveis `FFMPEG_*` do shell;
- o áudio do arquivo final é PCM, não AAC. AAC não é estável bit a bit entre builds.

O manifesto ao lado do clipe (`*.manifest.json`) guarda o SHA-256 do texto, o
hash da receita de comandos e a linha de versão do ffmpeg e do espeak-ng. Se
qualquer um desses mudar, o cache é refeito.

Não há um SHA-256 de referência commitado. A versão do libx264 e o conjunto de instruções da
CPU podem mudar os bytes mesmo com a mesma receita. O que o teste garante é a
repetição na mesma instalação: gerar duas vezes produz o mesmo SHA-256.

Mudou o texto falado? Suba `version` no arquivo, troque o nome para
`narracao_ptbr_v2.txt`, aponte `TEXT_PATH` e `SampleSpec.text_version` para a
nova versão e atualize o hash pinado no teste de unidade. Não edite a v1 no
lugar.

## Licenças

O detalhe está em [`tests/assets/LICENSES.md`](../../tests/assets/LICENSES.md).

- O texto é original e segue a MIT do repositório.
- eSpeak NG e os dados da voz pt-BR são GPL-3.0-or-later. Não são copiados para o git.
- O binário do ffmpeg com libx264 é GPL-2.0-or-later. Também não é vendorizado.

Nada disso relicencia o código do Megila. São programas externos chamados na
hora do teste.

## Como a amostra real entra depois

A amostra sintética permanece. Uma amostra real só entra quando existir um
arquivo que cumpra tudo isto:

1. Licença que possa conviver com um repositório MIT: domínio público, CC0 ou MIT. Outra licença só com registro em `tests/assets/LICENSES.md` e acordo de quem mantém o projeto. Vídeo de origem desconhecida não entra.
2. Se for servir à transcrição, fala em pt-BR, sem música de terceiros e sem pessoa identificável sem autorização.
3. Duração curta, de preferência também entre 30 e 60 s, com resolução conhecida.
4. O binário não é commitado se for grande. O caminho previsto é uma ficha com URL estável e SHA-256 pinado (o vídeo baixa para o cache), ou Git LFS se o projeto adotar isso mais tarde.
5. Esta página ganha o nome do arquivo, a licença e o comando de ffprobe que confere duração, resolução e áudio.

Nome sugerido para a ficha, quando chegar a hora:
`tests/assets/reais/amostra_real_v1.txt` (URL, licença, hash). O vídeo em si
fica no cache. Essa ficha não faz parte desta tarefa.
