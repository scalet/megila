"""Runtime dependencies stay on the permissive license list from ADR 0002."""

from __future__ import annotations

import importlib.metadata

import pytest

# ADR 0002: MIT, BSD-2-Clause, BSD-3-Clause, Apache-2.0, ISC, PSF-2.0,
# Unlicense, CC0-1.0. MPL and LGPL need their own ADR.
# MIT-0 is the MIT license with the attribution clause removed (SPDX). It adds
# no obligations. cffi, pulled in on Linux by keyring -> SecretStorage ->
# cryptography, declares it.
_ALLOWED = frozenset(
    {
        "MIT",
        "MIT-0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "Apache-2.0",
        "ISC",
        "PSF-2.0",
        "Unlicense",
        "CC0-1.0",
    }
)
_CLASSIFIER_MAP = {
    "License :: OSI Approved :: MIT License": "MIT",
    "License :: OSI Approved :: Apache Software License": "Apache-2.0",
    "License :: OSI Approved :: BSD License": "BSD-3-Clause",
    "License :: OSI Approved :: ISC License (ISCL)": "ISC",
    "License :: OSI Approved :: Python Software Foundation License": "PSF-2.0",
}
_PACKAGES = (
    "psutil",
    "pydantic",
    "pydantic-settings",
    "pydantic-core",
    "annotated-types",
    "typing-extensions",
    "python-dotenv",
    "typing-inspection",
    # keyring (MIT) and the Linux stack it installs.
    "keyring",
    "jaraco.classes",
    "jaraco.functools",
    "jaraco.context",
    "more-itertools",
    "SecretStorage",
    "jeepney",
    "cryptography",
    "cffi",
    "pycparser",
    # structlog is MIT OR Apache-2.0.
    "structlog",
)


def _declared_license(name: str) -> str:
    metadata = importlib.metadata.metadata(name)
    expression = metadata.get("License-Expression")
    if expression:
        return expression.strip()
    legacy = metadata.get("License")
    if legacy:
        first = legacy.strip().splitlines()[0].strip()
        if first and first.upper() != "UNKNOWN":
            return first
    classifiers = metadata.get_all("Classifier") or []
    mapped = [_CLASSIFIER_MAP[item] for item in classifiers if item in _CLASSIFIER_MAP]
    unique = sorted(set(mapped))
    if len(unique) == 1:
        return unique[0]
    message = f"{name} does not declare a license"
    raise AssertionError(message)


def _expression_allowed(expression: str) -> bool:
    """Accept an SPDX expression only when every choice is on the ADR 0002 list.

    ``MIT OR Apache-2.0`` is allowed because both licenses are. A disjunction
    that includes a copyleft license is not, even if another term is MIT.
    """
    or_parts = [part.strip() for part in expression.split(" OR ")]
    if len(or_parts) > 1:
        return all(_expression_allowed(part) for part in or_parts)
    and_parts = [part.strip() for part in expression.split(" AND ")]
    if len(and_parts) > 1:
        return all(_expression_allowed(part) for part in and_parts)
    token = expression.strip().strip("()")
    return token in _ALLOWED


@pytest.mark.parametrize("name", _PACKAGES)
def test_runtime_dependency_license_is_permissive(name: str) -> None:
    declared = _declared_license(name)
    assert _expression_allowed(declared), f"{name} is {declared}"


def test_settings_libraries_are_mit() -> None:
    assert _declared_license("pydantic") == "MIT"
    assert _declared_license("pydantic-settings") == "MIT"


def test_keyring_and_structlog_licenses() -> None:
    assert _declared_license("keyring") == "MIT"
    assert _declared_license("structlog") == "MIT OR Apache-2.0"
    assert _expression_allowed(_declared_license("structlog"))
    assert _declared_license("cffi") == "MIT-0"


def test_psutil_is_bsd_3_clause() -> None:
    assert _declared_license("psutil") == "BSD-3-Clause"
