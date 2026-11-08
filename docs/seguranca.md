# Segurança

A chave de um provedor de texto não entra na configuração, no ambiente,
no log nem no diretório do job. O lugar dela é o chaveiro do sistema
operacional. Esta página diz onde o valor fica, o que acontece quando a
máquina não tem chaveiro, e como o log esconde o segredo.

A decisão de produto está na
[ADR 0005](adr/0005-ia-plugavel-e-keyring.md). Os campos
`keyring_service` e `keyring_account` estão na
[configuração](configuracao.md). O perfil só guarda o nome do provedor,
como em [Perfis](perfis.md).

## Onde a chave fica

O programa usa a biblioteca
[keyring](https://github.com/jaraco/keyring). Ela fala com o chaveiro
do sistema: Keychain, Credential Manager ou Secret Service, conforme a
plataforma.

O serviço e a conta vêm de `text_model.keyring_service` e
`text_model.keyring_account`. O padrão do serviço é `megila`. A conta é
o nome usado em `megila keys set`. A referência desses campos está na
[configuração](configuracao.md). O valor da chave não está no modelo.

O provedor `local` não abre rede e não consulta o chaveiro.

## Comandos

A chave nunca é argumento de linha de comando. `set` lê o valor com um
prompt oculto (`getpass`, via o prompt do Typer com `hide_input`). O
terminal não ecoa o que foi digitado.

```bash
megila keys set openai
megila keys list
megila keys delete openai
```

| Comando | Efeito |
| --- | --- |
| `megila keys set <provedor>` | Grava a chave da conta `<provedor>`. O valor é pedido no prompt. |
| `megila keys list` | Mostra os nomes dos provedores que têm chave. Não mostra valores. |
| `megila keys delete <provedor>` | Apaga a chave dessa conta. |

Um argumento a mais, uma opção `--api-key` ou o próprio valor no lugar
do nome do provedor é recusado. A mensagem de erro não repete esse
texto. O nome do provedor segue a regra da
[configuração](configuracao.md): minúsculas, como `openai`.

`list` com a lista vazia não imprime nomes. A saída com nomes é uma
linha por provedor, em ordem, sem o segredo.

## Sem chaveiro no sistema

A [ADR 0005](adr/0005-ia-plugavel-e-keyring.md) exige o chaveiro do
sistema operacional. O Megila não grava a chave no `config.toml`, em
variável de ambiente, em arquivo separado, na fila SQLite nem no log.

Quando não há backend de chaveiro utilizável, `megila keys set` falha
com uma mensagem que pede para instalar ou desbloquear o chaveiro
(Keychain, Credential Manager ou Secret Service). O provedor `local`
continua funcionando sem chave. Um provedor externo só sobe depois que
o chaveiro estiver disponível.

O backend nulo e o backend que só falha contam como ausência de
chaveiro. Um chaveiro bloqueado não é substituído por outro lugar: o
comando pede para desbloquear.

## O que não guarda a chave

- O `config.toml` e qualquer campo com nome de credencial
  (`api_key`, `token`, `password` e equivalentes). O erro cita o nome
  do campo e não o valor.
- Variáveis de ambiente, inclusive `MEGILA_*`. Não há arquivo `.env`.
- Argumentos da linha de comando.
- O payload do job, o `manifest.json` e o diretório de saída.
- O log do processo.

## Logs mascarados

O log do Megila sai em JSON, uma linha por evento, pela biblioteca
[structlog](https://github.com/hynek/structlog). Antes de serializar,
um processador redige:

- todo valor que o processo gravou ou leu como chave, inclusive depois
  de a chave ser apagada;
- padrões comuns: `Authorization`, `Bearer`, `api_key`, `token`,
  `password`, `secret` e os equivalentes com hífen ou sublinhado;
- esses nomes em query string (`?api_key=...`) e em campo JSON;
- prefixos de chave no formato `sk-`, `ghp_` e `AKIA`.

O texto que substitui o segredo é `***`. O que pode aparecer no log é o
nome do provedor e o serviço do chaveiro. O valor não entra. Corpo de
pedido e corpo de resposta de um provedor também não são logados.

Um log da biblioteca padrão da linguagem passa pelo mesmo redator no
texto da mensagem. Esse redator é instalado como fábrica de `LogRecord`
do processo inteiro: ele renderiza e redige a mensagem de todo registro,
inclusive o de bibliotecas de terceiros, e descarta os `args` originais.

### Limite: chaves curtas

Um valor registrado com 8 caracteres ou mais é substituído em qualquer
posição do texto. Um valor com menos de 8 só é redigido quando é o texto
inteiro do campo; dentro de uma frase maior ele aparece. O corte evita
que uma chave de 2 ou 3 caracteres estrague todo o log. Chaves reais de
provedores são bem mais longas, mas quem usa um valor curto de teste deve
saber que o log não o esconde no meio de um texto.

## Dependências

A [ADR 0002](adr/0002-licenca-mit-sem-codigo-agpl.md) só admite
dependência Python de runtime com licença permissiva. Estas entram com
o chaveiro e o log:

| Pacote | Licença | Papel |
| --- | --- | --- |
| `keyring` | MIT | Chaveiro do sistema. |
| `structlog` | MIT OR Apache-2.0 | Log em JSON. |
| `jaraco.classes`, `jaraco.functools`, `jaraco.context` | MIT | Bibliotecas exigidas pelo keyring. |
| `more-itertools` | MIT | Biblioteca exigida pelo jaraco. |
| `SecretStorage` | BSD-3-Clause | Secret Service no Linux. |
| `jeepney` | MIT | D-Bus no Linux, exigido pelo Secret Service. |
| `cryptography` | Apache-2.0 OR BSD-3-Clause | Exigida pelo SecretStorage. |
| `cffi` | MIT-0 | Exigida pelo cryptography. É a MIT sem a cláusula de atribuição. |
| `pycparser` | BSD-3-Clause | Exigida pelo cffi. |

No Linux o pip instala `SecretStorage` e `jeepney` porque o keyring os
declara nessa plataforma. Sem um serviço de segredo acessível, o
backend não sobe e `megila keys` recusa gravar a chave. `MIT-0` não
acrescenta obrigação além da MIT. O teste de licenças do repositório
confere essa lista.
