"""
`shad todo edit` — open one item in $EDITOR, then report what the file now
gets wrong. `edit_in_editor` is also what the panel's `e` key runs.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from rich.text import Text

from shad import parsers
from shad.deps import Deps
from shad.errors import ShadError
from shad.shared.editor import resolve_editor
from shad.todo import store
from shad.todo.model import Item, problems


def register(sub: parsers.Subparsers) -> None:
    parser = parsers.command(sub, "edit", run=run, help="Open an item in $EDITOR")
    parser.add_argument("key", metavar="KEY", help="Item key, or a unique prefix")


def run(args: argparse.Namespace, deps: Deps) -> None:
    cfg = deps.config
    item = edit_in_editor(store.todo_dir(cfg), args.key)
    for problem in problems(item, cfg.todo_labels):
        deps.out.note(Text("  ! ", style="bold yellow") + Text(f"{item.key}: {problem}"))


def edit_in_editor(directory: Path, key: str) -> Item:
    """
    Open the file of the item *key* names, or a unique prefix of it, in the
    editor, and return the item as the file now reads. The editor takes the
    terminal over, so a textual caller must suspend the app around this call.
    """
    key = store.resolve_key(directory, key)
    path = store.item_path(directory, key)
    editor = resolve_editor()
    result = subprocess.run([*editor.split(), str(path)], check=False)
    if result.returncode != 0:
        raise ShadError.infrastructure(
            "editor_failed", f"editor exited with status {result.returncode}"
        )
    return store.read_item(directory, key)
