"""README.md and README.en.md keep the same section structure."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
README_PT = REPO_ROOT / "README.md"
README_EN = REPO_ROOT / "README.en.md"

# GitHub Pages does not serve this host yet. Both READMEs name the URL in
# code, as docs/index.md does, so the link checker does not fetch a 404.
# The in-repo pages are real relative links.
DOCS_SITE = "https://scalet.github.io/megila/"

# Level, Portuguese heading, English heading. Order is part of the contract.
HEADINGS: tuple[tuple[int, str, str], ...] = (
    (1, "Megila", "Megila"),
    (2, "O que o Megila faz", "What Megila does"),
    (2, "Origem do nome", "Name origin"),
    (2, "Princípios", "Principles"),
    (3, "Qualidade antes da velocidade", "Quality over speed"),
    (3, "Local por padrão e custo zero", "Local by default and zero cost"),
    (3, "IA plugável", "Pluggable AI"),
    (3, "Resiliência", "Resilience"),
    (2, "Estado atual", "Current status"),
    (2, "Instalação para desenvolvimento", "Development install"),
    (2, "Documentação", "Documentation"),
    (2, "Licença", "License"),
)

# Proper nouns and license names that stay the same in both languages.
SHARED_MARKERS: tuple[str, ...] = (
    "SupoClip",
    "AGPL",
    "yt-dlp",
    "MIT",
    "keyring",
    "SQLite",
    "WAL",
    DOCS_SITE,
)

_FENCE = re.compile(r"^```([^\s`]*)\s*$")
_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)\s*$")
_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parse(text: str) -> tuple[list[tuple[int, str]], dict[str, list[str]]]:
    """Return ATX headings outside fences, and fenced bodies by language."""
    headings: list[tuple[int, str]] = []
    blocks: dict[str, list[str]] = {}
    in_fence = False
    language = ""
    body: list[str] = []
    for line in text.splitlines():
        fence = _FENCE.match(line)
        if fence and not in_fence:
            in_fence = True
            language = fence.group(1)
            body = []
            continue
        if in_fence and line.startswith("```"):
            blocks.setdefault(language, []).append("\n".join(body))
            in_fence = False
            language = ""
            body = []
            continue
        if in_fence:
            body.append(line)
            continue
        heading = _HEADING.match(line)
        if heading is not None:
            headings.append((len(heading.group(1)), heading.group(2).strip()))
    if in_fence:
        message = "unclosed code fence"
        raise AssertionError(message)
    return headings, blocks


def _counts(headings: list[tuple[int, str]]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for level, _title in headings:
        counts[level] = counts.get(level, 0) + 1
    return counts


def _relative_link_targets(text: str, source: Path) -> list[Path]:
    targets: list[Path] = []
    for match in _LINK.finditer(text):
        raw = match.group(1)
        if raw.startswith(("http://", "https://", "mailto:")):
            continue
        path_part = raw.split("#", 1)[0]
        if path_part == "":
            continue
        targets.append((source.parent / path_part).resolve())
    return targets


def test_readmes_exist() -> None:
    assert README_PT.is_file()
    assert README_EN.is_file()


def test_heading_map_and_per_level_counts() -> None:
    pt_headings, _pt_blocks = _parse(_read(README_PT))
    en_headings, _en_blocks = _parse(_read(README_EN))
    assert _counts(pt_headings) == _counts(en_headings)
    assert [level for level, _title in pt_headings] == [
        level for level, _title in en_headings
    ]
    expected_pt = [(level, pt) for level, pt, _en in HEADINGS]
    expected_en = [(level, en) for level, _pt, en in HEADINGS]
    assert pt_headings == expected_pt
    assert en_headings == expected_en


def test_bash_blocks_match() -> None:
    _pt_headings, pt_blocks = _parse(_read(README_PT))
    _en_headings, en_blocks = _parse(_read(README_EN))
    assert set(pt_blocks) == set(en_blocks) == {"bash"}
    pt_bash = pt_blocks["bash"]
    en_bash = en_blocks["bash"]
    assert pt_bash
    assert pt_bash == en_bash
    joined = "\n".join(pt_bash)
    assert 'python -m pip install -e ".[dev]"' in joined
    assert "megila --version" in joined
    assert "python -m megila --version" in joined


def test_readmes_cross_link_and_share_markers() -> None:
    pt = _read(README_PT)
    en = _read(README_EN)
    assert "](README.en.md)" in pt
    assert "](README.md)" in en
    for marker in SHARED_MARKERS:
        assert marker in pt
        assert marker in en


def test_relative_links_resolve() -> None:
    for path in (README_PT, README_EN):
        targets = _relative_link_targets(_read(path), path)
        assert targets
        for target in targets:
            assert target.is_file(), str(target)
