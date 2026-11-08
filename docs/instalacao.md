# Instalação

Requisitos para rodar o Megila nesta fase e o que o comando `megila doctor`
confere na máquina. O guia do ambiente de desenvolvimento está em
[Ambiente de desenvolvimento](dev/ambiente.md). A configuração do diretório
de dados está em [Configuração](configuracao.md).

## Requisitos

### Python

Python 3.12 ou superior, no CPython.

### Dependências Python

O pacote declara estas dependências de runtime. As licenças estão na lista
permissiva da [ADR 0002](adr/0002-licenca-mit-sem-codigo-agpl.md): MIT,
BSD-2-Clause, BSD-3-Clause, Apache-2.0, ISC, PSF-2.0, Unlicense e CC0-1.0.

| Pacote | Licença | Função |
| --- | --- | --- |
| [psutil](https://github.com/giampaolo/psutil) | BSD-3-Clause | CPU, memória, disco livre e `sensors_temperatures` no `megila doctor`. |
| pydantic | MIT | Modelos de configuração e de perfil. |
| pydantic-settings | MIT | Leitura de ambiente e do TOML. |
| Typer | MIT | Linha de comando. |

O teste `tests/test_dependency_licenses.py` confere a licença declarada
desses pacotes e das dependências transitivas que o projeto já lista.
ffmpeg, ffprobe, yt-dlp e rclone ficam fora dessa lista: são programas
externos, chamados por subprocesso, como na
[ADR 0001](adr/0001-python-nao-rust.md) e na
[ADR 0002](adr/0002-licenca-mit-sem-codigo-agpl.md).

### ffmpeg

O binário `ffmpeg` precisa estar no `PATH`. O Megila não o vendoriza e não
liga libass, libvmaf nem libx264 dentro do processo Python.

O `megila doctor` trata três requisitos como duros: o executável tem de
rodar, e a build tem de incluir o libass e o libx264. O encode da
[ADR 0004](adr/0004-qualidade-em-primeiro-lugar.md) usa o libx264, então
sem ele o perfil de qualidade não pode ser entregue. Sem um dos três o
comando termina com código 1.

O gate de vídeo da mesma ADR também precisa de libvmaf. Se faltar, o
doctor avisa e ainda assim termina com código 0 quando o ffmpeg, o
libass e o libx264 estão presentes. O job, quando existir, continua
falhando fechado sem a medida.

O doctor lê três invocações, cada uma com lista de argumentos e sem shell:

```bash
ffmpeg -hide_banner -version
ffmpeg -hide_banner -filters
ffmpeg -hide_banner -encoders
ffmpeg -hide_banner -buildconf
```

O libass conta quando o filtro `ass` aparece em `-filters` ou quando
`--enable-libass` aparece em `-buildconf` (ou na linha `configuration` de
`-version`). O libvmaf conta pelo filtro `libvmaf` ou por
`--enable-libvmaf`. O filtro `vmafmotion` é outra coisa e não substitui o
libvmaf. O libx264 conta pelo encoder `libx264` em `-encoders` ou por
`--enable-libx264`.

O endereço de download do ffmpeg é <https://ffmpeg.org/download.html>. O
libass está em <https://github.com/libass/libass>. O VMAF está em
<https://github.com/Netflix/vmaf>.

### GPU

A GPU é opcional. O perfil de qualidade não muda com ela, como na
[ADR 0004](adr/0004-qualidade-em-primeiro-lugar.md) e na
[ADR 0006](adr/0006-local-por-padrao.md).

O doctor reconhece dois casos:

- CUDA, quando `nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits` termina com código 0 e lista uma placa.
- Apple Silicon com VideoToolbox, quando o sistema é Darwin e a máquina é `arm64` ou `aarch64`.

### Disco

O doctor informa o espaço livre do diretório de origem. O padrão desse
diretório é o `data_dir` da [configuração](configuracao.md). Um backup
local no mesmo disco da origem gera aviso: a cópia some junto com o disco.
A comparação usa o sistema de arquivos (`st_dev`), não o disco físico:
partições, volumes LVM e subvolumes btrfs do mesmo disco passam sem aviso.
Um remote rclone (`nome:prefixo`) é outro destino e não gera esse aviso.

## Instalar para desenvolvimento

Na raiz do repositório, com o ambiente descrito em
[Ambiente de desenvolvimento](dev/ambiente.md):

```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
megila doctor
```

As mensagens do comando estão em inglês, como o restante do código. Esta
página está em português.

## Comando megila doctor

`megila doctor` lê a máquina e encerra. Não inicia job, não grava
configuração e não altera o perfil de qualidade.

| Opção | Efeito |
| --- | --- |
| `--json` | Imprime um único objeto JSON na saída padrão. |
| `--source CAMINHO` | Diretório cujo disco é medido. Sem esta opção, vale o `data_dir` carregado da configuração. |
| `--backup DESTINO` | Destino do backup. Caminho local no mesmo disco de `--source` gera o aviso `backup_same_disk`. Remote rclone (`gdrive:megila`) não gera. |
| `--config ARQUIVO` | TOML de configuração usado só quando `--source` foi omitido. |

Um arquivo de configuração inválido não interrompe a leitura da máquina.
O doctor segue com o diretório de dados padrão e registra o aviso
`config_invalid`. O valor de um segredo continua fora da mensagem, como
na [configuração](configuracao.md).

Sensores de temperatura vêm de `psutil.sensors_temperatures`. Quando o
sistema operacional não expõe essa chamada, a linha fica `unavailable`.
Isso não é falha.

A saída humana é uma tabela em texto alinhado. O Rich não é dependência
do pacote, então o comando não depende dele.

## Perfil de máquina

O nome sugerido descreve a folga da máquina. Os perfis de conteúdo
(`default` e os demais em [Perfis](perfis.md)) continuam escolhendo
prompts, glossário, idioma e provedor. A qualidade do job permanece a da
[ADR 0004](adr/0004-qualidade-em-primeiro-lugar.md): transcrição `large-v3`
em `int8`, encode libx264 preset `slow` CRF 19.

O doctor testa nesta ordem:

| Perfil | Quando |
| --- | --- |
| `leve` | RAM de até 8 GiB, inclusive, ou CPU da classe leve. A referência é um MacBook com i5 de 2013 e 8 GB de RAM. Uma GPU presente não muda este resultado. |
| `forte` | A máquina ficou fora de `leve` e há CUDA ou Apple Silicon com VideoToolbox. |
| `padrao` | RAM acima de 8 GiB, CPU fora da classe leve, sem essa GPU. |

A classe leve de CPU é um chip com até 2 núcleos físicos, ou um Intel
Core do Core 2 até a 4ª geração (Haswell, o i5 de 2013). O número da
geração sai do modelo: `i5-4258U` é geração 4, `i5-1035G1` é geração 10,
`i5-12400` é geração 12. 8 GiB aqui são 8 × 1024³ bytes. Um pente vendido
como 8 GB (potência de dez) fica abaixo desse teto e também cai em `leve`.

## Código de saída

| Código | Quando |
| --- | --- |
| 0 | O ffmpeg roda e a build tem libass e libx264. Avisos podem existir. |
| 1 | O ffmpeg não está no `PATH`, não chega a responder, ou a build não tem libass ou libx264. |

Os códigos de falha no relatório são `ffmpeg_missing`, `libass_missing` e
`libx264_missing`. Avisos comuns: `libvmaf_missing`, `backup_same_disk`,
`config_invalid`, `memory_unreadable`, `disk_unreadable`.

## JSON

`megila doctor --json` escreve só o objeto. Campos que um script pode
ler: `ok`, `suggested_profile` (`leve`, `padrao` ou `forte`),
`hard_failures`, `warnings`, `ffmpeg.libass`, `ffmpeg.libvmaf`,
`cpu`, `memory.total_bytes`, `disk.free_bytes`, `gpu.kind` (`none`,
`cuda` ou `videotoolbox`), `temperatures` e `backup.status`
(`not_configured`, `remote`, `same_disk`, `distinct` ou `unknown`).

```bash
megila doctor --json --source /dados/videos --backup /backup/megila
```

Quando o doctor recusar a máquina ou avisar de disco, o texto de
[Solução de problemas](troubleshooting.md) diz o que conferir.
