from __future__ import annotations

import io
import sys

import pytest

import molochai_cli.console as console_module
from molochai_cli.console import (
    Console,
    Style,
    _line_reader,
    colors_wanted,
    enable_vt,
    is_tty,
    prepare_stdio,
)
from support import FakeStream


class BrokenIsatty:
    def isatty(self) -> bool:
        raise ValueError("closed")


def test_is_tty() -> None:
    assert is_tty(FakeStream(tty=True))
    assert not is_tty(FakeStream())
    assert not is_tty(object())
    assert not is_tty(BrokenIsatty())


def test_style() -> None:
    assert Style(False).red("x") == "x"
    on = Style(True)
    assert on.red("x") == "\x1b[31mx\x1b[0m"
    assert on.yellow("x") == "\x1b[33mx\x1b[0m"
    assert on.green("x") == "\x1b[32mx\x1b[0m"
    assert on.bold("x") == "\x1b[1mx\x1b[0m"
    assert on.dim("") == ""


def test_colors_wanted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(console_module, "enable_vt", lambda stream: True)
    tty = FakeStream(tty=True)
    assert colors_wanted(tty, no_color=False, environ={})
    assert not colors_wanted(tty, no_color=True, environ={})
    assert not colors_wanted(tty, no_color=False, environ={"NO_COLOR": "x"})
    assert colors_wanted(tty, no_color=False, environ={"NO_COLOR": ""})
    assert not colors_wanted(tty, no_color=False, environ={"TERM": "dumb"})
    assert not colors_wanted(FakeStream(), no_color=False, environ={})


def test_colors_off_when_vt_cannot_be_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(console_module, "enable_vt", lambda stream: False)
    assert not colors_wanted(FakeStream(tty=True), no_color=False, environ={})


def test_enable_vt_outside_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert enable_vt(FakeStream()) is True


@pytest.mark.skipif(sys.platform != "win32", reason="Windows console API")
def test_enable_vt_on_something_that_is_not_a_console() -> None:
    assert enable_vt(FakeStream(tty=True)) is False  # no file descriptor


def test_piped_line_reader() -> None:
    stdin = FakeStream("first\r\nsecond\n")
    stderr = FakeStream()
    read = _line_reader(stdin, FakeStream(), stderr)
    assert read("> ") == "first"
    assert read("> ") == "second"
    with pytest.raises(EOFError):
        read("> ")
    assert stderr.getvalue() == ""  # no prompt when nobody is typing


def test_terminal_line_reader_without_real_stdio() -> None:
    stdin = FakeStream("typed\n", tty=True)
    stderr = FakeStream()
    read = _line_reader(stdin, FakeStream(tty=True), stderr)
    assert read("> ") == "typed"
    assert stderr.getvalue() == "> "


def test_real_terminal_uses_input(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_stdin = FakeStream(tty=True)
    fake_stdout = FakeStream(tty=True)
    monkeypatch.setattr(sys, "stdin", fake_stdin)
    monkeypatch.setattr(sys, "stdout", fake_stdout)
    assert _line_reader(fake_stdin, fake_stdout, FakeStream()) is input


def test_console_messages() -> None:
    out, err = FakeStream(), FakeStream()
    console = Console(stdin=FakeStream(), stdout=out, stderr=err, environ={})
    console.out("hello")
    console.error("bad", ["try this"])
    console.warn("careful")
    console.note("fyi")
    assert out.getvalue() == "hello\n"
    assert err.getvalue() == "error: bad\n  try this\nwarning: careful\nnote: fyi\n"
    assert not console.interactive


def test_prepare_stdio_replaces_unencodable_characters() -> None:
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="ascii")
    prepare_stdio(io.TextIOWrapper(io.BytesIO(b""), encoding="ascii"), stream, FakeStream())
    stream.write("café")
    stream.flush()
    if sys.platform == "win32" and not sys.flags.utf8_mode:
        assert raw.getvalue() == "café".encode()  # pipes switched to UTF-8
    else:
        assert raw.getvalue() == b"caf?"


def test_prepare_stdio_ignores_streams_that_cannot_change() -> None:
    stream = io.TextIOWrapper(io.BytesIO(b"data"), encoding="utf-8")
    stream.read()
    prepare_stdio(stream, FakeStream(), FakeStream())  # reconfigure after reading fails quietly


def test_piped_line_reader_drops_a_leading_byte_order_mark() -> None:
    read = _line_reader(FakeStream("﻿hello\n﻿kept\n"), FakeStream(), FakeStream())
    assert read("> ") == "hello"
    assert read("> ") == "﻿kept"  # only the start of the input
