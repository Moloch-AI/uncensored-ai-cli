"""Terminal output: streams, colors, the transient status line and line input.

Colors are used only when the stream is a terminal, ``NO_COLOR`` is unset or empty, ``TERM`` is
not ``dumb`` and ``--no-color`` was not given. On Windows 10 and later, ANSI escape processing is
switched on for the console; if that fails, colors stay off.
"""

from __future__ import annotations

import contextlib
import getpass as getpass_module
import io
import os
import shutil
import sys
from collections.abc import Callable, Mapping
from typing import TextIO

__all__ = [
    "Console",
    "StatusLine",
    "Style",
    "colors_wanted",
    "enable_vt",
    "is_tty",
    "strip_bom",
]

_ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004


def is_tty(stream: object) -> bool:
    """``stream.isatty()``, treating missing or failing ``isatty`` as ``False``."""
    isatty = getattr(stream, "isatty", None)
    if isatty is None:
        return False
    try:
        return bool(isatty())
    except (OSError, ValueError):
        return False


def enable_vt(stream: TextIO) -> bool:
    """Make sure the terminal behind ``stream`` interprets ANSI escapes.

    Always true outside Windows. On Windows, turns on virtual terminal processing for the console
    (Windows 10 1511 and later); returns ``False`` if the stream is not a console or the call
    fails, in which case colors stay off.
    """
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        handle = msvcrt.get_osfhandle(stream.fileno())
        kernel32 = ctypes.windll.kernel32
        mode = wintypes.DWORD()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        if mode.value & _ENABLE_VIRTUAL_TERMINAL_PROCESSING:
            return True
        return bool(
            kernel32.SetConsoleMode(handle, mode.value | _ENABLE_VIRTUAL_TERMINAL_PROCESSING)
        )
    except (AttributeError, OSError, ValueError):
        return False


def colors_wanted(stream: TextIO, *, no_color: bool, environ: Mapping[str, str]) -> bool:
    """Whether to color output written to ``stream``."""
    if no_color or environ.get("NO_COLOR", ""):
        return False
    if environ.get("TERM") == "dumb":
        return False
    if not is_tty(stream):
        return False
    return enable_vt(stream)


class Style:
    """ANSI styling that turns into plain text when disabled."""

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        if not self.enabled or not text:
            return text
        return f"\x1b[{code}m{text}\x1b[0m"

    def bold(self, text: str) -> str:
        return self._wrap("1", text)

    def dim(self, text: str) -> str:
        return self._wrap("2", text)

    def red(self, text: str) -> str:
        return self._wrap("31", text)

    def yellow(self, text: str) -> str:
        return self._wrap("33", text)

    def green(self, text: str) -> str:
        return self._wrap("32", text)


class StatusLine:
    """A single transient line on a terminal (queue position, "thinking...").

    It is redrawn in place with a carriage return and erased with spaces, so it works without
    ANSI support. When the stream is not a terminal nothing is written: scripts and log files
    never see it.
    """

    def __init__(self, stream: TextIO, *, enabled: bool, style: Style) -> None:
        self.stream = stream
        self.enabled = enabled
        self.style = style
        self._width = 0

    @property
    def visible(self) -> bool:
        return self._width > 0

    def show(self, text: str) -> None:
        if not self.enabled:
            return
        columns = shutil.get_terminal_size((80, 24)).columns
        text = text[: max(1, columns - 1)]
        padding = " " * max(0, self._width - len(text))
        self.stream.write("\r" + self.style.dim(text) + padding)
        self.stream.flush()
        self._width = len(text)

    def clear(self) -> None:
        if not self._width:
            return
        self.stream.write("\r" + " " * self._width + "\r")
        self.stream.flush()
        self._width = 0


def _line_reader(stdin: TextIO, stdout: TextIO, stderr: TextIO) -> Callable[[str], str]:
    """Return a function that shows a prompt and reads one line.

    Raises ``EOFError`` at end of input and ``KeyboardInterrupt`` on Ctrl+C. Interactive use
    goes through :func:`input` (with ``readline`` line editing where available); piped input is
    read line by line without a prompt.
    """
    interactive = is_tty(stdin)
    if interactive and stdin is sys.stdin and stdout is sys.stdout and is_tty(stdout):
        with contextlib.suppress(ImportError):
            import readline  # noqa: F401  (line editing and history for input() on POSIX)
        return input

    first = True

    def read(prompt: str) -> str:
        nonlocal first
        if interactive:
            stderr.write(prompt)
            stderr.flush()
        line = stdin.readline()
        if not line:
            raise EOFError
        if first:
            line = strip_bom(line)
            first = False
        return line.rstrip("\r\n")

    return read


def strip_bom(text: str) -> str:
    """Drop a leading byte order mark. Windows PowerShell and some editors add one to UTF-8
    text; left in place it would end up in the message (or in a key read with --stdin)."""
    return text[1:] if text.startswith("﻿") else text


class Console:
    """The streams a command writes to, with styles and line input attached."""

    def __init__(
        self,
        *,
        stdin: TextIO,
        stdout: TextIO,
        stderr: TextIO,
        no_color: bool = False,
        environ: Mapping[str, str] | None = None,
        read_line: Callable[[str], str] | None = None,
        getpass: Callable[[str], str] | None = None,
    ) -> None:
        env = os.environ if environ is None else environ
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr
        self.out_style = Style(colors_wanted(stdout, no_color=no_color, environ=env))
        self.err_style = Style(colors_wanted(stderr, no_color=no_color, environ=env))
        self.status = StatusLine(stderr, enabled=is_tty(stderr), style=self.err_style)
        self.read_line = read_line or _line_reader(stdin, stdout, stderr)
        self.getpass = getpass or getpass_module.getpass

    @property
    def interactive(self) -> bool:
        """True when a person is typing: stdin is a terminal."""
        return is_tty(self.stdin)

    def out(self, text: str = "") -> None:
        """Write a line to stdout."""
        self.status.clear()
        self.stdout.write(text + "\n")
        self.stdout.flush()

    def err(self, text: str = "") -> None:
        """Write a line to stderr."""
        self.status.clear()
        self.stderr.write(text + "\n")
        self.stderr.flush()

    def error(self, message: str, hints: list[str] | None = None) -> None:
        self.err(f"{self.err_style.red('error:')} {message}")
        for hint in hints or []:
            self.err(f"  {hint}")

    def warn(self, message: str) -> None:
        self.err(f"{self.err_style.yellow('warning:')} {message}")

    def note(self, message: str) -> None:
        self.err(f"{self.err_style.yellow('note:')} {message}")


def prepare_stdio(stdin: TextIO, stdout: TextIO, stderr: TextIO) -> None:
    """Avoid encoding crashes on the real standard streams.

    On Windows, a pipe or file uses the ANSI code page unless UTF-8 mode is on, so model output
    with characters outside it would raise ``UnicodeEncodeError``. Pipes and files are switched
    to UTF-8 there (unless ``PYTHONIOENCODING`` is set), and characters that still cannot be
    encoded or decoded are replaced instead of crashing.
    """
    switch_to_utf8 = (
        sys.platform == "win32" and not sys.flags.utf8_mode and "PYTHONIOENCODING" not in os.environ
    )
    for stream in (stdin, stdout, stderr):
        if not isinstance(stream, io.TextIOWrapper):
            continue
        try:
            if switch_to_utf8 and not is_tty(stream):
                stream.reconfigure(encoding="utf-8", errors="replace")
            else:
                stream.reconfigure(errors="replace")
        except (OSError, ValueError):
            pass
