"""Opt-in tests of the CLI against the real MolochAI API at https://api.molochai.dev/api/v1.

The same switches as the SDK's live tests. Everything here is skipped unless
``MOLOCHAI_LIVE=1``. Two tiers:

* Unauthenticated: ``molochai models``, ``account`` and ``ask`` with an obviously invalid key
  must exit 1 with the CLI's HTTP 401 message. They cost nothing and need no account.
* Authenticated: also needs ``MOLOCHAI_API_KEY``. Runs ``molochai models``,
  ``molochai account`` and one ``molochai ask --json`` with a tiny prompt to the first available
  model. That uses a little of the account's quota or credit (reasoning tokens count too).

::

    MOLOCHAI_LIVE=1 pytest tests/live                                  # unauthenticated only
    MOLOCHAI_LIVE=1 MOLOCHAI_API_KEY=your-api-key pytest tests/live    # both tiers

The CLI runs in-process with a temporary config directory, so your own config file is neither
read nor changed, and ``MOLOCHAI_BASE_URL`` is not passed on: the CLI's default, the hosted API,
is used. Assertions check the shape of the output, never the model's wording, and failure
messages never include the account details that ``molochai account`` prints.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from molochai_cli.cli import main
from support import FakeStream

# Read at import time: the autouse fixture in tests/conftest.py removes MOLOCHAI_* variables from
# the environment of each test.
LIVE = os.environ.get("MOLOCHAI_LIVE", "").strip() == "1"
API_KEY = os.environ.get("MOLOCHAI_API_KEY", "").strip()

INVALID_KEY = "invalid-key-for-testing"
PROMPT = "Reply with the single word: pong"
FINISH_REASONS = {"stop", "length", "tool_calls"}
BILLING_URL = (
    "https://dash.molochai.dev/billing"
    "?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai-cli"
)

pytestmark = pytest.mark.skipif(not LIVE, reason="set MOLOCHAI_LIVE=1 to run the live API tests")
needs_key = pytest.mark.skipif(
    LIVE and not API_KEY, reason="set MOLOCHAI_API_KEY to run the authenticated live tests"
)


@dataclass
class Result:
    code: int
    out: str
    err: str


def run(config_dir: Path, key: str, *argv: str) -> Result:
    stdout, stderr = FakeStream(), FakeStream()
    code = main(
        list(argv),
        stdin=FakeStream(""),
        stdout=stdout,
        stderr=stderr,
        environ={"MOLOCHAI_API_KEY": key, "MOLOCHAI_CONFIG_DIR": str(config_dir)},
    )
    return Result(code, stdout.getvalue(), stderr.getvalue())


# -- unauthenticated tier ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [("models",), ("account",), ("ask", "--no-stdin", PROMPT)],
    ids=["models", "account", "ask"],
)
def test_invalid_key(tmp_path: Path, argv: tuple[str, ...]) -> None:
    result = run(tmp_path, INVALID_KEY, *argv)
    assert result.code == 1
    assert result.out == ""
    assert result.err.startswith("error: The API key was not accepted (HTTP 401).")


# -- authenticated tier ------------------------------------------------------------------------


def check_ok(result: Result) -> None:
    """Fail with one clear sentence when the command failed, naming an account problem."""
    if result.code == 0:
        return
    if "(HTTP 402)" in result.err:
        problem = (
            "The account behind MOLOCHAI_API_KEY has no plan or credit (HTTP 402 "
            f"no_active_plan). Add credit or a plan at {BILLING_URL} and run again."
        )
    else:
        # The CLI's error messages carry no key and no account details.
        problem = f"exit code {result.code}: {result.err.strip()}"
    pytest.fail(problem, pytrace=False)


@pytest.fixture(scope="module")
def models_run(tmp_path_factory: pytest.TempPathFactory) -> Result:
    """``molochai models``, run once for the module."""
    result = run(tmp_path_factory.mktemp("config"), API_KEY, "models")
    check_ok(result)
    return result


@pytest.fixture(scope="module")
def model(models_run: Result) -> str:
    rows = [line.split() for line in models_run.out.splitlines()[1:]]
    available = [row[0] for row in rows if row and row[-1] == "yes"]
    if not available:
        pytest.skip("`molochai models` lists no model that is being served right now")
    return available[0]


@needs_key
def test_models(models_run: Result) -> None:
    lines = models_run.out.splitlines()
    assert lines
    assert lines[0].split() == ["ID", "NAME", "AVAILABLE"]
    rows = [line.split() for line in lines[1:]]
    assert rows, "no models listed"
    assert all(row[-1] in {"yes", "no"} for row in rows)


@needs_key
def test_account(tmp_path: Path) -> None:
    # Not behind the quota check, so this also passes for an account with no plan or credit.
    result = run(tmp_path, API_KEY, "account")
    check_ok(result)
    # Booleans first: a failing assert on result.out would print the account details.
    labels = [line.split("  ")[0] for line in result.out.splitlines()]
    missing = [
        label
        for label in ("Plan", "Tier", "Credit", "Email verified", "Context limit", "MODEL")
        if label not in labels
    ]
    email_hidden = "@" not in result.out
    assert missing == [], "labels missing from `molochai account`"
    assert email_hidden, "`molochai account` printed the email without --show-email"


@needs_key
def test_ask_json(tmp_path: Path, model: str) -> None:
    result = run(tmp_path, API_KEY, "ask", "--no-stdin", "--json", "--model", model, PROMPT)
    check_ok(result)
    data = json.loads(result.out)
    assert data["object"] == "chat.completion"
    assert data["model"] == model
    choice = data["choices"][0]
    assert choice["finish_reason"] in FINISH_REASONS
    message = choice["message"]
    assert message["role"] == "assistant"
    assert message.get("content") or message.get("reasoning_content"), "no content or reasoning"
    usage = data["usage"]
    assert usage["prompt_tokens"] > 0
    assert usage["total_tokens"] >= usage["prompt_tokens"]
