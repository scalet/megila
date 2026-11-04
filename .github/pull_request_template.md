# Pull request

## O que muda

<!-- Descreva a mudança e o motivo. -->

## Como testar

<!-- Comandos rodados e o resultado. A suíte é `python -m pytest`. -->

## Checklist

O guia está em [CONTRIBUTING.md](../CONTRIBUTING.md).

- [ ] **Testes.** `python -m pytest` passa, com o ambiente descrito em [Ambiente de desenvolvimento](../docs/dev/ambiente.md).
- [ ] **Documentação.** A documentação que esta mudança toca foi atualizada.
- [ ] **Changelog.** Há uma entrada nova, em português, sob `[Unreleased]` em [CHANGELOG.md](../CHANGELOG.md).
- [ ] **README.** `README.md` e `README.en.md` foram atualizados juntos, quando a mudança os alcança.
- [ ] **Licenças.** O diff permanece MIT, conforme a [ADR 0002](../docs/adr/0002-licenca-mit-sem-codigo-agpl.md). Dependência Python de runtime nova está na lista permissiva ou tem uma ADR que cita o pacote.
- [ ] **Estilo.** `python -m ruff check .`, `python -m ruff format --check .` e `python -m mypy` passam quando o diff inclui Python.
