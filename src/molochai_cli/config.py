"""The config file and how settings are resolved.

Precedence, highest first: command-line flags, environment variables, the config file, built-in
defaults. The API key has no command-line flag on purpose: anything typed on a command line is
saved in shell history and visible to other processes.

The config file is JSON. Its location is ``$MOLOCHAI_CONFIG_DIR/config.json`` if that variable is
set, otherwise ``%APPDATA%\\molochai\\config.json`` on Windows and
``$XDG_CONFIG_HOME/molochai/config.json`` (default ``~/.config/molochai/config.json``) elsewhere.
On POSIX systems it is written with mode 0600 in a directory created with mode 0700. On Windows
it relies on the access rules of the user profile it lives in.
"""

from __future__ import annotations

import contextlib
import json
import os
import stat
import sys
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from molochai import DEFAULT_BASE_URL

from .errors import ConfigError, UsageError

__all__ = [
    "DEFAULT_MODEL",
    "SETTING_NAMES",
    "ConfigFile",
    "Setting",
    "Settings",
    "config_path",
    "env_value",
    "mask_key",
    "normalize_base_url",
    "resolve_settings",
]

DEFAULT_MODEL = "glm-5.3-flash"
CONFIG_FILENAME = "config.json"

SETTING_NAMES: dict[str, str] = {"api-key": "api_key", "base-url": "base_url", "model": "model"}
"""Names used on the command line (``config unset base-url``) and their keys in the file."""


def env_value(environ: Mapping[str, str], name: str) -> str | None:
    """An environment variable, with empty or blank values treated as unset."""
    value = environ.get(name)
    if value is None or not value.strip():
        return None
    return value.strip()


def config_dir(environ: Mapping[str, str], *, platform: str = sys.platform) -> Path:
    """The directory that holds ``config.json``."""
    override = env_value(environ, "MOLOCHAI_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    if platform == "win32":
        appdata = env_value(environ, "APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return base / "molochai"
    xdg = env_value(environ, "XDG_CONFIG_HOME")
    if xdg and Path(xdg).is_absolute():
        return Path(xdg) / "molochai"
    return Path.home() / ".config" / "molochai"


def config_path(environ: Mapping[str, str], *, platform: str = sys.platform) -> Path:
    return config_dir(environ, platform=platform) / CONFIG_FILENAME


def mask_key(key: str) -> str:
    """A form of the key that is safe to print: the last four characters of a long key."""
    if len(key) >= 12:
        return "****" + key[-4:]
    return "****"


def normalize_base_url(url: str) -> str:
    """Strip whitespace and a trailing slash; require http:// or https://."""
    cleaned = url.strip().rstrip("/")
    if not cleaned.startswith(("http://", "https://")) or len(cleaned.split("://", 1)[1]) == 0:
        raise ValueError(f"must start with http:// or https://, got {url!r}")
    return cleaned


class ConfigFile:
    """The JSON config file. Unknown keys are kept when the file is rewritten."""

    def __init__(self, path: Path, data: dict[str, Any] | None = None, *, exists: bool = False):
        self.path = path
        self.data: dict[str, Any] = dict(data or {})
        self.exists = exists

    @classmethod
    def load(cls, path: Path, *, warn: Callable[[str], None] | None = None) -> ConfigFile:
        """Read the file. A missing file is an empty config; an unreadable one is an error."""
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return cls(path)
        except OSError as exc:
            raise ConfigError(
                f"Could not read the config file {path}: {exc.strerror or exc}"
            ) from exc
        if warn is not None:
            mode = insecure_mode(path)
            if mode is not None:
                warn(
                    f"{path} can be read by other users (mode {mode:o}). "
                    f"Fix it with: chmod 600 '{path}'"
                )
        try:
            data = json.loads(text) if text.strip() else {}
        except ValueError as exc:
            raise ConfigError(
                f"The config file {path} is not valid JSON: {exc}",
                ["Fix the file, or delete it and set the values again with `molochai config`."],
            ) from exc
        if not isinstance(data, dict):
            raise ConfigError(f"The config file {path} must contain a JSON object.")
        for key in SETTING_NAMES.values():
            if key in data and data[key] is not None and not isinstance(data[key], str):
                raise ConfigError(f"{key} in {path} must be a string.")
        return cls(path, data, exists=True)

    def get(self, key: str) -> str | None:
        value = self.data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    def set(self, key: str, value: str) -> None:
        self.data[key] = value

    def unset(self, key: str) -> bool:
        """Remove ``key``; returns whether it was there."""
        return self.data.pop(key, None) is not None

    def save(self) -> None:
        write_private_file(self.path, json.dumps(self.data, indent=2, sort_keys=True) + "\n")
        self.exists = True


def insecure_mode(path: Path) -> int | None:
    """On POSIX, the permission bits of ``path`` if group or others can read it; else ``None``."""
    if sys.platform == "win32":
        return None
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        return None
    return mode if mode & 0o044 else None


def _ensure_private_dir(directory: Path) -> None:
    if directory.is_dir():
        return
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if sys.platform != "win32":
            os.chmod(directory, 0o700)  # mkdir's mode is reduced by the umask
    except OSError as exc:
        raise ConfigError(f"Could not create {directory}: {exc.strerror or exc}") from exc


def write_private_file(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically, readable only by the owner on POSIX.

    The text goes to a temporary file in the same directory (created with mode 0600), is synced
    to disk, and then replaces ``path`` in one step, so a crash never leaves a half-written file.
    """
    _ensure_private_dir(path.parent)
    try:
        fd, tmp_name = tempfile.mkstemp(prefix=".config-", suffix=".tmp", dir=path.parent)
    except OSError as exc:
        raise ConfigError(f"Could not write to {path.parent}: {exc.strerror or exc}") from exc
    try:
        if sys.platform != "win32":
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except OSError as exc:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise ConfigError(f"Could not write {path}: {exc.strerror or exc}") from exc
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


@dataclass
class Setting:
    """A resolved value and where it came from (shown by ``config show``)."""

    value: str | None
    source: str


@dataclass
class Settings:
    api_key: Setting
    base_url: Setting
    model: Setting


def _pick(*candidates: tuple[str | None, str], default: Setting) -> Setting:
    for value, source in candidates:
        if value:
            return Setting(value, source)
    return default


def resolve_settings(
    *,
    environ: Mapping[str, str],
    config: ConfigFile,
    model_flag: str | None = None,
    base_url_flag: str | None = None,
) -> Settings:
    """Apply the precedence rules: flags, then environment, then the config file, then defaults.

    Raises :class:`UsageError` for an invalid ``--base-url`` and :class:`ConfigError` for an
    invalid base URL from the environment or the file.
    """
    api_key = _pick(
        (env_value(environ, "MOLOCHAI_API_KEY"), "MOLOCHAI_API_KEY"),
        (config.get("api_key"), "config file"),
        default=Setting(None, "not set"),
    )
    base_url = _pick(
        (base_url_flag.strip() if base_url_flag else None, "--base-url"),
        (env_value(environ, "MOLOCHAI_BASE_URL"), "MOLOCHAI_BASE_URL"),
        (config.get("base_url"), "config file"),
        default=Setting(DEFAULT_BASE_URL, "default"),
    )
    if base_url.value is not None:
        try:
            base_url.value = normalize_base_url(base_url.value)
        except ValueError as exc:
            error = UsageError if base_url.source == "--base-url" else ConfigError
            raise error(f"The base URL from {base_url.source} {exc}.") from exc
    model = _pick(
        (model_flag.strip() if model_flag else None, "--model"),
        (env_value(environ, "MOLOCHAI_MODEL"), "MOLOCHAI_MODEL"),
        (config.get("model"), "config file"),
        default=Setting(DEFAULT_MODEL, "default"),
    )
    return Settings(api_key=api_key, base_url=base_url, model=model)
