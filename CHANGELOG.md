# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-11-13

First release. Not published to PyPI; install from the `v0.1.0` tag on GitHub. Requires the
`molochai` SDK 0.1.1, installed from its GitHub tag.

### Added

- `molochai chat`: interactive multi-turn chat with streamed replies, reasoning shown dimmed
  above the answer (`--show-reasoning`, the default) or hidden (`--hide-reasoning`), queue
  progress on a transient status line, the output-cap notice reported as a note, and
  `--no-stream`. Slash commands `/help`, `/model`, `/models`, `/system`, `/reasoning`, `/clear`,
  `/save`, `/usage`, `/exit`. Ctrl+C stops a reply and keeps the session; failed and stopped
  replies are not added to the conversation.
- `molochai ask`: one-shot questions that print only the answer, with stdin appended to the
  prompt when piped, `--json` for the final completion, `--show-reasoning` (to stderr),
  `--system`, `--model` and `--no-stdin`.
- `molochai models` and `molochai account` (`--show-email`).
- `molochai config set-key` (hidden prompt or `--stdin`), `config set model|base-url`,
  `config show` (masked key, with the source of each value), `config path`, `config unset`.
- Settings precedence: flags, then `MOLOCHAI_API_KEY` / `MOLOCHAI_BASE_URL` / `MOLOCHAI_MODEL`,
  then the JSON config file (`MOLOCHAI_CONFIG_DIR`, `%APPDATA%\molochai` or
  `$XDG_CONFIG_HOME/molochai`), then defaults. The file is written atomically, with mode 0600 in
  a 0700 directory on POSIX systems, and a warning when an existing file is readable by others.
- Messages for every SDK error type with the next step, documented exit codes (0, 1, 2, 3,
  130), colors only on terminals (`NO_COLOR`, `--no-color`, ANSI enabled on Windows 10 consoles),
  control characters removed from model output written to a terminal, UTF-8 on Windows pipes,
  and a leading byte order mark dropped from piped input.

[0.1.0]: https://github.com/Moloch-AI/uncensored-ai-cli/releases/tag/v0.1.0
