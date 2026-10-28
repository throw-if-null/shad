"""`shad todo list` — print the items, or just their keys with --keys."""

from __future__ import annotations

import argparse

from rich.console import Console
from rich.text import Text

from shad.shared.config import Config
from shad.shared.render import make_table
from shad.todo import store
from shad.todo.model import problems
from shad.todo.render import labels_text, status_glyph, status_word, title_text

console = Console()


def list_todos(cfg: Config, args: argparse.Namespace) -> None:
    directory = store.todo_dir(cfg)
    if getattr(args, "keys", False):
        for key in store.keys(directory):
            print(key)
        return

    items = store.list_items(directory)
    table = make_table("todo")
    for _ in range(5):
        table.add_column(no_wrap=True, overflow="ellipsis")
    if not items:
        table.add_row(Text("no todos", style="dim"), "", "", "", "")
        console.print(table)
        return

    for item in items:
        title = title_text(item)
        wrong = problems(item, cfg.todo_labels)
        if wrong:
            title.append(f"  ! {'; '.join(wrong)}", style="red")
        table.add_row(
            status_glyph(item.status),
            Text(item.key, style="bright_white"),
            status_word(item.status),
            labels_text(item.labels, cfg.todo_labels),
            title,
        )
    console.print(table)
