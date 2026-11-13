"""Opt-in tests of the CLI against the real MolochAI API at https://api.molochai.dev/api/v1.

The same switches as the SDK's live tests. Everything here is skipped unless
``MOLOCHAI_LIVE=1``. Two tiers:

* Unauthenticated: ``molochai models``, ``account`` and ``ask`` with an obviously invalid key
  must exit 1 with the CLI's HTTP 401 message. They cost nothing and need no account.
* Authenticated: also needs ``MOLOCHAI_API_KEY``. Runs ``molochai models``, ``molochai account``,
  ``molochai ask`` plain and with ``--json`` (one tiny prompt each), and ``molochai ask`` with an
  unknown model id and with a model that is not being served, which cost nothing. CONTRIBUTING.md
  lists how many requests one run sends.

::

    MOLOCHAI_LIVE=1 pytest tests/live                                  # unauthenticated only
    MOLOCHAI_LIVE=1 MOLOCHAI_API_KEY=your-api-key pytest tests/live    # both tiers

Optional:

* ``MOLOCHAI_LIVE_MODEL``: ask this model id instead of the automatic pick (the non-reasoning
  model when it is available, else the first available one).
* ``MOLOCHAI_LIVE_BASE_URL``: another deployment, such as the mock server while working on these
  tests.

The CLI runs in-process with a temporary config directory, so your own config file is neither
read nor changed, and ``MOLOCHAI_BASE_URL`` from your shell is not passed on: without
``MOLOCHAI_LIVE_BASE_URL`` the CLI's default, the hosted API, is used. The mock accepts any key,
so the unauthenticated tier fails there. Assertions check the shape of the output, never the
model's wording, and failure messages never include the account details that
``molochai account`` prints.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

import pytest

from molochai_cli.cli import main
from support import FakeStream

# Read at import time: the autouse fixture in tests/conftest.py removes MOLOCHAI_* variables from
# the environment of each test.
LIVE = os.environ.get("MOLOCHAI_LIVE", "").strip() == "1"
API_KEY = os.environ.get("MOLOCHAI_API_KEY", "").strip()
MODEL_OVERRIDE = os.environ.get("MOLOCHAI_LIVE_MODEL", "").strip()
BASE_URL = os.environ.get("MOLOCHAI_LIVE_BASE_URL", "").strip()

INVALID_KEY = "invalid-key-for-testing"
PROMPT = "Reply with the single word: pong"
# A preference only: which models exist and are served comes from `molochai models`. In the
# public catalog every other model reasons, which makes replies longer.
NON_REASONING = "llama-3.3-70b-instruct-abliterated"
UNKNOWN_MODEL = "molochai-live-test-no-such-model"
REPLY_REASONS = {"stop", "length"}
BILLING_URL = (
    "https://dash.molochai.dev/billing"
    "?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai-cli"
)

T = TypeVar("T")

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
    environ = {"MOLOCHAI_API_KEY": key, "MOLOCHAI_CONFIG_DIR": str(config_dir)}
    if BASE_URL:
        environ["MOLOCHAI_BASE_URL"] = BASE_URL
    stdout, stderr = FakeStream(), FakeStream()
    code = main(list(argv), stdin=FakeStream(""), stdout=stdout, stderr=stderr, environ=environ)
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


def account_problem(result: Result) -> str | None:
    """One sentence for a failure caused by the account rather than the CLI."""
    if result.code != 1:
        return None
    headline = result.err.splitlines()[0] if result.err else ""
    if "(HTTP 402)" in headline:
        return (
            "Top up the test account: the account behind MOLOCHAI_API_KEY has no plan and no "
            f"credit (HTTP 402 no_active_plan). Add credit at {BILLING_URL} and run again."
        )
    if "(HTTP 401)" in headline:
        return "MOLOCHAI_API_KEY was not accepted (HTTP 401): it is mistyped or revoked."
    if "(HTTP 403)" in headline:
        return "The account behind MOLOCHAI_API_KEY was refused (HTTP 403). Verify its email."
    if "quota is used up" in headline or "session cap is reached" in headline:
        # The CLI's quota messages carry the window and reset time, no account details.
        return f"The test account's quota is used up: {result.err.strip()}"
    return None


class Live:
    """Runs the CLI with the real key and remembers what earlier tests learned.

    An account problem (no plan or credit, a refused key, an unverified email, a used-up quota)
    fails the test that meets it with one sentence; every later test is then skipped instead of
    failing the same way. ``molochai models`` runs once for the module.
    """

    def __init__(self, tmp_path_factory: pytest.TempPathFactory) -> None:
        self._tmp = tmp_path_factory
        self.problem: str | None = None
        self._results: dict[str, Any] = {}

    def skip_after_problem(self) -> None:
        if self.problem is not None:
            pytest.skip("not run: an earlier test failed on an account problem")

    def run(self, *argv: str) -> Result:
        self.skip_after_problem()
        result = run(self._tmp.mktemp("config"), API_KEY, *argv)
        problem = account_problem(result)
        if problem is not None:
            self.problem = problem
            pytest.fail(problem, pytrace=False)
        return result

    def once(self, name: str, call: Callable[[], T]) -> T:
        """The result of ``call()``, made on first use. If it failed, later callers skip."""
        self.skip_after_problem()
        if name not in self._results:
            self._results[name] = None  # stays None if the call raises
            self._results[name] = call()
        result: T | None = self._results[name]
        if result is None:
            pytest.skip(f"not run: {name} failed earlier in this run")
        return result

    def models(self) -> Result:
        def call() -> Result:
            result = self.run("models")
            check_ok(result)
            return result

        return self.once("molochai models", call)

    def rows(self) -> list[list[str]]:
        """``[id, ..., "yes" | "no"]`` per model, from the ``molochai models`` table."""
        lines = self.models().out.splitlines()
        return [line.split() for line in lines[1:] if line.strip()]

    def chat_model(self) -> str:
        available = [row[0] for row in self.rows() if row[-1] == "yes"]
        if not available:
            pytest.skip("not run: `molochai models` lists no available model (see test_models)")
        if MODEL_OVERRIDE:
            if MODEL_OVERRIDE not in available:
                pytest.skip(f"not run: MOLOCHAI_LIVE_MODEL={MODEL_OVERRIDE} is not available")
            return MODEL_OVERRIDE
        return NON_REASONING if NON_REASONING in available else available[0]


@pytest.fixture(scope="module")
def live(tmp_path_factory: pytest.TempPathFactory) -> Live:
    return Live(tmp_path_factory)


def check_ok(result: Result) -> None:
    """Fail with the CLI's own message when a command failed (it carries no key or account data)."""
    if result.code != 0:
        pytest.fail(f"exit code {result.code}: {result.err.strip()}", pytrace=False)


@needs_key
def test_models(live: Live) -> None:
    # First in this tier: GET /models is behind the quota check, so an account without plan or
    # credit fails here with one message and the tests below are skipped.
    lines = live.models().out.splitlines()
    assert lines
    assert lines[0].split() == ["ID", "NAME", "AVAILABLE"]
    rows = live.rows()
    assert rows, "no models listed"
    assert all(len(row) >= 3 for row in rows), "a row has no display name"
    assert all(row[-1] in {"yes", "no"} for row in rows)
    available = [row[0] for row in rows if row[-1] == "yes"]
    if not available:
        pytest.fail(
            f"`molochai models` lists {len(rows)} models and none is available: no server is "
            "serving any model right now. That is an outage, not a test problem.",
            pytrace=False,
        )
    if MODEL_OVERRIDE and MODEL_OVERRIDE not in available:
        listed = any(row[0] == MODEL_OVERRIDE for row in rows)
        state = "is not available" if listed else "is not listed"
        pytest.fail(
            f"MOLOCHAI_LIVE_MODEL={MODEL_OVERRIDE} {state} in `molochai models`.", pytrace=False
        )


_FIELD = re.compile(r"^(\S.*?)\s{2,}(.*)$")
_CREDIT = re.compile(r"^\$-?[\d,]+\.\d\d$")
_TOKENS = re.compile(r"^[\d,]+$")


@needs_key
def test_account(live: Live) -> None:
    result = live.run("account")
    check_ok(result)
    # Only booleans reach an assert: a failing assert on result.out would print the account
    # details. The credit is checked for its format, never its amount.
    lines = result.out.splitlines()
    fields = {m.group(1): m.group(2) for line in lines if (m := _FIELD.match(line))}
    missing = [
        label
        for label in ("Plan", "Tier", "Credit", "Email verified", "Context limit")
        if label not in fields
    ]
    tier_known = fields.get("Tier", "unknown") not in {"", "unknown"}
    credit_is_amount = bool(_CREDIT.match(fields.get("Credit", "")))
    verified_is_bool = fields.get("Email verified") in {"yes", "no"}
    email_hidden = "@" not in result.out
    header = next((i for i, line in enumerate(lines) if line.startswith("MODEL ")), None)
    rows = []
    if header is not None:
        for line in lines[header + 1 :]:
            if not line.strip() or line.startswith("Context limit per model"):
                break
            rows.append(line.split())
    assert missing == [], "labels missing from `molochai account`"
    assert tier_known, "`molochai account` shows no tier, but the account can spend"
    assert credit_is_amount, "`molochai account` shows no credit amount"
    assert verified_is_bool, "`molochai account` shows no email verification state"
    assert email_hidden, "`molochai account` printed the email without --show-email"
    assert header is not None, "`molochai account` shows no per-model table"
    assert lines[header].split() == ["MODEL", "AVAILABLE", "CONTEXT", "LIMIT"]
    assert rows, "`molochai account` lists no models"
    for row in rows:
        assert len(row) == 3, f"unexpected model row: {row}"
        model, available, limit = row
        assert available in {"yes", "no"}
        if available == "yes":
            assert _TOKENS.match(limit), f"{model} is available but has no context limit"
        else:
            assert limit == "-" or _TOKENS.match(limit)


@needs_key
def test_ask(live: Live) -> None:
    model = live.chat_model()
    result = live.run("ask", "--no-stdin", "--model", model, PROMPT)
    check_ok(result)
    assert result.out.strip(), "`molochai ask` printed no answer"
    assert "error:" not in result.err


@needs_key
def test_ask_json(live: Live) -> None:
    model = live.chat_model()
    result = live.run("ask", "--no-stdin", "--json", "--model", model, PROMPT)
    check_ok(result)
    data = json.loads(result.out)
    assert data["object"] == "chat.completion"
    assert data["id"]
    assert data["model"] == model
    assert len(data["choices"]) == 1
    choice = data["choices"][0]
    assert choice["finish_reason"] in REPLY_REASONS
    message = choice["message"]
    assert message["role"] == "assistant"
    assert not message.get("tool_calls")
    assert message.get("content") or message.get("reasoning_content"), "no content or reasoning"
    usage = data["usage"]
    assert usage["prompt_tokens"] > 0
    assert usage["completion_tokens"] > 0
    assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]


@needs_key
def test_unknown_model(live: Live) -> None:
    # Rejected by validation before any model work: costs nothing.
    result = live.run("ask", "--no-stdin", "--model", UNKNOWN_MODEL, PROMPT)
    assert result.code == 1, f"exit code {result.code}, expected 1 (API error)"
    assert result.out == ""
    assert result.err.startswith("error: The request was rejected (HTTP 422)")


@needs_key
def test_unavailable_model(live: Live) -> None:
    unavailable = [row[0] for row in live.rows() if row[-1] == "no"]
    if not unavailable:
        pytest.skip(
            "`molochai models` lists every model as available, so model_unavailable cannot be "
            "checked without generating"
        )
    model = unavailable[0]
    result = live.run("ask", "--no-stdin", "--model", model, PROMPT)
    if result.code == 0:
        pytest.skip(f"{model} started being served between `molochai models` and this request")
    assert result.code == 1, f"exit code {result.code}, expected 1 (API error)"
    assert result.out == ""
    assert result.err.startswith(f"error: {model} is not being served right now")
