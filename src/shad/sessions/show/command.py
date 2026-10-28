"""`shad sessions show` — print the saved sessions."""

from __future__ import annotations

import argparse

from rich.console import Console
from rich.text import Text

from shad.sessions import render, store
from shad.shared.config import Config
from shad.shared.render import relative_age

console = Console()


def show_sessions(cfg: Config, args: argparse.Namespace) -> None:
    snapshot = store.read(store.snapshot_path())
    rows = [
        (entry, Text("attached" if entry.attached else "", style="dim"))
        for entry in snapshot.entries
    ]
    console.print(render.table("sessions", rows, console.width))
    total = len(snapshot.entries)
    count = f"{total} session" if total == 1 else f"{total} sessions"
    console.print(
        Text(f"  {count}, saved {relative_age(snapshot.saved_at)} ago", style="dim")
    )
