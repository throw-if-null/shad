"""
`shad sessions stop` — pick running sessions and kill them.

Nothing starts checked. The session the command runs in is not listed,
because killing it would detach the client mid-command. The snapshot is not
touched: whether a session comes back is `save`'s decision.
"""

from __future__ import annotations

import argparse

from rich.text import Text

from shad import parsers
from shad.deps import Deps
from shad.sessions import live, render
from shad.sessions.pick import pick
from shad.shared.tmux import current_session, kill_session


def register(sub: parsers.Subparsers) -> None:
    parsers.command(sub, "stop", run=run, help="Pick running shad sessions and kill them")


def run(args: argparse.Namespace, deps: Deps) -> None:
    out = deps.out
    running = live.collect(deps.config)
    current = current_session()
    rows = [item for item in running if item.session != current]
    if not rows:
        message = "no shad sessions are running"
        if running:
            message += " besides this one"
        out.print(Text(f"  {message}", style="dim"))
        return

    picked = pick(rows, (), title="stop sessions", accept="stop", hint="stop needs a terminal")
    if not picked:
        out.print(Text("  nothing stopped", style="dim"))
        return
    stopped = [rows[index] for index in sorted(picked)]
    for item in stopped:
        kill_session(item.session)
    out.print(render.running_table("stopped", stopped, out.width))
