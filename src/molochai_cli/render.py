"""Printing a reply: reasoning, the answer, the output-cap notice and queue progress."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, TextIO

from molochai import (
    CAP_NOTICE,
    ChatCompletion,
    MolochAI,
    QueueStatus,
    has_cap_notice,
    split_think,
    strip_cap_notice,
)

from .console import StatusLine, Style, is_tty
from .links import PRICING_URL

__all__ = ["CapNoticeFilter", "ReplyPrinter", "describe_queue", "fetch_reply", "terminal_safe"]

REASONING_GUTTER = "| "

_CONTROL_CHARACTERS = dict.fromkeys([*range(0x09), *range(0x0B, 0x20), 0x7F, *range(0x80, 0xA0)])


def terminal_safe(text: str) -> str:
    """Remove control characters except newline and tab.

    Model output is untrusted. Written to a terminal as-is, escape sequences in it could move
    the cursor, rewrite earlier lines, change the window title or set the clipboard. Text that
    goes to a pipe or a file is left unchanged.
    """
    return text.translate(_CONTROL_CHARACTERS)


CAP_NOTE = (
    "The reply stopped at your plan's output cap. Ask for less, or see the limits per plan: "
    + PRICING_URL
)
LENGTH_NOTE = "The reply was cut off at the output limit (finish_reason: length)."


class CapNoticeFilter:
    """Keeps the gateway's output-cap notice out of streamed answer text.

    The notice is appended to the content when a reply stops at the plan's output cap. While
    streaming, text that could be the start of the notice is held back until it is clear whether
    the notice follows; :meth:`finish` drops it if it did.
    """

    def __init__(self) -> None:
        self._pending = ""

    def feed(self, text: str) -> str:
        """Add streamed text; return the part that is safe to print now."""
        buffer = self._pending + text
        keep = 0
        for size in range(min(len(buffer), len(CAP_NOTICE)), 0, -1):
            if buffer.endswith(CAP_NOTICE[:size]):
                keep = size
                break
        self._pending = buffer[len(buffer) - keep :]
        return buffer[: len(buffer) - keep]

    def finish(self) -> tuple[str, bool]:
        """End of the answer: return the rest of the text and whether the notice was there."""
        pending, self._pending = self._pending, ""
        if has_cap_notice(pending):
            return strip_cap_notice(pending), True
        return pending, False


def describe_queue(status: QueueStatus) -> str:
    """``queued: position 2 of 3, waited 4s`` from a queue comment."""
    if status.position is None:
        return status.raw
    text = f"queued: position {status.position}"
    if status.waiting is not None:
        text += f" of {status.waiting}"
    if status.waited_seconds is not None:
        text += f", waited {status.waited_seconds:.0f}s"
    return text


class ReplyPrinter:
    """Writes one reply as it arrives.

    Reasoning goes to ``reasoning_out`` with a ``| `` gutter, dimmed when colors are on. With
    ``reasoning_out=None`` it is hidden and a transient "thinking..." status is shown instead.
    The answer goes to ``out``; the cap notice is reported through ``note`` instead of being
    printed as part of the answer. Control characters are removed from text written to a
    terminal (see :func:`terminal_safe`).
    """

    def __init__(
        self,
        *,
        out: TextIO,
        reasoning_out: TextIO | None,
        reasoning_style: Style,
        status: StatusLine,
        note: Callable[[str], None],
    ) -> None:
        self.out = out
        self.reasoning_out = reasoning_out
        self.reasoning_style = reasoning_style
        self.status = status
        self.note = note
        self._clean_out = is_tty(out)
        self._clean_reasoning = reasoning_out is not None and is_tty(reasoning_out)
        self._filter = CapNoticeFilter()
        self._answer_started = False
        self._answer_line_open = False
        self._reasoning_started = False
        self._reasoning_line_open = False
        self._reasoning_at_line_start = True
        self.answer_parts: list[str] = []

    @property
    def wrote_answer(self) -> bool:
        return self._answer_started

    # -- reasoning ------------------------------------------------------------------------

    def reasoning(self, text: str) -> None:
        if not text:
            return
        if self.reasoning_out is None or self._answer_started:
            if not self._answer_started:
                self.status.show("thinking...")
            return
        if self._clean_reasoning:
            text = terminal_safe(text)
        if not self._reasoning_started:
            text = text.lstrip("\r\n")
            if not text:
                return
            self._reasoning_started = True
        self.status.clear()
        pieces: list[str] = []
        for part in text.splitlines(keepends=True):
            if self._reasoning_at_line_start:
                pieces.append(self.reasoning_style.dim(REASONING_GUTTER))
            line = part.rstrip("\r\n")
            pieces.append(self.reasoning_style.dim(line))
            if line != part:
                pieces.append("\n")
                self._reasoning_at_line_start = True
            else:
                self._reasoning_at_line_start = False
        self.reasoning_out.write("".join(pieces))
        self.reasoning_out.flush()
        self._reasoning_line_open = not self._reasoning_at_line_start

    def _end_reasoning(self, *, before_answer: bool) -> None:
        if not self._reasoning_started or self.reasoning_out is None:
            return
        if self._reasoning_line_open:
            self.reasoning_out.write("\n")
            self._reasoning_line_open = False
            self._reasoning_at_line_start = True
        if before_answer and self.reasoning_out is self.out:
            self.reasoning_out.write("\n")  # a blank line between reasoning and answer
        self.reasoning_out.flush()
        self._reasoning_started = False

    # -- answer ---------------------------------------------------------------------------

    def content(self, text: str) -> None:
        if not text:
            return
        self.answer_parts.append(text)
        self._write_answer(self._filter.feed(text))

    def _write_answer(self, text: str) -> None:
        if self._clean_out:
            text = terminal_safe(text)
        if not text:
            return
        if not self._answer_started:
            text = text.lstrip("\r\n")
            if not text:
                return
            self.status.clear()
            self._end_reasoning(before_answer=True)
            self._answer_started = True
        self.status.clear()
        self.out.write(text)
        self.out.flush()
        self._answer_line_open = not text.endswith("\n")

    def finish(self, finish_reason: str | None = None) -> bool:
        """End of the reply. Returns ``True`` if it stopped at the output cap."""
        rest, capped = self._filter.finish()
        if rest:
            self._write_answer(rest)
        self.status.clear()
        self._end_reasoning(before_answer=False)
        if self._answer_line_open:
            self.out.write("\n")
            self._answer_line_open = False
        self.out.flush()
        if not capped and has_cap_notice("".join(self.answer_parts)):
            capped = True
        if capped:
            self.note(CAP_NOTE)
        elif finish_reason == "length":
            self.note(LENGTH_NOTE)
        return capped

    def abort(self) -> None:
        """Stop mid-reply (error or Ctrl+C): end any open line so the next message starts clean."""
        self.status.clear()
        if self._reasoning_line_open and self.reasoning_out is not None:
            self.reasoning_out.write("\n")
            self.reasoning_out.flush()
            self._reasoning_line_open = False
        if self._answer_line_open:
            self.out.write("\n")
            self.out.flush()
            self._answer_line_open = False


def fetch_reply(
    client: MolochAI,
    *,
    model: str,
    messages: Sequence[dict[str, Any]],
    stream: bool,
    printer: ReplyPrinter | None,
    status: StatusLine,
) -> ChatCompletion:
    """Request a reply and print it as it arrives (or not at all with ``printer=None``).

    Streams by default: the edge proxy in front of the API gives up on a plain request after
    about 100 seconds. Queue progress and "waiting" go to the status line.
    """

    def on_queue(queue: QueueStatus) -> None:
        status.show(describe_queue(queue))

    status.show(f"waiting for {model}...")
    try:
        if stream:
            with client.chat.completions.create(
                model=model, messages=messages, stream=True, on_queue=on_queue
            ) as reply:
                for chunk in reply:
                    if printer is None:
                        continue
                    for choice in chunk.choices:
                        if choice.index != 0:
                            continue
                        if choice.delta.reasoning_content:
                            printer.reasoning(choice.delta.reasoning_content)
                        if choice.delta.content:
                            printer.content(choice.delta.content)
                completion = reply.final_completion()
        else:
            completion = client.chat.completions.create(model=model, messages=messages)
            if printer is not None and completion.choices:
                message = completion.choices[0].message
                reasoning, answer = message.reasoning_content, message.content
                if reasoning is None:
                    reasoning, answer = split_think(answer)
                if reasoning:
                    printer.reasoning(reasoning)
                if answer:
                    printer.content(answer)
    except BaseException:
        if printer is not None:
            printer.abort()
        status.clear()
        raise
    status.clear()
    if printer is not None:
        finish_reason = completion.choices[0].finish_reason if completion.choices else None
        printer.finish(finish_reason)
    return completion
