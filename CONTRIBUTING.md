# Contributing

Thanks for helping. Bug reports, fixes and documentation improvements are welcome. For a larger
change, open an issue first so we can agree on the approach.

This repository is the command-line client only. HTTP, streaming, retries and error parsing live
in the [Python SDK](https://github.com/Moloch-AI/uncensored-ai-python); fix SDK behavior there.
Questions about the hosted API, your account or billing go to
[molochai.dev/contact](https://molochai.dev/contact?utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai-cli).
Never paste an API key into an issue, pull request or log.

## Setup

Python 3.10 or newer, and `git` (the SDK dependency is installed from its GitHub tag).

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

To work against a local checkout of the SDK instead of the tag, install it first and then this
package without dependencies:

```bash
pip install -e ../uncensored-ai-python
pip install --no-deps -e .
pip install "pytest>=8" "pytest-cov>=5" "ruff>=0.6" "mypy>=1.11" "build>=1.2" "twine>=6.1"
```

## Checks

CI runs all of these; please run them before opening a pull request.

```bash
ruff check .
ruff format --check .            # `ruff format .` to fix
mypy                             # strict, on src/
pytest --cov                     # unit tests with coverage
python -m build                  # sdist and wheel into dist/
twine check --strict dist/*
python .github/scripts/check_dist.py dist   # warns while the SDK comes from a git URL
```

`twine check` cannot catch broken links in a Markdown README, and the README is also the PyPI
project page, where relative links do not resolve. Link to files in this repository with
absolute `https://github.com/Moloch-AI/uncensored-ai-cli/blob/main/...` URLs;
`tests/test_readme.py` enforces this.

The unit tests call `molochai_cli.cli.main()` in-process with fake streams (which can claim to be
terminals), a fixed environment, a scripted line reader for the chat prompt, and an SDK client
whose `httpx` transport is an `httpx.MockTransport`. They run offline and do not touch your real
config file. Tests of POSIX file permissions are skipped on Windows.

## Integration tests against the mock server

`tests/integration/` runs the real CLI and SDK over HTTP against the mock server from
[uncensored-ai-api](https://github.com/Moloch-AI/uncensored-ai-api) (Node 20 or newer). The tests
are skipped unless `MOLOCHAI_MOCK_BASE_URL` is set:

```bash
node mock-server/server.mjs --port 4010 --quiet      # in an uncensored-ai-api checkout
MOLOCHAI_MOCK_BASE_URL=http://127.0.0.1:4010/api/v1 pytest tests/integration
```

The mock's behavior triggers (`[mock:queue]`, `[mock:cap]`, `[mock:quota]` and others, see that
repository) are handy for trying the CLI by hand:

```bash
export MOLOCHAI_BASE_URL=http://127.0.0.1:4010/api/v1 MOLOCHAI_API_KEY=mock-key
molochai ask "[mock:queue] hello"
molochai chat
```

## Live tests against the real API

`tests/live/` runs the CLI against the hosted API at `https://api.molochai.dev/api/v1`, with a
temporary config directory (your config file is not used) and without `MOLOCHAI_BASE_URL`. It
uses the same switches as the SDK's live tests and is skipped unless `MOLOCHAI_LIVE=1`:

```bash
MOLOCHAI_LIVE=1 pytest tests/live -v -rs                                 # unauthenticated tier
MOLOCHAI_LIVE=1 MOLOCHAI_API_KEY=your-api-key pytest tests/live -v -rs   # both tiers
```

- The unauthenticated tier runs `molochai models`, `account` and `ask` with an obviously invalid
  key and expects exit code 1 with the HTTP 401 message. It costs nothing and needs no account.
- The authenticated tier runs `molochai models`, `molochai account` and one
  `molochai ask --json` with a tiny prompt to the first available model. It checks the shape of
  the output, not the wording, and uses a little of the account's quota or credit. An account
  with no plan and no credit fails with a message that says so (HTTP 402).

API keys are not scoped, so use a key from an account that holds only a small amount of credit.

`.github/workflows/live.yml` runs the suite every Monday and on demand (Actions, "Live API",
"Run workflow"). The unauthenticated tier always runs; the authenticated tier runs only when the
repository has a `MOLOCHAI_API_KEY` secret and is reported as skipped otherwise. GitHub turns
off scheduled workflows in a public repository after 60 days without activity; re-enable it on
the Actions page.

## Releases

Maintainers release from GitHub; see [RELEASING.md](RELEASING.md). The CLI is not on PyPI yet:
it first has to depend on the SDK from PyPI instead of a git URL, and RELEASING.md describes
that switch.

## Guidelines

- Keep the runtime dependencies to the SDK. The standard library covers argument parsing,
  prompts, JSON and terminal output.
- Do not reimplement HTTP, SSE parsing or retries here; use the SDK.
- Keep `--help`, `/help` and the README in step with what the code does. Every command shown in
  the README should be one that runs.
- Every link to `molochai.dev` or `dash.molochai.dev` carries
  `utm_source=github&utm_medium=oss&utm_campaign=uncensored-ai-cli`.
- Code reads error types and fields, never human-readable error messages.
- Add a test for every bug fix and every new branch of behavior; coverage should not drop.
- Update `CHANGELOG.md` under an "Unreleased" heading.

The org-wide code of conduct applies to all participation.
