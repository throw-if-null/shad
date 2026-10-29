"""`shad todo rm` — delete one item's file."""

from __future__ import annotations

import argparse

from rich.console import Console
from rich.text import Text

from shad.shared.config import Config
from shad.todo import store

console = Console()


def remove_todo(cfg: Config, args: argparse.Namespace) -> None:
    directory = store.todo_dir(cfg)
    key = store.resolve_key(directory, args.key)
    path = store.remove(directory, key)
    console.print(
        Text("  ✓ ", style="bold green")
        + Text(f"removed {key}", style="bright_white")
        + Text(f"  {path}", style="dim")
    )
