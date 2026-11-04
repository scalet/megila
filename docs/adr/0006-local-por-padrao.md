---
status: accepted
date: 2026-11-04
decision-makers: Renan Scalet
---

# ADR 0006: Local por padrão

## Contexto e problema

O vídeo, a transcrição e os dois prompts podem ser material pessoal. A
máquina em que o Megila roda é modesta e não tem GPU. O projeto não
paga nuvem. Ainda assim, quem usa pode querer uma cópia do diretório
de saída no Google Drive, ou uma mão de GPU num Colab ou noutra
máquina, quando a CPU local tornar o perfil da
[ADR 0004](0004-qualidade-em-primeiro-lugar.md) longo demais.

A pergunta é onde o vídeo é processado e guardado, e o que continua
local quando um extra opcional é ligado.

## Motivadores da decisão

- O caminho padrão tem de funcionar na máquina da pessoa, sem conta e
  sem upload.
- Ligar um extra não pode inverter o padrão para o próximo job.
- O banco da fila não sobrevive em disco de rede, como na
  [ADR 0003](0003-fila-sqlite-wal.md). Backup não pode ser "montar o
  Drive e apontar o SQLite para lá".
- Um worker remoto vê o conteúdo do passo que recebe. Isso só pode
  acontecer por opção explícita.
- Custo do projeto permanece zero. Colab, Drive e API saem da conta de
  quem usa, quando essa pessoa os liga.

## Opções consideradas

- Local por padrão, com backup e worker opcionais
- Nuvem como caminho padrão
- Colab como caminho padrão
- Cópia automática para o Google Drive em todo job

## Decisão

Opção escolhida: "Local por padrão, com backup e worker opcionais",
porque o processamento e o arquivo ficam na máquina, e tanto o backup
quanto o worker só existem se quem usa os ligar.

**Processamento.** O job roda no computador em que o Megila está
instalado. A transcrição é o modelo local da
[ADR 0004](0004-qualidade-em-primeiro-lugar.md). O modelo de texto
padrão é o provedor `local` da
[ADR 0005](0005-ia-plugavel-e-keyring.md). Não há telemetria, não há
envio de crash e não há conta "Megila" na nuvem.

**Armazenamento.** A fila SQLite e o diretório de cada job ficam num
diretório de dados em disco local. O padrão desse diretório é local; um
filesystem de rede conhecido é recusado na abertura do banco, pela
[ADR 0003](0003-fila-sqlite-wal.md). O diretório do job contém os
arquivos definidos na [ADR 0004](0004-qualidade-em-primeiro-lugar.md):
`transcript.json`, `overlays.ass` quando há overlay, `video-quality.mp4`
quando há encode, `video.mp4`, `summary.txt` quando o resumo passa no
gate, `qa.json` e `manifest.json`. Esse diretório é a entrega. Sucesso
do job não depende de alguém lá fora ter recebido uma cópia.

**Rede que o padrão ainda faz.** yt-dlp só roda quando a entrada é uma
URL. Não é dependência de quem já tem o arquivo. O download dos pesos
do `large-v3`, e o de um modelo de texto local que a pessoa peça, é
preparação explícita, cacheada no disco. Com os pesos presentes, o job
padrão segue sem rede. Fora isso, o processo padrão não abre conexão.

**Backup.** É opt-in e usa o rclone que a pessoa já autenticou. O
Megila não embute SDK do Google, não lê o token do Drive e não pede
client id. A configuração informa o remote e o prefixo. Drive é um
remote possível, não uma dependência: qualquer remote rclone serve. O
comando é `rclone copy` do diretório do job para
`<remote>:<prefixo>/<id-do-job>`, sem apagar a cópia local. O backup
começa depois que o job já tem estado terminal (`succeeded` ou
`dead`), e a falha do rclone não apaga a saída, não promove um `dead` a
`succeeded` e não derruba um `succeeded` a `dead`. O resultado do
backup fica num `backup.json` ao lado, no disco local, com o nome do
remote, o instante e o sucesso ou o erro. O remote em si não entra no
log com segredo; rclone guarda a credencial no próprio arquivo de
configuração, fora do Megila.

**Worker remoto.** É opt-in. Serve para um Colab da conta de quem usa,
ou para outra máquina que a pessoa controle. Não é o caminho padrão e
não é um serviço hospedado pelo projeto. O processo local continua dono
da fila. O worker não recebe o arquivo SQLite e não o abre pela rede.
Ele recebe as entradas de um passo e devolve artefatos. O processo
local confere o hash e grava o checkpoint, como na
[ADR 0003](0003-fila-sqlite-wal.md).

A API que entrega esses passos escuta em `127.0.0.1` por padrão. Um
alcance maior, túnel SSH inclusive, é configuração explícita de quem
usa. Quando o worker não é local, ele apresenta um token guardado no
keyring, sob a mesma regra de redação da
[ADR 0005](0005-ia-plugavel-e-keyring.md). Ligar o worker remoto envia
a mídia daquele passo para a máquina de destino. A documentação de uso,
no momento em que a opção existir, diz isso na frente da chave de
configuração. Colab, em particular, envia o passo para a infraestrutura
do Google.

GPU continua sendo aceleração opcional do mesmo perfil de qualidade.
Não é requisito e não cria um perfil paralelo.

Chamadas a rclone, yt-dlp, ffmpeg e ffprobe usam lista de argumentos,
sem shell, como na [ADR 0001](0001-python-nao-rust.md).

### Consequências

- Bom, porque um job comum não sai da máquina e não exige conta.
- Bom, porque o sucesso do pipeline é local. Drive fora do ar não
  segura o vídeo já pronto.
- Bom, porque o SQLite não é colocado num mount do rclone, que é o
  cenário em que o arquivo corrompe.
- Ruim, porque CRF 19 em duas passagens enche disco. A pessoa precisa
  de espaço para a origem, para `video-quality.mp4` e para `video.mp4`.
  Sem espaço, o job falha de forma limpa, pela
  [ADR 0003](0003-fila-sqlite-wal.md).
- Ruim, porque um worker remoto ou um provedor de texto externo tira
  conteúdo da máquina. A proteção é a opção vir desligada, não uma
  garantia mágica depois que alguém a liga.
- Ruim, porque Colab gratuito tem cota, fila e corte de sessão da
  própria Google. O lease e o checkpoint existem para esse corte; a
  [ADR 0003](0003-fila-sqlite-wal.md) é o que torna o corte recuperável.
  O Megila não compra cota para evitar isso.
- Neutro, porque os pesos do modelo, na primeira preparação, vêm da
  rede pública em que o faster-whisper os publica. Isso é download
  pedido por quem instala, não telemetria.

### Confirmação

- A configuração padrão liga `provider: local`, não declara remote
  rclone e não declara worker remoto.
- Um teste do bind da API de worker confere `127.0.0.1` quando a
  configuração de alcance não foi alterada.
- Um teste de backup com rclone falso confere que o job já está
  `succeeded` antes da cópia, que a falha do rclone preserva esse
  status e grava `backup.json`, e que o diretório local permanece.
- Um teste de worker confirma que o processo remoto de mentira não
  recebe o caminho do SQLite e que o checkpoint só aparece depois que
  o processo local confere o hash.
- Um teste de rede do caminho padrão, com a mídia já em arquivo e os
  pesos já em cache, não abre conexão. O caso com URL de entrada pode
  chamar o yt-dlp e mais nada.

## Prós e contras das opções

### Local por padrão, com backup e worker opcionais

Processo, fila e diretório de saída na máquina. rclone e worker só com
opção explícita, cada um com regra de falha própria.

- Bom, porque o uso comum coincide com a máquina real do projeto: sem
  GPU, sem fatura, com o vídeo em casa.
- Bom, porque backup e aceleração existem para quem precisa, sem
  redefinir o sucesso do job.
- Ruim, porque a pessoa que esquecer de ligar o backup não tem cópia
  fora da máquina. O padrão prefere isso a enviar vídeo sem pedido.
- Neutro, porque o Google Drive entra só como exemplo de remote
  rclone. Trocar de remote não muda o Megila.

### Nuvem como caminho padrão

O vídeo subiria para um bucket, e a fila viveria num serviço gerenciado.

- Bom, porque trocar de computador não exigiria carregar o diretório
  de dados.
- Ruim, porque cria custo mensal, conta e uma superfície de vazamento
  no caminho que deveria ser o trivial.
- Ruim, porque a máquina modesta passaria a ser um cliente fino de um
  sistema que o projeto teria de operar.
- Ruim, porque contradiz o SQLite local da
  [ADR 0003](0003-fila-sqlite-wal.md): o estado iria para a rede.

### Colab como caminho padrão

Todo job seria preparado para rodar num notebook Colab, pela GPU
gratuita.

- Bom, porque a GPU encurtaria o `large-v3` e o x264 sem uma fatura do
  projeto.
- Ruim, porque o vídeo sairia da máquina em todo job, mesmo no caso
  em que a CPU local daria conta.
- Ruim, porque a cota e o corte de sessão da Google virariam
  dependência do caminho padrão. O programa deixaria de funcionar na
  única máquina que ele promete atender.
- Ruim, porque o projeto passaria a documentar e a testar o notebook
  como se fosse a instalação principal.

### Cópia automática para o Google Drive em todo job

O processamento continuaria local, mas todo diretório de saída seria
enviado ao Drive ao terminar.

- Bom, porque a pessoa ganharia cópia externa sem lembrar de ligar
  nada.
- Ruim, porque o envio deixaria de ser opção. Material pessoal iria
  para a conta Google assim que um job terminasse.
- Ruim, porque uma falha de autenticação do Drive passaria a parecer
  falha do pipeline, ou, pior, o programa teria de ignorá-la em
  silêncio. As duas leituras são ruins. Na opção escolhida a falha
  fica no `backup.json` e o status do job não mente.
- Ruim, porque embutir a conta Google no fluxo padrão puxa SDK, token
  e client id para dentro do Megila, contra a escolha de deixar isso
  com o rclone.

## Mais informações

- O [rclone](https://rclone.org/docs/) é o programa externo de backup.
  A credencial fica na configuração dele.
- O [yt-dlp](https://github.com/yt-dlp/yt-dlp) só entra quando a origem
  é uma URL. A licença dele precisa continuar aceitável pela
  [ADR 0002](0002-licenca-mit-sem-codigo-agpl.md); o projeto é
  Unlicense.
- A [ADR 0003](0003-fila-sqlite-wal.md) é o contrato da fila que este
  worker remoto não abre.
- A [ADR 0004](0004-qualidade-em-primeiro-lugar.md) é o perfil que o
  worker pode acelerar e não pode enfraquecer.
- A [ADR 0005](0005-ia-plugavel-e-keyring.md) é a única porta pela qual
  o texto do prompt sai da máquina, e só com provedor externo ligado.
- Vale reabrir se a máquina padrão deixar de ser um computador local
  sem GPU. Até lá, nuvem, Colab e Drive permanecem opt-in.
