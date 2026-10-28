"""`shad todo status` — set one item's status."""

from __future__ import annotations

import argparse

from rich.console import Console
from rich.text import Text

from shad.shared.config import Config
from shad.shared.errors import ShadError
from shad.todo import store
from shad.todo.model import STATUSES
from shad.todo.render import status_word

console = Console()


def set_todo_status(cfg: Config, args: argparse.Namespace) -> None:
    if args.status not in STATUSES:
        raise ShadError(f"unknown status '{args.status}'; must be one of: {', '.join(STATUSES)}")
    directory = store.todo_dir(cfg)
    key = store.resolve_key(directory, args.key)
    item = store.set_status(directory, key, args.status)
    console.print(
        Text("  ✓ ", style="bold green")
        + Text(item.key, style="bright_white")
        + Text("  ")
        + status_word(item.status)
    )
