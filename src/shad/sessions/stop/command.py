"""
`shad sessions stop` — pick running sessions and kill them.

Nothing starts checked. The session the command runs in is not listed,
because killing it would detach the client mid-command. The snapshot is not
touched: whether a session comes back is `save`'s decision.
"""

from __future__ import annotations

import argparse

from rich.console import Console
from rich.text import Text

from shad.sessions import live, render
from shad.sessions.pick import pick
from shad.shared.config import Config
from shad.shared.tmux import current_session, kill_session

console = Console()


def stop_sessions(cfg: Config, args: argparse.Namespace) -> None:
    running = live.collect(cfg)
    current = current_session()
    rows = [item for item in running if item.session != current]
    if not rows:
        message = "no shad sessions are running"
        if running:
            message += " besides this one"
        console.print(Text(f"  {message}", style="dim"))
        return

    picked = pick(rows, (), title="stop sessions", accept="stop", hint="stop needs a terminal")
    if not picked:
        console.print(Text("  nothing stopped", style="dim"))
        return
    stopped = [rows[index] for index in sorted(picked)]
    for item in stopped:
        kill_session(item.session)
    console.print(render.running_table("stopped", stopped, console.width))
