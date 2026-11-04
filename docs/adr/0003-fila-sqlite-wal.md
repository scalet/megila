---
status: accepted
date: 2026-11-04
decision-makers: Renan Scalet
---

# ADR 0003: Fila própria em SQLite com WAL

## Contexto e problema

Um job do Megila dura o tempo de baixar a mídia, transcrever, planejar
overlays, codificar, medir qualidade e escrever o resumo. Isso cabe em
horas numa máquina sem GPU. O processo pode cair no meio. Dois workers,
o local e um remoto opcional, não podem executar o mesmo pedaço ao
mesmo tempo. Não há orçamento para Redis, Postgres ou uma fila
gerenciada, e não há vontade de operar outro serviço só para guardar
estado.

A pergunta é como a fila sobrevive a queda, a retry e a mais de um
worker sem um broker.

## Motivadores da decisão

- O estado do job tem de continuar no disco depois de um kill, de uma
  falta de energia ou de um worker que para de responder.
- Um pedaço de transcrição ou de encode já confirmado não deve ser
  refeito do zero.
- Dois workers não podem gravar o mesmo checkpoint.
- A operação padrão é um processo na máquina local, como na
  [ADR 0006](0006-local-por-padrao.md). Subir Redis só para a fila
  gasta memória que o modelo e o encode precisam.
- Trabalho que falhou vezes demais fica visível, com o pedido intacto,
  até alguém pedir para tentar de novo.

## Opções consideradas

- Fila própria em SQLite com WAL
- Celery com Redis
- Postgres com SKIP LOCKED
- Fila só em memória
- Diretório de arquivos com lock

## Decisão

Opção escolhida: "Fila própria em SQLite com WAL", porque um arquivo
SQLite no disco local dá posse temporária do job, sinal de vida,
fila de falha definitiva e retomada por pedaço, sem outro serviço.

O banco fica num filesystem local, no diretório de dados do Megila. Não
fica em NFS, SMB nem num mount de nuvem. Ao abrir, se o tipo do
filesystem for reconhecível como rede ou como FUSE de nuvem (`nfs`,
`cifs`, `smb`, `fuse.rclone` e equivalentes), o processo recusa subir.
O tipo detectado entra no log de startup. Workers remotos não abrem
esse arquivo: recebem um passo pela API local e devolvem artefatos. Só
o processo dono do banco grava nele. A
[ADR 0006](0006-local-por-padrao.md) detalha esse worker.

O padrão é um worker local, com um job pesado por vez. A máquina não
tem folga para dois `large-v3` nem para dois encodes em preset `slow`
ao mesmo tempo. Um worker remoto, opt-in, pode levar outro job, porque
usa outra CPU.

Na abertura do banco valem estas pragmas:

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = FULL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
```

`WAL` permite ler o status enquanto um worker grava. `synchronous=FULL`
faz o commit já devolvido sobreviver a falta de energia. As transações
ficam curtas: a transcrição e o encode acontecem fora da transação. O
banco guarda o estado, não a mídia.

O esquema normativo é este. Tipos e nomes podem ganhar colunas; não
podem perder a semântica descrita aqui.

```sql
CREATE TABLE job (
  id TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  payload TEXT NOT NULL,
  lease_owner TEXT,
  lease_token TEXT,
  lease_until TEXT,
  heartbeat_at TEXT,
  attempt INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 5,
  last_error TEXT,
  idempotency_key TEXT UNIQUE,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE job_checkpoint (
  job_id TEXT NOT NULL REFERENCES job (id),
  step TEXT NOT NULL,
  chunk_index INTEGER NOT NULL,
  artifact_path TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  PRIMARY KEY (job_id, step, chunk_index)
);
```

`status` é `pending`, `leased`, `succeeded` ou `dead`. Os instantes são
UTC, em texto ISO-8601. `payload` é JSON com caminhos e com os dois prompts.
Não leva segredo de API, como na
[ADR 0005](0005-ia-plugavel-e-keyring.md). A mídia fica em arquivo, não
no JSON.

A chave de idempotência identifica a mesma entrada: identidade da
mídia, os dois prompts e o perfil de encode. Um reenvio devolve o job
já criado e não enfileira outro.

**Lease.** É a posse temporária do job por um worker. O padrão dura
60 segundos e é configurável. O claim roda em `BEGIN IMMEDIATE`. O
worker leva o job `pending` mais antigo, ou o `leased` cujo
`lease_until` já passou. Ganha um `lease_token` novo, um
`lease_owner` e um `lease_until`. Trabalho nenhum começa sem esse
token.

**Tentativas.** Cada execução que termina em erro, ou cada lease que
expira, consome uma tentativa. O padrão de `max_attempts` é 5. A falha
que atinge o máximo leva o job a `dead`. Devolver o job no fim de um
passo bem-sucedido não consome tentativa: o worker grava o checkpoint e
pode seguir no mesmo lease ou voltar o status a `pending`.

**Heartbeat.** A cada 20 segundos, dentro do TTL de 60, o worker renova
`lease_until` e `heartbeat_at` somente se o `lease_token` ainda for o
dele. Zero linhas atualizadas significa que a posse acabou. O worker
para na hora e não grava mais checkpoint. Um `SIGTERM` deixa de renovar;
o lease expira e outro worker retoma do último pedaço confirmado. O
sinal não marca o job como `succeeded`.

**DLQ.** O status `dead` é a dead-letter queue. Não há segundo banco. O
payload, o `last_error` e os checkpoints permanecem. Nada é apagado para
"limpar a fila". Reprocessar é transição explícita de `dead` para
`pending`: zera `attempt`, troca o token e mantém todo checkpoint cujo
arquivo ainda produz o mesmo hash. Não existe retry infinito.

**Checkpoint em pedaços.** Cada passo longo, transcrição e encode em
especial, grava pedaços. A ordem é: escrever o artefato num caminho
temporário, `fsync` do arquivo e do diretório, renomear para o caminho
final, e só então inserir a linha de checkpoint. A inserção só conta se
o `lease_token` ainda for o dono e o lease não tiver expirado. O hash é
SHA-256 do arquivo final.

Na retomada:

- linha e arquivo com o mesmo hash: o pedaço é pulado
- linha sem arquivo, ou hash diferente: a linha é apagada e o pedaço é
  refeito
- arquivo sem linha: o arquivo é ignorado e o pedaço é refeito

Disco cheio falha a transação. O temporário é removido e a tentativa é
consumida. Um mp4 truncado não vira sucesso.

Os números 60 segundos, 20 segundos e 5 tentativas são o padrão do
projeto. Um job pode configurá-los. O valor efetivo fica registrado no
manifesto desse job. O código não espalha outros números mágicos.

### Consequências

- Bom, porque um kill no meio da transcrição retoma do último pedaço
  cujo hash confere, em vez de recomeçar a hora já gasta.
- Bom, porque a DLQ guarda o caso que não se resolve sozinho. O erro
  continua legível.
- Bom, porque não há Redis nem Postgres para instalar na máquina
  modesta.
- Ruim, porque a fila é código nosso. Lease, heartbeat, token e hash
  precisam de teste que mata o processo de propósito. Um broker pronto
  já traria isso.
- Ruim, porque o SQLite tem um escritor por vez. Isso é aceitável: as
  transações são curtas e a máquina não roda dezenas de jobs pesados
  em paralelo.
- Ruim, porque um worker remoto não pode "só abrir o banco" num
  diretório compartilhado. A API local é obrigatória. A
  [ADR 0006](0006-local-por-padrao.md) assume esse desenho.
- Neutro, porque WAL cria os arquivos `-wal` e `-shm` ao lado do
  banco. Backup do estado copia os três de forma consistente, ou usa
  a API de backup do SQLite. Copiar só o arquivo principal durante
  escrita não é backup.

### Confirmação

- Um teste de integração abre o banco e lê `journal_mode` igual a
  `wal` e `synchronous` igual a `2` (`FULL`).
- Um teste adquire o lease, grava um pedaço, mata o worker antes do
  commit e verifica que o pedaço é refeito. Outro teste mata depois do
  commit e verifica que o pedaço é pulado.
- Um teste deixa o lease expirar e verifica que um segundo worker
  retoma, e que o primeiro, ao tentar gravar checkpoint, não altera a
  tabela.
- Um teste leva o job a `dead` na quinta falha, confere que o payload
  permanece e que um sexto retry automático não ocorre. Um replay
  explícito volta a `pending` e reaproveita o pedaço com hash válido.
- Um teste aponta o diretório de dados para um tipo de filesystem
  recusado, quando a plataforma consegue simular o tipo, e espera a
  recusa na abertura.

## Prós e contras das opções

### Fila própria em SQLite com WAL

Um arquivo local, com lease, heartbeat, status `dead` e checkpoint por
pedaço.

- Bom, porque o estado cabe num arquivo, sem serviço extra e sem
  custo.
- Bom, porque WAL deixa a leitura do progresso livre enquanto o worker
  grava, e `synchronous=FULL` trata o commit como durável.
- Bom, porque o contrato de hash torna o pedaço idempotente. Dois
  workers em cima do mesmo job não corrompem o resultado: o token
  decide quem grava.
- Ruim, porque lease, DLQ e retomada são implementação e teste nossos.
- Ruim, porque SQLite em disco de rede corrompe arquivo. A recusa de
  filesystem conhecido reduz esse risco e não cobre todo mount exótico.

### Celery com Redis

Celery executaria os passos, com Redis de broker e de backend.

- Bom, porque retry, worker e um lugar para falha são funções prontas
  da ferramenta.
- Ruim, porque Redis é outro processo, outra porta e outra memória,
  permanente, numa máquina que já fica justa com o large-v3 e o x264.
- Ruim, porque checkpoint de pedaço de arquivo, com hash e fsync, não
  vem pronto. Teríamos a ferramenta e ainda assim o código difícil.
- Ruim, porque a operação deixa de ser "um programa Python" e passa a
  ser dois serviços.

### Postgres com SKIP LOCKED

Um Postgres local guardaria a fila, com `SELECT ... FOR UPDATE SKIP
LOCKED` para o claim.

- Bom, porque o claim concorrente é um padrão conhecido e o banco
  aguenta muitos escritores melhor do que o SQLite.
- Ruim, porque a máquina modesta passaria a rodar um servidor de banco
  para uma fila de um usuário.
- Ruim, porque backup, porta, usuário do banco e migração entram na
  operação do dia a dia sem melhorar o vídeo.
- Neutro, porque, se um dia o Megila tiver muitos workers de verdade
  contra o mesmo estado, esta opção volta a merecer uma ADR. Não é o
  caso do padrão local.

### Fila só em memória

Uma estrutura no processo, perdida quando o processo sai.

- Bom, porque não há esquema nem migração.
- Ruim, porque uma queda no meio do encode perde o job inteiro. Isso
  contraria a resiliência que o pipeline longo exige.
- Ruim, porque um segundo worker noutro processo não enxerga a fila.
- Ruim, porque não há DLQ: o erro desaparece junto com o processo.

### Diretório de arquivos com lock

Cada job seria uma pasta, com um arquivo de lock para a posse.

- Bom, porque o estado fica visível no filesystem e não há SQL.
- Ruim, porque lock de arquivo não expressa TTL, heartbeat e token de
  forma atômica. Dois workers passam pelo lock quando o dono morre sem
  apagá-lo, ou ficam presos quando o lock fica órfão.
- Ruim, porque o commit do checkpoint e o commit do status deixam de
  ser uma transação. É exatamente o furo que o hash está aqui para
  fechar, e o fechamento fica mais frágil.
- Neutro, porque os artefatos de mídia continuam sendo arquivos mesmo
  na opção escolhida. A diferença é onde mora o estado.

## Mais informações

- O modo WAL está documentado em
  [sqlite.org/wal.html](https://www.sqlite.org/wal.html).
- Transações, inclusive `BEGIN IMMEDIATE`, estão em
  [sqlite.org/lang_transaction.html](https://www.sqlite.org/lang_transaction.html).
- A [ADR 0004](0004-qualidade-em-primeiro-lugar.md) define os passos que
  geram pedaço: transcrição, encode de qualidade e queima do overlay.
- A [ADR 0006](0006-local-por-padrao.md) impede o worker remoto de abrir
  este arquivo e descreve o backup, que não substitui o banco.
- Vale reabrir se o padrão deixar de ser um processo local e a disputa
  de escritores no SQLite aparecer em medida, não em hipótese.
