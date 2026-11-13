# Releasing

How a version of `molochai-cli` gets from `main` to a GitHub release and to PyPI. This is for
maintainers; contributors do not need any of it.

## Where things stand

The CLI depends on the SDK through a direct reference:

```toml
dependencies = ["molochai @ git+https://github.com/Moloch-AI/uncensored-ai-python@v0.1.1"]
```

That keeps `pipx install "git+https://github.com/Moloch-AI/uncensored-ai-cli@v0.1.0"` and
installs from `main` working while the SDK is not on PyPI. PyPI rejects any upload whose
metadata contains a direct reference, so the CLI can go to PyPI only after the SDK is there and
the dependency has been switched to `molochai>=0.1.2,<0.2` (see
[Switching the SDK dependency to PyPI](#switching-the-sdk-dependency-to-pypi)). Until then:

- the release workflow still builds, checks and attaches the files to GitHub releases;
- its `build` job warns about the direct reference, and fails with an explanation if it is
  about to publish to PyPI (a published release with `PUBLISH_TO_PYPI` set to `true`), so
  nothing is uploaded;
- CI shows the same warning on every run of the build job.

## What the release workflow does

[.github/workflows/release.yml](.github/workflows/release.yml) runs when a GitHub release is
published. It never runs on a push or a tag alone.

| Job | Runs when | Permissions | What it does |
|---|---|---|---|
| `build` | always | `contents: read` | Builds the sdist and wheel, runs `twine check --strict`, runs [.github/scripts/check_dist.py](.github/scripts/check_dist.py) (one wheel and one sdist with the same version, tag `v<version>`, no direct references when publishing to PyPI), installs the wheel into a fresh virtual environment and runs `molochai --version` and `molochai --help`. |
| `github-release` | a release was published | `contents: write` | Attaches the sdist and wheel to the GitHub release, so downloads are counted there too. |
| `pypi` | a release was published and the repository variable `PUBLISH_TO_PYPI` is `true` | `id-token: write`, environment `pypi` | Publishes the same files to PyPI with Trusted Publishing (no token is stored anywhere). |
| `verify-pypi` | after `pypi` | none | Installs `molochai-cli==<version>` from PyPI into a fresh virtual environment and runs `molochai --version`. Retries for about five minutes while the index catches up. |

Each job runs only after the previous one succeeded, so nothing reaches PyPI unless the checks
passed and the files are on the GitHub release. If `PUBLISH_TO_PYPI` is not `true`, a release is
attached to GitHub only and the run says so in a notice.

Started by hand (Actions, "Release", "Run workflow"), the workflow is a dry run: it builds and
checks, uploads nothing, and skips the tag check unless it was started from a tag.

## Order across repositories

1. **The SDK first.** `molochai` is released to PyPI from `uncensored-ai-python` (its
   RELEASING.md; the first upload is planned as 0.1.3, because 0.1.2 went to GitHub only). Its `verify-pypi` job must have passed.
2. **Then this CLI**: switch the dependency, release 0.1.1, the first version on PyPI.

Do not set `PUBLISH_TO_PYPI` in this repository before the switch is merged. If it is set
early, a release fails in the `build` job with an explanation and nothing is uploaded.

## Switching the SDK dependency to PyPI

Do this once, as version 0.1.1, after step 1 above.

1. Check that the SDK is installable from PyPI:

   ```bash
   python -m pip download --no-deps --dest /tmp/molochai-check "molochai>=0.1.2,<0.2"
   ```

2. On a branch from `main`, edit `pyproject.toml`:
   - Replace the three comment lines above `dependencies` and the dependency itself with:

     ```toml
     dependencies = ["molochai>=0.1.2,<0.2"]
     ```

   - Delete the whole `[tool.hatch.metadata]` table (its header, its comment and
     `allow-direct-references = true`). Without it, hatchling refuses to build if a direct
     reference ever comes back.
3. In `src/molochai_cli/_version.py`, set `__version__ = "0.1.1"`.
4. In `CHANGELOG.md`, turn `## [Unreleased]` into `## [0.1.1] - YYYY-MM-DD` with the release
   date. Replace the "Planned for 0.1.1" paragraph with what this release is, for example:

   ```markdown
   The first version on PyPI (`pipx install molochai-cli`). The CLI's code is unchanged.

   ### Changed

   - The SDK dependency is `molochai>=0.1.2,<0.2` from PyPI instead of the SDK's `v0.1.1` git
     tag, so installing the CLI no longer needs `git`.
   ```

   At the bottom, replace the `[Unreleased]` link with
   `[0.1.1]: https://github.com/Moloch-AI/uncensored-ai-cli/compare/v0.1.0...v0.1.1`.
5. Update the documentation that mentions the git dependency:
   - `README.md`, Requirements: the SDK is "0.1.2 or newer, below 0.2 (installed automatically
     from PyPI)".
   - `README.md`, Installation: `pipx install molochai-cli`, `uv tool install molochai-cli` and
     `pip install molochai-cli` first; the GitHub tag (`@v0.1.1`) as the fallback; remove the
     sentence that `git` must be available.
   - `CONTRIBUTING.md`, Setup: `git` is no longer needed.
   - `.github/workflows/ci.yml` and `.github/workflows/live.yml`: remove the comments about the
     SDK coming from a git tag and the check_dist warning.
6. Verify in a fresh virtual environment (`Scripts` instead of `bin` on Windows):

   ```bash
   python -m venv /tmp/cli-switch && . /tmp/cli-switch/bin/activate
   pip install -e ".[dev]"                 # now takes molochai from PyPI
   ruff check . && ruff format --check . && mypy && pytest
   rm -rf dist && python -m build && twine check --strict dist/*
   python .github/scripts/check_dist.py --tag v0.1.1 --for-pypi dist   # no warning, exit 0
   unzip -p dist/molochai_cli-0.1.1-py3-none-any.whl molochai_cli-0.1.1.dist-info/METADATA | grep "^Requires-Dist: molochai"
   ```

   The last command prints `Requires-Dist: molochai<0.2,>=0.1.2`. Then install the wheel into
   another fresh environment and run `molochai --version`; it prints
   `molochai-cli 0.1.1 (molochai SDK 0.1.2, ...)`.
7. Open a pull request, wait for CI, and merge.
8. Do the one-time setup below, then release `v0.1.1` as described in
   [Making a release](#making-a-release) (from step 5).

## One-time setup

Do this once, shortly before the first PyPI release. Steps 1 and 2 can be done in either order.

### 1. PyPI: add a pending publisher

A pending publisher lets the workflow create the `molochai-cli` project on its first upload.

1. Sign in at https://pypi.org with the account that will own the project (PyPI requires
   two-factor authentication).
2. Open your account menu, **Publishing** (https://pypi.org/manage/account/publishing/).
3. Under **Add a new pending publisher**, choose **GitHub** and enter exactly:

   | Field | Value |
   |---|---|
   | PyPI Project Name | `molochai-cli` |
   | Owner | `Moloch-AI` |
   | Repository name | `uncensored-ai-cli` |
   | Workflow name | `release.yml` |
   | Environment name | `pypi` |

4. Click **Add**.

A pending publisher does not reserve the name: if someone else registers `molochai-cli` before
the first upload, it stops working. Make the first release soon after adding it. After the first
upload it turns into a normal trusted publisher, listed under the project's **Manage**,
**Publishing** page.

### 2. GitHub: environment and variable

In the `Moloch-AI/uncensored-ai-cli` repository settings:

1. **Environments**, **New environment**, name `pypi`. Recommended protection:
   - **Required reviewers**: yourself, so every upload to PyPI waits for your approval.
   - **Deployment branches and tags**: **Selected branches and tags**, add a rule of type
     **Tag** with the pattern `v*`.
2. After the switch is merged: **Secrets and variables**, **Actions**, **Variables** tab,
   **New repository variable**: name `PUBLISH_TO_PYPI`, value `true`. Without it (or with any
   other value), releases go to GitHub only.
3. Optional, for the weekly live tests (see [CONTRIBUTING.md](CONTRIBUTING.md)): **Secrets**
   tab, **New repository secret** `MOLOCHAI_API_KEY`, with a key from an account that holds only
   a small amount of credit (keys are not scoped).

## Making a release

Replace `X.Y.Z` with the new version.

1. On `main`, set the version in `src/molochai_cli/_version.py`.
2. In `CHANGELOG.md`, give the changes a `## [X.Y.Z] - YYYY-MM-DD` heading with the release date
   and add the compare link at the bottom. Update versioned commands in `README.md` (the
   `@vX.Y.Z` install commands).
3. Run the checks from [CONTRIBUTING.md](CONTRIBUTING.md), then:

   ```bash
   python -m build
   twine check --strict dist/*
   python .github/scripts/check_dist.py --tag vX.Y.Z --for-pypi dist
   ```

4. Commit, push to `main`, and wait for CI to pass.
5. Dry run: Actions, **Release**, **Run workflow** on `main`. The `build` job must pass, without
   a "Not publishable to PyPI" warning if this release is meant for PyPI.
6. Publish the release, from a clone of `main`:

   ```bash
   awk '/^## \[X.Y.Z\]/{f=1; next} /^## \[/{f=0} f' CHANGELOG.md > /tmp/release-notes.md
   git tag -a vX.Y.Z -m "uncensored-ai-cli vX.Y.Z"
   git push origin vX.Y.Z
   gh release create vX.Y.Z --title vX.Y.Z --notes-file /tmp/release-notes.md --verify-tag
   ```

   Creating the release on the GitHub website (tag `vX.Y.Z` on `main`, then **Publish
   release**) works the same. A pre-release also triggers the workflow and also goes to PyPI. A
   draft does not trigger it until it is published.
7. Watch the run under Actions, **Release**. Approve the `pypi` deployment if you set required
   reviewers.
8. Check https://pypi.org/project/molochai-cli/: the README renders and its links open the files
   on GitHub. `pipx install molochai-cli` then `molochai --version` shows the new version.

## When something fails

- **`build` fails** (tag and version differ, a direct reference while publishing to PyPI, the
  smoke test): nothing was uploaded. Delete the release and its tag
  (`gh release delete vX.Y.Z --cleanup-tag`), fix `main`, and release again.
- **`github-release` or `pypi` fails**: fix the cause, then **Re-run failed jobs** on the same
  run; the files built by `build` are reused. For PyPI the usual cause is a publisher that does
  not match exactly: owner `Moloch-AI`, repository `uncensored-ai-cli`, workflow `release.yml`,
  environment `pypi`.
- **A broken version reached PyPI**: PyPI never accepts the same file name twice, even after a
  deletion. Yank the version on pypi.org (the project's **Manage**, **Releases** page) and
  release the next patch version.
