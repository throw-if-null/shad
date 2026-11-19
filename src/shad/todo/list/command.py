"""`shad todo list` — the items as a result, or just their keys with --keys."""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from rich.text import Text

from shad import parsers
from shad.deps import Deps
from shad.errors import ShadError
from shad.output import Output
from shad.shared.render import make_table
from shad.todo import store
from shad.todo.model import problems
from shad.todo.render import labels_text, status_glyph, status_word, title_style


@dataclass(frozen=True)
class TodoRow:
    key: str
    title: str
    status: str
    labels: tuple[str, ...]
    created: str  # ISO 8601, as the file holds it
    updated: int  # unix seconds, the file mtime
    body: str
    problems: tuple[str, ...]  # what a hand edit left wrong: an unknown status or label


@dataclass(frozen=True)
class TodoList:
    labels: tuple[str, ...]  # the configured vocabulary
    items: tuple[TodoRow, ...]


def register(sub: parsers.Subparsers) -> None:
    parser = parsers.command(sub, "list", run=run, render=render, help="Print the items")
    parser.add_argument(
        "--keys",
        action="store_true",
        help="Print only the item keys, one per line: the machine form as it is, so no --json",
    )


def run(args: argparse.Namespace, deps: Deps) -> TodoList | None:
    cfg = deps.config
    directory = store.todo_dir(cfg)
    if getattr(args, "keys", False):
        if getattr(args, "json", False):
            raise ShadError.usage("no_json", "--keys prints the keys as they are; drop --json")
        for key in store.keys(directory):
            deps.out.plain(key)
        return None
    return TodoList(
        labels=tuple(cfg.todo_labels),
        items=tuple(
            TodoRow(
                key=item.key,
                title=item.title,
                status=item.status,
                labels=item.labels,
                created=item.created,
                updated=item.updated,
                body=item.body,
                problems=tuple(problems(item, cfg.todo_labels)),
            )
            for item in store.list_items(directory)
        )
    )


def render(result: TodoList, out: Output) -> None:
    table = make_table("todo")
    for _ in range(5):
        table.add_column(no_wrap=True, overflow="ellipsis")
    if not result.items:
        table.add_row(Text("no todos", style="dim"), "", "", "", "")
        out.print(table)
        return

    vocabulary = list(result.labels)
    for row in result.items:
        title = Text(row.title or f"({row.key})", style=title_style(row.status))
        if row.problems:
            title.append(f"  ! {'; '.join(row.problems)}", style="red")
        table.add_row(
            status_glyph(row.status),
            Text(row.key, style="bright_white"),
            status_word(row.status),
            labels_text(row.labels, vocabulary),
            title,
        )
    out.print(table)
