"""`shad todo status` — set one item's status. `set_status` is also what the panel's keys run."""

from __future__ import annotations

import argparse
from pathlib import Path

from rich.text import Text

from shad import parsers
from shad.errors import ShadError
from shad.output import Output
from shad.todo import store
from shad.todo.model import STATUSES, Item
from shad.todo.render import status_word


def register(sub: parsers.Subparsers) -> None:
    parser = parsers.command(sub, "status", run=run, help="Set an item's status")
    parser.add_argument("key", metavar="KEY", help="Item key, or a unique prefix")
    parser.add_argument("status", metavar="STATUS", choices=STATUSES)


def run(args: argparse.Namespace, *, out: Output, todo_dir: Path) -> None:
    item = set_status(todo_dir, args.key, args.status)
    out.print(
        Text("  ✓ ", style="bold green")
        + Text(item.key, style="bright_white")
        + Text("  ")
        + status_word(item.status)
    )


def set_status(directory: Path, key: str, status: str) -> Item:
    """The item *key* names, or a unique prefix of it, rewritten with *status*."""
    if status not in STATUSES:
        raise ShadError.validation(
            "invalid_status",
            f"unknown status '{status}'; must be one of: {', '.join(STATUSES)}",
        )
    return store.set_status(directory, store.resolve_key(directory, key), status)
