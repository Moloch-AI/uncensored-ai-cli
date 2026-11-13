"""The one-shot commands: ``ask``, ``models``, ``account`` and ``config``."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from typing import Any

from molochai import Model, NotFoundError

from .app import App
from .config import SETTING_NAMES, mask_key, normalize_base_url
from .console import Style, is_tty, strip_bom
from .errors import ExitCode, UsageError, format_local_time
from .render import ReplyPrinter, fetch_reply

__all__ = [
    "cmd_account",
    "cmd_ask",
    "cmd_config_path",
    "cmd_config_set",
    "cmd_config_set_key",
    "cmd_config_show",
    "cmd_config_unset",
    "cmd_models",
    "format_table",
    "yes_no",
]


def format_table(headers: Sequence[str], rows: Sequence[Sequence[str]], style: Style) -> list[str]:
    """Left-aligned columns separated by two spaces, with a bold header row."""
    widths = [len(h) for h in headers]
    for row in rows:
        widths = [max(w, len(cell)) for w, cell in zip(widths, row, strict=False)]

    def line(cells: Sequence[str]) -> str:
        return "  ".join(c.ljust(w) for c, w in zip(cells, widths, strict=False)).rstrip()

    return [style.bold(line(headers)), *(line(row) for row in rows)]


def yes_no(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return "yes" if value else "no"


# -- ask --------------------------------------------------------------------------------------


def cmd_ask(app: App, args: argparse.Namespace) -> int:
    console = app.console
    parts: list[str] = []
    if args.prompt and args.prompt.strip():
        parts.append(args.prompt)
    if not args.no_stdin and not is_tty(console.stdin):
        # Shown only on a terminal: a stdin that never ends would otherwise look like a hang.
        console.status.show("reading stdin (--no-stdin skips it)...")
        piped = strip_bom(console.stdin.read())
        console.status.clear()
        if piped.strip():
            parts.append(piped)
    if not parts:
        raise UsageError(
            "Nothing to ask.",
            ['Give a prompt (molochai ask "...") or pipe text in (cat notes.md | molochai ask).'],
        )
    messages: list[dict[str, Any]] = []
    if args.system:
        messages.append({"role": "system", "content": args.system})
    messages.append({"role": "user", "content": "\n\n".join(parts)})

    settings = app.settings(model_flag=args.model)
    client = app.client(settings)
    model = settings.model.value or ""

    if args.json:
        completion = fetch_reply(
            client, model=model, messages=messages, stream=True, printer=None, status=console.status
        )
        console.out(json.dumps(completion.raw, ensure_ascii=False, indent=2))
        return ExitCode.OK

    printer = ReplyPrinter(
        out=console.stdout,
        reasoning_out=console.stderr if args.show_reasoning else None,
        reasoning_style=console.err_style,
        status=console.status,
        note=console.note,
    )
    fetch_reply(
        client, model=model, messages=messages, stream=True, printer=printer, status=console.status
    )
    return ExitCode.OK


# -- models -----------------------------------------------------------------------------------


def model_table(models: Sequence[Model], style: Style, current: str | None = None) -> list[str]:
    rows = []
    for model in models:
        marker = "*" if current is not None and model.id == current else ""
        rows.append(
            [model.id + (" " + marker if marker else ""), model.name or "", yes_no(model.available)]
        )
    return format_table(["ID", "NAME", "AVAILABLE"], rows, style)


def cmd_models(app: App, args: argparse.Namespace) -> int:
    console = app.console
    client = app.client(app.settings())
    models = client.models.list()
    if not models:
        console.out("The server returned no models.")
        return ExitCode.OK
    for line in model_table(models, console.out_style):
        console.out(line)
    return ExitCode.OK


# -- account ----------------------------------------------------------------------------------


def _tokens(value: int | None) -> str:
    return f"{value:,}" if value is not None else "unknown"


def cmd_account(app: App, args: argparse.Namespace) -> int:
    console = app.console
    settings = app.settings()
    client = app.client(settings)
    try:
        account = client.account.retrieve()
    except NotFoundError:
        console.error(
            f"{settings.base_url.value} does not look like the MolochAI API: its account "
            "endpoint returned 404.",
            [
                "`molochai account` works only against MolochAI. Chat, ask and models also "
                "work with other OpenAI-compatible servers.",
            ],
        )
        return ExitCode.API_ERROR

    tier = account.tier or "unknown"
    if account.tier == "payg":
        tier = "payg (running on credit, no plan)"
    fields: list[tuple[str, str]] = [("Plan", account.plan or "none")]
    if account.plan_expires_at is not None:
        fields.append(("Plan expires", format_local_time(account.plan_expires_at)))
    fields.append(("Tier", tier))
    credit = f"${account.credit_usd:,.2f}" if account.credit_usd is not None else "unknown"
    fields.append(("Credit", credit))
    if args.show_email:
        fields.append(("Email", account.email or "unknown"))
    fields.append(("Email verified", yes_no(account.email_verified)))
    if account.default_model:
        fields.append(("Default model", account.default_model))
    fields.append(("Context limit", f"{_tokens(account.context_limit)} tokens (plan)"))
    if account.api_base:
        fields.append(("API base", account.api_base))

    width = max(len(label) for label, _ in fields)
    for label, value in fields:
        console.out(f"{label.ljust(width)}  {value}")

    if account.models:
        console.out()
        rows = [
            [
                m.id,
                yes_no(m.available),
                _tokens(m.context_limit) if m.context_limit is not None else "-",
            ]
            for m in account.models
        ]
        for line in format_table(["MODEL", "AVAILABLE", "CONTEXT LIMIT"], rows, console.out_style):
            console.out(line)
        console.out(
            console.out_style.dim(
                "Context limit per model: the smaller of the plan's and the serving server's."
            )
        )
    return ExitCode.OK


# -- config -----------------------------------------------------------------------------------


def cmd_config_path(app: App, args: argparse.Namespace) -> int:
    app.console.out(str(app.config_path))
    return ExitCode.OK


def cmd_config_show(app: App, args: argparse.Namespace) -> int:
    console = app.console
    config = app.config()
    settings = app.settings()
    dim = console.out_style.dim
    state = "" if config.exists else "  " + dim("(not created yet)")
    key = mask_key(settings.api_key.value) if settings.api_key.value else "not set"
    rows = [
        ("Config file", f"{config.path}{state}"),
        ("API key", f"{key}  {dim('(' + settings.api_key.source + ')')}"),
        ("Base URL", f"{settings.base_url.value}  {dim('(' + settings.base_url.source + ')')}"),
        ("Model", f"{settings.model.value}  {dim('(' + settings.model.source + ')')}"),
    ]
    for label, value in rows:
        console.out(f"{label.ljust(11)}  {value}")
    return ExitCode.OK


def _key_name(name: str) -> str:
    key = SETTING_NAMES.get(name) or SETTING_NAMES.get(name.replace("_", "-"))
    if key is None:
        raise UsageError(
            f"Unknown setting {name!r}.",
            [f"Settings: {', '.join(SETTING_NAMES)}."],
        )
    return key


def cmd_config_set(app: App, args: argparse.Namespace) -> int:
    console = app.console
    key = _key_name(args.name)
    if key == "api_key":
        raise UsageError(
            "The API key is not accepted as a command-line argument: it would be saved in your "
            "shell history.",
            ["Use `molochai config set-key` (hidden prompt, or --stdin from a pipe)."],
        )
    value = args.value.strip()
    if key == "base_url":
        try:
            value = normalize_base_url(value)
        except ValueError as exc:
            raise UsageError(f"The base URL {exc}.") from exc
    elif not value or any(c.isspace() for c in value):
        raise UsageError(f"Invalid model id {args.value!r}.", ["Run `molochai models`."])
    config = app.config()
    config.set(key, value)
    config.save()
    label = "Base URL" if key == "base_url" else "Model"
    console.out(f"{label} set to {value} in {config.path}")
    env_name = "MOLOCHAI_BASE_URL" if key == "base_url" else "MOLOCHAI_MODEL"
    if app.environ.get(env_name, "").strip():
        console.note(f"{env_name} is set in your environment and takes precedence over the file.")
    return ExitCode.OK


def cmd_config_set_key(app: App, args: argparse.Namespace) -> int:
    console = app.console
    if args.stdin:
        key = strip_bom(console.stdin.read()).strip()
    elif not is_tty(console.stdin):
        raise UsageError(
            "stdin is not a terminal, so the key cannot be typed in.",
            ["To read the key from a pipe, add --stdin."],
        )
    else:
        key = console.getpass("API key (input hidden): ").strip()
    if not key:
        raise UsageError("No key given; nothing was changed.")
    if any(c.isspace() for c in key):
        raise UsageError("An API key is a single word without spaces or line breaks.")
    config = app.config()
    config.set("api_key", key)
    config.save()
    console.out(f"Saved the API key ({mask_key(key)}) to {config.path}")
    if app.environ.get("MOLOCHAI_API_KEY", "").strip():
        console.note(
            "MOLOCHAI_API_KEY is set in your environment and takes precedence over the file."
        )
    return ExitCode.OK


def cmd_config_unset(app: App, args: argparse.Namespace) -> int:
    console = app.console
    key = _key_name(args.name)
    config = app.config()
    if not config.unset(key):
        console.out(f"{args.name} is not set in {config.path}")
        return ExitCode.OK
    config.save()
    console.out(f"Removed {args.name} from {config.path}")
    return ExitCode.OK
