from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from molochai import CAP_NOTICE

from support import (
    Router,
    Runner,
    completion_body,
    json_response,
    models_response,
    stream_reply,
)


def test_one_exchange_shows_reasoning_then_answer(cli: Runner) -> None:
    router = Router(stream_reply(["Hi", " there."], reasoning=["Let me think.\n", "Done."]))
    result = cli("chat", handler=router, lines=["Hello"], stdin_tty=True)
    assert result.code == 0
    assert result.prompts == ["> ", "> "]
    lines = result.out.splitlines()
    assert lines[0].startswith("Chatting with glm-5.3-flash.")
    assert lines[1:] == ["| Let me think.", "| Done.", "", "Hi there.", ""]
    assert router.chat_bodies()[0]["messages"] == [{"role": "user", "content": "Hello"}]


def test_history_keeps_reasoning_content_as_the_sdk_documents(cli: Runner) -> None:
    router = Router(
        stream_reply(["First answer."], reasoning=["First thought."]),
        stream_reply(["Second answer."], reasoning=[]),
    )
    result = cli("chat", "--system", "Be brief.", handler=router, lines=["One", "Two"])
    assert result.code == 0
    second = router.chat_bodies()[1]["messages"]
    assert second == [
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": "One"},
        {
            "role": "assistant",
            "content": "First answer.",
            "reasoning_content": "First thought.",
        },
        {"role": "user", "content": "Two"},
    ]


def test_cap_notice_is_not_sent_back(cli: Runner) -> None:
    router = Router(
        stream_reply(["Long", CAP_NOTICE], reasoning=[], finish_reason="length"),
        stream_reply(["Ok."], reasoning=[]),
    )
    result = cli("chat", handler=router, lines=["Write a lot", "Shorter please"])
    assert "Response is too large" not in result.out
    assert "output cap" in result.err
    assistant = router.chat_bodies()[1]["messages"][1]
    assert assistant == {"role": "assistant", "content": "Long"}


def test_piped_chat_has_no_banner_or_prompt(cli: Runner) -> None:
    router = Router(stream_reply(["A."], reasoning=[]))
    result = cli("chat", handler=router, stdin="Hello\n")
    assert result.code == 0
    assert result.out == "A.\n"
    assert result.err == ""


def test_hide_reasoning(cli: Runner) -> None:
    router = Router(stream_reply(["A."], reasoning=["hidden"]))
    result = cli("chat", "--hide-reasoning", handler=router, lines=["Hi"])
    assert "hidden" not in result.out
    assert result.out == "A.\n"


def test_reasoning_toggle(cli: Runner) -> None:
    router = Router(
        stream_reply(["A."], reasoning=["shown thought"]),
        stream_reply(["B."], reasoning=["hidden thought"]),
    )
    result = cli(
        "chat",
        handler=router,
        lines=["/reasoning", "One", "/reasoning off", "Two", "/reasoning maybe", "/reasoning on"],
    )
    assert "Reasoning is shown." in result.out
    assert "| shown thought" in result.out
    assert "Reasoning is hidden." in result.out
    assert "hidden thought" not in result.out
    assert "Use /reasoning on or /reasoning off." in result.err
    assert result.out.rstrip().endswith("Reasoning is shown.")


def test_ctrl_c_during_a_reply_keeps_the_session(cli: Runner) -> None:
    router = Router(
        stream_reply(["Partial"], reasoning=[], tail=[], error=KeyboardInterrupt()),
        stream_reply(["Fine."], reasoning=[]),
    )
    result = cli("chat", handler=router, lines=["Long story", "Short one"])
    assert result.code == 0
    assert "Partial\n" in result.out
    assert "Reply stopped" in result.err
    assert result.out.endswith("Fine.\n")
    # The interrupted turn is not part of the conversation.
    assert router.chat_bodies()[1]["messages"] == [{"role": "user", "content": "Short one"}]


def test_ctrl_c_before_the_reply_starts(cli: Runner) -> None:
    router = Router(KeyboardInterrupt(), stream_reply(["Fine."], reasoning=[]))
    result = cli("chat", handler=router, lines=["One", "Two"])
    assert result.code == 0
    assert "Reply stopped" in result.err
    assert result.out.endswith("Fine.\n")


def test_ctrl_c_at_the_prompt_exits_130(cli: Runner) -> None:
    result = cli("chat", handler=Router(), lines=[KeyboardInterrupt()])
    assert result.code == 130
    assert result.out == "\n"


def test_ctrl_d_at_the_prompt_exits_0(cli: Runner) -> None:
    result = cli("chat", handler=Router(), lines=[], stdin_tty=True)
    assert result.code == 0
    assert result.out.endswith("\n")


def test_exit_and_quit(cli: Runner) -> None:
    assert cli("chat", handler=Router(), lines=["/exit", "never sent"]).code == 0
    assert cli("chat", handler=Router(), lines=["/QUIT"]).code == 0


def test_api_error_keeps_the_session(cli: Runner) -> None:
    unavailable = json_response(
        503,
        {
            "error": {
                "type": "model_unavailable",
                "message": "No server.",
                "model": "glm-5.3-flash",
            }
        },
    )
    router = Router(unavailable, stream_reply(["Back."], reasoning=[]))
    result = cli("chat", handler=router, lines=["One", "Two"])
    assert result.code == 0
    assert "glm-5.3-flash is not being served right now" in result.err
    assert "/models lists them, /model <id> switches" in result.err
    assert router.chat_bodies()[1]["messages"] == [{"role": "user", "content": "Two"}]


def test_context_error_in_chat_suggests_clear(cli: Runner) -> None:
    body = {
        "error": {
            "type": "context_length_exceeded",
            "message": "Too long.",
            "estimated_tokens": 70000,
            "context_cap": 65536,
            "bound_by": "server",
        }
    }
    result = cli("chat", handler=Router(json_response(413, body)), lines=["Huge"])
    assert "about 70,000 tokens, limit 65,536 (set by the server serving this model)" in result.err
    assert "/clear" in result.err


def test_help_and_unknown_command(cli: Runner) -> None:
    result = cli("chat", handler=Router(), lines=["/help", "/frobnicate"])
    assert "/model [id]" in result.out
    assert "/save [file]" in result.out
    assert "Unknown command /frobnicate" in result.err


def test_double_slash_sends_a_message_starting_with_slash(cli: Runner) -> None:
    router = Router(stream_reply(["Ok."], reasoning=[]))
    cli("chat", handler=router, lines=["//etc/hosts is a file"])
    assert router.chat_bodies()[0]["messages"][0]["content"] == "/etc/hosts is a file"


def test_blank_lines_are_ignored(cli: Runner) -> None:
    router = Router()
    result = cli("chat", handler=router, lines=["", "   "])
    assert result.code == 0
    assert router.requests == []


def test_model_show_and_switch(cli: Runner) -> None:
    router = Router(stream_reply(["Ok."], reasoning=[]), models=models_response())
    result = cli(
        "chat",
        handler=router,
        lines=["/model", "/model llama-3.3-70b-instruct-abliterated", "Hi", "/model"],
    )
    assert "Model: glm-5.3-flash" in result.out
    assert "Switched to llama-3.3-70b-instruct-abliterated." in result.out
    assert router.chat_bodies()[0]["model"] == "llama-3.3-70b-instruct-abliterated"
    assert result.out.rstrip().endswith("Model: llama-3.3-70b-instruct-abliterated")


def test_model_unknown_is_refused(cli: Runner) -> None:
    router = Router(models=models_response())
    result = cli("chat", handler=router, lines=["/model nope", "/model"])
    assert "Unknown model 'nope'" in result.err
    assert "Model: glm-5.3-flash" in result.out


def test_model_unavailable_switches_with_a_warning(cli: Runner) -> None:
    router = Router(models=models_response())
    result = cli("chat", handler=router, lines=["/model gemma4-26b-a4b-qat"])
    assert "Switched to gemma4-26b-a4b-qat." in result.out
    assert "warning: gemma4-26b-a4b-qat is not being served right now" in result.err


def test_model_list_error(cli: Runner) -> None:
    router = Router(
        models=json_response(402, {"error": {"type": "no_active_plan", "message": "x"}})
    )
    result = cli("chat", handler=router, lines=["/model glm-5.3-flash", "/models"])
    assert result.err.count("No active plan and no credit") == 2


def test_models_table_marks_the_current_model(cli: Runner) -> None:
    result = cli("chat", handler=Router(models=models_response()), lines=["/models"])
    lines = result.out.splitlines()
    assert lines[0].split() == ["ID", "NAME", "AVAILABLE"]
    assert lines[1].startswith("glm-5.3-flash *")
    assert "gemma4-26b-a4b-qat" in lines[3]
    assert lines[3].rstrip().endswith("no")
    assert "* the model this chat uses" in result.out


def test_models_empty(cli: Runner) -> None:
    result = cli("chat", handler=Router(models=models_response([])), lines=["/models"])
    assert "The server returned no models." in result.out


def test_system_show_set_clear(cli: Runner) -> None:
    router = Router(stream_reply(["A."], reasoning=[]), stream_reply(["B."], reasoning=[]))
    result = cli(
        "chat",
        handler=router,
        lines=["/system", "/system You are terse.", "/system", "One", "/system --clear", "Two"],
    )
    assert "No system prompt." in result.out
    assert "System prompt: You are terse." in result.out
    assert "System prompt removed." in result.out
    first, second = router.chat_bodies()
    assert first["messages"][0] == {"role": "system", "content": "You are terse."}
    assert second["messages"][0]["role"] == "user"


def test_clear_resets_the_conversation(cli: Runner) -> None:
    router = Router(stream_reply(["A."], reasoning=[]), stream_reply(["B."], reasoning=[]))
    result = cli("chat", handler=router, lines=["One", "/clear", "Two"])
    assert "Started a new conversation." in result.out
    assert router.chat_bodies()[1]["messages"] == [{"role": "user", "content": "Two"}]


def test_usage_totals(cli: Runner) -> None:
    router = Router(
        stream_reply(["A."], reasoning=[], prompt_tokens=10, completion_tokens=5),
        stream_reply(["B."], reasoning=[], prompt_tokens=20, completion_tokens=7),
    )
    result = cli("chat", handler=router, lines=["/usage", "One", "Two", "/usage"])
    assert "No replies yet." in result.out
    assert "This session: 2 replies, 42 tokens (prompt 30, completion 12)." in result.out
    assert "Last reply: 27 tokens (prompt 20, completion 7)." in result.out
    assert "Rate limit: 59 of 60 requests left this minute." in result.out


def test_usage_singular(cli: Runner) -> None:
    router = Router(stream_reply(["A."], reasoning=[]))
    result = cli("chat", handler=router, lines=["One", "/usage"])
    assert "This session: 1 reply, 8 tokens" in result.out


def test_no_stream_mode(cli: Runner) -> None:
    router = Router(json_response(200, completion_body("Plain answer.", reasoning="Thought.")))
    result = cli("chat", "--no-stream", handler=router, lines=["Hi", "/usage"])
    assert "stream" not in router.chat_bodies()[0]
    assert "| Thought.\n\nPlain answer.\n" in result.out
    assert "This session: 1 reply, 10 tokens" in result.out


def test_no_stream_inline_think_and_cap(cli: Runner) -> None:
    content = "<think>Inline plan.</think>\n\nThe answer." + CAP_NOTICE
    router = Router(
        json_response(200, completion_body(content, reasoning=None, finish_reason="length")),
        json_response(200, completion_body("Next.", reasoning=None)),
    )
    result = cli("chat", "--no-stream", handler=router, lines=["Hi", "More"])
    assert "| Inline plan.\n\nThe answer.\n" in result.out
    assert "Response is too large" not in result.out
    assert "output cap" in result.err
    # Sent back as the SDK's to_param() gives it, minus the cap notice.
    assistant = router.chat_bodies()[1]["messages"][1]
    assert assistant == {
        "role": "assistant",
        "content": "<think>Inline plan.</think>\n\nThe answer.",
    }


def test_no_stream_524_suggests_streaming(cli: Runner) -> None:
    router = Router(httpx.Response(524, text="<html>A timeout occurred</html>"))
    result = cli("chat", "--no-stream", handler=router, lines=["Hi"])
    assert "HTTP 524" in result.err
    assert "drop --no-stream" in result.err


def test_empty_choices_warns(cli: Runner) -> None:
    body = completion_body()
    body["choices"] = []
    result = cli("chat", "--no-stream", handler=Router(json_response(200, body)), lines=["Hi"])
    assert "The server returned no reply." in result.err


# -- /save ------------------------------------------------------------------------------------


@pytest.fixture
def in_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_save_writes_markdown(cli: Runner, in_tmp: Path) -> None:
    router = Router(
        stream_reply(["First answer."], reasoning=["A thought."]),
        stream_reply(["Long", CAP_NOTICE], reasoning=[], finish_reason="length"),
        models=models_response(),
    )
    result = cli(
        "chat",
        "--system",
        "Be brief.",
        handler=router,
        lines=["One", "/model llama-3.3-70b-instruct-abliterated", "Two", "/save chat.md"],
    )
    assert "Saved to chat.md" in result.out
    assert "Check for secrets before sharing" in result.out
    text = (in_tmp / "chat.md").read_text(encoding="utf-8")
    assert text.startswith("# MolochAI chat\n")
    assert "- Models: glm-5.3-flash, llama-3.3-70b-instruct-abliterated" in text
    assert "  > Be brief." in text
    assert "## You\n\nOne\n\n## glm-5.3-flash\n" in text
    assert "<details><summary>Reasoning</summary>\n\nA thought.\n\n</details>" in text
    assert "First answer." in text
    assert "## llama-3.3-70b-instruct-abliterated\n\nLong\n" in text
    assert "*The reply stopped at the plan's output cap.*" in text
    assert "Response is too large" not in text


def test_save_default_name(cli: Runner, in_tmp: Path) -> None:
    router = Router(stream_reply(["A."], reasoning=[]))
    result = cli("chat", handler=router, lines=["One", "/save"])
    saved = list(in_tmp.glob("molochai-chat-*.md"))
    assert len(saved) == 1
    assert f"Saved to {saved[0].name}" in result.out
    assert "- Model: glm-5.3-flash" in saved[0].read_text(encoding="utf-8")


def test_save_with_nothing_to_save(cli: Runner, in_tmp: Path) -> None:
    result = cli("chat", handler=Router(), lines=["/save x.md"])
    assert "Nothing to save yet." in result.out
    assert not (in_tmp / "x.md").exists()


def test_save_refuses_to_overwrite_when_not_interactive(cli: Runner, in_tmp: Path) -> None:
    (in_tmp / "chat.md").write_text("keep me", encoding="utf-8")
    router = Router(stream_reply(["A."], reasoning=[]))
    result = cli("chat", handler=router, lines=["One", "/save chat.md"])
    assert "already exists" in result.err
    assert (in_tmp / "chat.md").read_text(encoding="utf-8") == "keep me"


@pytest.mark.parametrize(("answer", "overwritten"), [("y", True), ("n", False), ("", False)])
def test_save_asks_before_overwriting(
    cli: Runner, in_tmp: Path, answer: str, overwritten: bool
) -> None:
    (in_tmp / "chat.md").write_text("keep me", encoding="utf-8")
    router = Router(stream_reply(["A."], reasoning=[]))
    result = cli("chat", handler=router, lines=["One", "/save chat.md", answer], stdin_tty=True)
    assert "chat.md exists. Overwrite it? [y/N] " in result.prompts
    text = (in_tmp / "chat.md").read_text(encoding="utf-8")
    assert (text != "keep me") is overwritten
    if not overwritten:
        assert "Not saved." in result.out


def test_save_confirmation_interrupted(cli: Runner, in_tmp: Path) -> None:
    (in_tmp / "chat.md").write_text("keep me", encoding="utf-8")
    router = Router(stream_reply(["A."], reasoning=[]))
    result = cli(
        "chat",
        handler=router,
        lines=["One", "/save chat.md", KeyboardInterrupt(), "/exit"],
        stdin_tty=True,
    )
    assert result.code == 0
    assert "Not saved." in result.out


def test_save_into_a_directory_or_missing_folder(cli: Runner, in_tmp: Path) -> None:
    (in_tmp / "folder").mkdir()
    router = Router(stream_reply(["A."], reasoning=[]))
    result = cli("chat", handler=router, lines=["One", "/save folder", "/save missing/chat.md"])
    assert "folder is a directory" in result.err
    assert "Could not save to" in result.err


def test_ctrl_c_during_a_slash_command_keeps_the_session(cli: Runner) -> None:
    def interrupt(request: httpx.Request) -> httpx.Response:
        raise KeyboardInterrupt

    router = Router(stream_reply(["After."], reasoning=[]))
    router.models = None
    result = cli(
        "chat",
        handler=lambda request: (
            interrupt(request) if request.url.path.endswith("/models") else router(request)
        ),
        lines=["/models", "Hi"],
    )
    assert result.code == 0
    assert "Command stopped." in result.err
    assert result.out.endswith("After.\n")
