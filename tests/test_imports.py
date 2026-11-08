"""Import every Megila subpackage."""

import importlib
import pkgutil

import pytest

import megila

EXPECTED_SUBPACKAGES: tuple[str, ...] = (
    "megila.api",
    "megila.cli",
    "megila.config",
    "megila.doctor",
    "megila.jobs",
    "megila.jobs.queue",
    "megila.notify",
    "megila.plugins",
    "megila.providers",
    "megila.secrets",
    "megila.stages",
    "megila.storage",
)


def _discovered_subpackages() -> list[str]:
    discovered: list[str] = []
    prefix = f"{megila.__name__}."
    for module in pkgutil.walk_packages(megila.__path__, prefix=prefix):
        if module.ispkg:
            discovered.append(module.name)
    return sorted(discovered)


def test_package_version_is_set() -> None:
    assert megila.__version__ == "0.1.0"


def test_subpackage_set_matches_layout() -> None:
    assert _discovered_subpackages() == sorted(EXPECTED_SUBPACKAGES)


@pytest.mark.parametrize("name", EXPECTED_SUBPACKAGES)
def test_subpackage_imports(name: str) -> None:
    module = importlib.import_module(name)
    assert module.__name__ == name
