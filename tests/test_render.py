from __future__ import annotations

import pytest
from molochai import CAP_NOTICE, QueueStatus

from molochai_cli.console import StatusLine, Style
from molochai_cli.render import CapNoticeFilter, ReplyPrinter, describe_queue
from support import FakeStream


def run_filter(pieces: list[str]) -> tuple[str, bool]:
    f = CapNoticeFilter()
    shown = "".join(f.feed(p) for p in pieces)
    rest, capped = f.finish()
    return shown + rest, capped


@pytest.mark.parametrize(
    ("pieces", "text", "capped"),
    [
        (["Answer", CAP_NOTICE], "Answer", True),
        (["Answer" + CAP_NOTICE], "Answer", True),
        (["Answer", *CAP_NOTICE], "Answer", True),
        (["Answer\n\n[Resp", "onse is too large"], "Answer\n\n[Response is too large", False),
        (["A", CAP_NOTICE, " and more"], "A" + CAP_NOTICE + " and more", False),
        (["Ends with newlines\n\n"], "Ends with newlines\n\n", False),
        ([], "", False),
    ],
)
def test_cap_notice_filter(pieces: list[str], text: str, capped: bool) -> None:
    assert run_filter(pieces) == (text, capped)


def test_filter_holds_back_only_a_possible_prefix() -> None:
    f = CapNoticeFilter()
    assert f.feed("Hello\n") == "Hello"
    assert f.feed("world") == "\nworld"


@pytest.mark.parametrize(
    ("comment", "text"),
    [
        ("queued · position 2 of 3 · waiting 4s", "queued: position 2 of 3, waited 4s"),
        ("queued · position 2", "queued: position 2"),
        ("queued", "queued"),
    ],
)
def test_describe_queue(comment: str, text: str) -> None:
    status = QueueStatus.parse(comment)
    assert status is not None
    assert describe_queue(status) == text


def make_printer(
    *, separate: bool = False, hidden: bool = False, tty: bool = False, color: bool = False
) -> tuple[ReplyPrinter, FakeStream, FakeStream, list[str]]:
    out = FakeStream()
    err = FakeStream(tty=tty)
    notes: list[str] = []
    status = StatusLine(err, enabled=tty, style=Style(False))
    reasoning_out = None if hidden else (err if separate else out)
    printer = ReplyPrinter(
        out=out,
        reasoning_out=reasoning_out,
        reasoning_style=Style(color),
        status=status,
        note=notes.append,
    )
    return printer, out, err, notes


def test_reasoning_then_answer_on_one_stream() -> None:
    printer, out, _, notes = make_printer()
    printer.reasoning("\n\nFirst line\nsecond ")
    printer.reasoning("half\n")
    printer.content("\n\nThe answer")
    printer.content(" is 4.")
    assert printer.finish("stop") is False
    assert out.getvalue() == "| First line\n| second half\n\nThe answer is 4.\n"
    assert notes == []


def test_reasoning_colored() -> None:
    printer, out, _, _ = make_printer(color=True)
    printer.reasoning("Hmm")
    printer.content("Yes")
    printer.finish()
    assert out.getvalue() == "\x1b[2m| \x1b[0m\x1b[2mHmm\x1b[0m\n\nYes\n"


def test_reasoning_on_a_separate_stream() -> None:
    printer, out, err, _ = make_printer(separate=True)
    printer.reasoning("Plan")
    printer.content("Answer")
    printer.finish()
    assert err.getvalue() == "| Plan\n"
    assert out.getvalue() == "Answer\n"


def test_reasoning_after_the_answer_is_ignored() -> None:
    printer, out, _, _ = make_printer()
    printer.content("Answer")
    printer.reasoning("late")
    printer.finish()
    assert out.getvalue() == "Answer\n"


def test_hidden_reasoning_shows_status_on_a_terminal() -> None:
    printer, out, err, _ = make_printer(hidden=True, tty=True)
    printer.reasoning("secret")
    assert "thinking..." in err.getvalue()
    printer.content("Answer")
    printer.finish()
    assert out.getvalue() == "Answer\n"
    assert "secret" not in err.getvalue()
    assert err.getvalue().endswith("\r")


def test_empty_pieces_are_ignored() -> None:
    printer, out, _, _ = make_printer()
    printer.reasoning("")
    printer.reasoning("\n")
    printer.content("")
    printer.content("\n")
    printer.finish()
    assert out.getvalue() == ""


def test_abort_closes_open_lines() -> None:
    printer, _, _, _ = make_printer(separate=True)
    printer.reasoning("half a thought")
    printer.abort()
    printer2, out2, _, _ = make_printer()
    printer2.content("half an answer")
    printer2.abort()
    assert out2.getvalue() == "half an answer\n"


def test_cap_notice_with_trailing_whitespace_is_still_reported() -> None:
    printer, _, _, notes = make_printer()
    printer.content("Answer" + CAP_NOTICE + "\n")
    assert printer.finish("length") is True
    assert len(notes) == 1


def test_length_note() -> None:
    printer, _, _, notes = make_printer()
    printer.content("Cut")
    printer.finish("length")
    assert notes == ["The reply was cut off at the output limit (finish_reason: length)."]


def test_status_line() -> None:
    stream = FakeStream(tty=True)
    status = StatusLine(stream, enabled=True, style=Style(False))
    status.show("a longer message")
    status.show("short")
    assert status.visible
    status.clear()
    status.clear()
    assert not status.visible
    assert stream.getvalue() == (
        "\ra longer message" + "\rshort" + " " * 11 + "\r" + " " * 5 + "\r"
    )


def test_status_line_disabled() -> None:
    stream = FakeStream()
    status = StatusLine(stream, enabled=False, style=Style(True))
    status.show("hidden")
    status.clear()
    assert stream.getvalue() == ""


def test_status_line_is_cut_to_the_terminal_width(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLUMNS", "10")
    stream = FakeStream(tty=True)
    StatusLine(stream, enabled=True, style=Style(False)).show("x" * 50)
    assert stream.getvalue() == "\r" + "x" * 9


def test_control_characters_are_removed_on_a_terminal() -> None:
    out = FakeStream(tty=True)
    printer = ReplyPrinter(
        out=out,
        reasoning_out=out,
        reasoning_style=Style(False),
        status=StatusLine(FakeStream(), enabled=False, style=Style(False)),
        note=lambda text: None,
    )
    printer.reasoning("think\x1b]52;c;ZXZpbA==\x07ing")
    printer.content("a\x1b[2J\x9b31mred\r\nb\tc")
    printer.content("\x1b")  # nothing printable left
    printer.finish()
    assert out.getvalue() == "| think]52;c;ZXZpbA==ing\n\na[2J31mred\nb\tc\n"


def test_control_characters_are_kept_in_pipes() -> None:
    printer, out, _, _ = make_printer()
    printer.content("a\x1b[1mb")
    printer.finish()
    assert out.getvalue() == "a\x1b[1mb\n"
