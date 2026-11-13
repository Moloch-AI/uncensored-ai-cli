"""Check the built distributions before they are released.

* ``dist/`` holds exactly one wheel and one sdist, with the same name and version.
* With ``--tag``: the tag is ``v<version>``.
* No requirement is a direct reference (``name @ git+https://...``). PyPI rejects uploads whose
  metadata contains one. With ``--for-pypi`` that is an error, otherwise a warning.

Used by .github/workflows/release.yml; also runs locally::

    python .github/scripts/check_dist.py --tag v1.2.3 --for-pypi dist

Writes ``name`` and ``version`` to ``$GITHUB_OUTPUT`` when that is set. Needs ``packaging``.
"""

from __future__ import annotations

import argparse
import os
import sys
import tarfile
import zipfile
from email.message import Message
from email.parser import Parser
from pathlib import Path

from packaging.requirements import Requirement

IN_ACTIONS = os.environ.get("GITHUB_ACTIONS") == "true"


def report(level: str, title: str, message: str) -> None:
    """Print a message; in GitHub Actions as an annotation on the run."""
    if IN_ACTIONS:
        text = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::{level} title={title}::{text}")
    else:
        print(f"{level}: {title}: {message}", file=sys.stderr)


def single(names: list[str], what: str, archive: Path) -> str:
    if len(names) != 1:
        raise SystemExit(f"{archive.name}: expected one {what}, found {names}")
    return names[0]


def wheel_metadata(path: Path) -> Message:
    with zipfile.ZipFile(path) as wheel:
        candidates = [
            name
            for name in wheel.namelist()
            if name.count("/") == 1 and name.endswith(".dist-info/METADATA")
        ]
        data = wheel.read(single(candidates, "METADATA file", path))
    return Parser().parsestr(data.decode("utf-8"))


def sdist_metadata(path: Path) -> Message:
    with tarfile.open(path) as sdist:
        candidates = [
            member.name
            for member in sdist.getmembers()
            if member.name.count("/") == 1 and member.name.endswith("/PKG-INFO")
        ]
        handle = sdist.extractfile(single(candidates, "PKG-INFO file", path))
        if handle is None:
            raise SystemExit(f"{path.name}: PKG-INFO is not a regular file")
        data = handle.read()
    return Parser().parsestr(data.decode("utf-8"))


def direct_references(metadata: Message) -> list[str]:
    return [
        line
        for line in metadata.get_all("Requires-Dist") or []
        if Requirement(line).url is not None
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("dist", nargs="?", type=Path, default=Path("dist"))
    parser.add_argument("--tag", help="release tag; must be v<version>")
    parser.add_argument(
        "--for-pypi",
        action="store_true",
        help="the files are about to go to PyPI: a direct reference is an error",
    )
    args = parser.parse_args(argv)

    wheels = sorted(args.dist.glob("*.whl"))
    sdists = sorted(args.dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        found = [path.name for path in [*wheels, *sdists]]
        report("error", "Unexpected files", f"Expected one wheel and one sdist, found {found}.")
        return 1
    metadata = {
        wheels[0].name: wheel_metadata(wheels[0]),
        sdists[0].name: sdist_metadata(sdists[0]),
    }
    identities = {(meta["Name"], meta["Version"]) for meta in metadata.values()}
    if len(identities) != 1:
        report("error", "Mismatched files", f"The wheel and sdist disagree: {sorted(identities)}.")
        return 1
    ((name, version),) = identities
    failed = False

    if args.tag is not None and args.tag != f"v{version}":
        report(
            "error",
            "Tag does not match the version",
            f"The release tag is {args.tag}, but the package version is {version}. Release "
            f"from tag v{version}, or change the version and tag again.",
        )
        failed = True

    direct = sorted({line for meta in metadata.values() for line in direct_references(meta)})
    if direct:
        message = (
            f"{name} {version} depends on {', '.join(direct)}. PyPI rejects packages with a "
            "direct reference in their metadata. Switch to a version range on PyPI before "
            "publishing there; RELEASING.md has the steps."
        )
        if args.for_pypi:
            report("error", "Not publishable to PyPI", message)
            failed = True
        else:
            report("warning", "Not publishable to PyPI", message)

    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"name={name}\nversion={version}\n")
    print(f"{name} {version}: {', '.join(metadata)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
