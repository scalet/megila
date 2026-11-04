# Segurança

A chave de um provedor de texto não entra na configuração, no ambiente,
no log nem no diretório do job. O lugar dela é o chaveiro do sistema
operacional. Esta página diz onde o valor fica, o que acontece quando a
máquina não tem chaveiro, e como o log esconde o segredo.

A decisão de produto está na
[ADR 0005](adr/0005-ia-plugavel-e-keyring.md). Os nomes `keyring_service`
e `keyring_account`, que não são o segredo, estão na
[configuração](configuracao.md). O perfil só guarda o nome do provedor,
como em [Perfis](perfis.md).

## Onde a chave fica

O programa usa a biblioteca
[keyring](https://github.com/jaraco/keyring). Ela fala com o chaveiro
do sistema: Keychain, Credential Manager ou Secret Service, conforme a
plataforma.

O serviço é `text_model.keyring_service`. O padrão é `megila`. A conta
é o nome do provedor passado ao comando, e deve ser o mesmo valor de
`text_model.keyring_account`. Os dois campos estão no modelo de
configuração. O valor da chave não está.

```toml
[text_model]
provider = "openai-compatible"
model = "nome-do-modelo"
base_url = "https://exemplo-do-provedor/v1"
keyring_service = "megila"
keyring_account = "openai"
```

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

## Alternativa em arquivo

A [ADR 0005](adr/0005-ia-plugavel-e-keyring.md) prefere o chaveiro e
recusa segredo no arquivo de configuração, em variável de ambiente, na
fila e no log. Quando o sistema não oferece um backend de chaveiro, o
Megila não pede para colocar a chave no `config.toml` nem no ambiente.
Ele grava um arquivo separado, só nessa situação.

O caminho é `$XDG_CONFIG_HOME/megila/secrets.json` quando
`XDG_CONFIG_HOME` é um caminho absoluto e não está vazio. Caso
contrário, `~/.config/megila/secrets.json`. Um valor vazio ou relativo
em `XDG_CONFIG_HOME` é ignorado, como na
[configuração](configuracao.md).

O arquivo é criado com modo `0600`: só quem é dono lê e escreve. A
gravação usa um temporário no mesmo diretório, também em `0600`, e
troca o nome com `os.replace`. O modo não depende do `umask`. Um link
simbólico nesse caminho é recusado na leitura. `megila keys set`
substitui o link e não escreve no alvo.

Esse arquivo não é o `config.toml`, não é um `.env` e não fica no
diretório de dados nem no diretório do job. A fila SQLite não recebe a
chave. Se mais tarde a máquina passar a ter chaveiro, as chaves que já
estavam no arquivo continuam nele: o processo usa o chaveiro e não
copia o arquivo sozinho. Apagar o arquivo, ou gravar de novo com
`megila keys set` enquanto o chaveiro existe, é uma ação de quem usa.

O backend nulo e o backend que só falha contam como ausência de
chaveiro. Um chaveiro presente e bloqueado não cai para o arquivo: o
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
nome do provedor, o serviço do chaveiro, o tipo de backend
(`keyring` ou `file`) e, na alternativa em arquivo, o caminho. O valor
não entra. Corpo de pedido e corpo de resposta de um provedor também
não são logados.

Um log da biblioteca padrão da linguagem passa pelo mesmo redator no
texto da mensagem.

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
backend não sobe e vale a alternativa em arquivo. `MIT-0` não acrescenta
obrigação além da MIT. O teste de licenças do repositório confere essa
lista.
