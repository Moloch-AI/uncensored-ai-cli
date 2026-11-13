"""Shared test helpers: fake terminals, SSE bodies, a request recorder and a CLI runner."""

from __future__ import annotations

import io
import json
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from molochai import MolochAI

from molochai_cli.app import default_client_factory
from molochai_cli.cli import main
from molochai_cli.config import Settings

BASE_URL = "https://api.example.test/api/v1"
API_KEY = "test-key-abcdefghijklmnop"

Handler = Callable[[httpx.Request], httpx.Response]


class FakeStream(io.StringIO):
    """A text stream that can claim to be a terminal."""

    def __init__(self, text: str = "", *, tty: bool = False) -> None:
        super().__init__(text)
        self.tty = tty

    def isatty(self) -> bool:
        return self.tty


class ByteChunks(httpx.SyncByteStream):
    """A response body delivered in pieces, optionally raising after the last one."""

    def __init__(self, chunks: Iterable[bytes], error: BaseException | None = None) -> None:
        self.chunks = list(chunks)
        self.error = error

    def __iter__(self) -> Iterator[bytes]:
        yield from self.chunks
        if self.error is not None:
            raise self.error

    def close(self) -> None:
        pass


def sse(*items: Any) -> bytes:
    """Dicts become data events, ``"[DONE]"`` the terminator, ``":..."`` comment lines."""
    out = []
    for item in items:
        if isinstance(item, dict):
            out.append(f"data: {json.dumps(item)}\n\n")
        elif item == "[DONE]":
            out.append("data: [DONE]\n\n")
        elif isinstance(item, str) and item.startswith(":"):
            out.append(item + "\n")
        else:
            out.append(str(item))
    return "".join(out).encode("utf-8")


def chunk(
    *,
    content: str | None = None,
    reasoning: str | None = None,
    role: str | None = None,
    finish_reason: str | None = None,
    model: str = "glm-5.3-flash",
) -> dict[str, Any]:
    delta: dict[str, Any] = {}
    if role is not None:
        delta["role"] = role
    if reasoning is not None:
        delta["reasoning_content"] = reasoning
    if content is not None:
        delta["content"] = content
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion.chunk",
        "created": 1700000000,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }


def usage_chunk(prompt: int = 3, completion: int = 5) -> dict[str, Any]:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion.chunk",
        "created": 1700000000,
        "model": "glm-5.3-flash",
        "choices": [],
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
        },
    }


RATE_HEADERS = {"X-RateLimit-Limit": "60", "X-RateLimit-Remaining": "59"}


def stream_reply(
    content: Sequence[str] = ("Hello", " there."),
    *,
    reasoning: Sequence[str] = ("Thinking.",),
    finish_reason: str = "stop",
    comments: Sequence[str] = (),
    prompt_tokens: int = 3,
    completion_tokens: int = 5,
    error: BaseException | None = None,
    tail: Sequence[Any] | None = None,
) -> httpx.Response:
    """A streamed reply the way the gateway sends it."""
    items: list[Any] = [*comments, chunk(role="assistant")]
    items += [chunk(reasoning=r) for r in reasoning]
    items += [chunk(content=c) for c in content]
    if tail is not None:
        items += list(tail)
    else:
        items += [
            chunk(finish_reason=finish_reason),
            usage_chunk(prompt_tokens, completion_tokens),
            "[DONE]",
        ]
    pieces = [sse(item) for item in items]
    return httpx.Response(
        200,
        headers={"Content-Type": "text/event-stream", **RATE_HEADERS},
        stream=ByteChunks(pieces, error),
    )


def completion_body(
    content: str | None = "Hello there.",
    *,
    reasoning: str | None = "Thinking.",
    finish_reason: str = "stop",
    model: str = "glm-5.3-flash",
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if reasoning is not None:
        message["reasoning_content"] = reasoning
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1700000000,
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 4, "completion_tokens": 6, "total_tokens": 10},
    }


def json_response(
    status: int, body: Any, headers: Mapping[str, str] | None = None
) -> httpx.Response:
    return httpx.Response(status, json=body, headers={**RATE_HEADERS, **(headers or {})})


MODELS = [
    {"id": "glm-5.3-flash", "name": "GLM-5.3-Flash", "available": True},
    {"id": "llama-3.3-70b-instruct-abliterated", "name": "Llama", "available": True},
    {"id": "gemma4-26b-a4b-qat", "name": "Gemma4-26B-A4B-QAT", "available": False},
]


def models_response(models: list[dict[str, Any]] | None = None) -> httpx.Response:
    data = [
        {"object": "model", "created": 0, "owned_by": "molochai", **m}
        for m in (MODELS if models is None else models)
    ]
    return json_response(200, {"object": "list", "data": data})


class Router:
    """Answers requests by path. Chat replies are taken in order (the last one repeats)."""

    def __init__(
        self,
        *chat: httpx.Response | BaseException | Handler,
        models: httpx.Response | None = None,
        account: httpx.Response | None = None,
    ) -> None:
        self.chat = list(chat)
        self.models = models
        self.account = account
        self.requests: list[httpx.Request] = []
        self._chat_calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.endswith("/chat/completions"):
            if not self.chat:
                raise AssertionError("unexpected chat request")
            item = self.chat[min(self._chat_calls, len(self.chat) - 1)]
            self._chat_calls += 1
            if isinstance(item, BaseException):
                raise item
            if isinstance(item, httpx.Response):
                return item
            return item(request)
        if path.endswith("/models") and self.models is not None:
            return self.models
        if path.endswith("/auth/me") and self.account is not None:
            return self.account
        return json_response(404, {"message": "Not found."})

    def chat_bodies(self) -> list[dict[str, Any]]:
        return [
            json.loads(r.content) for r in self.requests if r.url.path.endswith("/chat/completions")
        ]


@dataclass
class Result:
    code: int
    out: str
    err: str
    prompts: list[str] = field(default_factory=list)
    settings: list[Settings] = field(default_factory=list)


@dataclass
class Runner:
    """Runs ``main()`` with fake streams, an environment and a mock-transport client."""

    config_dir: Path
    env: dict[str, str] = field(default_factory=dict)

    def __call__(
        self,
        *argv: str,
        handler: Handler | None = None,
        stdin: str = "",
        stdin_tty: bool = False,
        stdout_tty: bool = False,
        stderr_tty: bool = False,
        lines: Sequence[str | BaseException] | None = None,
        getpass: Callable[[str], str] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> Result:
        environ = {"MOLOCHAI_CONFIG_DIR": str(self.config_dir), **self.env, **(env or {})}
        stdout = FakeStream(tty=stdout_tty)
        stderr = FakeStream(tty=stderr_tty)
        prompts: list[str] = []
        captured: list[Settings] = []
        pending = list(lines or [])

        def read_line(prompt: str) -> str:
            prompts.append(prompt)
            if not pending:
                raise EOFError
            item = pending.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item

        def factory(settings: Settings) -> MolochAI:
            captured.append(settings)
            transport = httpx.MockTransport(handler or Router())
            return default_client_factory(
                settings, http_client=httpx.Client(transport=transport), max_retries=0
            )

        code = main(
            list(argv),
            stdin=FakeStream(stdin, tty=stdin_tty),
            stdout=stdout,
            stderr=stderr,
            environ=environ,
            client_factory=factory,
            read_line=read_line if lines is not None else None,
            getpass=getpass,
        )
        return Result(code, stdout.getvalue(), stderr.getvalue(), prompts, captured)
