---
status: accepted
date: 2026-11-04
decision-makers: Renan Scalet
---

# ADR 0002: Licença MIT e nenhum código AGPL

## Contexto e problema

O arquivo `LICENSE` na raiz já publica o Megila sob a licença MIT,
copyright Renan Scalet, 2026. Mais adiante o pipeline pode gerar cortes
curtos a partir de um vídeo longo. Produtos como o
[SupoClip](https://github.com/FujiwaraChoki/supoclip) fazem esse tipo de
trabalho e publicam o código sob a GNU AGPL-3.0. Copiar esse código, ou
traduzi-lo, puxaria obrigação de copyleft forte para um programa que
acabou de ser oferecido como MIT.

A pergunta é como o repositório permanece MIT quando uma ideia vizinha
já existe em código AGPL.

Esta ADR é política do projeto. Não é parecer jurídico.

## Motivadores da decisão

- A licença pública do Megila já é a MIT, no arquivo `LICENSE`.
- Quem reutiliza o programa, num script local ou dentro de outro
  produto, não deve descobrir depois uma obrigação de AGPL.
- Cortes curtos podem se inspirar na ideia de produto. A inspiração
  não é licença para colar código.
- Dependências e programas externos também carregam licença. A regra
  precisa cobrir os dois.

## Opções consideradas

- MIT, com barreira para código copyleft forte
- Relicenciar como AGPL-3.0 e reaproveitar o SupoClip
- Licença dupla MIT e AGPL
- MIT no texto, com trechos AGPL isolados no repositório

## Decisão

Opção escolhida: "MIT, com barreira para código copyleft forte",
porque o projeto já é MIT e a barreira impede que código AGPL entre
pela porta dos cortes curtos ou de uma dependência.

O Megila permanece MIT, o mesmo texto do arquivo `LICENSE`. Não há
relicenciamento para AGPL, GPL ou SSPL, nem licença dupla.

Não entra no repositório, nem como dependência Python, código sob
copyleft forte. Isso inclui GPL, AGPL e SSPL, em qualquer versão.
Também não entra tradução, adaptação mecânica, teste, prompt, esquema,
asset, Dockerfile ou workflow copiado desses projetos. Ler o código
alheio para reproduzir a estrutura ainda conta como derivação: a
implementação nasce de requisitos escritos no Megila.

O SupoClip é o caso que motiva a regra. A ideia de produto que cabe
aqui, no futuro e com ADR própria, é gerar cortes curtos a partir de
um vídeo longo. Não cabem o código, os prompts, os esquemas nem os
textos daquele repositório.

Dependência Python de runtime só entra com licença permissiva desta
lista: MIT, BSD-2-Clause, BSD-3-Clause, Apache-2.0, ISC, PSF-2.0,
Unlicense e CC0-1.0. Qualquer outra licença, inclusive MPL-2.0 e LGPL,
só entra se uma ADR a citar pelo nome do pacote.

ffmpeg, ffprobe, yt-dlp e rclone não são vendorizados. O Megila não
liga libx264, libass nem libvmaf dentro do processo Python e não
redistribui esses binários. Quem instala o programa externo aceita a
licença daquele binário. Uma build GPL do ffmpeg pode existir na
máquina; ela não passa a fazer parte do código-fonte do Megila. A
chamada é por subprocesso, como na [ADR 0001](0001-python-nao-rust.md).

### Consequências

- Bom, porque o arquivo `LICENSE` e o código andam juntos. Quem clona
  o repositório leva MIT, sem um subdiretório de exceção.
- Bom, porque um corte curto futuro pode existir sem herdar a AGPL de
  um projeto vizinho.
- Bom, porque a lista de licenças permissivas é curta e dá para
  conferir num PR.
- Ruim, porque funcionalidade que o SupoClip já implementou terá de
  ser desenhada e escrita de novo, a partir de requisitos nossos.
- Ruim, porque uma biblioteca útil sob MPL ou LGPL fica de fora até
  uma ADR nomeá-la. Esse atraso é o custo de não misturar copyleft por
  acidente.
- Neutro, porque o ffmpeg instalado pelo usuário pode ser GPL. A
  política cobre o que o Megila distribui e vincula, não a licença do
  programa que a pessoa já tem no PATH.

### Confirmação

- A raiz continua com um único `LICENSE`, o texto MIT, copyright
  Renan Scalet.
- Um PR que cola código, teste, prompt, esquema ou asset de projeto
  GPL, AGPL ou SSPL é recusado.
- Quando o CI de dependências existir, a verificação de licença falha
  se uma dependência Python estiver fora da lista permissiva e nenhuma
  ADR citar o pacote.
- O repositório não contém o código-fonte do ffmpeg, do x264, do
  SupoClip nem de outro projeto copyleft forte.

## Prós e contras das opções

### MIT, com barreira para código copyleft forte

O programa permanece como o `LICENSE` já descreve. Copyleft forte não
entra no código nem nas dependências Python.

- Bom, porque reutilização local, fork e incorporação noutro programa
  continuam possíveis nos termos da MIT.
- Bom, porque a regra é anterior ao primeiro corte curto. Não fica
  para "decidir na hora de colar".
- Ruim, porque reimplementar custa tempo que copiar o SupoClip
  economizaria.
- Neutro, porque programas externos copyleft seguem utilizáveis como
  processo separado, sem serem redistribuídos pelo Megila.

### Relicenciar como AGPL-3.0 e reaproveitar o SupoClip

O Megila passaria a AGPL-3.0 para poder trazer código do SupoClip.

- Bom, porque pedaços já escritos de corte, legenda e seleção de
  trechos poderiam ser estudados e reutilizados dentro da licença
  deles.
- Ruim, porque contradiz o `LICENSE` que já está na raiz e a escolha
  de publicar o Megila como MIT.
- Ruim, porque quem quisesse embutir o pipeline num programa que não é
  AGPL deixaria de poder fazê-lo nos termos atuais.
- Ruim, porque "reaproveitar" convida a copiar estrutura, não só a
  ideia, e a fronteira do que é derivado fica frouxa.

### Licença dupla MIT e AGPL

Duas licenças conviveriam, uma para código próprio e outra para trechos
trazidos de projetos AGPL.

- Bom, porque o código escrito aqui continuaria oferecido sob MIT.
- Ruim, porque o programa combinado não fica MIT na prática. O trecho
  AGPL puxa a obrigação dele para a obra que o inclui quando a licença
  daquele trecho o exige.
- Ruim, porque duas licenças no mesmo repositório são exatamente a
  surpresa que a política quer evitar.
- Ruim, porque cada arquivo precisaria de dono de licença, e um import
  errado misturaria os dois.

### MIT no texto, com trechos AGPL isolados no repositório

O `LICENSE` continuaria MIT, e um diretório separado guardaria código
AGPL "que não faz parte do pacote".

- Bom, porque o arquivo da raiz não muda.
- Ruim, porque o diretório isolado continua no repositório que as
  pessoas clonam. Isolar pasta não apaga a licença do código.
- Ruim, porque cedo ou tarde um import atravessa a cerca.
- Ruim, porque a combinação "MIT no título, AGPL no tree" é a pior
  forma de comunicar a licença.

## Mais informações

- O texto MIT do projeto está no arquivo `LICENSE`, na raiz.
- A licença MIT está descrita em
  [opensource.org/license/mit](https://opensource.org/license/mit).
- A GNU AGPL-3.0 está em
  [gnu.org/licenses/agpl-3.0](https://www.gnu.org/licenses/agpl-3.0.html).
- O [SupoClip](https://github.com/FujiwaraChoki/supoclip) publica o
  próprio código sob AGPL-3.0. Ele é referência de problema (cortes
  curtos), não de implementação.
- A [ADR 0001](0001-python-nao-rust.md) fixa o subprocesso para
  programas externos. A [ADR 0006](0006-local-por-padrao.md) fixa quais
  desses programas são opcionais.
- Vale reabrir esta ADR só com uma decisão explícita de relicenciar o
  projeto inteiro. Um caso pontual de pacote MPL ou LGPL pede uma ADR
  que nomeie o pacote, sem relaxar a barreira de AGPL, GPL e SSPL.
