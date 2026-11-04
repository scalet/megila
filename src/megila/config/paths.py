"""XDG locations for Megila configuration and data.

Empty or relative ``XDG_*`` values are ignored, as the XDG Base Directory
specification requires.
"""

from __future__ import annotations

import os
from pathlib import Path


def config_home() -> Path:
    """Return the XDG config home, or ``~/.config``."""
    return _xdg_dir("XDG_CONFIG_HOME", Path.home() / ".config")


def config_path() -> Path:
    """Return the Megila TOML path.

    ``$XDG_CONFIG_HOME/megila/config.toml`` when that variable is an absolute
    path, otherwise ``~/.config/megila/config.toml``.
    """
    return config_home() / "megila" / "config.toml"


def secrets_path() -> Path:
    """Return the file used when no OS keyring backend is available.

    ``$XDG_CONFIG_HOME/megila/secrets.json`` when that variable is an absolute
    path, otherwise ``~/.config/megila/secrets.json``. The file is not
    ``config.toml``. Callers create it with mode ``0600``.
    """
    return config_home() / "megila" / "secrets.json"


def data_home() -> Path:
    """Return the XDG data home, or ``~/.local/share``."""
    return _xdg_dir("XDG_DATA_HOME", Path.home() / ".local" / "share")


def default_data_dir() -> Path:
    """Return the default local data directory, ``<data home>/megila``."""
    return data_home() / "megila"


def _xdg_dir(env_name: str, default: Path) -> Path:
    raw = os.environ.get(env_name)
    if raw is None or raw.strip() == "":
        return default
    path = Path(raw).expanduser()
    if not path.is_absolute():
        return default
    return path
