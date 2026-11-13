# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

Packaging, documentation and tests only. The CLI's code is unchanged, so the version stays
0.1.0.

Planned for 0.1.1: once `molochai` is on PyPI (its first upload is planned as 0.1.3), the SDK dependency changes from
`molochai @ git+https://github.com/Moloch-AI/uncensored-ai-python@v0.1.1` to
`molochai>=0.1.2,<0.2`, installing the CLI no longer needs `git`, and 0.1.1 becomes the first
version on PyPI. PyPI rejects packages that depend on a git URL, so this has to wait for the
SDK. `RELEASING.md` has the steps.

### Changed

- README links to files in this repository are now absolute GitHub URLs, so they also work on
  the PyPI project page, which does not resolve relative links. A unit test fails if a relative
  link or image comes back.

### Added

- `.github/workflows/release.yml`: when a GitHub release is published, it builds the sdist and
  wheel, runs `twine check --strict`, checks that the tag is `v` plus the package version,
  installs the wheel into a fresh virtual environment and runs `molochai --version` and
  `molochai --help`, and attaches both files to the release. If the repository variable
  `PUBLISH_TO_PYPI` is `true`, it then publishes them to PyPI with Trusted Publishing, but it
  refuses while a dependency is a direct reference such as the current git URL. Run by hand,
  it is a dry run.
- `tests/live/`: opt-in tests against the real API, skipped unless `MOLOCHAI_LIVE=1`.
  `molochai models`, `account` and `ask` with an invalid key must exit 1 with the HTTP 401
  message; with `MOLOCHAI_API_KEY` set, `models`, `account` and one small `ask --json` are
  checked as well. `.github/workflows/live.yml` runs them weekly and on demand.
- `RELEASING.md`: the one-time PyPI and GitHub setup, the switch to the SDK from PyPI, and the
  release steps.

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

[Unreleased]: https://github.com/Moloch-AI/uncensored-ai-cli/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Moloch-AI/uncensored-ai-cli/releases/tag/v0.1.0
