# Perfis

Um perfil diz como um job deve ser tratado: os dois prompts, o
glossário, o idioma, os interruptores e o provedor de IA pelo nome. Ele
não guarda URL, conta do chaveiro nem segredo. A configuração que aponta
o arquivo e o modelo de texto está em
[Configuração](configuracao.md).

O perfil padrão se chama `default`. O campo `active_profile` escolhe
qual perfil o processo usa. Um nome fora da tabela `profiles` é erro.
O nome é um identificador em minúsculas, como `default` ou `aula`.

O objeto é congelado: depois de carregado, os campos não mudam.
`export()` devolve uma cópia só com os campos públicos, pronta para
JSON. A cópia não tem campo de segredo.

## Campos

| Campo | Padrão | Função |
| --- | --- | --- |
| `video_prompt` | vazio | Instruções do plano de overlay. |
| `summary_prompt` | vazio | Instruções do resumo. O texto segue o prompt e nada mais, como na [ADR 0004](adr/0004-qualidade-em-primeiro-lugar.md). |
| `glossary` | vazio | Mapa de termo para a forma preferida. |
| `language` | `pt-BR` | Etiqueta BCP 47. Fixa a língua do job; a [ADR 0004](adr/0004-qualidade-em-primeiro-lugar.md) detecta a língua só quando o job não a fixa. |
| `compress` | `false` | Pede um arquivo de entrega menor. Não autoriza subir o CRF nem trocar o preset da [ADR 0004](adr/0004-qualidade-em-primeiro-lugar.md). |
| `audio_enhance` | `false` | Pede tratamento de áudio. Desligado, o áudio segue a regra da ADR: cópia, ou AAC quando a cópia não cabe. |
| `overlays` | `true` | Permite queimar overlay quando o prompt de vídeo pede. `false` desliga essa etapa. Sem pedido no prompt, o programa não reencoda só por hábito. |
| `auto_approve` | `false` | Reserva um futuro passo de aprovação humana. Não desliga os gates de qualidade. Não existe interruptor de "pular QA". |
| `provider` | `local` | Nome do provedor de texto. Não é a chave. |

`local` não abre conexão externa e não consulta o chaveiro. Outro nome,
como `openai-compatible`, é opt-in. A URL e a conta ficam em
`text_model` na [configuração](configuracao.md), não no perfil
exportado. A chave dessa conta é gravada com `megila keys`, como em
[Segurança](seguranca.md). Enquanto o perfil disser `local`, o job não
usa essa URL.

Um nome de provedor tem de 1 a 64 caracteres: letras minúsculas,
dígitos, hífens e sublinhados, começando por letra. `local` e
`openai-compatible` cabem. `OpenAI` não.

## Exemplo

```toml
active_profile = "default"

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

[profiles.aula]
language = "pt-BR"
video_prompt = "Legendas só nos termos do glossário."
summary_prompt = "Um parágrafo, sem título."
provider = "local"
```

No ambiente, o mesmo idioma do perfil `aula` é
`MEGILA_PROFILES__AULA__LANGUAGE`. Um campo definido no ambiente
substitui o do arquivo e deixa o resto do perfil como está.

## Glossário

As chaves e os valores são texto. Um termo vazio, ou só com espaço, é
erro. O termo `token` pode ser uma palavra do glossário; isso não é um
campo de credencial. A chave de API não vai no glossário: o programa
não tem como adivinhar um segredo escondido numa frase, e o lugar dela
é o chaveiro.

## Erro de perfil inválido

Idioma fora do padrão, provedor com maiúscula, campo desconhecido ou
campo de segredo produzem `ProfileError` (ou `ConfigError`, quando o
perfil vem do arquivo de configuração). A mensagem lista o campo. O
valor de um segredo não entra na mensagem nem na causa da exceção.

Idioma inválido:

```text
Invalid profile 'default':
- profiles.default.language: must be a BCP 47 tag such as 'pt-BR' or 'en' (got 'nope!')
```

Quando o perfil é carregado direto, sem o arquivo, o caminho do campo
não repete o nome do perfil:

```text
Invalid profile:
- language: must be a BCP 47 tag such as 'pt-BR' or 'en' (got '123')
```

Campo de segredo:

```text
Invalid profile:
- api_key cannot store secrets. Put the key in the OS keyring (service 'megila'), not in the profile.
```

As mensagens estão em inglês, como o restante do código.

## Exportação

Os campos exportados, nesta ordem, são `video_prompt`,
`summary_prompt`, `glossary`, `language`, `compress`, `audio_enhance`,
`overlays`, `auto_approve` e `provider`. Não há `api_key`, `token`,
`password`, `base_url` nem `keyring_account`. Alterar o dicionário
devolvido não altera o perfil congelado.
