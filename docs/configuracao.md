# Configuração

O Megila lê a configuração em camadas. A camada mais específica vence:

1. Argumentos passados a `load_settings` no código.
2. Variáveis de ambiente com o prefixo `MEGILA_`.
3. O arquivo TOML.
4. Os padrões do programa.

Para quem edita o arquivo ou o ambiente, a ordem que importa é
**ambiente, depois arquivo, depois padrão**. Um valor definido no
ambiente substitui o mesmo valor no arquivo. Um valor definido só no
arquivo substitui o padrão. Os outros campos do arquivo permanecem.

Não existe arquivo `.env`. A chave de API não entra em nenhuma camada.
Ela fica no chaveiro do sistema operacional, no serviço `megila`, como
na [ADR 0005](adr/0005-ia-plugavel-e-keyring.md). Esta versão ainda não
lê o chaveiro: só guarda o nome do serviço e o nome da conta. O segredo
em si é recusado se aparecer na configuração.

## Onde fica o arquivo

O caminho é `$XDG_CONFIG_HOME/megila/config.toml` quando
`XDG_CONFIG_HOME` é um caminho absoluto e não está vazio. Caso
contrário, `~/.config/megila/config.toml`.

Um valor vazio ou relativo em `XDG_CONFIG_HOME` é ignorado, como pede a
especificação XDG. Um arquivo ausente não é erro: valem os padrões. O
Megila não cria o arquivo sozinho.

## Diretório de dados

O padrão é `$XDG_DATA_HOME/megila`, ou `~/.local/share/megila` quando
`XDG_DATA_HOME` não é um caminho absoluto. A fila e o diretório de cada
job ficam aí, em disco local, como na
[ADR 0006](adr/0006-local-por-padrao.md).

`data_dir` tem de ser absoluto. `~` é expandido. Um caminho relativo é
erro. `MEGILA_DATA_DIR` vence o arquivo, e o arquivo vence esse padrão.
`XDG_DATA_HOME` só entra no cálculo do padrão; não é uma variável
`MEGILA_`.

## Variáveis de ambiente

O prefixo é `MEGILA_`. Campos aninhados usam `__`. A leitura não
distingue maiúsculas de minúsculas. Nomes de perfil são identificadores
em minúsculas, como `default` ou `aula`.

| Variável | Efeito |
| --- | --- |
| `MEGILA_DATA_DIR` | Diretório de dados. |
| `MEGILA_ACTIVE_PROFILE` | Nome do perfil ativo. |
| `MEGILA_TEXT_MODEL__PROVIDER` | Nome do provedor do modelo de texto. |
| `MEGILA_TEXT_MODEL__MODEL` | Nome do modelo. |
| `MEGILA_TEXT_MODEL__BASE_URL` | URL base, sem usuário, senha, query ou fragmento. |
| `MEGILA_TEXT_MODEL__KEYRING_SERVICE` | Serviço no chaveiro. O padrão é `megila`. |
| `MEGILA_TEXT_MODEL__KEYRING_ACCOUNT` | Conta no chaveiro. Não é o segredo. |
| `MEGILA_PROFILES__DEFAULT__LANGUAGE` | Idioma do perfil `default`. O mesmo vale para os outros campos do perfil. |

Uma variável desconhecida com o prefixo `MEGILA_` é ignorada, exceto
quando o nome parece um segredo (`API_KEY`, `TOKEN`, `PASSWORD` e
equivalentes). Nesse caso o programa para e pede para apagar a
variável. A mensagem cita o nome da variável e não o valor.

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
