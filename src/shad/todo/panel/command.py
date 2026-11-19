"""`shad todo panel` — the pane; a thin textual view over the todo files."""

from __future__ import annotations

import argparse

from shad import parsers
from shad.deps import Deps
from shad.todo import store


def register(sub: parsers.Subparsers) -> None:
    parsers.command(
        sub, "panel", run=run, help="Show the todo pane (a full-screen view; no --json)"
    )


def run(args: argparse.Namespace, deps: Deps) -> None:
    # Imported here, not at module scope: textual costs roughly 100ms to
    # import, and `shad todo add` from a script must not pay it.
    from shad.todo.panel.app import run_panel

    cfg = deps.config
    run_panel(store.todo_dir(cfg), cfg.todo_labels, deps.out, deps.editor)
