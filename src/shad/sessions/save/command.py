"""
`shad sessions save` — pick the running sessions to record.

The snapshot becomes exactly the rows the picker accepts. Rows whose
conversation the snapshot already holds start checked, or every row when
there is no snapshot yet. `--all` records every running session without the
picker, which is the form that works without a terminal. A session whose
harness cannot be saved is reported on stderr and left out.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Sequence

from rich.text import Text

from shad import parsers
from shad.deps import Deps
from shad.errors import ShadError
from shad.sessions import live, render, store
from shad.sessions.live import Running
from shad.sessions.model import Snapshot
from shad.sessions.pick import pick


def register(sub: parsers.Subparsers) -> None:
    parser = parsers.command(sub, "save", run=run, help="Pick the running shad sessions to record")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Record every running session without the picker; works without a terminal",
    )


def run(args: argparse.Namespace, deps: Deps) -> None:
    cfg = deps.config
    out = deps.out
    running = live.collect(cfg, deps.tmux)
    savable = [item for item in running if item.unsupported is None]
    if not savable:
        if running:
            reasons = "; ".join(f"{item.session}: {item.unsupported}" for item in running)
            raise ShadError.conflict(
                "no_saveable_session",
                f"no session could be saved ({reasons}); the saved sessions are unchanged",
            )
        raise ShadError.not_found(
            "no_running_sessions", "no shad sessions are running; the saved sessions are unchanged"
        )
    for skipped in running:
        if skipped.unsupported:
            out.note(
                Text("  ✗ ", style="bold red")
                + Text(skipped.session, style="bright_white")
                + Text(f"  {skipped.unsupported}", style="dim")
            )

    if getattr(args, "all", False):
        chosen = savable
    else:
        picked = pick(
            savable,
            _previously_saved(savable),
            title="save sessions",
            accept="save",
            hint="use `shad sessions save --all` to save every running session",
        )
        if picked is None:
            out.print(Text("  cancelled; the saved sessions are unchanged", style="dim"))
            return
        chosen = [savable[index] for index in sorted(picked)]

    snapshot = Snapshot(saved_at=int(time.time()), entries=tuple(item.entry for item in chosen))
    path = store.snapshot_path()
    store.write(path, snapshot)
    out.print(render.running_table("saved", chosen, out.width, note_missing_id=True))
    count = f"{len(chosen)} session" if len(chosen) == 1 else f"{len(chosen)} sessions"
    out.print(Text(f"  {count} saved to {path}", style="dim"))


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
