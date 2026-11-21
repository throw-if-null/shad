"""`shad todo panel` — the pane; a thin textual view over the todo files."""

from __future__ import annotations

import argparse
from pathlib import Path

from shad import parsers
from shad.editor import Editor
from shad.output import Output


def register(sub: parsers.Subparsers) -> None:
    parsers.command(
        sub, "panel", run=run, help="Show the todo pane (a full-screen view; no --json)"
    )


def run(
    args: argparse.Namespace,
    *,
    out: Output,
    editor: Editor,
    todo_dir: Path,
    todo_labels: list[str],
) -> None:
    # Imported here, not at module scope: textual costs roughly 100ms to
    # import, and `shad todo add` from a script must not pay it.
    from shad.todo.panel.app import run_panel

    run_panel(todo_dir, todo_labels, out, editor)
