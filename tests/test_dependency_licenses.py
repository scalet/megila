"""Runtime dependencies stay on the permissive license list from ADR 0002."""

from __future__ import annotations

import importlib.metadata

import pytest

# ADR 0002: MIT, BSD-2-Clause, BSD-3-Clause, Apache-2.0, ISC, PSF-2.0,
# Unlicense, CC0-1.0. MPL and LGPL need their own ADR.
_ALLOWED = frozenset(
    {
        "MIT",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "Apache-2.0",
        "ISC",
        "PSF-2.0",
        "Unlicense",
        "CC0-1.0",
    }
)
_PACKAGES = (
    "pydantic",
    "pydantic-settings",
    "pydantic-core",
    "annotated-types",
    "typing-extensions",
    "python-dotenv",
    "typing-inspection",
)


def _declared_license(name: str) -> str:
    metadata = importlib.metadata.metadata(name)
    expression = metadata.get("License-Expression")
    if expression:
        return expression.strip()
    legacy = metadata.get("License")
    if legacy:
        return legacy.strip().splitlines()[0].strip()
    message = f"{name} does not declare a license"
    raise AssertionError(message)


@pytest.mark.parametrize("name", _PACKAGES)
def test_runtime_dependency_license_is_permissive(name: str) -> None:
    declared = _declared_license(name)
    assert declared in _ALLOWED, f"{name} is {declared}"


def test_settings_libraries_are_mit() -> None:
    assert _declared_license("pydantic") == "MIT"
    assert _declared_license("pydantic-settings") == "MIT"
