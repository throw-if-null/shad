"""
`shad git panel` — the read-only repository view, as a command: resolve the
one repository, then hand the terminal to the textual app in `app.py`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from shad import parsers
from shad.addressing import resolve_target
from shad.config import Config
from shad.deps import Deps
from shad.errors import ShadError
from shad.git import discover
from shad.git.model import Repo
from shad.git.run import GitMissing, require_git


def register(sub: parsers.Subparsers) -> None:
    panel = parsers.command(
        sub,
        "panel",
        run=run,
        help="Read-only branch, worktree and stash view for one repository (full-screen)",
        description=(
            "A read-only view of one repository, shown in shad's third pane.\n\n"
            "Sections:\n"
            "  branches    local branches, tracking state, and upstream\n"
            "  worktrees   path, branch, and locked/prunable/bare flags\n"
            "  stashes     ref, branch, message, and age\n\n"
            "The header carries the active branch, how far it is ahead of and\n"
            "behind upstream, the repository, and the git version — in that\n"
            "order, because a narrow pane truncates the tail.\n\n"
            "Unlike `sync`, no name means the current directory, not every\n"
            "configured project: this view shows one repository. A name that\n"
            "matches more than one project is an error.\n\n"
            "The panel fetches on open so the counts are accurate, and `r`\n"
            "fetches again. It never prunes and never writes to a working\n"
            "tree — nothing here changes the repository. It is a full-screen\n"
            "view, so it has no --json.\n\n"
            "Keys:\n"
            "  tab         move focus between the section list and the table\n"
            "  up/down     move the row cursor (j / k also work)\n"
            "  r           fetch and reload\n"
            "  q           quit\n\n"
            "Examples:\n"
            "  shad git panel\n"
            "  shad git panel shad\n"
            "  shad git panel tin shad\n"
            "  shad git panel --no-fetch"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    panel.add_argument(
        "name",
        nargs="*",
        metavar="NAME",
        help="[group] [project]  — omit to use the current directory",
    )
    panel.add_argument(
        "--no-fetch",
        action="store_true",
        help="Skip the fetch on open; show local state only",
    )


def run(args: argparse.Namespace, deps: Deps) -> None:
    open_panel(deps.config, list(args.name), fetch=not getattr(args, "no_fetch", False))


def open_panel(cfg: Config, name: list[str], *, fetch: bool) -> None:
    """Run the read-only git panel against exactly one repository."""
    require_git()
    repo = _resolve_one(cfg, name)
    # Imported here, not at module scope: textual costs roughly 100ms to
    # import, and `shad git sync` must not pay it.
    from shad.git.panel.app import run_panel

    run_panel(repo, fetch=fetch)


def _resolve_one(cfg: Config, name: list[str]) -> Repo:
    """
    The single repository the panel shows.

    With no name this is the current directory, which is what makes the panel
    usable from any repository rather than only from a configured project.
    That differs from `sync`, where no name means every configured project —
    a single-repository view has no all-projects form.
    """
    if not name:
        path = Path.cwd()
    else:
        target = resolve_target(cfg, name, usage="shad git panel")
        if len(target.projects) != 1:
            names = ", ".join(p.display_name for p in target.projects)
            raise ShadError.usage(
                "ambiguous_target",
                f"'{' '.join(name)}' matches {len(target.projects)} projects "
                f"({names}); shad git panel shows one repository"
            )
        path = target.projects[0].path

    try:
        return discover.discover(path)
    except discover.NotUsable as exc:
        # The sync report prints a NotUsable hint on its own line; the error
        # line is one line.
        reason = "; ".join(line.strip() for line in str(exc).splitlines())
        raise ShadError.not_found("no_repository", reason) from None
    except GitMissing as exc:
        raise ShadError.infrastructure("git_missing", str(exc)) from None
