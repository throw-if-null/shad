"""`shad todo rm` — delete one item's file. `remove` is also what the panel's `d` key runs."""

from __future__ import annotations

import argparse
from pathlib import Path

from rich.text import Text

from shad import parsers
from shad.output import Output
from shad.todo import store


def register(sub: parsers.Subparsers) -> None:
    parser = parsers.command(sub, "rm", run=run, help="Delete an item")
    parser.add_argument("key", metavar="KEY", help="Item key, or a unique prefix")


def run(args: argparse.Namespace, *, out: Output, todo_dir: Path) -> None:
    key = store.resolve_key(todo_dir, args.key)
    path = remove(todo_dir, key)
    out.print(
        Text("  ✓ ", style="bold green")
        + Text(f"removed {key}", style="bright_white")
        + Text(f"  {path}", style="dim")
    )


def remove(directory: Path, key: str) -> Path:
    """Delete the item *key* names, or a unique prefix of it; returns the file it was."""
    return store.remove(directory, store.resolve_key(directory, key))
