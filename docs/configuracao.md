# Configuração

O Megila lê a configuração em camadas. A mais específica vence.

1. Argumentos nomeados (`kwargs`) de `load_settings` e do
   construtor `Settings`.
2. Variáveis de ambiente (`env`) com o prefixo `MEGILA_`.
3. O arquivo `config.toml`.
4. Os padrões embutidos no programa.

Um valor passado em `kwargs` substitui o ambiente. Um valor no
ambiente substitui o mesmo campo no `config.toml`. Um valor
definido só no arquivo substitui o padrão. Os outros campos do
arquivo permanecem.

A chave de API não entra em nenhuma camada. O modelo guarda
`keyring_service` e `keyring_account`, que são nomes, não o
segredo. Quem grava a chave usa `megila keys`. O contrato desses
campos está na seção [Chaveiro](#chaveiro) e na
[ADR 0005](adr/0005-ia-plugavel-e-keyring.md). Se o segredo
aparecer na configuração, o programa recusa o arquivo, a
variável ou o argumento e não repete o valor.

Esta página é gerada a partir do modelo `Settings`. Não edite o
arquivo à mão. Para atualizar depois de mudar um campo:

```bash
python -m megila.config.docgen
```

## Onde fica o arquivo

O diretório de configuração respeita `XDG_CONFIG_HOME`. O caminho do
arquivo é `$XDG_CONFIG_HOME/megila/config.toml` quando essa variável é
um caminho absoluto e não está vazio. Caso contrário, o arquivo é
`~/.config/megila/config.toml`.

```text
~/.config/megila/
└── config.toml
```

Um valor vazio ou relativo em `XDG_CONFIG_HOME` é ignorado, como
pede a especificação XDG Base Directory. Um arquivo ausente não
é erro: valem os padrões. O Megila não cria o arquivo sozinho.

## Diretório de dados

O padrão de `data_dir` é
`$XDG_DATA_HOME/megila`, ou `~/.local/share/megila`
quando `XDG_DATA_HOME` não é um caminho absoluto. A fila e o
diretório de cada job ficam aí, em disco local, como na
[ADR 0006](adr/0006-local-por-padrao.md).

`data_dir` tem de ser absoluto. `~` é expandido. Um caminho
relativo é erro. `MEGILA_DATA_DIR` vence o arquivo, e o arquivo
vence esse padrão. `XDG_DATA_HOME` só entra no cálculo do
padrão; não é uma variável `MEGILA_`.

## Variáveis de ambiente

O prefixo é `MEGILA_`. Campos aninhados usam `__`. A comparação não
distingue maiúsculas de minúsculas. Arquivos `.env` não são lidos.

O campo `text_model` corresponde às variáveis que começam com
`MEGILA_TEXT_MODEL__`. Como alcançar o modelo de texto. O segredo não
fica aqui.

O campo `profiles` é uma tabela. Cada chave entra na variável, entre
`MEGILA_PROFILES__` e o nome do campo. A chave é escrita em maiúsculas.
Perfis nomeados. A chave é o identificador do perfil, como `default`. A
chave do padrão é `default` (`DEFAULT` na variável). Outra chave segue o
mesmo formato. O campo `video_prompt` da chave `aula` é
`MEGILA_PROFILES__AULA__VIDEO_PROMPT`.

| Variável | Tipo | Padrão | Descrição |
| --- | --- | --- | --- |
| `MEGILA_DATA_DIR` | `Path` | `~/.local/share/megila` | Diretório local da fila e das saídas de cada job. O padrão é `$XDG_DATA_HOME/megila`, ou `~/.local/share/megila` quando `XDG_DATA_HOME` não é um caminho absoluto. |
| `MEGILA_ACTIVE_PROFILE` | `str` | `default` | Nome do perfil ativo. Precisa existir em `profiles`. |
| `MEGILA_TEXT_MODEL__PROVIDER` | `str` | `local` | Nome do provedor. `local` não abre conexão de rede. |
| `MEGILA_TEXT_MODEL__MODEL` | `str` | `""` | Identificador do modelo escolhido por quem opera. |
| `MEGILA_TEXT_MODEL__BASE_URL` | `Union[str, None]` | `None` | URL base compatível com a API OpenAI, sem usuário, senha, query ou fragmento. |
| `MEGILA_TEXT_MODEL__KEYRING_SERVICE` | `str` | `megila` | Serviço no chaveiro do sistema. O padrão é `megila`. Não é o segredo. |
| `MEGILA_TEXT_MODEL__KEYRING_ACCOUNT` | `Union[str, None]` | `None` | Conta no chaveiro. É o nome passado a `megila keys set`. Não é o segredo. |
| `MEGILA_PROFILES__DEFAULT__VIDEO_PROMPT` | `str` | `""` | Instruções do plano de overlay. Não é segredo. |
| `MEGILA_PROFILES__DEFAULT__SUMMARY_PROMPT` | `str` | `""` | Instruções que o resumo deve seguir, e nada além delas. |
| `MEGILA_PROFILES__DEFAULT__GLOSSARY` | `dict[str, str]` | `{}` | Termo mapeado para a forma preferida. |
| `MEGILA_PROFILES__DEFAULT__LANGUAGE` | `str` | `pt-BR` | Etiqueta BCP 47 fixa para os jobs que usam este perfil. |
| `MEGILA_PROFILES__DEFAULT__COMPRESS` | `bool` | `false` | Pede um arquivo de entrega menor. Não autoriza subir o CRF. |
| `MEGILA_PROFILES__DEFAULT__AUDIO_ENHANCE` | `bool` | `false` | Pede tratamento de áudio. Desligado, o áudio permanece intacto. |
| `MEGILA_PROFILES__DEFAULT__OVERLAYS` | `bool` | `true` | Permite queimar overlays quando o prompt de vídeo os pede. |
| `MEGILA_PROFILES__DEFAULT__AUTO_APPROVE` | `bool` | `false` | Reserva um futuro pulo da aprovação humana. Não desliga a checagem de qualidade. |
| `MEGILA_PROFILES__DEFAULT__PROVIDER` | `str` | `local` | Nome do provedor de IA. A chave de API não fica aqui. |

Uma variável desconhecida com o prefixo `MEGILA_` é ignorada,
exceto quando o nome parece um segredo (`API_KEY`, `TOKEN`,
`PASSWORD` e equivalentes). Nesse caso o programa para e pede
para apagar a variável. A mensagem cita o nome da variável e
não o valor.

## Exemplo

```toml
data_dir = "~/.local/share/megila"
active_profile = "default"

[text_model]
provider = "local"

[profiles.default]
language = "pt-BR"
video_prompt = "Descreva só os overlays pedidos."
summary_prompt = "Escreva o resumo pedido, e só isso."
compress = false
audio_enhance = false
overlays = true
auto_approve = false
provider = "local"

[profiles.default.glossary]
Megila = "pipeline de vídeo"
```

O provedor padrão é `local`: sem URL, sem conta e sem rede de
inferência. Um provedor externo é opt-in e continua sem o segredo no
arquivo:

```toml
[text_model]
provider = "openai-compatible"
model = "nome-do-modelo"
base_url = "https://exemplo-do-provedor/v1"
keyring_service = "megila"
keyring_account = "openai"
```

A URL não pode carregar usuário, senha, query ou fragmento. Isso evita
`https://chave@host` e `?api_key=...`. O perfil que escolhe o provedor
está em [Perfis](perfis.md). Enquanto o perfil ativo disser `local`, o
job não usa o provedor externo, mesmo que `text_model` já descreva uma
URL.

## Segredos

Estes nomes são recusados no arquivo, no ambiente e nos argumentos:
`api_key`, `token`, `password`, `secret`, `authorization` e os
equivalentes com hífen ou sufixo (`client_secret`, `access_token`).
O erro é legível e não repete o valor:

```text
/home/pessoa/.config/megila/config.toml cannot contain secrets (text_model.api_key). Remove those fields and store the key in the OS keyring (service 'megila').
```

O glossário é texto do perfil. Um termo chamado `token` é uma palavra,
não um campo de credencial. Ver [Perfis](perfis.md).

## Chaveiro

`keyring_service` é o serviço no chaveiro. O padrão é `megila`.
`keyring_account` é a conta. Ela é o mesmo nome passado a
`megila keys set`. Com `keyring_account = "openai"`, o comando é
`megila keys set openai`.

O comando não aceita a chave como argumento. O programa pede o valor
num prompt oculto. `megila keys list` mostra só os nomes dos
provedores. `megila keys delete` apaga uma conta.

Sem um backend de chaveiro, a chave vai para um arquivo com modo
`0600` em `$XDG_CONFIG_HOME/megila/secrets.json`, ou
`~/.config/megila/secrets.json`. Esse arquivo não é o `config.toml`.
O caminho, a permissão e o mascaramento do log estão em
[Segurança](seguranca.md).

## Escrita atômica

`megila.storage.atomic_write` substitui um arquivo sem publicar um
conteúdo pela metade. O helper grava um temporário no mesmo diretório,
chama `fsync` nesse temporário, troca o nome com `os.replace` e chama
`fsync` no diretório. A troca no mesmo diretório é atômica no sistema
de arquivos. Uma falha antes do `replace` deixa o destino como estava,
ou ausente se ele ainda não existia, e apaga o temporário. Um crash do
processo no meio do temporário pode deixar um irmão `*.tmp`; o destino
não fica pela metade.

O modo de um arquivo novo é `0644`. Se o destino já existe, o modo
dele é preservado. Um link simbólico é substituído; a escrita não o
segue.

## Erros

TOML inválido, perfil desconhecido, caminho relativo e campo fora do
modelo viram `ConfigError`. A mensagem diz o arquivo ou o campo. Ela
não inclui o valor de um segredo rejeitado. Um perfil inválido dentro
do arquivo usa o mesmo texto de [Perfis](perfis.md), com o nome do
perfil.
