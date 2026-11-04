---
status: accepted
date: 2026-11-04
decision-makers: Renan Scalet
---

# ADR 0004: Qualidade antes da velocidade

## Contexto e problema

O Megila entrega um diretório por job: transcrição, vídeo com overlays
pedidos por um prompt, resumo escrito sob o outro prompt e um
relatório do que foi medido. A máquina padrão não tem GPU. O projeto
não paga API para "subir a qualidade". Velocidade é desejável, e perde
quando a escolha é entre um resultado melhor e um resultado mais cedo.

A pergunta é qual perfil de qualidade a saída precisa cumprir, e o que
acontece quando não cumpre.

## Motivadores da decisão

- A saída é o produto. Um preset rápido que estraga o vídeo, a fala ou
  o resumo não serve como padrão.
- A transcrição alimenta o overlay e o resumo. Erro aqui se propaga.
- O resumo tem de seguir o prompt à letra. Um molde da casa, com
  seções fixas, entrega um texto que a pessoa não pediu.
- Overlay queimado muda o pixel de propósito. Uma métrica cega contra
  o vídeo limpo reprovaria justamente o que foi pedido.
- Falha de qualidade tem de ser visível e repetível. Entregar em
  silêncio um arquivo pior não é resiliência.

## Opções consideradas

- Perfil único de alta qualidade, com gates que falham fechado
- Presets rápidos e modelo pequeno de transcrição
- Melhor esforço, sem gate numérico
- GPU obrigatória para o perfil de qualidade

## Decisão

Opção escolhida: "Perfil único de alta qualidade, com gates que falham fechado",
porque a máquina sem GPU ainda roda este perfil, e um atalho rápido no
padrão apagaria a prioridade de qualidade.

Não há preset "rápido" no caminho padrão. Um perfil de rascunho, se
existir um dia, pede outra ADR. Compactar não autoriza subir o CRF nem
trocar o preset: o encode continua o deste documento. Se o prompt de
overlay não pede nenhuma sobreposição, o programa não reencoda só por
hábito e registra isso no relatório.

**Transcrição.** O modelo padrão é o `large-v3` do faster-whisper, com
`compute_type` `int8`. Esse é o caminho de CPU do CTranslate2 para o
modelo grande: `float16` pede GPU, e `float32` gasta memória e tempo
que a máquina padrão não tem, sem ser o ponto de qualidade adotado.
Modelos menores, `distil` e `large-v3-turbo` inclusive, não são o
padrão. A busca usa `beam_size` 5, não decodificação gulosa. O filtro
de voz padrão do faster-whisper fica ligado, para não promover
silêncio a fala; o job pode desligá-lo, e o relatório guarda a escolha.
A língua é detectada, salvo se o job fixar uma. A transcrição sai com
segmentos e com tempo por palavra, porque o overlay precisa da fala
alinhada. Quem executa é a biblioteca local da
[ADR 0001](0001-python-nao-rust.md). Trocar a transcrição por uma API
não faz parte desta decisão; a
[ADR 0005](0005-ia-plugavel-e-keyring.md) limita a porta plugável ao
modelo de texto.

**Encode.** Quando há encode, o vídeo usa `libx264`, preset `slow`,
CRF `19` e formato de pixel `yuv420p`. Na escala CRF, um número menor
aumenta a qualidade e o tamanho. CRF 19 fica ao lado de 18, o valor que
o guia do x264 trata como visualmente sem perda na prática. É o ponto
de qualidade adotado: ainda no topo da escala, com arquivo menor do que
em 17 ou 18.
O áudio é copiado (`-c:a copy`) quando o container aceita. Quando a
cópia é impossível, o áudio vira AAC a 256 kb/s. Não há segundo arquivo
"mais comprimido" com outro CRF.

O encode de qualidade não queima overlay. Ele é o arquivo
`video-quality.mp4` e é a referência medida pelo VMAF. A entrega com
overlay, `video.mp4`, é uma segunda passagem a partir desse arquivo,
de novo com `libx264`, preset `slow`, CRF `19` e a mesma regra de
áudio, aplicando o filtro `ass`. Duas passagens custam tempo. O custo
fica aceito: a medida de qualidade não pode tratar o texto pedido como
se fosse defeito de compressão.

**Overlays.** O formato é ASS (Advanced SubStation Alpha), renderizado
pelo libass via ffmpeg. SRT não expressa posição e estilo que o prompt
de vídeo pede. O modelo de texto não escreve o ASS final e não escreve
filtro de ffmpeg. Ele devolve uma lista estruturada: início, fim,
texto e a intenção de estilo. O compilador do Megila gera
`overlays.ass` com um subconjunto seguro de tags. O arquivo ASS entra
no diretório de saída, editável, além de ir queimado em `video.mp4`.

**Resumo.** O texto obedece ao prompt de resumo e a mais nada. O
programa não acrescenta título, sumário, tópicos nem rodapé. O fluxo
tem três papéis, todos no modelo de texto da
[ADR 0005](0005-ia-plugavel-e-keyring.md):

1. Escrita: recebe o prompt e o material (a transcrição e o que o
   prompt pedir) e produz o rascunho.
2. Verificação: recebe o prompt e o rascunho e lista violações
   objetivas, como pedido ausente, seção extra ou formato diferente do
   que o prompt exigiu. Não reescreve.
3. Correção: reescreve a partir do prompt, do rascunho e da lista de
   violações.

A verificação e a correção repetem até a lista vir vazia, no máximo
três correções. Se ainda houver violação, o resumo não está aprovado.
O último rascunho fica em `summary.draft.txt`. O arquivo aprovado,
`summary.txt`, só existe em UTF-8, com os bytes do texto aceito, sem
embrulho. O nome do arquivo é contrato do Megila; o prompt manda no
texto, não no caminho.

**Gates.** Todos rodam. Não há interruptor de "pular QA". Falha deixa
o job fora de `succeeded`, conserva o diretório para diagnóstico e
devolve o caso à fila, rumo a retry ou a `dead`, como na
[ADR 0003](0003-fila-sqlite-wal.md). O relatório `qa.json` guarda cada
resultado. O mínimo é:

- Transcrição: `transcript.json` presente, pelo menos um segmento com
  texto, tempos monotônicos e não negativos, e cada palavra dentro do
  segmento pai. Vídeo sem fala falha este gate em vez de inventar
  resumo.
- ASS: `overlays.ass` saiu do compilador do Megila e o ffmpeg da
  queima terminou com código 0. Se não havia overlay pedido, o gate
  registra a ausência e não exige o arquivo.
- Vídeo: o VMAF do `video-quality.mp4` contra a origem é medido com o
  libvmaf, modelo padrão `vmaf_v0.6.1`, na resolução e na taxa de
  quadros desse encode. Só a origem é escalada, com `lanczos`, para
  casar geometria. O encode não é reduzido para esconder defeito. O
  piso padrão é 90. O job pode configurar outro piso; o relatório
  guarda o piso efetivo e a nota. Ausência de nota nunca é aprovação.
  Se a altura do encode passar de 1080, o modelo de VMAF é
  `vmaf_4k_v0.6.1`. A diferença de duração entre `video.mp4` e
  `video-quality.mp4` não passa de 0,1 s. Sem reencode, a entrega é a
  própria origem, o hash dela entra no relatório e o VMAF não se aplica.
- Resumo: a verificação terminou sem violação e `summary.txt` existe.
- Ferramentas: a build do ffmpeg usada no job contém `libx264`,
  `libass` e `libvmaf`. Se faltar qualquer uma, o gate falha fechado
  em vez de seguir sem medida.

`manifest.json`, no mesmo diretório, guarda o id do job, a identidade
da origem, os dois prompts, o perfil efetivo (modelo, `compute_type`,
preset, CRF, piso de VMAF) e as versões do ffmpeg e do faster-whisper.
Segredo de API não entra nesse arquivo.

### Consequências

- Bom, porque o padrão de CPU já é o modelo grande de transcrição e o
  CRF 19, sem um segundo perfil escondido.
- Bom, porque o VMAF incide no encode sem overlay. O texto queimado
  não derruba a nota por existir.
- Bom, porque o resumo que não cumpre o prompt não aparece como
  `summary.txt` aprovado.
- Ruim, porque `large-v3` em `int8`, x264 `slow`, duas passagens, VMAF
  e até três correções de resumo são lentos numa máquina sem GPU. Esse
  tempo é a decisão, não um defeito a contornar com preset `veryfast`.
- Ruim, porque `video-quality.mp4` e `video.mp4` ocupam disco. Disco
  cheio falha o job, como na [ADR 0003](0003-fila-sqlite-wal.md), e não
  produz um mp4 truncado marcado como sucesso.
- Ruim, porque a pessoa precisa de uma build do ffmpeg com libx264,
  libass e libvmaf. Uma build mínima da distro pode não bastar, e o
  programa recusa seguir sem ela.
- Neutro, porque o piso 90 é padrão, não lei física. Conteúdo com
  grão forte pode pedir outro piso no job. O relatório torna o desvio
  visível.

### Confirmação

- Um teste do perfil de encode confere preset `slow`, CRF `19` e
  `yuv420p` nos argumentos do ffmpeg, e confere que a passagem medida
  pelo VMAF não recebe o filtro `ass`.
- Um teste de transcrição confere o modelo `large-v3`, o
  `compute_type` `int8` e `beam_size` 5.
- Um teste do resumo, com modelo falso, entrega um rascunho fora do
  prompt, vê a correção, e no limite de três falhas encontra
  `summary.draft.txt` sem `summary.txt`, com o job fora de
  `succeeded`.
- Um teste do compilador de ASS recusa tag fora do subconjunto seguro
  e recusa filtro de ffmpeg vindo do modelo.
- Um teste remove o libvmaf do cenário e espera falha fechada, sem
  `succeeded`.

## Prós e contras das opções

### Perfil único de alta qualidade, com gates que falham fechado

`large-v3` `int8`, x264 `slow` CRF 19, ASS compilado, resumo em várias
passagens e VMAF com piso, sem interruptor para pular a medida.

- Bom, porque a qualidade não depende de lembrar uma flag. O padrão já
  é o perfil alto.
- Bom, porque cada gate tem artefato no diretório. Dá para auditar o
  job depois, sem reproduzir a corrida inteira só para saber a nota.
- Ruim, porque o wall clock numa CPU modesta fica longo. A
  [ADR 0006](0006-local-por-padrao.md) oferece worker opcional, sem
  mudar este perfil.
- Ruim, porque duas passagens de encode dobram o tempo de compressão
  quando há overlay.

### Presets rápidos e modelo pequeno de transcrição

O padrão seria um modelo `small` ou `distil`, preset `veryfast` e um
CRF mais alto, para caber melhor no tempo da máquina.

- Bom, porque o primeiro resultado apareceria mais cedo e o disco
  sofreria menos.
- Ruim, porque a transcrição menor erra mais palavra, e o overlay e o
  resumo herdam esse erro.
- Ruim, porque preset rápido e CRF mais alto são exatamente a troca de
  qualidade por tempo que o projeto recusou como padrão.
- Neutro, porque esses presets continuam existindo no ffmpeg, para
  quem for experimentar. Não são o caminho do Megila.

### Melhor esforço, sem gate numérico

O programa usaria os mesmos codecs e confiaria no exit code do ffmpeg
e numa leitura por cima do resumo.

- Bom, porque não exige libvmaf e não segura o job por causa de uma
  nota.
- Ruim, porque um encode quebrado, com quadro repetido ou escala
  errada, pode sair com código 0. Sem VMAF isso vira entrega.
- Ruim, porque um resumo que ignora o prompt também seria entregue,
  desde que o modelo tivesse respondido alguma coisa.
- Ruim, porque "melhor esforço" não deixa no diretório um número contra
  o qual a entrega possa ser conferida.

### GPU obrigatória para o perfil de qualidade

O perfil alto existiria só com CUDA ou equivalente, e a máquina sem
GPU receberia um perfil menor.

- Bom, porque `float16` e um preset mais pesado caberiam no tempo de
  quem tem placa.
- Ruim, porque a máquina alvo não tem GPU. Tornar a placa obrigatória
  empurra o padrão para fora da única máquina que o projeto promete
  atender.
- Ruim, porque cria dois Megilas: o de quem tem placa e o de quem não
  tem. O gate deixaria de ser único.
- Neutro, porque uma placa, um Colab ou um worker remoto podem acelerar
  o mesmo perfil no futuro. Acelerar não é baixar o perfil. A
  [ADR 0006](0006-local-por-padrao.md) trata esse worker como opcional.

## Mais informações

- O guia de CRF do x264 está em
  [trac.ffmpeg.org/wiki/Encode/H.264](https://trac.ffmpeg.org/wiki/Encode/H.264).
  CRF 18 é citado ali como visualmente sem perda na prática; CRF 19 é
  o degrau adotado por esta ADR, ainda no topo da escala e menos
  inchado do que 18.
- O [VMAF](https://github.com/Netflix/vmaf) é a métrica do gate de
  vídeo. A nota vai de 0 a 100; maior é melhor. O piso padrão 90
  reprova encode quebrado, como escala errada ou quadro perdido, e não
  exige pixel idêntico. Acima de 1080 de altura usa-se o modelo 4K.
- O formato dos overlays é o do [libass](https://github.com/libass/libass).
- A [ADR 0001](0001-python-nao-rust.md) coloca essa orquestração em
  Python. A [ADR 0003](0003-fila-sqlite-wal.md) retoma o pedaço se a
  passagem longa cair. A [ADR 0005](0005-ia-plugavel-e-keyring.md)
  fornece o modelo de texto das passagens de resumo e do planejamento
  do overlay.
- Vale reabrir se uma medida mostrar que `int8` no `large-v3` fica
  abaixo do piso de forma sistemática num tipo de áudio que o projeto
  precise atender. A resposta é ajustar o perfil numa ADR nova, não
  ligar um atalho rápido em silêncio.
