"""The interactive ``molochai chat`` session and its slash commands."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from molochai import ChatCompletion, MolochAI, MolochAIError, RateLimitInfo, strip_cap_notice

from .commands import model_table
from .console import Console
from .errors import ExitCode, describe_error
from .render import ReplyPrinter, fetch_reply

__all__ = ["EOF_KEYS", "ChatSession", "Turn", "UsageTotals"]

EOF_KEYS = "Ctrl+Z then Enter" if sys.platform == "win32" else "Ctrl+D"
"""The key that ends input at the prompt."""

HELP = f"""\
Commands:
  /help              show this help
  /model [id]        show the model, or switch to another one
  /models            list the models and whether they are being served
  /system [text]     show the system prompt, or set it; /system --clear removes it
  /reasoning on|off  show or hide the model's reasoning
  /clear             start a new conversation (keeps the model and system prompt)
  /save [file]       save the conversation as Markdown
  /usage             tokens used in this session
  /exit              leave ({EOF_KEYS} or Ctrl+C at the prompt also leave)

Each line you type is sent as one message. Start a line with // to send a message that begins
with /. Ctrl+C while a reply is printing stops that reply and keeps the session."""


@dataclass
class Turn:
    """One completed exchange. ``assistant`` is the message as it is sent back to the API."""

    user: str
    assistant: dict[str, Any]
    model: str
    reasoning: str | None = None
    capped: bool = False


@dataclass
class UsageTotals:
    replies: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    last: tuple[int, int, int] | None = None
    rate_limit: RateLimitInfo | None = None

    def add(self, completion: ChatCompletion) -> None:
        self.replies += 1
        if completion.rate_limit is not None:
            self.rate_limit = completion.rate_limit
        usage = completion.usage
        if usage is None:
            return
        self.prompt_tokens += usage.prompt_tokens
        self.completion_tokens += usage.completion_tokens
        self.total_tokens += usage.total_tokens
        self.last = (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens)


@dataclass
class ChatSession:
    console: Console
    client: MolochAI
    model: str
    base_url: str
    system: str | None = None
    stream: bool = True
    show_reasoning: bool = True
    turns: list[Turn] = field(default_factory=list)
    usage: UsageTotals = field(default_factory=UsageTotals)

    # -- the loop -------------------------------------------------------------------------

    def run(self) -> int:
        console = self.console
        if console.interactive:
            console.out(
                console.out_style.dim(
                    f"Chatting with {self.model}. /help for commands, /exit or {EOF_KEYS} to leave."
                )
            )
        while True:
            try:
                line = console.read_line("> ")
            except EOFError:
                if console.interactive:
                    console.out()
                return ExitCode.OK
            except KeyboardInterrupt:
                console.out()
                return ExitCode.INTERRUPTED
            if not line.strip():
                continue
            if line.startswith("//"):
                self.send(line[1:])
            elif line.startswith("/"):
                try:
                    if self.command(line) == "exit":
                        return ExitCode.OK
                except KeyboardInterrupt:
                    console.status.clear()
                    console.err(console.err_style.dim("Command stopped."))
            else:
                self.send(line)

    def messages(self, user_text: str | None = None) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        if self.system:
            messages.append({"role": "system", "content": self.system})
        for turn in self.turns:
            messages.append({"role": "user", "content": turn.user})
            messages.append(turn.assistant)
        if user_text is not None:
            messages.append({"role": "user", "content": user_text})
        return messages

    def send(self, text: str) -> None:
        """Send one message and print the reply. Failed or interrupted replies are dropped."""
        console = self.console
        printer = ReplyPrinter(
            out=console.stdout,
            reasoning_out=console.stdout if self.show_reasoning else None,
            reasoning_style=console.out_style,
            status=console.status,
            note=console.note,
        )
        try:
            completion = fetch_reply(
                self.client,
                model=self.model,
                messages=self.messages(text),
                stream=self.stream,
                printer=printer,
                status=console.status,
            )
        except KeyboardInterrupt:
            console.err(console.err_style.dim("Reply stopped. It is not part of the conversation."))
            return
        except MolochAIError as exc:
            problem = describe_error(
                exc, in_chat=True, base_url=self.base_url, streaming=self.stream
            )
            console.error(problem.message, problem.hints)
            return
        self.usage.add(completion)
        if not completion.choices:
            console.warn("The server returned no reply.")
            return
        message = completion.choices[0].message
        assistant = message.to_param()
        content = assistant.get("content")
        capped = isinstance(content, str) and content != strip_cap_notice(content)
        if capped:
            # The notice is the gateway's text, not the model's: do not send it back.
            assistant["content"] = strip_cap_notice(content)
        self.turns.append(
            Turn(
                user=text,
                assistant=assistant,
                model=self.model,
                reasoning=message.reasoning_content,
                capped=capped,
            )
        )

    # -- slash commands -------------------------------------------------------------------

    def command(self, line: str) -> str | None:
        name, _, arg = line.strip().partition(" ")
        name = name.lower()
        arg = arg.strip()
        handlers = {
            "/help": self.cmd_help,
            "/model": self.cmd_model,
            "/models": self.cmd_models,
            "/system": self.cmd_system,
            "/reasoning": self.cmd_reasoning,
            "/clear": self.cmd_clear,
            "/save": self.cmd_save,
            "/usage": self.cmd_usage,
        }
        if name in ("/exit", "/quit"):
            return "exit"
        handler = handlers.get(name)
        if handler is None:
            self.console.error(f"Unknown command {name}. Type /help for the list.")
            return None
        handler(arg)
        return None

    def cmd_help(self, arg: str) -> None:
        self.console.out(HELP)

    def _list_models(self) -> list[Any] | None:
        try:
            return self.client.models.list()
        except MolochAIError as exc:
            problem = describe_error(exc, in_chat=True, base_url=self.base_url)
            self.console.error(problem.message, problem.hints)
            return None

    def cmd_model(self, arg: str) -> None:
        console = self.console
        if not arg:
            console.out(f"Model: {self.model}")
            return
        models = self._list_models()
        if models is None:
            return
        found = next((m for m in models if m.id == arg), None)
        if found is None:
            console.error(f"Unknown model {arg!r}. Type /models to see the ids.")
            return
        self.model = arg
        console.out(f"Switched to {arg}.")
        if found.available is False:
            console.warn(
                f"{arg} is not being served right now, so replies will fail with "
                "model_unavailable until it is. /models shows which models are available."
            )

    def cmd_models(self, arg: str) -> None:
        models = self._list_models()
        if models is None:
            return
        if not models:
            self.console.out("The server returned no models.")
            return
        for line in model_table(models, self.console.out_style, current=self.model):
            self.console.out(line)
        self.console.out(self.console.out_style.dim("* the model this chat uses"))

    def cmd_system(self, arg: str) -> None:
        console = self.console
        if not arg:
            console.out(f"System prompt: {self.system}" if self.system else "No system prompt.")
        elif arg == "--clear":
            self.system = None
            console.out("System prompt removed.")
        else:
            self.system = arg
            console.out("System prompt set. It applies from the next message.")

    def cmd_reasoning(self, arg: str) -> None:
        console = self.console
        value = arg.lower()
        if value in ("on", "off"):
            self.show_reasoning = value == "on"
        elif value:
            console.error("Use /reasoning on or /reasoning off.")
            return
        console.out(f"Reasoning is {'shown' if self.show_reasoning else 'hidden'}.")

    def cmd_clear(self, arg: str) -> None:
        self.turns.clear()
        self.console.out("Started a new conversation.")

    def cmd_usage(self, arg: str) -> None:
        console = self.console
        usage = self.usage
        if not usage.replies:
            console.out("No replies yet.")
            return
        console.out(
            f"This session: {usage.replies} {'reply' if usage.replies == 1 else 'replies'}, "
            f"{usage.total_tokens:,} tokens (prompt {usage.prompt_tokens:,}, "
            f"completion {usage.completion_tokens:,})."
        )
        if usage.last is not None:
            prompt, completion, total = usage.last
            console.out(
                f"Last reply: {total:,} tokens (prompt {prompt:,}, completion {completion:,})."
            )
        limit = usage.rate_limit
        if limit is not None and limit.limit is not None and limit.remaining is not None:
            console.out(
                f"Rate limit: {limit.remaining} of {limit.limit} requests left this minute."
            )
        console.out(
            console.out_style.dim(
                "Totals come from the usage the API reports with each reply. They include "
                "reasoning; interrupted replies are not counted."
            )
        )

    def cmd_save(self, arg: str) -> None:
        console = self.console
        if not self.turns:
            console.out("Nothing to save yet.")
            return
        name = arg or datetime.now().strftime("molochai-chat-%Y%m%d-%H%M%S.md")
        path = Path(name).expanduser()
        if path.exists():
            if path.is_dir():
                console.error(f"{path} is a directory.")
                return
            if not console.interactive:
                console.error(f"{path} already exists. Choose another file name.")
                return
            try:
                answer = console.read_line(f"{path} exists. Overwrite it? [y/N] ")
            except (EOFError, KeyboardInterrupt):
                console.out()
                answer = ""
            if answer.strip().lower() not in ("y", "yes"):
                console.out("Not saved.")
                return
            mode = "w"
        else:
            mode = "x"
        try:
            with path.open(mode, encoding="utf-8", newline="\n") as handle:
                handle.write(self.transcript())
        except FileExistsError:
            console.error(f"{path} already exists. Choose another file name.")
            return
        except OSError as exc:
            console.error(f"Could not save to {path}: {exc.strerror or exc}")
            return
        console.out(f"Saved to {path}")
        console.out(
            console.out_style.dim(
                "Transcripts contain everything you typed. Check for secrets before sharing."
            )
        )

    def transcript(self) -> str:
        models = list(dict.fromkeys(turn.model for turn in self.turns))
        lines = [
            "# MolochAI chat",
            "",
            f"- Saved: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %z')}",
            f"- {'Model' if len(models) == 1 else 'Models'}: {', '.join(models)}",
        ]
        if self.system:
            lines.append("- System prompt (when saved):")
            lines.append("")
            lines.extend(f"  > {row}" if row else "  >" for row in self.system.splitlines())
        for turn in self.turns:
            lines += ["", "## You", "", turn.user, "", f"## {turn.model}", ""]
            if turn.reasoning:
                lines += [
                    "<details><summary>Reasoning</summary>",
                    "",
                    turn.reasoning.strip(),
                    "",
                    "</details>",
                    "",
                ]
            content = turn.assistant.get("content")
            lines.append(content.strip() if isinstance(content, str) and content else "*(empty)*")
            if turn.capped:
                lines += ["", "*The reply stopped at the plan's output cap.*"]
        return "\n".join(lines) + "\n"
