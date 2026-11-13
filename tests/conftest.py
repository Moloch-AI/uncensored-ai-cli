from __future__ import annotations

from pathlib import Path

import pytest

from support import API_KEY, BASE_URL, Runner


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The SDK reads a few variables from the real environment; keep them out of the tests."""
    for name in (
        "MOLOCHAI_API_KEY",
        "MOLOCHAI_BASE_URL",
        "MOLOCHAI_MODEL",
        "MOLOCHAI_CONFIG_DIR",
        "MOLOCHAI_TIMEOUT",
        "MOLOCHAI_MAX_RETRIES",
        "NO_COLOR",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    return tmp_path / "config"


@pytest.fixture
def cli(config_dir: Path) -> Runner:
    """A runner with an API key and base URL in the environment."""
    return Runner(
        config_dir=config_dir,
        env={"MOLOCHAI_API_KEY": API_KEY, "MOLOCHAI_BASE_URL": BASE_URL},
    )


@pytest.fixture
def bare_cli(config_dir: Path) -> Runner:
    """A runner with nothing set: no key, no base URL."""
    return Runner(config_dir=config_dir)
