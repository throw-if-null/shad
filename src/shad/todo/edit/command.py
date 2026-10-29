"""`shad todo edit` — open one item in $EDITOR, then report what the file now gets wrong."""

from __future__ import annotations

import argparse
import subprocess

from rich.console import Console
from rich.text import Text

from shad.shared.config import Config
from shad.shared.editor import resolve_editor
from shad.shared.errors import ShadError
from shad.todo import store
from shad.todo.model import problems

console = Console()


def edit_todo(cfg: Config, args: argparse.Namespace) -> None:
    directory = store.todo_dir(cfg)
    key = store.resolve_key(directory, args.key)
    path = store.item_path(directory, key)
    editor = resolve_editor()
    result = subprocess.run([*editor.split(), str(path)], check=False)
    if result.returncode != 0:
        raise ShadError(f"editor exited with status {result.returncode}")
    item = store.read_item(directory, key)
    for problem in problems(item, cfg.todo_labels):
        console.print(Text("  ! ", style="bold yellow") + Text(f"{item.key}: {problem}"))
