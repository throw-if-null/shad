"""
`shad todo add` — create an item file; with no title, write it in $EDITOR first.

`add_in_editor` is also what the panel's `a` key runs.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from rich.console import Console
from rich.prompt import Confirm
from rich.text import Text

from shad.errors import ShadError
from shad.shared.config import Config
from shad.shared.editor import resolve_editor
from shad.todo import store
from shad.todo.model import Item, check_labels, parse, template

console = Console()


def add_todo(cfg: Config, args: argparse.Namespace) -> None:
    directory = store.todo_dir(cfg)
    labels = list(args.label or [])
    if args.title is None:
        item = add_in_editor(directory, labels, cfg.todo_labels)
    else:
        item = store.add(directory, args.title, labels, cfg.todo_labels)
    console.print(
        Text("  ✓ ", style="bold green")
        + Text(item.key, style="bright_white")
        + Text(f"  {store.item_path(directory, item.key)}", style="dim")
    )


def add_in_editor(directory: Path, labels: list[str], vocabulary: list[str]) -> Item:
    """
    Open the editor on a draft of a new item, create the item from it, and
    return the item.

    The draft is in the temporary directory, not in the item directory, so the
    list and the panel never show an unfinished draft. When store.add rejects
    the draft, the editor opens it again on request. The draft file is kept
    when the user declines.

    The editor and the prompt use the terminal, so a textual caller must
    suspend the app around this call.
    """
    if not sys.stdin.isatty():
        raise ShadError.infrastructure(
            "no_terminal", "no title given, and stdin is not a terminal to open an editor in"
        )
    check_labels(labels, vocabulary)

    fd, name = tempfile.mkstemp(prefix="shad-todo-", suffix=".md")
    draft = Path(name)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(template(labels, vocabulary))

    keep = False
    try:
        while True:
            _open_in_editor(draft)
            fields = parse(draft.read_text(encoding="utf-8", errors="replace"), key="")
            if not fields.title and not fields.body.strip():
                raise ShadError.validation("empty_todo", "empty title and body; no todo created")
            try:
                return store.add(
                    directory,
                    fields.title,
                    list(fields.labels),
                    vocabulary,
                    status=fields.status,
                    body=fields.body,
                    extra=fields.extra,
                )
            except ShadError as exc:
                console.print(Text(f"  ✗ {exc}", style="bold red"))
                if Confirm.ask("  Edit again?", default=True):
                    continue
                keep = True
                raise ShadError.validation(
                    "draft_rejected", f"no todo created; the draft is kept in {draft}"
                ) from None
    finally:
        if not keep:
            draft.unlink(missing_ok=True)


def _open_in_editor(path: Path) -> None:
    editor = resolve_editor()
    result = subprocess.run([*editor.split(), str(path)], check=False)
    if result.returncode != 0:
        raise ShadError.infrastructure(
            "editor_failed", f"editor exited with status {result.returncode}"
        )
