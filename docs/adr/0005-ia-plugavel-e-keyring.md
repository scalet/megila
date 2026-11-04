---
status: accepted
date: 2026-11-04
decision-makers: Renan Scalet
---

# ADR 0005: IA plugável, local por padrão, segredo no keyring

## Contexto e problema

Dois pontos do pipeline pedem um modelo de linguagem: planejar os
overlays a partir do prompt de vídeo e escrever o resumo a partir do
prompt de resumo, nas passagens da
[ADR 0004](0004-qualidade-em-primeiro-lugar.md). A transcrição não entra
nessa escolha: ela é local, `large-v3` em `int8`, e permanece assim.

O projeto não tem verba para uma API. Ao mesmo tempo, uma máquina
modesta pode não rodar um modelo de texto grande, e quem usa pode
querer apontar para um provedor com a própria chave. Essa chave não
pode aparecer em log, em traceback, na fila, no diretório de saída nem
num arquivo de configuração commitado.

A pergunta é como o modelo de texto é escolhido sem custo obrigatório
e sem vazar o segredo.

## Motivadores da decisão

- O padrão tem de funcionar sem conta, sem chave e sem rede de
  inferência.
- Trocar o modelo de texto não pode reescrever o resumo nem o
  compilador de ASS.
- A chave é da pessoa, não do projeto. O gasto de uma API externa, se
  existir, é dela.
- Segredo em YAML, em `.env`, em SQLite ou em log deixa de ser segredo
  assim que o diretório é copiado ou o log é compartilhado.
- A máquina pode ser um Linux sem chaveiro gráfico. O caminho local não
  pode depender disso.

## Opções consideradas

- Provedores plugáveis, local por padrão, segredo no keyring
- Somente modelo local
- Somente API externa
- Segredo em arquivo de configuração ou na base SQLite

## Decisão

Opção escolhida: "Provedores plugáveis, local por padrão, segredo no keyring",
porque o padrão não gasta nada e não pede chave, e um provedor externo
continua possível sem gravar o segredo no projeto.

A porta de texto é única. Transcrição não passa por ela. Um provedor
implementa uma operação de completar texto, com uma instrução de
sistema e o texto do usuário, e devolve texto. Não recebe a chave como
argumento. Quem precisa de chave a obtém dentro do adaptador, no
momento da chamada, e não a guarda em atributo que um traceback ou um
`repr` mostre.

```python
class TextModel(Protocol):
    def complete(self, *, system: str, user: str) -> str:
        """Devolve o texto do modelo. Não recebe segredo."""
```

O provedor padrão se chama `local`. Não abre conexão externa e não
consulta o keyring. O motor concreto (um processo `llama.cpp`, um
servidor local compatível com a API da OpenAI, ou outro que caiba na
máquina) é configuração. O Megila não escolhe um fornecedor pago
escondido quando o motor local falta: o passo que precisa do modelo
falha com erro claro, e a transcrição, que não usa esta porta, segue
disponível.

Um provedor externo é opt-in. O adaptador padrão de rede fala o
subconjunto HTTP compatível com a API da OpenAI, para que a URL e o
nome do modelo sejam configuração e não um fork de código por
fornecedor. A configuração leva o provedor, o modelo, a URL base e a
identidade da conta no keyring. Não leva o segredo.

```yaml
text_model:
  provider: local
  model: nome-escolhido-por-quem-usa
```

```yaml
text_model:
  provider: openai-compatible
  model: nome-do-modelo
  base_url: https://exemplo-do-provedor/v1
  keyring_service: megila
  keyring_account: openai
```

O segredo é lido com a biblioteca Python `keyring`, no serviço
`megila` e na conta configurada. Essa biblioteca usa o chaveiro do
sistema operacional: Keychain, Credential Manager ou Secret Service,
conforme a plataforma. Se o backend do keyring não estiver disponível,
o provedor externo não liga. O processo explica o que falta e não cai
para arquivo, variável de ambiente persistida nem tabela SQLite. O
provedor `local` continua funcionando sem chave.

O valor lido não entra no payload do job, não entra no `manifest.json`
nem no `qa.json` da [ADR 0004](0004-qualidade-em-primeiro-lugar.md), e
não é escrito no diretório de saída. Um filtro de log do processo
redige o valor, o cabeçalho `Authorization` e qualquer query string que
carregue segredo. Corpo de pedido e corpo de resposta do provedor
também não são logados: a resposta pode ecoar o prompt ou, pior, o
próprio segredo. O que pode ser logado é o nome do provedor, o id do
modelo, o nome da conta no keyring (não o segredo), a latência, a
contagem de tokens se o provedor a informar, e o código HTTP.

O token de um worker remoto, da
[ADR 0006](0006-local-por-padrao.md), segue a mesma regra de guarda e
de redação quando ele existir.

### Consequências

- Bom, porque o clone recém-baixado não chama API e não embute chave.
  O gasto do projeto continua zero.
- Bom, porque trocar o modelo de texto é trocar configuração e
  adaptador, sem mexer no gate do resumo nem no compilador de ASS.
- Bom, porque um backup do diretório de dados ou um trecho de log não
  carregam a chave da API.
- Ruim, porque a qualidade do resumo e do plano de overlay fica limitada
  ao modelo local que a máquina aguenta. Um modelo grande pode não
  caber. O gate da [ADR 0004](0004-qualidade-em-primeiro-lugar.md) não
  afrouxa por causa disso: se o texto não cumprir o prompt, o job falha
  em vez de entregar um resumo genérico.
- Ruim, porque quem quiser um provedor externo precisa ter o chaveiro
  do sistema funcionando. Num Linux sem Secret Service, a API externa
  fica desligada até isso existir. Não há atalho em `.env`.
- Neutro, porque a conta e a fatura de um provedor externo são de quem
  usa. O Megila não cria conta, não guarda cartão e não mede crédito.

### Confirmação

- A configuração de exemplo do provedor externo não contém um campo de
  segredo, só `keyring_service` e `keyring_account`.
- Um teste de log injeta um segredo conhecido, executa uma chamada com
  adaptador falso e falha se o texto capturado do log contiver esse
  segredo, o cabeçalho `Authorization` ou o corpo do pedido.
- Um teste do payload e do `manifest.json` falha se o segredo aparecer.
- Um teste sem backend de keyring confere que o provedor externo recusa
  subir e que o provedor `local` ainda completa uma chamada falsa.
- Um teste de arquitetura confere que a transcrição não importa a porta
  `TextModel`.

## Prós e contras das opções

### Provedores plugáveis, local por padrão, segredo no keyring

A porta é única, o padrão é local e sem chave, e a chave externa mora
no chaveiro do sistema e não entra em log.

- Bom, porque atende ao mesmo tempo gasto zero e a possibilidade de um
  modelo melhor, pago por quem usa, sem mudar o código do resumo.
- Bom, porque o segredo fica no componente do sistema operacional feito
  para isso, não num arquivo do repositório.
- Ruim, porque cada adaptador novo precisa respeitar a redação de log.
  Um `print` de depuração no lugar errado quebra a política. O teste
  do segredo conhecido existe por causa disso.
- Neutro, porque o motor local concreto ainda é escolha de quem usa. A
  ADR fixa a porta e o padrão, não um checkpoint de LLM.

### Somente modelo local

Não existiria adaptador de rede. Sem chave, sem provedor externo.

- Bom, porque não há segredo para vazar e não há ambiguidade de custo.
- Bom, porque o modo offline fica total para o modelo de texto.
- Ruim, porque a máquina modesta pode não rodar um modelo de texto à
  altura do gate de resumo. Sem saída externa, o resumo não teria como
  melhorar.
- Ruim, porque a pessoa que já paga um provedor e aceita enviar o
  texto do prompt não teria como ligar isso no programa.

### Somente API externa

O padrão seria um fornecedor na rede, com chave obrigatória.

- Bom, porque a qualidade do modelo seria mais previsível entre
  máquinas fracas.
- Ruim, porque o projeto passaria a exigir gasto, ou uma chave
  embutida, o que a prioridade de custo zero recusa.
- Ruim, porque o pipeline deixaria de rodar offline e passaria a enviar
  transcrição e prompts para fora por padrão, contra a
  [ADR 0006](0006-local-por-padrao.md).
- Ruim, porque uma chave obrigatória torna o vazamento por log um
  problema do caminho padrão, não de uma opção.

### Segredo em arquivo de configuração ou na base SQLite

O provedor poderia ser plugável, mas a chave ficaria no YAML, num
`.env` ou numa coluna do job.

- Bom, porque funciona num Linux sem Secret Service e é fácil de
  scriptar.
- Ruim, porque o arquivo entra em backup, em cópia de diretório e, com
  um descuido, em commit. A fila da
  [ADR 0003](0003-fila-sqlite-wal.md) seria replicada junto com a chave.
- Ruim, porque log de configuração e dump de linha do job passariam a
  expor o segredo.
- Ruim, porque "não logar" fica frágil se o valor já está no mesmo
  lugar que o sistema loga para depurar.

## Mais informações

- A biblioteca [keyring](https://github.com/jaraco/keyring) é a porta
  para o chaveiro do sistema. O pacote precisa caber na lista de
  licenças da [ADR 0002](0002-licenca-mit-sem-codigo-agpl.md); a licença
  atual do projeto é MIT.
- A [ADR 0004](0004-qualidade-em-primeiro-lugar.md) define as passagens
  de resumo e a lista estruturada de overlay que este modelo produz.
- A [ADR 0006](0006-local-por-padrao.md) mantém o processamento na
  máquina. Ligar um provedor externo é o ato explícito que envia o
  texto do prompt para fora.
- Vale reabrir se o chaveiro do sistema se mostrar inviável na máquina
  real de operação. A alternativa terá de continuar fora do arquivo de
  configuração e fora da tabela `job`. Variável de ambiente solta não
  substitui esta ADR sem uma decisão nova, porque ela vaza em lista de
  processo e em dump de ambiente.
