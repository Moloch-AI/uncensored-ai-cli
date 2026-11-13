from __future__ import annotations

import json

import httpx
import pytest
from molochai import CAP_NOTICE

import molochai_cli.console as console_module
from support import Router, Runner, chunk, stream_reply, usage_chunk


def test_prints_only_the_answer(cli: Runner) -> None:
    router = Router(stream_reply(["Hello", " there."], reasoning=["Secret plan."]))
    result = cli("ask", "Hi", handler=router)
    assert result.code == 0
    assert result.out == "Hello there.\n"
    assert result.err == ""
    body = router.chat_bodies()[0]
    assert body["model"] == "glm-5.3-flash"
    assert body["stream"] is True
    assert body["messages"] == [{"role": "user", "content": "Hi"}]
    request = router.requests[0]
    assert request.headers["authorization"] == "Bearer test-key-abcdefghijklmnop"
    assert request.headers["user-agent"].startswith("molochai-cli/0.1.0 molochai-python/")


def test_answer_keeps_its_own_trailing_newline(cli: Runner) -> None:
    result = cli("ask", "Hi", handler=Router(stream_reply(["Line one\n"])))
    assert result.out == "Line one\n"


def test_piped_stdin_is_added_after_the_prompt(cli: Runner) -> None:
    router = Router(stream_reply())
    result = cli("ask", "Summarize this", handler=router, stdin="# Notes\nfirst point\n")
    assert result.code == 0
    content = router.chat_bodies()[0]["messages"][0]["content"]
    assert content == "Summarize this\n\n# Notes\nfirst point\n"


def test_stdin_alone_is_the_prompt(cli: Runner) -> None:
    router = Router(stream_reply())
    assert cli("ask", handler=router, stdin="only stdin").code == 0
    assert router.chat_bodies()[0]["messages"][0]["content"] == "only stdin"


def test_terminal_stdin_is_not_read(cli: Runner) -> None:
    router = Router(stream_reply())
    assert cli("ask", "Hi", handler=router, stdin="typed ahead", stdin_tty=True).code == 0
    assert router.chat_bodies()[0]["messages"][0]["content"] == "Hi"


def test_no_stdin_flag_ignores_piped_input(cli: Runner) -> None:
    router = Router(stream_reply())
    assert cli("ask", "Hi", "--no-stdin", handler=router, stdin="loop input").code == 0
    assert router.chat_bodies()[0]["messages"][0]["content"] == "Hi"


def test_nothing_to_ask_is_a_usage_error(cli: Runner) -> None:
    result = cli("ask", handler=Router(), stdin="   \n")
    assert result.code == 2
    assert "Nothing to ask" in result.err


def test_system_and_model(cli: Runner) -> None:
    router = Router(stream_reply())
    result = cli(
        "ask", "Hi", "--system", "Be terse.", "--model", "gemma4-26b-a4b-qat", handler=router
    )
    assert result.code == 0
    body = router.chat_bodies()[0]
    assert body["model"] == "gemma4-26b-a4b-qat"
    assert body["messages"][0] == {"role": "system", "content": "Be terse."}


def test_json_prints_the_final_completion(cli: Runner) -> None:
    router = Router(stream_reply(["Hello", " there."], reasoning=["Plan."]))
    result = cli("ask", "Hi", "--json", handler=router)
    assert result.code == 0
    data = json.loads(result.out)
    assert data["object"] == "chat.completion"
    message = data["choices"][0]["message"]
    assert message["content"] == "Hello there."
    assert message["reasoning_content"] == "Plan."
    assert data["choices"][0]["finish_reason"] == "stop"
    assert data["usage"]["total_tokens"] == 8
    assert router.chat_bodies()[0]["stream"] is True  # streamed even for --json


def test_show_reasoning_goes_to_stderr(cli: Runner) -> None:
    router = Router(stream_reply(["Answer."], reasoning=["Step one.\n", "Step two."]))
    result = cli("ask", "Hi", "--show-reasoning", handler=router)
    assert result.out == "Answer.\n"
    assert result.err == "| Step one.\n| Step two.\n"


def test_cap_notice_is_a_note_not_part_of_the_answer(cli: Runner) -> None:
    pieces = ["Long answer", *CAP_NOTICE]  # the notice split into single characters
    router = Router(stream_reply(pieces, finish_reason="length"))
    result = cli("ask", "Hi", handler=router)
    assert result.code == 0
    assert result.out == "Long answer\n"
    assert "Response is too large" not in result.out
    assert "note: The reply stopped at your plan's output cap" in result.err
    assert "utm_campaign=uncensored-ai-cli" in result.err


def test_length_without_notice_is_reported(cli: Runner) -> None:
    result = cli("ask", "Hi", handler=Router(stream_reply(["Cut"], finish_reason="length")))
    assert result.out == "Cut\n"
    assert "cut off at the output limit" in result.err


def test_queue_progress_on_a_terminal(cli: Runner) -> None:
    router = Router(
        stream_reply(
            ["Done."],
            comments=[": queued · position 2 of 3 · waiting 1s", ": ka"],
        )
    )
    result = cli("ask", "Hi", handler=router, stderr_tty=True)
    assert result.out == "Done.\n"
    assert "waiting for glm-5.3-flash..." in result.err
    assert "queued: position 2 of 3, waited 1s" in result.err
    assert result.err.endswith("\r")  # the status line was erased


def test_queue_progress_is_silent_when_stderr_is_not_a_terminal(cli: Runner) -> None:
    router = Router(stream_reply(["Done."], comments=[": queued · position 1 of 1 · waiting 0s"]))
    result = cli("ask", "Hi", handler=router)
    assert result.err == ""


def test_hidden_reasoning_shows_thinking_status(cli: Runner) -> None:
    result = cli("ask", "Hi", handler=Router(stream_reply()), stderr_tty=True)
    assert "thinking..." in result.err
    assert "Thinking." not in result.err + result.out


def test_ctrl_c_mid_reply_exits_130(cli: Runner) -> None:
    router = Router(stream_reply(["Partial"], tail=[], error=KeyboardInterrupt()))
    result = cli("ask", "Hi", handler=router)
    assert result.code == 130
    assert result.out == "Partial\n"


def test_stream_error_after_content(cli: Runner) -> None:
    error_event = {"error": {"type": "preempted", "message": "Server reclaimed."}}
    router = Router(stream_reply(["Partial"], tail=[error_event, "[DONE]"]))
    result = cli("ask", "Hi", handler=router)
    assert result.code == 1
    assert result.out == "Partial\n"
    assert "preempted" in result.err
    assert "Try again in a minute" in result.err


def test_no_color_when_not_a_terminal(cli: Runner, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(console_module, "enable_vt", lambda stream: True)
    router = Router(stream_reply(["A"], reasoning=["R"]))
    result = cli("ask", "Hi", "--show-reasoning", handler=router)
    assert "\x1b[" not in result.err


@pytest.mark.parametrize(
    ("args", "env", "colored"),
    [
        ((), {}, True),
        (("--no-color",), {}, False),
        ((), {"NO_COLOR": "1"}, False),
        ((), {"NO_COLOR": ""}, True),
        ((), {"TERM": "dumb"}, False),
    ],
)
def test_color_rules(
    cli: Runner,
    monkeypatch: pytest.MonkeyPatch,
    args: tuple[str, ...],
    env: dict[str, str],
    colored: bool,
) -> None:
    monkeypatch.setattr(console_module, "enable_vt", lambda stream: True)
    router = Router(stream_reply(["A"], reasoning=["R"]))
    result = cli("ask", "Hi", "--show-reasoning", *args, handler=router, stderr_tty=True, env=env)
    assert ("\x1b[2m" in result.err) is colored


def test_global_no_color_before_the_command(cli: Runner, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(console_module, "enable_vt", lambda stream: True)
    router = Router(stream_reply(["A"], reasoning=["R"]))
    result = cli("--no-color", "ask", "Hi", "--show-reasoning", handler=router, stderr_tty=True)
    assert "\x1b[" not in result.err


def test_reasoning_only_reply(cli: Runner) -> None:
    router = Router(stream_reply([], reasoning=["Only thoughts."]))
    result = cli("ask", "Hi", "--show-reasoning", handler=router)
    assert result.code == 0
    assert result.out == ""
    assert result.err == "| Only thoughts.\n"


def test_usage_chunk_without_choices_is_handled(cli: Runner) -> None:
    router = Router(
        stream_reply(["A"], tail=[usage_chunk(), chunk(finish_reason="stop"), "[DONE]"])
    )
    assert cli("ask", "Hi", handler=router).out == "A\n"


def test_connection_error(cli: Runner) -> None:
    router = Router(httpx.ConnectError("refused"))
    result = cli("ask", "Hi", handler=router)
    assert result.code == 1
    assert "Could not reach https://api.example.test/api/v1" in result.err


def test_byte_order_mark_is_dropped_from_piped_text(cli: Runner) -> None:
    router = Router(stream_reply())
    assert cli("ask", "Echo", handler=router, stdin="﻿café").code == 0
    assert router.chat_bodies()[0]["messages"][0]["content"] == "Echo\n\ncafé"


def test_reading_stdin_is_announced_on_a_terminal(cli: Runner) -> None:
    result = cli("ask", "Hi", handler=Router(stream_reply()), stdin="x", stderr_tty=True)
    assert "reading stdin (--no-stdin skips it)..." in result.err
