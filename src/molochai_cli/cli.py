"""Command-line parsing and the ``molochai`` entry point."""

from __future__ import annotations

import argparse
import contextlib
import os
import platform
import sys
import textwrap
from collections.abc import Callable, Mapping, Sequence
from typing import TextIO

import molochai
from molochai import MolochAIError

from ._version import __version__
from .app import App, ClientFactory, default_client_factory
from .chat import EOF_KEYS, ChatSession
from .commands import (
    cmd_account,
    cmd_ask,
    cmd_config_path,
    cmd_config_set,
    cmd_config_set_key,
    cmd_config_show,
    cmd_config_unset,
    cmd_models,
)
from .console import Console, prepare_stdio
from .errors import CLIError, ExitCode, describe_error
from .links import DOCS_URL

__all__ = ["build_parser", "main"]

PROG = "molochai"

EPILOG = f"""\
settings, highest precedence first:
  command-line flags  --model, --base-url
  environment         MOLOCHAI_API_KEY, MOLOCHAI_BASE_URL, MOLOCHAI_MODEL
  config file         see `molochai config path`
  defaults            model glm-5.3-flash, the hosted MolochAI API

The API key has no command-line flag: arguments are saved in shell history and
visible to other processes. Use `molochai config set-key` or MOLOCHAI_API_KEY.

exit codes:
  0    success
  1    API or network error
  2    usage error (invalid arguments)
  3    configuration error (no API key, invalid config file or setting)
  130  interrupted (Ctrl+C)

docs: {DOCS_URL}
"""


class _Parser(argparse.ArgumentParser):
    """An ArgumentParser that writes to the streams given to :func:`main`."""

    out: TextIO | None = None
    err: TextIO | None = None

    def _print_message(self, message: str, file: object = None) -> None:
        if not message:
            return
        to_stdout = file is sys.stdout
        target: TextIO = sys.stdout if to_stdout else sys.stderr
        if to_stdout and self.out is not None:
            target = self.out
        elif not to_stdout and self.err is not None:
            target = self.err
        target.write(message)
        target.flush()


class _Formatter(argparse.HelpFormatter):
    """Wraps prose paragraphs; keeps indented or multi-line blocks (examples, tables) as written."""

    def _fill_text(self, text: str, width: int, indent: str) -> str:
        blocks = []
        for block in text.split("\n\n"):
            if block.startswith(" ") or "\n" in block.strip("\n"):
                blocks.append("\n".join(indent + line for line in block.splitlines()))
            else:
                blocks.append(
                    textwrap.fill(
                        " ".join(block.split()),
                        width,
                        initial_indent=indent,
                        subsequent_indent=indent,
                    )
                )
        return "\n\n".join(blocks)


Handler = Callable[[App, argparse.Namespace], int]


def cmd_chat(app: App, args: argparse.Namespace) -> int:
    settings = app.settings(model_flag=args.model)
    client = app.client(settings)
    session = ChatSession(
        console=app.console,
        client=client,
        model=settings.model.value or "",
        base_url=settings.base_url.value or "",
        system=args.system or None,
        stream=not args.no_stream,
        show_reasoning=args.show_reasoning,
    )
    return session.run()


def build_parser(out: TextIO | None = None, err: TextIO | None = None) -> argparse.ArgumentParser:
    """The argument parser. ``out`` and ``err`` receive help and error messages."""

    def common(defaults: bool) -> _Parser:
        # Global options work before or after the command. In subcommands they default to
        # SUPPRESS so a value given before the command is not overwritten.
        parent = _Parser(add_help=False)
        parent.add_argument(
            "--base-url",
            metavar="URL",
            default=None if defaults else argparse.SUPPRESS,
            help="API base URL (default: MOLOCHAI_BASE_URL, the config file, then the hosted API)",
        )
        parent.add_argument(
            "--no-color",
            action="store_true",
            default=False if defaults else argparse.SUPPRESS,
            help="no colors (also off when NO_COLOR is set or output is not a terminal)",
        )
        return parent

    sub_common = common(False)

    parser = _Parser(
        prog=PROG,
        description="Terminal client for the MolochAI API: interactive chat, one-shot "
        "questions for scripts, the model list and your account.",
        epilog=EPILOG,
        formatter_class=_Formatter,
        parents=[common(True)],
    )
    parser.add_argument("--version", action="store_true", help="show the version and exit")
    commands = parser.add_subparsers(dest="command", title="commands", metavar="<command>")

    def add(
        group: argparse._SubParsersAction[_Parser],
        name: str,
        handler: Handler | None,
        summary: str,
        description: str | None = None,
        parents: Sequence[_Parser] = (),
    ) -> _Parser:
        sub = group.add_parser(
            name,
            help=summary,
            description=description or summary,
            parents=list(parents),
            formatter_class=_Formatter,
        )
        sub.set_defaults(handler=handler, parser=sub)
        sub.out, sub.err = out, err
        return sub

    # chat
    chat = add(
        commands,
        "chat",
        cmd_chat,
        "interactive multi-turn chat",
        "Interactive multi-turn chat with streaming replies. Type /help inside the chat for "
        "the slash commands.\n\nCtrl+C while a reply is printing stops that reply; Ctrl+C or "
        f"{EOF_KEYS} at the prompt leaves.",
        [sub_common],
    )
    chat.add_argument("--model", metavar="ID", help="model id (see `molochai models`)")
    chat.add_argument("--system", metavar="TEXT", help="system prompt for the conversation")
    chat.add_argument(
        "--no-stream",
        action="store_true",
        help="wait for each whole reply instead of streaming it (long replies may hit the "
        "edge proxy's 100-second limit)",
    )
    reasoning = chat.add_mutually_exclusive_group()
    reasoning.add_argument(
        "--show-reasoning",
        dest="show_reasoning",
        action="store_const",
        const=True,
        default=True,
        help="print the model's reasoning, dimmed, above the answer (default)",
    )
    reasoning.add_argument(
        "--hide-reasoning",
        dest="show_reasoning",
        action="store_const",
        const=False,
        help="do not print the reasoning",
    )

    # ask
    ask = add(
        commands,
        "ask",
        cmd_ask,
        "one-shot question; prints only the answer (for scripts)",
        "Send one message and print only the answer to stdout. Text piped on stdin is added "
        "after the prompt:\n\n"
        '  cat notes.md | molochai ask "Summarize this"\n\n'
        "Reasoning, notices and errors go to stderr. The reply is streamed either way.",
        [sub_common],
    )
    ask.add_argument("prompt", nargs="?", help="the message (optional when text is piped in)")
    ask.add_argument("--model", metavar="ID", help="model id (see `molochai models`)")
    ask.add_argument("--system", metavar="TEXT", help="system prompt")
    ask.add_argument(
        "--json",
        action="store_true",
        help="print the final chat.completion object as JSON instead of the answer",
    )
    ask.add_argument(
        "--show-reasoning", action="store_true", help="print the model's reasoning to stderr"
    )
    ask.add_argument(
        "--no-stdin",
        action="store_true",
        help="do not read stdin even when it is not a terminal (for use inside loops that "
        "read from stdin)",
    )

    # models
    add(
        commands,
        "models",
        cmd_models,
        "list the models and whether a server is serving each one",
        parents=[sub_common],
    )

    # account
    account = add(
        commands,
        "account",
        cmd_account,
        "show plan, tier, credit and per-model context limits",
        "Show the plan, tier, credit and per-model context limits of the account behind the "
        "API key (GET /api/auth/me). Works only against the MolochAI API.",
        [sub_common],
    )
    account.add_argument("--show-email", action="store_true", help="also print the email")

    # config
    config = add(
        commands,
        "config",
        None,
        "show or change the saved settings",
        "Show or change the settings saved in the config file. Environment variables and "
        "flags take precedence over the file.",
        [sub_common],
    )
    config_commands = config.add_subparsers(
        dest="config_command", title="config commands", metavar="<command>"
    )
    set_key = add(
        config_commands,
        "set-key",
        cmd_config_set_key,
        "save the API key (typed at a hidden prompt, or read with --stdin)",
        "Save the API key in the config file. The key is typed at a hidden prompt, or read "
        "from stdin with --stdin:\n\n"
        "  pass show molochai | molochai config set-key --stdin\n\n"
        "There is no way to pass the key as an argument: it would be saved in your shell "
        "history.",
        [sub_common],
    )
    set_key.add_argument("--stdin", action="store_true", help="read the key from stdin")
    config_set = add(
        config_commands,
        "set",
        cmd_config_set,
        "save a setting: model <id> or base-url <url>",
        parents=[sub_common],
    )
    config_set.add_argument("name", help="model or base-url")
    config_set.add_argument("value", help="the new value")
    add(
        config_commands,
        "show",
        cmd_config_show,
        "show the settings in effect and where each comes from (the key is masked)",
        parents=[sub_common],
    )
    add(
        config_commands,
        "path",
        cmd_config_path,
        "print the config file location",
        parents=[sub_common],
    )
    unset = add(
        config_commands,
        "unset",
        cmd_config_unset,
        "remove a setting from the config file: api-key, model or base-url",
        parents=[sub_common],
    )
    unset.add_argument("name", help="api-key, model or base-url")

    parser.out, parser.err = out, err
    return parser


def _version_text() -> str:
    return (
        f"molochai-cli {__version__} (molochai SDK {molochai.__version__}, "
        f"Python {platform.python_version()}, {platform.system() or sys.platform})"
    )


def _exit_status(code: object) -> int:
    if code is None:
        return ExitCode.OK
    if isinstance(code, int):
        return code
    return ExitCode.USAGE


def main(
    argv: Sequence[str] | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    environ: Mapping[str, str] | None = None,
    client_factory: ClientFactory | None = None,
    read_line: Callable[[str], str] | None = None,
    getpass: Callable[[str], str] | None = None,
) -> int:
    """Run the ``molochai`` command and return its exit code.

    Every argument is optional; tests pass their own streams, environment, line reader and a
    ``client_factory`` that builds an SDK client with a mock transport.
    """
    real_stdio = stdin is None and stdout is None and stderr is None
    in_stream = stdin if stdin is not None else sys.stdin
    out_stream = stdout if stdout is not None else sys.stdout
    err_stream = stderr if stderr is not None else sys.stderr
    if real_stdio:
        prepare_stdio(in_stream, out_stream, err_stream)
    env = os.environ if environ is None else environ

    parser = build_parser(out_stream, err_stream)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return _exit_status(exc.code)

    console = Console(
        stdin=in_stream,
        stdout=out_stream,
        stderr=err_stream,
        no_color=args.no_color,
        environ=env,
        read_line=read_line,
        getpass=getpass,
    )
    if args.version:
        console.out(_version_text())
        return ExitCode.OK
    handler: Handler | None = getattr(args, "handler", None)
    if handler is None:
        target = getattr(args, "parser", parser)
        target.print_usage(err_stream)
        console.err(f"Choose a command. `{target.prog} --help` lists them.")
        return ExitCode.USAGE

    app = App(
        console=console,
        environ=env,
        client_factory=client_factory or default_client_factory,
        base_url_flag=args.base_url,
    )
    try:
        return int(handler(app, args))
    except CLIError as exc:
        console.error(exc.message, exc.hints)
        return exc.exit_code
    except MolochAIError as exc:
        base_url = None
        with contextlib.suppress(CLIError):
            base_url = app.settings().base_url.value
        problem = describe_error(exc, base_url=base_url)
        console.error(problem.message, problem.hints)
        return ExitCode.API_ERROR
    except KeyboardInterrupt:
        console.status.clear()
        console.err()
        return ExitCode.INTERRUPTED
    except BrokenPipeError:
        # The reader went away (for example `molochai ask ... | head -1`). Stop quietly.
        if real_stdio:
            try:
                devnull = os.open(os.devnull, os.O_WRONLY)
                os.dup2(devnull, sys.stdout.fileno())
            except (OSError, ValueError):
                pass
        return ExitCode.API_ERROR
    finally:
        app.close()
