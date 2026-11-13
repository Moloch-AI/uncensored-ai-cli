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
```

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
