"""Shared state for one command run: console, config file, settings and the SDK client."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import molochai
from molochai import MolochAI, MolochAIError

from ._version import __version__
from .config import ConfigFile, Settings, config_path, resolve_settings
from .console import Console
from .errors import ConfigError, describe_error
from .links import KEYS_URL

__all__ = ["App", "ClientFactory", "default_client_factory"]

ClientFactory = Callable[[Settings], MolochAI]

USER_AGENT = f"molochai-cli/{__version__} molochai-python/{molochai.__version__}"


def default_client_factory(settings: Settings, **options: Any) -> MolochAI:
    """The real client. Timeout and retries come from the SDK's own environment variables
    (``MOLOCHAI_TIMEOUT``, ``MOLOCHAI_MAX_RETRIES``) and defaults. ``options`` go to
    :class:`molochai.MolochAI` (tests pass an ``http_client`` with a mock transport)."""
    return MolochAI(
        api_key=settings.api_key.value,
        base_url=settings.base_url.value,
        default_headers={"User-Agent": USER_AGENT},
        **options,
    )


class App:
    def __init__(
        self,
        *,
        console: Console,
        environ: Mapping[str, str],
        client_factory: ClientFactory,
        base_url_flag: str | None = None,
    ) -> None:
        self.console = console
        self.environ = environ
        self.client_factory = client_factory
        self.base_url_flag = base_url_flag
        self._config: ConfigFile | None = None
        self._client: MolochAI | None = None

    @property
    def config_path(self) -> Path:
        return config_path(self.environ)

    def config(self) -> ConfigFile:
        if self._config is None:
            self._config = ConfigFile.load(self.config_path, warn=self.console.warn)
        return self._config

    def settings(self, model_flag: str | None = None) -> Settings:
        return resolve_settings(
            environ=self.environ,
            config=self.config(),
            model_flag=model_flag,
            base_url_flag=self.base_url_flag,
        )

    def client(self, settings: Settings) -> MolochAI:
        """The SDK client for ``settings``, created once per run."""
        if self._client is not None:
            return self._client
        if not settings.api_key.value:
            raise ConfigError(
                "No API key.",
                [
                    "Save one with `molochai config set-key`, or set MOLOCHAI_API_KEY.",
                    f"Keys are created at {KEYS_URL}",
                ],
            )
        try:
            self._client = self.client_factory(settings)
        except MolochAIError as exc:  # for example an invalid MOLOCHAI_TIMEOUT
            raise ConfigError(describe_error(exc).message) from exc
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
