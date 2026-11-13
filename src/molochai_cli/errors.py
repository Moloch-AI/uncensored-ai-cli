"""Exit codes, CLI errors, and friendly messages for every SDK error type."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum

from molochai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    ContextLengthExceededError,
    ModelUnavailableError,
    MolochAIError,
    NotFoundError,
    PaymentRequiredError,
    PermissionDeniedError,
    QuotaExceededError,
    RateLimitError,
    ServerBusyError,
    StreamError,
    UnprocessableEntityError,
    UpstreamError,
)

from .links import BILLING_URL, DASHBOARD_URL, KEYS_URL, PRICING_URL

__all__ = [
    "CLIError",
    "ConfigError",
    "ExitCode",
    "Problem",
    "UsageError",
    "describe_error",
    "format_local_time",
]


class ExitCode(IntEnum):
    """Process exit codes. Documented in the README and in ``molochai --help``."""

    OK = 0
    API_ERROR = 1
    """The API returned an error, the connection failed, or a stream ended with an error."""
    USAGE = 2
    """Invalid command-line arguments or input."""
    CONFIG = 3
    """No API key, or an invalid config file, environment variable or setting."""
    INTERRUPTED = 130
    """Ctrl+C."""


class CLIError(Exception):
    """An error with a message for the user and an exit code."""

    exit_code = ExitCode.USAGE

    def __init__(self, message: str, hints: list[str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hints = list(hints or [])


class UsageError(CLIError):
    exit_code = ExitCode.USAGE


class ConfigError(CLIError):
    exit_code = ExitCode.CONFIG


@dataclass
class Problem:
    """A rendered error: one headline and optional hint lines."""

    message: str
    hints: list[str] = field(default_factory=list)


def format_local_time(when: datetime, *, now: datetime | None = None) -> str:
    """``2026-11-13 16:04 local time (in 59 min)``."""
    local = when.astimezone()
    text = local.strftime("%Y-%m-%d %H:%M") + " local time"
    reference = now or datetime.now(timezone.utc)
    seconds = (when - reference).total_seconds()
    if seconds > 0:
        minutes = int(seconds // 60)
        if minutes < 1:
            text += " (in less than a minute)"
        elif minutes < 120:
            text += f" (in {minutes} min)"
        elif minutes < 48 * 60:
            hours, rest = divmod(minutes, 60)
            text += f" (in {hours} h {rest} min)" if rest else f" (in {hours} h)"
        else:
            text += f" (in {minutes // (24 * 60)} days)"
    return text


def _number(value: float | None) -> str:
    if value is None:
        return "?"
    return f"{value:,.0f}"


def _with_request_id(hints: list[str], error: APIStatusError) -> list[str]:
    if error.request_id:
        hints.append(f"Request id: {error.request_id} (include it if you contact support).")
    return hints


def describe_error(
    error: MolochAIError,
    *,
    in_chat: bool = False,
    base_url: str | None = None,
    streaming: bool = True,
    now: datetime | None = None,
) -> Problem:
    """Turn an SDK error into a message and the next step to take.

    ``in_chat`` picks slash-command hints (``/models``) over shell commands.
    """
    models_hint = "Type /models to see the ids." if in_chat else "Run `molochai models`."

    if isinstance(error, AuthenticationError):
        return Problem(
            "The API key was not accepted (HTTP 401).",
            [
                "Check which key is used with `molochai config show`.",
                f"Keys are created (and revoked) at {KEYS_URL}",
            ],
        )
    if isinstance(error, PaymentRequiredError):
        return Problem(
            "No active plan and no credit (HTTP 402).",
            [
                f"Add credit or buy a plan in the dashboard under Billing: {BILLING_URL}",
                f"Plans and limits: {PRICING_URL}",
            ],
        )
    if isinstance(error, PermissionDeniedError):
        if error.type == "email_unverified":
            return Problem(
                f"Your account email is not verified yet (HTTP 403): {error.message}",
                [f"Verify it, then try again. Dashboard: {DASHBOARD_URL}"],
            )
        return Problem(f"Access denied (HTTP 403): {error.message}")
    if isinstance(error, NotFoundError):
        where = f" at {base_url}" if base_url else ""
        return Problem(
            f"Not found (HTTP 404){where}.",
            ["Check the base URL with `molochai config show`."],
        )
    if isinstance(error, ContextLengthExceededError):
        limit_owner = {"plan": "your plan", "server": "the server serving this model"}.get(
            error.bound_by or "", "the context limit"
        )
        hints = [
            "Type /clear to start a new conversation." if in_chat else "Shorten the input.",
        ]
        if error.bound_by == "plan":
            hints.append(f"Context sizes per plan: {PRICING_URL}")
        return Problem(
            f"The input is too long for this model: about {_number(error.estimated_tokens)} "
            f"tokens, limit {_number(error.context_cap)} (set by {limit_owner}).",
            hints,
        )
    if isinstance(error, UnprocessableEntityError):
        details = "; ".join(m for messages in error.errors.values() for m in messages)
        hints = [models_hint] if "model" in error.errors else []
        return Problem(f"The request was rejected (HTTP 422): {details or error.message}", hints)
    if isinstance(error, QuotaExceededError):
        if error.kind == "session":
            headline = "The 5-hour session cap is reached."
        elif error.kind in ("monthly", "weekly"):
            headline = f"Your {error.kind} quota is used up"
            if error.used is not None and error.cap is not None:
                headline += f" ({_number(error.used)} of {_number(error.cap)} tokens)"
            headline += "."
        else:
            headline = "Your quota is used up."
        hints = []
        if error.resets_at is not None:
            hints.append(f"It resets at {format_local_time(error.resets_at, now=now)}.")
        if error.kind != "session":
            hints.append(f"Add credit to keep going now: {BILLING_URL}")
        return Problem(headline, hints)
    if isinstance(error, RateLimitError):
        wait = (
            f"Wait {error.retry_after:.0f} s and try again."
            if error.retry_after is not None
            else "Wait a minute and try again."
        )
        return Problem("Too many requests: over the limit of 60 requests a minute.", [wait])
    if isinstance(error, ModelUnavailableError):
        model = error.model or "This model"
        return Problem(
            f"{model} is not being served right now (model_unavailable).",
            [
                "Pick another model: /models lists them, /model <id> switches."
                if in_chat
                else "Pick another model: `molochai models` lists them; pass it with --model."
            ],
        )
    if isinstance(error, ServerBusyError):
        return Problem(
            "Every slot is busy (server_busy), even after retries.",
            ["Try again in a moment."],
        )
    if isinstance(error, UpstreamError):
        if error.status_code == 524:
            hints = (
                ["Long replies need streaming: drop --no-stream."]
                if not streaming
                else ["Try again."]
            )
            return Problem(
                "The edge proxy stopped waiting for the reply after about 100 s (HTTP 524).",
                _with_request_id(hints, error),
            )
        label = f"HTTP {error.status_code}" + (f" {error.type}" if error.type else "")
        return Problem(
            f"The model server had a problem ({label}): {error.message}",
            _with_request_id(["It was retried; try again shortly."], error),
        )
    if isinstance(error, APIStatusError):
        label = f"HTTP {error.status_code}" + (f" {error.type}" if error.type else "")
        return Problem(f"{label}: {error.message}", _with_request_id([], error))
    if isinstance(error, StreamError):
        if error.type == "preempted":
            return Problem(
                "The server was reclaimed in the middle of the reply (preempted).",
                ["Try again in a minute."],
            )
        if error.type == "upstream_timeout":
            event = error.raw.get("error")
            elapsed = event.get("elapsed_s") if isinstance(event, dict) else None
            after = ""
            if isinstance(elapsed, (int, float)) and not isinstance(elapsed, bool):
                after = f" after {elapsed:.0f} s" if elapsed >= 10 else f" after {elapsed:.1f} s"
            return Problem(
                f"The reply took too long and was stopped{after} (upstream_timeout).",
                ["Try again, or ask for something shorter."],
            )
        if error.type in ("invalid_json", "invalid_chunk"):
            return Problem(f"The server sent something that is not a valid stream: {error}")
        return Problem(
            f"The reply ended with an error ({error.type}): {error.message}",
            ["Try again shortly."],
        )
    if isinstance(error, APITimeoutError):
        return Problem(
            "The request timed out.",
            ["Check your connection. MOLOCHAI_TIMEOUT sets the timeout in seconds."],
        )
    if isinstance(error, APIConnectionError):
        target = base_url or "the API"
        return Problem(
            f"Could not reach {target}: {error.message}",
            ["Check your network connection and the base URL (`molochai config show`)."],
        )
    return Problem(str(error))
