"""`shad git`: the group parser; `sync` and `panel` register on it."""

from __future__ import annotations

import argparse

from shad import parsers
from shad.git.panel import command as panel
from shad.git.sync import command as sync


def register(sub: parsers.Subparsers) -> None:
    _, actions = parsers.group(
        sub,
        "git",
        dest="git_action",
        help="Run git maintenance across configured projects",
        description=(
            "Git maintenance across one, some, or all configured projects.\n\n"
            "Actions:\n"
            "  sync     fetch, fast-forward, and prune dead branches and worktrees\n"
            "  panel    read-only branch, worktree and stash view for one repository\n\n"
            "Examples:\n"
            "  shad git sync                     every configured project\n"
            "  shad git sync kb                  one top-level project\n"
            "  shad git sync alvr                every project in the alvr group\n"
            "  shad git sync alvr db             one grouped project\n\n"
            "Prefix matching is supported at each level."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sync.register(actions)
    panel.register(actions)
