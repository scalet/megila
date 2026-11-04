# Solução de problemas

Falhas comuns do `megila doctor` e o que a mensagem quer dizer. O
contrato do comando está em [Instalação](instalacao.md).

## O doctor sai com código 1

O código 1 significa um requisito duro ausente. O objeto JSON traz
`ok: false` e `hard_failures` com um destes códigos:

| Código | O que falta |
| --- | --- |
| `ffmpeg_missing` | O executável `ffmpeg` não está no `PATH`, ou a chamada `-version` não devolveu uma linha `ffmpeg version`. |
| `libass_missing` | O ffmpeg rodou, e nem o filtro `ass` nem a flag `--enable-libass` apareceram. |

Avisos (`libvmaf_missing`, `backup_same_disk` e os demais) mantêm o
código 0. A tabela humana marca o aviso na coluna Status.

```bash
megila doctor
megila doctor --json
```

## ffmpeg ausente no PATH

A linha `ffmpeg` fica `missing` e o detalhe é `ffmpeg was not found on
PATH`. Instale um ffmpeg e deixe o executável visível para o mesmo
usuário que roda o Megila. O projeto não baixa nem embute o binário. O
download público está em <https://ffmpeg.org/download.html>.

Confira com:

```bash
command -v ffmpeg
ffmpeg -hide_banner -version
```

## A build do ffmpeg não tem libass

O doctor encontrou o executável e não encontrou o libass. Overlays ASS
da [ADR 0004](adr/0004-qualidade-em-primeiro-lugar.md) dependem dessa
biblioteca, via filtro `ass`.

Procure as duas evidências que o doctor aceita:

```bash
ffmpeg -hide_banner -filters
ffmpeg -hide_banner -buildconf
```

Na lista de filtros, a linha do `ass` cita o libass. Em `-buildconf`,
a flag é `--enable-libass`. O filtro `subtitles` também usa libass em
muitas builds; o doctor exige o filtro `ass` ou a flag de build, para
não tratar um texto solto como biblioteca presente.

Uma build mínima da distribuição pode sair sem essa flag. Troque por
uma build que liste `--enable-libass`. O libass está em
<https://github.com/libass/libass>.

## A build do ffmpeg não tem libvmaf

O aviso é `libvmaf_missing`. O comando termina com código 0 se o libass
estiver presente. O gate de vídeo da
[ADR 0004](adr/0004-qualidade-em-primeiro-lugar.md) continua falhando
fechado enquanto a build não tiver libvmaf: sem nota, o gate não aprova.

O pacote `ffmpeg` de algumas distribuições traz libass e libx264 e omite
o libvmaf. É o caso de conferir a flag `--enable-libvmaf` e o filtro
`libvmaf`. O filtro `vmafmotion` mede movimento e não substitui o libvmaf.

O VMAF está em <https://github.com/Netflix/vmaf>.

## libx264 ausente

O aviso é `libx264_missing` quando o encoder `libx264` não aparece em
`-encoders` e `--enable-libx264` não aparece na configuração da build. O
encode da
[ADR 0004](adr/0004-qualidade-em-primeiro-lugar.md) usa esse codificador.
O doctor avisa e deixa o código 0, pelo mesmo motivo do libvmaf: a
pessoa precisa ler o relatório numa máquina que ainda não tem a build
completa.

## Backup no mesmo disco da origem

O aviso é `backup_same_disk`. O destino passado em `--backup` e o
diretório `--source` (ou o `data_dir`, quando `--source` foi omitido)
resolvem para o mesmo `st_dev`. Uma cópia nesse disco não sobrevive à
falha dele.

```bash
megila doctor --source /dados/videos --backup /dados/copia
```

Esse par gera o aviso quando `/dados/videos` e `/dados/copia` estão no
mesmo sistema de arquivos. O código de saída continua 0 se o ffmpeg e o
libass estiverem em ordem.

Um remote rclone não é disco local:

```bash
megila doctor --source /dados/videos --backup gdrive:megila
```

O status no JSON fica `remote`. A cópia em si continua sendo o rclone
opt-in da [ADR 0006](adr/0006-local-por-padrao.md). O doctor só compara
o disco; não chama o rclone.

Sem `--backup`, o status fica `not_configured`. Não há aviso, porque
ainda não existe destino para comparar. O campo de remote no arquivo de
configuração entra numa fase posterior. Até lá, a comparação é a opção
`--backup`.

Um caminho local cujo dispositivo não deu para ler fica `unknown`. Isso
também não é o aviso de mesmo disco.

## Sensores de temperatura indisponíveis

A linha `temperature` fica `unavailable` com o detalhe `the OS does not
expose sensors`. O `psutil.sensors_temperatures` não existe em todo
sistema (é comum no Linux com a interface de sensores, e costuma falhar
com `NotImplementedError` em outros). O doctor registra a ausência e
segue. Não é requisito duro e não entra em `hard_failures`.

Quando há leituras, a tabela mostra a mais quente e o JSON lista cada
sensor com `current_celsius`.

## Nenhuma GPU aparece

`gpu.kind` fica `none` quando o `nvidia-smi` não está no `PATH`, a
chamada não termina com código 0, ou a saída não tem uma linha de placa,
e o processo não está num Apple Silicon (`Darwin` com `arm64` ou
`aarch64`).

Isso escolhe `padrao` ou `leve`, conforme RAM e CPU. A máquina padrão do
projeto não tem GPU, como na
[ADR 0006](adr/0006-local-por-padrao.md). A ausência da placa não é
erro do doctor.

Um Apple Silicon de 8 GiB ou menos continua em `leve`: a RAM é o limite
mais apertado, e a GPU segue visível no relatório (`videotoolbox`).

## A máquina de 8 GB recebe o perfil leve

`suggested_profile` `leve` numa máquina com até 8 GiB de RAM, com até
2 núcleos físicos, ou com Intel Core até a 4ª geração (o i5 de 2013),
é o resultado previsto. A referência escrita na mensagem é um MacBook
com i5 de 2013 e 8 GB de RAM.

O nome descreve folga. A transcrição continua `large-v3` em `int8` e o
encode continua libx264 preset `slow` CRF 19. Um perfil de conteúdo em
[Perfis](perfis.md) é outra tabela: prompts, glossário e provedor.

## Como ler a saída JSON

A saída de `--json` é um único objeto. `ok` acompanha o código de saída:
`true` com código 0, `false` com código 1.

```bash
megila doctor --json --source /dados/videos
```

Campos úteis numa leitura rápida: `hard_failures`, `warnings`,
`ffmpeg.libass`, `ffmpeg.libvmaf`, `suggested_profile`,
`memory.total_bytes`, `disk.free_bytes`, `gpu.kind` e `backup.status`.
O texto humano correspondente sai sem `--json`, com a linha
`suggested profile:`.
