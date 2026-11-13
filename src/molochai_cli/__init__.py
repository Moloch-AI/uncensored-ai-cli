"""Terminal chat client for the MolochAI API, built on the ``molochai`` Python SDK.

The command is ``molochai``; see ``molochai --help``. :func:`molochai_cli.cli.main` is the entry
point and takes optional streams and a client factory so it can be driven from tests.
"""

from ._version import __version__

__all__ = ["__version__"]
