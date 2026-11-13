# MolochAI CLI

`molochai`: a terminal client for the MolochAI API, with interactive streaming chat, one-shot
questions for scripts and pipes, the model list and your account details.

[![CI](https://github.com/Moloch-AI/uncensored-ai-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/Moloch-AI/uncensored-ai-cli/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

## Overview

[MolochAI](https://molochai.dev/?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai-cli)
is an OpenAI-compatible API that serves five less-restricted ("uncensored") open-weight models.
Less-restricted means refusal behavior is reduced: the models still sometimes decline, they are
not more accurate than their base models, and the
[Acceptable Use Policy](https://molochai.dev/acceptable-use?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai-cli)
still applies.

This repository is the command-line client. It is for people who want to talk to those models
from a terminal, and for shell scripts that need one answer on stdout. It is built on the
[MolochAI Python SDK](https://github.com/Moloch-AI/uncensored-ai-python), which does the HTTP
work: streaming, retries, queue progress and typed errors. The CLI adds the terminal side:
rendering, slash commands, a config file and error messages that say what to do next.

```
 you, or a shell script
    |
    v
 molochai (this CLI)   -- prompt, rendering, slash commands, config file, exit codes
    |
    v
 molochai SDK          -- streaming, retries, queue progress, typed errors
    |
    |  HTTPS, Authorization: Bearer <key>
    v
 https://api.molochai.dev/api/v1   (or the mock server for offline use)
```

Related repositories:

- [uncensored-ai-python](https://github.com/Moloch-AI/uncensored-ai-python): the Python SDK this
  CLI uses.
- [uncensored-ai-api](https://github.com/Moloch-AI/uncensored-ai-api): the HTTP contract and the
  mock server used by the tests and the examples below.
- [uncensored-ai](https://github.com/Moloch-AI/uncensored-ai): the reference guide (what these
  models are, setup, troubleshooting).
- [uncensored-llm-examples](https://github.com/Moloch-AI/uncensored-llm-examples): task-oriented
  code examples.

## Features

- `molochai chat`: multi-turn chat with streamed replies. Reasoning is shown dimmed above the
  answer (or hidden), queue position is shown on a status line that disappears when the reply
  starts, and the output-cap notice is reported as a note instead of being printed as part of
  the answer.
- Slash commands: `/model` (validated against the live model list), `/models`, `/system`,
  `/reasoning`, `/clear`, `/save` (Markdown transcript), `/usage` (tokens this session), `/help`,
  `/exit`.
- Ctrl+C while a reply is printing stops that reply and keeps the conversation. Ctrl+C or end of
  input at the prompt leaves.
- `molochai ask`: one message, only the answer on stdout. Text piped on stdin is added after the
  prompt. `--json` prints the final `chat.completion` object. Replies are streamed in both cases,
  which avoids the edge proxy's 100-second limit on plain requests.
- `molochai models` and `molochai account` (plan, tier, credit, per-model context limits; the
  email only with `--show-email`).
- A config file for the key, model and base URL, written atomically with owner-only permissions
  on Linux and macOS. The key is never accepted as a command-line argument.
- Error messages for every API error type with the next step, for example when a quota resets
  (in local time), which limit a too-long prompt hit, or which command lists the available
  models.
- Colors only on terminals, off with `NO_COLOR` or `--no-color`. Control characters in model
  output are removed before it reaches a terminal.
- Documented exit codes.

What it does not do, because the API does not: there is no JSON mode, no image upload from the
CLI, no tool calling and no way to change a model's reasoning effort per request.

## Requirements

- Python 3.10 or newer.
- The [molochai](https://github.com/Moloch-AI/uncensored-ai-python) SDK 0.1.1 (installed
  automatically from its GitHub tag) and its dependency `httpx`.
- A MolochAI API key, created at
  [dash.molochai.dev/account](https://dash.molochai.dev/account?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai-cli),
  or the mock server (Node 20 or newer) for offline use.

### Platforms

| Platform | Status | What was checked |
|---|---|---|
| Windows 10 (22H2) | Tested locally | Unit and integration tests on Python 3.12 and 3.10. In a real console window: ANSI colors switched on by the CLI, the interactive chat typed into the console, Ctrl+Z then Enter to leave, Ctrl+C during a reply. |
| Linux | CI | Ubuntu, Python 3.10 to 3.14, including the config file permission tests. Not run locally. |
| macOS | CI | Python 3.13, including the config file permission tests. Not run locally. |

On Windows, Ctrl+C takes effect when the next data arrives from the server. During a streamed
reply the gateway sends something about once a second, so that is quick; before the server has
answered at all it can take longer.

## Installation

Registry packages are not published yet. Install from GitHub with
[pipx](https://pipx.pypa.io/), which puts `molochai` on your PATH in its own environment:

```bash
pipx install "git+https://github.com/Moloch-AI/uncensored-ai-cli@v0.1.0"
```

With [uv](https://docs.astral.sh/uv/):

```bash
uv tool install "git+https://github.com/Moloch-AI/uncensored-ai-cli@v0.1.0"
```

Or with pip in a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install "git+https://github.com/Moloch-AI/uncensored-ai-cli@v0.1.0"
```

Each of these also installs the SDK from its `v0.1.1` tag, so `git` must be available. Check
the install with `molochai --version`.

## Quickstart

Save your key. It is typed at a hidden prompt and stored in the config file:

```bash
molochai config set-key
molochai chat
```

Or use environment variables instead of the config file:

```bash
export MOLOCHAI_API_KEY=your-api-key
molochai ask "Explain TCP slow start in three sentences."
```

To try it offline, run the mock server from a checkout of
[uncensored-ai-api](https://github.com/Moloch-AI/uncensored-ai-api). It returns canned text, not
model output:

```bash
node mock-server/server.mjs --port 4010          # in the uncensored-ai-api checkout
export MOLOCHAI_BASE_URL=http://127.0.0.1:4010/api/v1 MOLOCHAI_API_KEY=mock-key
molochai chat
```

## Usage examples

### Chat

A session against the mock server, captured from a Windows console (the replies are the mock's
canned text, not model output; on Linux and macOS the banner says Ctrl+D):

```text
$ molochai chat
Chatting with glm-5.3-flash. /help for commands, /exit or Ctrl+Z then Enter to leave.
> Hello
| Mock reasoning for glm-5.3-flash.

Mock reply from glm-5.3-flash: Hello
> /usage
This session: 1 reply, 20 tokens (prompt 2, completion 18).
Last reply: 20 tokens (prompt 2, completion 18).
Rate limit: 59 of 60 requests left this minute.
Totals come from the usage the API reports with each reply. They include reasoning; interrupted replies are not counted.
> /model llama-3.3-70b-instruct-abliterated
Switched to llama-3.3-70b-instruct-abliterated.
> Again
Mock reply from llama-3.3-70b-instruct-abliterated: Again
> /exit
```

Lines starting with `| ` are the model's reasoning (dimmed on a color terminal). Each line you
type is one message; start a line with `//` to send a message that begins with `/`.

| Command | What it does |
|---|---|
| `/help` | List the commands. |
| `/model [id]` | Show the model, or switch. The id is checked against `GET /models`; switching to a model that is not being served right now works but warns. |
| `/models` | The model list with availability; `*` marks the one in use. |
| `/system [text]` | Show the system prompt, or set it for the following messages. `/system --clear` removes it. |
| `/reasoning on\|off` | Show or hide reasoning. |
| `/clear` | Start a new conversation. The model, system prompt and usage totals stay. |
| `/save [file]` | Save the conversation as Markdown (default `molochai-chat-YYYYMMDD-HHMMSS.md`). An existing file is overwritten only after you confirm; when input is piped, it is never overwritten. |
| `/usage` | Prompt, completion and total tokens used this session, from the usage the API sends with each reply, and the rate-limit headroom. |
| `/exit`, `/quit` | Leave. |

Replies that fail or are stopped with Ctrl+C are not added to the conversation, so you can send
the message again. The assistant messages sent back with each request are the SDK's
`message.to_param()`, which includes `reasoning_content` so thinking models keep their reasoning
across turns; the output-cap notice is removed from them because it is the gateway's text, not
the model's.

Options: `--model ID`, `--system TEXT`, `--hide-reasoning` (or `--show-reasoning`, the default)
and `--no-stream` (wait for whole replies; long ones can then fail with HTTP 524 at the edge).

### One-shot questions and pipes

`molochai ask` prints only the answer on stdout; notes and errors go to stderr.

```bash
molochai ask "Write a haiku about SSE keep-alives."
cat notes.md | molochai ask "Summarize this"          # piped text goes after the prompt
git diff | molochai ask --model qwen3.8-27b-uncensored "Review this diff"
molochai ask --show-reasoning "Is 1001 prime?"         # reasoning on stderr
```

Inside a loop that reads from stdin, add `--no-stdin` so `ask` does not consume the loop's input:

```bash
while read -r topic; do
  molochai ask --no-stdin "One sentence about $topic" >> facts.txt
done < topics.txt
```

`--json` prints the final completion (assembled from the stream) instead of the text. Against
the mock:

```text
$ molochai ask --json "Hello"
{
  "id": "chatcmpl-mock-66",
  "object": "chat.completion",
  "created": 1794538122,
  "model": "glm-5.3-flash",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Mock reply from glm-5.3-flash: Hello",
        "reasoning_content": "Mock reasoning for glm-5.3-flash."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 2,
    "completion_tokens": 18,
    "total_tokens": 20
  }
}
```

The JSON is what the API sent: when a reply hits the output cap, `finish_reason` is `"length"`
and `content` ends with the cap notice. Scripts should check the exit code:

```text
$ molochai ask "[mock:context] hi"; echo $?
error: The input is too long for this model: about 70,000 tokens, limit 65,536 (set by your plan).
  Shorten the input.
  Context sizes per plan: https://molochai.dev/pricing?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai-cli
1
```

### Models and account

```text
$ molochai models
ID                                  NAME                                     AVAILABLE
glm-5.3-flash                       GLM-5.3-Flash                            yes
glm-4.7-flash-uncensored            GLM-4.7-Flash-Uncensored                 yes
gemma4-26b-a4b-qat                  Gemma4-26B-A4B-QAT                       yes
qwen3.8-27b-uncensored              Qwen3.8-27B-Uncensored                   yes
llama-3.3-70b-instruct-abliterated  Llama-3.3-70B-Instruct-abliterated-GGUF  yes
```

That is the mock's list, which matches the public catalog of 2026-11-07. The list is always
fetched from the API; see
[molochai.dev/models](https://molochai.dev/models?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai-cli)
for the current models. Facts about each model come from its own model card.

`molochai account` shows the plan, its expiry in local time, the tier (`payg` when running on
credit), credit, whether the email is verified, the default model and each model's context limit
(the smaller of the plan's and the serving server's). The email is printed only with
`--show-email`. Against a server that is not MolochAI, it says so instead of failing with a bare
404.

## Configuration

Each setting is taken from the first of these that has it:

1. command-line flags (`--model`, `--base-url`),
2. environment variables,
3. the config file,
4. built-in defaults.

| Setting | Flag | Environment variable | Config file | Default |
|---|---|---|---|---|
| API key | none, on purpose | `MOLOCHAI_API_KEY` | `api_key`, set with `molochai config set-key` | none |
| Base URL | `--base-url URL` | `MOLOCHAI_BASE_URL` | `base_url` | `https://api.molochai.dev/api/v1` |
| Model | `--model ID` (`chat`, `ask`) | `MOLOCHAI_MODEL` | `model` | `glm-5.3-flash` |
| Config directory | | `MOLOCHAI_CONFIG_DIR` | | see below |
| Request timeout (seconds) | | `MOLOCHAI_TIMEOUT` (read by the SDK) | | 120 read, 10 connect |
| Retries | | `MOLOCHAI_MAX_RETRIES` (read by the SDK) | | 2 |
| Colors | `--no-color` | `NO_COLOR` (any non-empty value), `TERM=dumb` | | on for terminals |

Empty environment variables count as unset. `--base-url` and `--no-color` work before or after
the command name. [.env.example](.env.example) lists the variables.

The config file is JSON. `molochai config path` prints its location:

| Platform | Location |
|---|---|
| any, if `MOLOCHAI_CONFIG_DIR` is set | `$MOLOCHAI_CONFIG_DIR/config.json` |
| Windows | `%APPDATA%\molochai\config.json` |
| Linux, macOS | `$XDG_CONFIG_HOME/molochai/config.json`, or `~/.config/molochai/config.json` |

Pointing the CLI at the mock server through the config file (`<config path>` stands for the
location from the table above):

```text
$ molochai config set base-url http://127.0.0.1:4010/api/v1
Base URL set to http://127.0.0.1:4010/api/v1 in <config path>
$ printf mock-key | molochai config set-key --stdin
Saved the API key (****) to <config path>
$ molochai config show
Config file  <config path>
API key      ****  (config file)
Base URL     http://127.0.0.1:4010/api/v1  (config file)
Model        glm-5.3-flash  (default)
```

| Command | What it does |
|---|---|
| `config set-key` | Save the key. Typed at a hidden prompt; `--stdin` reads it from a pipe (for a password manager). |
| `config set model <id>` | Save the default model. |
| `config set base-url <url>` | Save the base URL (for example the mock server's). |
| `config show` | The values in effect and where each comes from. The key is masked (last four characters of keys of 12 or more characters). |
| `config path` | Print the config file location. |
| `config unset <name>` | Remove `api-key`, `model` or `base-url` from the file. |

## Command reference

```
molochai [--base-url URL] [--no-color] [--version] [--help] <command>

  chat     [--model ID] [--system TEXT] [--no-stream] [--show-reasoning | --hide-reasoning]
  ask      [prompt] [--model ID] [--system TEXT] [--json] [--show-reasoning] [--no-stdin]
  models
  account  [--show-email]
  config   set-key [--stdin] | set <model|base-url> <value> | show | path | unset <name>
```

`molochai <command> --help` describes each command. `python -m molochai_cli` works the same as
`molochai`.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Success. A reply cut off at the output cap still exits 0 (with a note on stderr). |
| 1 | The API returned an error, the connection failed, or a stream ended with an error. Also used when the output pipe is closed early. |
| 2 | Usage error: invalid arguments, nothing to ask, a key passed where it is not accepted. |
| 3 | Configuration error: no API key, an invalid config file, base URL or SDK setting. |
| 130 | Interrupted with Ctrl+C (in `ask`, or at the chat prompt). |

`molochai chat` exits 0 when you leave with `/exit` or end of input, even if some replies failed;
use `ask` in scripts that need to detect errors.

## Troubleshooting

| Message | Cause and fix |
|---|---|
| `molochai ask` waits and prints nothing | It is reading stdin, which is not a terminal and has not ended (some IDE terminals, task runners and parent processes leave it open). Add `--no-stdin`, or redirect `< /dev/null`. On a terminal a "reading stdin" status line shows while it waits. |
| `No API key.` (exit 3) | Run `molochai config set-key`, or set `MOLOCHAI_API_KEY`. |
| `The API key was not accepted (HTTP 401).` | The key is mistyped or revoked. `molochai config show` shows which source is used; create a new key in the dashboard. |
| `No active plan and no credit (HTTP 402).` | Add credit or buy a plan in the [dashboard](https://dash.molochai.dev/?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai-cli). This also happens on `molochai models`. |
| `Your account email is not verified yet (HTTP 403)` | Verify the email address, then try again. |
| `The input is too long for this model` | The prompt is over the context limit. The message says whether your plan or the serving server set it. In chat, `/clear` starts over. |
| `Your monthly quota is used up` / `The 5-hour session cap is reached.` | The message shows when it resets, in local time. These are not retried. |
| `... is not being served right now (model_unavailable)` | Pick another model: `/models` in chat, `molochai models` otherwise. |
| `Too many requests` | Over 60 requests a minute. The SDK already waited and retried; wait and try again. |
| `The edge proxy stopped waiting ... (HTTP 524)` | A non-streamed reply took over 100 seconds. Drop `--no-stream`. |
| `The server was reclaimed in the middle of the reply (preempted).` | Try again in a minute. |
| A note that the reply stopped at the output cap | The plan's output cap per reply. Ask for less; `max_tokens` cannot raise it. |
| `... does not look like the MolochAI API` | `molochai account` needs MolochAI. Chat, ask and models also work with other OpenAI-compatible servers. |
| `warning: ... can be read by other users` | The config file's permissions are too open (Linux, macOS). Run the `chmod 600` command it prints. |
| Non-ASCII text piped in Windows PowerShell 5.1 arrives as `?` | PowerShell 5.1 encodes text piped to programs with `$OutputEncoding`, which is ASCII by default. Run `$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()` first. The CLI reads and writes UTF-8 on pipes and drops the byte order mark PowerShell adds. |

More in the [MolochAI docs](https://molochai.dev/docs?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai-cli).
For problems with the hosted API or your account, use
[molochai.dev/contact](https://molochai.dev/contact?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai-cli).

## Security considerations

- **Key storage.** `config set-key` stores the key in plain text in the config file. On Linux
  and macOS the file is written with mode 0600 in a directory created with mode 0700, and the
  CLI warns if an existing file can be read by group or others. On Windows the file is in your
  profile (`%APPDATA%`), which by default only your account, administrators and the system can
  read; the CLI does not change ACLs. If you prefer an OS keychain or a password manager, keep
  the key there and set `MOLOCHAI_API_KEY` from it for the session, or pipe it in with
  `config set-key --stdin`.
- **No key on the command line.** There is no `--api-key` flag: command lines are saved in shell
  history and can be read by other processes on the machine (`ps`). `config show` masks the key
  and `account` hides the email unless asked.
- **Keys are not scoped.** A key can read account details and create invoices. Treat it as a
  password and revoke it in the dashboard if it leaks.
- **Transcripts.** `/save` writes everything you typed and every reply to a file. Check it for
  secrets before sharing it, and do not paste secrets into a chat: they are sent to the API. The
  default transcript name is in this repository's `.gitignore`; other repositories will not
  ignore it.
- **Model output.** Replies are untrusted text. The CLI only prints them; it never runs them.
  Control characters (escape sequences) are removed before output reaches a terminal so a reply
  cannot rewrite the screen or set the clipboard; output to pipes and files is left unchanged.
- **Reduced refusals.** These models decline less often. The
  [Acceptable Use Policy](https://molochai.dev/acceptable-use?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai-cli)
  applies to everything sent through the API.
- Report vulnerabilities in this CLI as described in [SECURITY.md](SECURITY.md). Never post API
  keys in issues.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development setup, the unit and integration tests
and the checks CI runs. Changes are listed in [CHANGELOG.md](CHANGELOG.md).

## License

MIT. See [LICENSE](LICENSE).
