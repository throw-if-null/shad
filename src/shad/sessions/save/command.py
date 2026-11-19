"""
`shad sessions save` — record which running shad sessions to bring back.

The sessions to record are named, or every running session with `--all`, or
chosen in a picker with `--pick`. The snapshot becomes exactly those
sessions. A session whose harness cannot be saved is reported on stderr and
left out; a named session that is not running is an error and nothing is
written.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Sequence

from rich.text import Text

from shad import parsers
from shad.config import Config
from shad.deps import Deps
from shad.errors import ShadError
from shad.sessions import live, render, store
from shad.sessions.live import Running
from shad.sessions.model import Snapshot, parse
from shad.sessions.pick import pick


def register(sub: parsers.Subparsers) -> None:
    parser = parsers.command(sub, "save", run=run, help="Record the running shad sessions")
    parser.add_argument(
        "name",
        nargs="*",
        metavar="NAME",
        help="Session or project names to record; omit with --all or --pick",
    )
    parser.add_argument(
        "--all", action="store_true", help="Record every running session"
    )
    parser.add_argument(
        "--pick", action="store_true", help="Choose the sessions in a picker (needs a terminal)"
    )


def run(args: argparse.Namespace, deps: Deps) -> None:
    cfg = deps.config
    out = deps.out
    running = live.collect(cfg, deps.tmux, deps.harnesses)
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

    chosen = _chosen(args, cfg, savable)
    if chosen is None:
        out.print(Text("  cancelled; the saved sessions are unchanged", style="dim"))
        return

    snapshot = Snapshot(saved_at=int(time.time()), entries=tuple(item.entry for item in chosen))
    path = store.snapshot_path(cfg)
    store.write(path, snapshot)
    out.print(render.running_table("saved", chosen, out.width, note_missing_id=True))
    count = f"{len(chosen)} session" if len(chosen) == 1 else f"{len(chosen)} sessions"
    out.print(Text(f"  {count} saved to {path}", style="dim"))


def _chosen(
    args: argparse.Namespace, cfg: Config, savable: Sequence[Running]
) -> list[Running] | None:
    """The sessions to record: by name, --all, or the picker. None on cancel."""
    if getattr(args, "pick", False):
        picked = pick(
            savable,
            _previously_saved(cfg, savable),
            title="save sessions",
            accept="save",
            hint="pass session names or --all instead",
        )
        return None if picked is None else [savable[index] for index in sorted(picked)]
    if getattr(args, "all", False):
        return list(savable)
    names = list(getattr(args, "name", []))
    if not names:
        raise ShadError.usage(
            "no_selection",
            "name the sessions to save, or pass --all, or --pick to choose in a terminal",
        )
    matched, unmatched = live.resolve_names(savable, names)
    if unmatched:
        raise ShadError.not_found(
            "no_such_session",
            f"no running shad session matches {', '.join(unmatched)}; "
            "the saved sessions are unchanged",
        )
    return [savable[index] for index in matched]


def _previously_saved(cfg: Config, savable: Sequence[Running]) -> set[int]:
    """
    The rows to check before the picker opens: the sessions whose
    conversation the snapshot already holds, or every row when there is no
    snapshot yet.
    """
    path = store.snapshot_path(cfg)
    if not path.exists():
        return set(range(len(savable)))
    saved = {entry.session_id for entry in parse(path.read_text()).entries if entry.session_id}
    return {
        index
        for index, item in enumerate(savable)
        if item.conversation is not None and item.conversation.id in saved
    }
