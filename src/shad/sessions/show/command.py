"""`shad sessions show` — the saved sessions, as a result."""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from rich.text import Text

from shad import parsers
from shad.deps import Deps
from shad.output import Output
from shad.sessions import render, store
from shad.sessions.model import Entry
from shad.style import relative_age


@dataclass(frozen=True)
class SavedSessions:
    saved_at: int  # unix seconds
    sessions: tuple[Entry, ...]


def register(sub: parsers.Subparsers) -> None:
    parsers.command(sub, "show", run=run, render=render_saved, help="Print the saved sessions")


def run(args: argparse.Namespace, deps: Deps) -> SavedSessions:
    snapshot = store.read(store.snapshot_path(deps.config))
    return SavedSessions(saved_at=snapshot.saved_at, sessions=snapshot.entries)


def render_saved(result: SavedSessions, out: Output) -> None:
    rows = [
        (entry, Text("attached" if entry.attached else "", style="dim"))
        for entry in result.sessions
    ]
    out.print(render.table("sessions", rows, out.width))
    total = len(result.sessions)
    count = f"{total} session" if total == 1 else f"{total} sessions"
    out.print(Text(f"  {count}, saved {relative_age(result.saved_at)} ago", style="dim"))
