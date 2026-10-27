"""
`shad sessions` — save the running shad sessions, and bring them back.

Actions:
  save      record every running shad tmux session and its conversation id
  restore   create each saved session that is not running, then attach
  show      print what is saved

The snapshot is read from tmux when `save` runs and is exact for that moment.
Nothing keeps it current afterwards: a session opened or stopped later is not
in it until the next `save`.
"""

from __future__ import annotations

import argparse
import time

from rich.console import Console
from rich.text import Text

from shad.projects.open.layout import _create_session
from shad.sessions import live, restore, store
from shad.sessions.model import Entry, Snapshot
from shad.sessions.restore import Step
from shad.shared.config import Config
from shad.shared.errors import ShadError
from shad.shared.render import make_table, relative_age
from shad.shared.tmux import _attach

console = Console()

ACTIONS = ("save", "restore", "show")

_ID_WIDTH = 8


def cmd_sessions(cfg: Config, args: argparse.Namespace) -> int | None:
    """Returns the tmux exit code when restore attached, else None."""
    action = getattr(args, "sessions_action", None)
    if action is None:
        raise ShadError(f"no sessions action given; available: {', '.join(ACTIONS)}")
    if action not in ACTIONS:
        raise ShadError(f"unknown sessions action '{action}'; available: {', '.join(ACTIONS)}")

    if action == "save":
        _save(cfg)
    elif action == "restore":
        return _restore(cfg, attach=not getattr(args, "no_attach", False))
    else:
        _show()
    return None


def _save(cfg: Config) -> None:
    collected = live.collect(cfg)
    for skipped in collected.skipped:
        console.print(
            Text("  ✗ ", style="bold red")
            + Text(skipped.session, style="bright_white")
            + Text(f"  {skipped.reason}", style="dim")
        )
    if not collected.entries:
        if collected.skipped:
            raise ShadError("no session could be saved; the saved sessions are unchanged")
        raise ShadError("no shad sessions are running; the saved sessions are unchanged")

    snapshot = Snapshot(saved_at=int(time.time()), entries=tuple(collected.entries))
    path = store.snapshot_path()
    store.write(path, snapshot)

    table = make_table("saved")
    for entry in snapshot.entries:
        table.add_row(*_entry_cells(entry), _save_note(entry))
    console.print(table)
    console.print(Text(f"  {_count(snapshot.entries)} saved to {path}", style="dim"))


def _restore(cfg: Config, *, attach: bool) -> int | None:
    snapshot = store.read(store.snapshot_path())
    steps = restore.plan(cfg, snapshot, live.collect(cfg).running)
    for step in steps:
        if step.creates:
            assert step.project is not None
            assert step.command is not None
            assert step.session is not None
            _create_session(step.project, cfg.defaults, step.command, step.session)

    table = make_table("restored")
    for step in steps:
        table.add_row(*_entry_cells(step.entry), _outcome(step))
    console.print(table)

    if not attach:
        return None
    target = restore.attach_target(steps)
    if target is None:
        return None
    return _attach(target)


def _show() -> None:
    snapshot = store.read(store.snapshot_path())
    table = make_table("sessions")
    for entry in snapshot.entries:
        table.add_row(
            *_entry_cells(entry),
            Text("attached" if entry.attached else "", style="dim"),
        )
    if not snapshot.entries:
        table.add_row(Text("no sessions", style="dim"), "", "", "")
    console.print(table)
    console.print(
        Text(
            f"  {_count(snapshot.entries)}, saved {relative_age(snapshot.saved_at)} ago",
            style="dim",
        )
    )


# ── rendering ─────────────────────────────────────────────────────────────


def _entry_cells(entry: Entry) -> tuple[Text, Text, Text]:
    session_id = entry.session_id[:_ID_WIDTH] if entry.session_id else "—"
    return (
        Text(entry.display_name, style="bright_white"),
        Text(entry.harness, style="dim"),
        Text(session_id, style="yellow" if entry.session_id else "dim"),
    )


def _save_note(entry: Entry) -> Text:
    if entry.session_id is None:
        return Text("no conversation id; restores as a new conversation", style="yellow")
    return Text("attached" if entry.attached else "", style="dim")


def _outcome(step: Step) -> Text:
    if step.outcome == "resume":
        return Text("resumed", style="bold green")
    if step.outcome == "new":
        return Text(f"new conversation; {step.reason}", style="yellow")
    if step.outcome == "running":
        return Text("already running", style="dim")
    return Text(f"skipped; {step.reason}", style="red")


def _count(entries: tuple[Entry, ...]) -> str:
    return f"{len(entries)} session" if len(entries) == 1 else f"{len(entries)} sessions"
