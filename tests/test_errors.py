"""Every SDK error type renders with a message and a next step."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
from molochai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    MolochAIError,
    StreamError,
)

from molochai_cli.errors import describe_error, format_local_time
from support import Router, Runner, json_response, stream_reply

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)


def gateway(http_status: int, error_type: str, **extra: Any) -> httpx.Response:
    return json_response(http_status, {"error": {"type": error_type, "message": "msg", **extra}})


CASES: list[tuple[str, httpx.Response, list[str]]] = [
    (
        "401",
        json_response(401, {"message": "Unauthenticated."}),
        ["The API key was not accepted (HTTP 401).", "dash.molochai.dev/account?utm_source="],
    ),
    (
        "402",
        gateway(402, "no_active_plan", plan=None),
        ["No active plan and no credit", "Add credit or buy a plan", "molochai.dev/pricing?utm"],
    ),
    (
        "403 unverified",
        json_response(
            403, {"message": "Verify your email to continue.", "code": "email_unverified"}
        ),
        ["not verified yet (HTTP 403): Verify your email to continue."],
    ),
    (
        "403 other",
        json_response(403, {"message": "Forbidden."}),
        ["Access denied (HTTP 403): Forbidden."],
    ),
    (
        "413",
        gateway(
            413,
            "context_length_exceeded",
            estimated_tokens=70123,
            context_cap=65536,
            bound_by="plan",
            plan="pro",
        ),
        ["about 70,123 tokens, limit 65,536 (set by your plan)", "Shorten the input."],
    ),
    (
        "422 model",
        json_response(
            422,
            {
                "message": "The selected model is invalid.",
                "errors": {"model": ["The selected model is invalid."]},
            },
        ),
        ["rejected (HTTP 422): The selected model is invalid.", "Run `molochai models`."],
    ),
    (
        "422 other",
        json_response(422, {"message": "Bad.", "errors": {}}),
        ["rejected (HTTP 422): Bad."],
    ),
    (
        "429 rate limit",
        json_response(429, {"message": "Too Many Attempts."}, headers={"Retry-After": "75"}),
        ["over the limit of 60 requests a minute", "Wait 75 s"],
    ),
    (
        "429 rate limit no header",
        json_response(429, {"message": "Too Many Attempts."}),
        ["Wait a minute and try again."],
    ),
    (
        "429 session",
        gateway(429, "session_quota_exceeded", resets_at="2026-11-13T13:30:00Z"),
        ["The 5-hour session cap is reached.", "It resets at", "local time"],
    ),
    (
        "429 weekly",
        gateway(429, "quota_exceeded", resets_at=None, weekly_used=5, weekly_cap=5, plan="starter"),
        ["Your weekly quota is used up (5 of 5 tokens).", "Add credit"],
    ),
    (
        "429 quota",
        gateway(429, "quota_exceeded"),
        ["Your quota is used up."],
    ),
    (
        "503 unavailable",
        gateway(503, "model_unavailable", model="glm-5.3-flash"),
        ["glm-5.3-flash is not being served", "`molochai models` lists them"],
    ),
    (
        "503 busy",
        gateway(503, "server_busy"),
        ["Every slot is busy (server_busy)"],
    ),
    (
        "502 upstream",
        gateway(502, "upstream_error", status=500, body="x", request_id="req_1"),
        ["(HTTP 502 upstream_error): msg", "Request id: req_1"],
    ),
    (
        "524",
        httpx.Response(524, text="<html>timeout</html>"),
        ["edge proxy stopped waiting", "HTTP 524"],
    ),
    (
        "418 other",
        json_response(418, {"message": "Teapot."}),
        ["HTTP 418: Teapot."],
    ),
]


@pytest.mark.parametrize(("name", "response", "expected"), CASES, ids=[c[0] for c in CASES])
def test_http_errors_through_ask(
    cli: Runner, name: str, response: httpx.Response, expected: list[str]
) -> None:
    result = cli("ask", "Hi", handler=Router(response))
    assert result.code == 1
    assert result.out == ""
    assert result.err.startswith("error: ")
    for text in expected:
        assert text in result.err


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        ({"type": "preempted", "message": "m"}, "reclaimed in the middle of the reply"),
        ({"type": "upstream_timeout", "message": "m", "elapsed_s": 181.2}, "after 181 s"),
        ({"type": "upstream_timeout", "message": "m", "elapsed_s": 1.25}, "after 1.2 s"),
        ({"type": "upstream_error", "message": "boom", "status": 500}, "(upstream_error): boom"),
    ],
)
def test_stream_errors_through_ask(cli: Runner, event: dict[str, Any], expected: str) -> None:
    router = Router(stream_reply(["Part"], reasoning=[], tail=[{"error": event}, "[DONE]"]))
    result = cli("ask", "Hi", handler=router)
    assert result.code == 1
    assert result.out == "Part\n"
    assert expected in result.err


def test_invalid_stream(cli: Runner) -> None:
    router = Router(stream_reply(["Part"], reasoning=[], tail=["data: {nope\n\n"]))
    result = cli("ask", "Hi", handler=router)
    assert result.code == 1
    assert "not a valid stream" in result.err


def test_timeout(cli: Runner) -> None:
    result = cli("ask", "Hi", handler=Router(httpx.ReadTimeout("slow")))
    assert result.code == 1
    assert "The request timed out." in result.err
    assert "MOLOCHAI_TIMEOUT" in result.err


def test_describe_error_direct() -> None:
    assert describe_error(MolochAIError("plain")).message == "plain"
    assert "Could not reach the API" in describe_error(APIConnectionError("x")).message
    assert describe_error(APITimeoutError()).message == "The request timed out."
    problem = describe_error(StreamError("server_busy", "Busy."))
    assert problem.message == "The reply ended with an error (server_busy): Busy."
    assert describe_error(StreamError("upstream_timeout", "m", {"error": "text"})).message == (
        "The reply took too long and was stopped (upstream_timeout)."
    )
    plain = APIStatusError("m", status_code=409)
    assert describe_error(plain).message == "HTTP 409: m"


def test_quota_reset_in_local_time() -> None:
    from molochai import QuotaExceededError

    error = QuotaExceededError(
        "m",
        resets_at=NOW + timedelta(minutes=59, seconds=30),
        kind="monthly",
        status_code=429,
    )
    problem = describe_error(error, now=NOW)
    assert problem.message == "Your monthly quota is used up."
    expected_local = (
        (NOW + timedelta(minutes=59, seconds=30)).astimezone().strftime("%Y-%m-%d %H:%M")
    )
    assert problem.hints[0] == f"It resets at {expected_local} local time (in 59 min)."


@pytest.mark.parametrize(
    ("delta", "suffix"),
    [
        (timedelta(seconds=20), " (in less than a minute)"),
        (timedelta(minutes=5), " (in 5 min)"),
        (timedelta(hours=3), " (in 3 h)"),
        (timedelta(hours=3, minutes=7), " (in 3 h 7 min)"),
        (timedelta(days=4, hours=1), " (in 4 days)"),
        (timedelta(minutes=-5), ""),
    ],
)
def test_format_local_time(delta: timedelta, suffix: str) -> None:
    text = format_local_time(NOW + delta, now=NOW)
    assert text.endswith("local time" + suffix)


def test_context_error_bound_by_unknown() -> None:
    from molochai import ContextLengthExceededError

    error = ContextLengthExceededError("m", status_code=413)
    problem = describe_error(error, in_chat=True)
    assert "about ? tokens, limit ? (set by the context limit)" in problem.message
    assert problem.hints == ["Type /clear to start a new conversation."]


def test_upstream_without_type() -> None:
    from molochai import UpstreamError

    problem = describe_error(UpstreamError("m", status_code=500))
    assert problem.message == "The model server had a problem (HTTP 500): m"
