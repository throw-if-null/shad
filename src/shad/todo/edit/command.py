"""
`shad todo edit` — open one item in $EDITOR, then report what the file now
gets wrong. `edit_in_editor` is also what the panel's `e` key runs.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from rich.text import Text

from shad import parsers
from shad.deps import Deps
from shad.editor import Editor
from shad.todo import store
from shad.todo.model import Item, problems


def register(sub: parsers.Subparsers) -> None:
    parser = parsers.command(sub, "edit", run=run, help="Open an item in $EDITOR")
    parser.add_argument("key", metavar="KEY", help="Item key, or a unique prefix")


def run(args: argparse.Namespace, deps: Deps) -> None:
    cfg = deps.config
    item = edit_in_editor(cfg.todo_dir, args.key, deps.editor)
    for problem in problems(item, cfg.todo_labels):
        deps.out.note(Text("  ! ", style="bold yellow") + Text(f"{item.key}: {problem}"))


def edit_in_editor(directory: Path, key: str, editor: Editor) -> Item:
    """
    Open the file of the item *key* names, or a unique prefix of it, in
    *editor*, and return the item as the file now reads. The editor takes
    the terminal over, so a textual caller must suspend the app around this
    call.
    """
    key = store.resolve_key(directory, key)
    editor.open(store.item_path(directory, key))
    return store.read_item(directory, key)
