"""Runtime configuration.

Settings load from ``MEGILA_*`` environment variables and
``$XDG_CONFIG_HOME/megila/config.toml`` (``~/.config/megila/config.toml`` when
``XDG_CONFIG_HOME`` is unset). API keys belong in the operating-system keyring,
not in config files, profiles, or logs. When no keyring backend is available,
``secrets_path`` is the mode-0600 file that holds them instead.
"""

from megila.config.errors import ConfigError, ProfileError
from megila.config.paths import (
    config_home,
    config_path,
    data_home,
    default_data_dir,
    secrets_path,
)
from megila.config.profile import PROFILE_EXPORT_FIELDS, Profile, load_profile
from megila.config.settings import Settings, TextModelSettings, load_settings

__all__ = [
    "PROFILE_EXPORT_FIELDS",
    "ConfigError",
    "Profile",
    "ProfileError",
    "Settings",
    "TextModelSettings",
    "config_home",
    "config_path",
    "data_home",
    "default_data_dir",
    "load_profile",
    "load_settings",
    "secrets_path",
]
