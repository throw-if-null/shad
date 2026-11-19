"""
The `git` package: the tool crosscut at its root (`run`, `refs`,
`discover`, `apply`, `model`) and the `sync` and `panel` commands.

Another package reads a repository through the names published here.
"""

from __future__ import annotations

from shad import parsers
from shad.git.discover import head_branch, is_clean
from shad.git.model import Commit, short_branch
from shad.git.refs import latest_tag, recent_commits

__all__ = [
    "Commit",
    "head_branch",
    "is_clean",
    "latest_tag",
    "recent_commits",
    "register",
    "short_branch",
]


def register(sub: parsers.Subparsers) -> None:
    """Add this package's parsers to *sub*. Imported on call, so that a module
    of this package can be imported without the whole command tree."""
    from shad.git.command import register as add

    add(sub)
