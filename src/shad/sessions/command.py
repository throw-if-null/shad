"""
`shad sessions` — save the running shad sessions, bring them back, stop them.

Actions:
  save      pick the running sessions to record, with their conversations
  restore   create each saved session that is not running, then attach
  stop      pick running sessions and kill them
  show      print what is saved

save and stop show the same picker over the live sessions. The snapshot is
exactly what save's picker accepted, and nothing keeps it current afterwards:
a session opened or stopped later is not in it until the next save.
"""

from __future__ import annotations

import argparse
import shutil
import time
from collections.abc import Iterable, Sequence

from rich.console import Console
from rich.text import Text

from shad.projects.open.layout import _create_session
from shad.sessions import live, render, restore, store
from shad.sessions.live import Running
from shad.sessions.model import Snapshot
from shad.sessions.restore import Step
from shad.shared.config import Config
from shad.shared.errors import ShadError
from shad.shared.picker import NoTerminal, pick_many
from shad.shared.render import relative_age
from shad.shared.tmux import _attach, current_session, kill_session

console = Console()

ACTIONS = ("save", "restore", "stop", "show")


def cmd_sessions(cfg: Config, args: argparse.Namespace) -> int | None:
    """Returns the tmux exit code when restore attached, else None."""
    action = getattr(args, "sessions_action", None)
    if action is None:
        raise ShadError(f"no sessions action given; available: {', '.join(ACTIONS)}")
    if action not in ACTIONS:
        raise ShadError(f"unknown sessions action '{action}'; available: {', '.join(ACTIONS)}")

    if action == "save":
        _save(cfg, everything=getattr(args, "all", False))
    elif action == "restore":
        return _restore(cfg, attach=not getattr(args, "no_attach", False))
    elif action == "stop":
        _stop(cfg)
    else:
        _show()
    return None


# ── save ──────────────────────────────────────────────────────────────────


def _save(cfg: Config, *, everything: bool) -> None:
    running = live.collect(cfg)
    for skipped in running:
        if skipped.unsupported:
            console.print(
                Text("  ✗ ", style="bold red")
                + Text(skipped.session, style="bright_white")
                + Text(f"  {skipped.unsupported}", style="dim")
            )
    savable = [item for item in running if item.unsupported is None]
    if not savable:
        if running:
            raise ShadError("no session could be saved; the saved sessions are unchanged")
        raise ShadError("no shad sessions are running; the saved sessions are unchanged")

    if everything:
        chosen = savable
    else:
        picked = _pick(
            savable,
            _previously_saved(savable),
            title="save sessions",
            accept="save",
            hint="use `shad sessions save --all` to save every running session",
        )
        if picked is None:
            console.print(Text("  cancelled; the saved sessions are unchanged", style="dim"))
            return
        chosen = [savable[index] for index in sorted(picked)]

    snapshot = Snapshot(saved_at=int(time.time()), entries=tuple(item.entry for item in chosen))
    path = store.snapshot_path()
    store.write(path, snapshot)
    _print_rows("saved", chosen, note_missing_id=True)
    console.print(Text(f"  {_count(len(chosen))} saved to {path}", style="dim"))


def _previously_saved(savable: Sequence[Running]) -> set[int]:
    """
    The rows to check before the picker opens: the sessions whose
    conversation the snapshot already holds, or every row when there is no
    snapshot yet.
    """
    path = store.snapshot_path()
    if not path.exists():
        return set(range(len(savable)))
    saved = {entry.session_id for entry in store.read(path).entries if entry.session_id}
    return {
        index
        for index, item in enumerate(savable)
        if item.conversation is not None and item.conversation.id in saved
    }


# ── restore ───────────────────────────────────────────────────────────────


def _restore(cfg: Config, *, attach: bool) -> int | None:
    snapshot = store.read(store.snapshot_path())
    steps = restore.plan(cfg, snapshot, live.collect(cfg))
    for step in steps:
        if step.creates:
            assert step.project is not None
            assert step.command is not None
            assert step.session is not None
            _create_session(step.project, cfg.defaults, step.command, step.session)

    console.print(
        render.table("restored", [(step.entry, _outcome(step)) for step in steps], console.width)
    )

    if not attach:
        return None
    target = restore.attach_target(steps)
    if target is None:
        return None
    return _attach(target)


def _outcome(step: Step) -> Text:
    if step.outcome == "resume":
        return Text("resumed", style="bold green")
    if step.outcome == "new":
        return Text(f"new conversation; {step.reason}", style="yellow")
    if step.outcome == "running":
        return Text("already running", style="dim")
    return Text(f"skipped; {step.reason}", style="red")


# ── stop ──────────────────────────────────────────────────────────────────


def _stop(cfg: Config) -> None:
    running = live.collect(cfg)
    current = current_session()
    rows = [item for item in running if item.session != current]
    if not rows:
        message = "no shad sessions are running"
        if len(rows) < len(running):
            message += " besides this one"
        console.print(Text(f"  {message}", style="dim"))
        return

    picked = _pick(rows, (), title="stop sessions", accept="stop", hint="stop needs a terminal")
    if not picked:
        console.print(Text("  nothing stopped", style="dim"))
        return
    stopped = [rows[index] for index in sorted(picked)]
    for item in stopped:
        kill_session(item.session)
    _print_rows("stopped", stopped)


# ── show ──────────────────────────────────────────────────────────────────


def _show() -> None:
    snapshot = store.read(store.snapshot_path())
    rows = [
        (entry, Text("attached" if entry.attached else "", style="dim"))
        for entry in snapshot.entries
    ]
    console.print(render.table("sessions", rows, console.width))
    console.print(
        Text(
            f"  {_count(len(snapshot.entries))}, saved {relative_age(snapshot.saved_at)} ago",
            style="dim",
        )
    )


# ── shared ────────────────────────────────────────────────────────────────


def _pick(
    rows: Sequence[Running], checked: Iterable[int], *, title: str, accept: str, hint: str
) -> frozenset[int] | None:
    width, height = shutil.get_terminal_size()

    def draw(cursor: int, chosen: frozenset[int]) -> bytes:
        return render.picker(
            rows, cursor, chosen, title=title, accept=accept, width=width, height=height
        )

    try:
        return pick_many(draw, len(rows), checked)
    except NoTerminal:
        raise ShadError(f"no terminal to pick in; {hint}") from None


def _print_rows(title: str, rows: Sequence[Running], *, note_missing_id: bool = False) -> None:
    duplicate = live.duplicates(rows)
    cells = []
    for item in rows:
        state = render.state(item, duplicate=item.session in duplicate)
        if note_missing_id and item.conversation is None:
            state.append("  no conversation id; restores as a new conversation", style="yellow")
        cells.append((item.entry, state))
    console.print(render.table(title, cells, console.width))


def _count(count: int) -> str:
    return f"{count} session" if count == 1 else f"{count} sessions"
