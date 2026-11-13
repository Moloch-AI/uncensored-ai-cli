from __future__ import annotations

import subprocess
import sys

import httpx
import molochai
import pytest

from molochai_cli import __version__
from molochai_cli.app import default_client_factory
from molochai_cli.cli import build_parser, main
from molochai_cli.config import Settings
from support import FakeStream, Router, Runner, models_response


def test_version(bare_cli: Runner) -> None:
    result = bare_cli("--version")
    assert result.code == 0
    assert result.out.startswith(f"molochai-cli {__version__} (molochai SDK {molochai.__version__}")


def test_help_lists_commands_exit_codes_and_docs(bare_cli: Runner) -> None:
    result = bare_cli("--help")
    assert result.code == 0
    for command in ("chat", "ask", "models", "account", "config"):
        assert command in result.out
    assert "130  interrupted (Ctrl+C)" in result.out
    assert "MOLOCHAI_MODEL" in result.out
    assert "shell history" in result.out
    assert "https://molochai.dev/docs?utm_source=github&utm_medium=oss" in result.out


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["chat", "--help"], ["--show-reasoning", "--hide-reasoning", "--no-stream", "/help"]),
        (["ask", "--help"], ["--json", "--show-reasoning", "--no-stdin", "cat notes.md"]),
        (["models", "--help"], ["--base-url"]),
        (["account", "--help"], ["--show-email"]),
        (["config", "--help"], ["set-key", "show", "path", "unset"]),
        (["config", "set-key", "--help"], ["--stdin", "shell history"]),
        (["config", "set", "--help"], ["base-url"]),
        (["config", "unset", "--help"], ["api-key"]),
    ],
)
def test_command_help(bare_cli: Runner, argv: list[str], expected: list[str]) -> None:
    result = bare_cli(*argv)
    assert result.code == 0
    for text in expected:
        assert text in result.out


def test_no_command_is_a_usage_error(bare_cli: Runner) -> None:
    result = bare_cli()
    assert result.code == 2
    assert "usage: molochai" in result.err
    assert "Choose a command" in result.err


def test_config_without_subcommand(bare_cli: Runner) -> None:
    result = bare_cli("config")
    assert result.code == 2
    assert "usage: molochai config" in result.err


def test_unknown_option(bare_cli: Runner) -> None:
    result = bare_cli("chat", "--temperature", "2")
    assert result.code == 2
    assert "unrecognized arguments" in result.err


def test_reasoning_flags_are_exclusive(bare_cli: Runner) -> None:
    assert bare_cli("chat", "--show-reasoning", "--hide-reasoning").code == 2


def test_parser_defaults() -> None:
    args = build_parser().parse_args(["chat"])
    assert args.show_reasoning is True
    assert args.no_color is False
    assert args.base_url is None


def test_api_error_exit_code(cli: Runner) -> None:
    router = Router(models=models_response())
    router.models = None  # the router answers 404
    result = cli("models", handler=router)
    assert result.code == 1
    assert "Not found (HTTP 404) at https://api.example.test/api/v1." in result.err


def test_broken_pipe_stops_quietly() -> None:
    class ClosedPipe(FakeStream):
        def write(self, text: str) -> int:
            raise BrokenPipeError

    def factory(settings: Settings) -> molochai.MolochAI:
        transport = httpx.MockTransport(Router(models=models_response()))
        return default_client_factory(settings, http_client=httpx.Client(transport=transport))

    stderr = FakeStream()
    code = main(
        ["models"],
        stdin=FakeStream(),
        stdout=ClosedPipe(),
        stderr=stderr,
        environ={"MOLOCHAI_API_KEY": "k", "MOLOCHAI_BASE_URL": "https://x.test/v1"},
        client_factory=factory,
    )
    assert code == 1
    assert stderr.getvalue() == ""


def test_module_entry_point() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "molochai_cli", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert completed.stdout.startswith("molochai-cli ")
