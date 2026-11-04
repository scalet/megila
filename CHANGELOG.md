# Changelog

Todas as mudanças notáveis deste projeto serão documentadas neste arquivo.

O formato é baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
e este projeto adere ao [Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [Unreleased]

### Added

- Esqueleto do pacote (`src/megila`), CLI Typer (`megila --version`) e
  ferramental de desenvolvimento (hatchling, ruff, mypy estrito, pre-commit)
  (M0-01).
- Código de Conduta (Contributor Covenant 2.1, pt-BR), política de segurança
  com reporte privado via GitHub Security Advisories e prazo de resposta,
  changelog e verificação de Markdown no GitHub Actions (M0-02).
- Clipe sintético determinístico em pt-BR para os testes
  (`tests/assets/make_sample.py`). A mídia gerada fica em cache local e não
  é commitada (M0-03).
- ADRs 0001 a 0006 em `docs/adr/`, no formato MADR, com índice e modelo para
  decisões novas (M0-04).
- Site de documentação com MkDocs Material, build estrito nos pull requests
  e publicação no GitHub Pages em `https://scalet.github.io/megila/` (M0-05).
- Comandos `megila keys set`, `list` e `delete` para guardar a chave do
  provedor no chaveiro do sistema, com logs JSON com mascaramento (M0-10).

[Unreleased]: https://github.com/scalet/megila/commits/main
