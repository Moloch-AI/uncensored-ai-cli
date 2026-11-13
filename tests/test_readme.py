"""The README is also the project description on PyPI, which does not resolve relative links.

Links and images in it must be absolute URLs so they work on GitHub and on PyPI alike.
"""

from __future__ import annotations

import re
from pathlib import Path

README = Path(__file__).resolve().parents[1] / "README.md"

FENCED_CODE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)
INLINE_CODE = re.compile(r"`[^`\n]*`")
# Inline links and images: the target after "](". Covers nested forms such as a badge image
# inside a link.
INLINE_TARGET = re.compile(r"\]\(\s*<?([^)\s>]+)")
# Reference definitions: "[name]: target".
REFERENCE_TARGET = re.compile(r"^ {0,3}\[[^\]]+\]:\s*<?(\S+?)>?\s*$", re.MULTILINE)
HTML_TARGET = re.compile(r"""\b(?:href|src)\s*=\s*["']([^"']+)["']""", re.IGNORECASE)


def link_targets(markdown: str) -> list[str]:
    prose = INLINE_CODE.sub("", FENCED_CODE.sub("", markdown))
    return [
        *INLINE_TARGET.findall(prose),
        *REFERENCE_TARGET.findall(prose),
        *HTML_TARGET.findall(prose),
    ]


def test_link_targets_are_found() -> None:
    sample = (
        "[![CI](https://x.test/b.svg)](https://x.test/ci) [a](LICENSE) [b](#usage)\n"
        '<img src="logo.png">\n'
        "[ref]: docs/guide.md\n"
        "```\n[c](ignored.md)\n```\n"
        "`[d](ignored.md)`\n"
    )
    assert link_targets(sample) == [
        "https://x.test/b.svg",
        "https://x.test/ci",
        "LICENSE",
        "#usage",
        "docs/guide.md",
        "logo.png",
    ]


def test_readme_links_and_images_are_absolute() -> None:
    targets = link_targets(README.read_text(encoding="utf-8"))
    assert targets, "no links found; the pattern is broken"
    relative = [target for target in targets if not target.startswith("https://")]
    assert relative == [], (
        "README.md is the PyPI description and PyPI does not resolve relative links. Use "
        "https://github.com/Moloch-AI/uncensored-ai-cli/blob/main/<path> instead."
    )
