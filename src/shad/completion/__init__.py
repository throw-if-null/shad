"""The `completion` package: `register` is what the root calls."""

from __future__ import annotations

from shad import parsers


def register(sub: parsers.Subparsers) -> None:
    """Add this package's parsers to *sub*. Imported on call, so that a module
    of this package can be imported without the whole command tree."""
    from shad.completion.command import register as add

    add(sub)
