"""Integration tests: the real CLI and SDK against the MolochAI mock server over HTTP.

The mock lives in https://github.com/Moloch-AI/uncensored-ai-api (``mock-server/``). Start it and
point these tests at it::

    node mock-server/server.mjs --port 4010 --quiet
    MOLOCHAI_MOCK_BASE_URL=http://127.0.0.1:4010/api/v1 pytest tests/integration

Without ``MOLOCHAI_MOCK_BASE_URL`` every test here is skipped. The mock's replies are canned text,
not model output.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from molochai_cli.cli import main
from support import FakeStream

MOCK_BASE_URL = os.environ.get("MOLOCHAI_MOCK_BASE_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not MOCK_BASE_URL, reason="set MOLOCHAI_MOCK_BASE_URL to run against the mock server"
)


@dataclass
class Result:
    code: int
    out: str
    err: str


class Mock:
    def __init__(self, config_dir: Path) -> None:
        self.config_dir = config_dir
        # A key per test keeps each test inside its own rate-limit window on the mock.
        self.key = f"mock-key-{uuid.uuid4().hex[:12]}"

    def env(self, **extra: str) -> dict[str, str]:
        return {
            "MOLOCHAI_BASE_URL": MOCK_BASE_URL,
            "MOLOCHAI_API_KEY": self.key,
            "MOLOCHAI_CONFIG_DIR": str(self.config_dir),
            **extra,
        }

    def __call__(
        self,
        *argv: str,
        stdin: str = "",
        stderr_tty: bool = False,
        lines: Sequence[str] | None = None,
        **env: str,
    ) -> Result:
        stdout, stderr = FakeStream(), FakeStream(tty=stderr_tty)
        pending = list(lines or [])

        def read_line(prompt: str) -> str:
            if not pending:
                raise EOFError
            return pending.pop(0)

        code = main(
            list(argv),
            stdin=FakeStream(stdin),
            stdout=stdout,
            stderr=stderr,
            environ=self.env(**env),
            read_line=read_line if lines is not None else None,
        )
        return Result(code, stdout.getvalue(), stderr.getvalue())


@pytest.fixture
def mock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Mock:
    # Error tests should not wait for the SDK's retries.
    monkeypatch.setenv("MOLOCHAI_MAX_RETRIES", "0")
    return Mock(tmp_path / "config")


def test_models(mock: Mock) -> None:
    result = mock("models")
    assert result.code == 0
    rows = [line.split() for line in result.out.splitlines()[1:]]
    assert [row[0] for row in rows] == [
        "glm-5.3-flash",
        "glm-4.7-flash-uncensored",
        "gemma4-26b-a4b-qat",
        "qwen3.8-27b-uncensored",
        "llama-3.3-70b-instruct-abliterated",
    ]
    assert all(row[-1] == "yes" for row in rows)


def test_account(mock: Mock) -> None:
    result = mock("account")
    assert result.code == 0
    assert "Plan            pro" in result.out
    assert "Context limit   65,536 tokens (plan)" in result.out
    assert "dev@example.com" not in result.out
    assert "dev@example.com" in mock("account", "--show-email").out


def test_ask(mock: Mock) -> None:
    result = mock("ask", "Hello")
    assert result.code == 0
    assert result.out == "Mock reply from glm-5.3-flash: Hello\n"
    assert result.err == ""


def test_ask_with_stdin_and_reasoning(mock: Mock) -> None:
    result = mock("ask", "Summarize this", "--show-reasoning", stdin="some notes")
    assert result.code == 0
    assert result.out == "Mock reply from glm-5.3-flash: Summarize this\n\nsome notes\n"
    assert result.err == "| Mock reasoning for glm-5.3-flash.\n"


def test_ask_json(mock: Mock) -> None:
    result = mock("ask", "Hello", "--json", "--model", "gemma4-26b-a4b-qat")
    data = json.loads(result.out)
    message = data["choices"][0]["message"]
    assert message["content"] == "Mock reply from gemma4-26b-a4b-qat: Hello"
    assert message["reasoning_content"] == "Mock reasoning for gemma4-26b-a4b-qat."
    assert data["usage"]["total_tokens"] > 0


def test_queue_progress(mock: Mock) -> None:
    result = mock("ask", "[mock:queue] hi", stderr_tty=True)
    assert result.code == 0
    assert "queued: position 2 of 3, waited 1s" in result.err
    assert "queued: position 1 of 3, waited 2s" in result.err
    assert result.out.startswith("Mock reply from glm-5.3-flash:")


def test_cap_notice(mock: Mock) -> None:
    result = mock("ask", "[mock:cap] hi")
    assert result.code == 0
    assert result.out == "Mock reply from glm-5.3-flash: [mock:cap] hi\n"
    assert "output cap" in result.err


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("[mock:quota] hi", "Your monthly quota is used up"),
        ("[mock:session-quota] hi", "The 5-hour session cap is reached."),
        ("[mock:context] hi", "limit 65,536 (set by your plan)"),
        ("[mock:unavailable] hi", "glm-5.3-flash is not being served right now"),
        ("[mock:busy] hi", "Every slot is busy (server_busy)"),
        ("[mock:upstream-error] hi", "The model server had a problem (HTTP 502 upstream_error)"),
        ("[mock:preempted] hi", "reclaimed in the middle of the reply (preempted)"),
        ("[mock:timeout] hi", "(upstream_timeout)"),
        ("[mock:rate-limit] hi", "over the limit of 60 requests a minute"),
    ],
)
def test_error_rendering(mock: Mock, prompt: str, expected: str) -> None:
    result = mock("ask", prompt)
    assert result.code == 1
    assert expected in result.err


def test_quota_reset_is_shown_in_local_time(mock: Mock) -> None:
    result = mock("ask", "[mock:quota] hi")
    assert "local time (in 59 min)" in result.err or "local time (in 60 min)" in result.err


def test_auth_errors(mock: Mock) -> None:
    assert "No active plan" in mock("models", MOLOCHAI_API_KEY="mock-no-plan").err
    assert "not verified" in mock("ask", "hi", MOLOCHAI_API_KEY="mock-unverified").err
    blank = mock("ask", "hi", MOLOCHAI_API_KEY="   ")  # blank counts as unset
    assert blank.code == 3
    assert "No API key." in blank.err


def test_unknown_model(mock: Mock) -> None:
    result = mock("ask", "hi", "--model", "not-a-model")
    assert result.code == 1
    assert "The selected model is invalid." in result.err


def test_524_without_streaming(mock: Mock) -> None:
    result = mock("chat", "--no-stream", lines=["[mock:cloudflare-524] hi"])
    assert result.code == 0
    assert "HTTP 524" in result.err
    assert "drop --no-stream" in result.err


def test_chat_session(mock: Mock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = mock(
        "chat",
        lines=[
            "Hello",
            "/model llama-3.3-70b-instruct-abliterated",
            "And now?",
            "/usage",
            "[mock:unavailable] x",
            "/save chat.md",
        ],
    )
    assert result.code == 0
    assert "| Mock reasoning for glm-5.3-flash.\n\nMock reply from glm-5.3-flash: Hello\n" in (
        result.out
    )
    assert "Mock reply from llama-3.3-70b-instruct-abliterated: And now?\n" in result.out
    assert "This session: 2 replies" in result.out
    assert "/models lists them" in result.err
    text = (tmp_path / "chat.md").read_text(encoding="utf-8")
    assert "## llama-3.3-70b-instruct-abliterated" in text
    assert "[mock:unavailable]" not in text  # the failed turn was dropped


def test_chat_multi_turn_sends_history(mock: Mock) -> None:
    # The mock echoes the last user message; a 422 here would mean the history was malformed.
    result = mock("chat", "--system", "Be brief.", lines=["One", "Two", "Three"])
    assert result.code == 0
    assert result.out.count("Mock reply from glm-5.3-flash:") == 3
    assert result.err == ""


def _run_process(
    args: Sequence[str], env: dict[str, str], stdin: bytes = b""
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", "molochai_cli", *args],
        input=stdin,
        capture_output=True,
        env={**os.environ, **env},
        check=False,
        timeout=60,
    )


def test_real_process_with_piped_unicode(mock: Mock) -> None:
    completed = _run_process(["ask", "Echo"], mock.env(), stdin="café → ok\n".encode())
    assert completed.returncode == 0, completed.stderr
    out = completed.stdout.decode("utf-8")
    assert out.replace("\r\n", "\n") == "Mock reply from glm-5.3-flash: Echo\n\ncafé → ok\n"


def test_real_process_set_key_then_use_it(mock: Mock) -> None:
    env = mock.env(MOLOCHAI_API_KEY="")  # blank counts as unset, so the saved key is used
    saved = _run_process(["config", "set-key", "--stdin"], env, stdin=mock.key.encode())
    assert saved.returncode == 0, saved.stderr
    assert mock.key.encode() not in saved.stdout
    models = _run_process(["models"], env)
    assert models.returncode == 0, models.stderr
    assert b"glm-5.3-flash" in models.stdout
