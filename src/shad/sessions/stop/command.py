"""
`shad sessions stop` — kill running shad sessions.

The sessions to kill are named, or every running one with `--all`, or chosen
in a picker with `--pick`. Each named session is reported, and a name that
matches nothing is reported too; the run exits 1 when any name matched
nothing, after killing the ones that did. The session the command runs in is
left out, because killing it would detach the client mid-command. The
snapshot is not touched: whether a session comes back is `save`'s decision.
"""

from __future__ import annotations

import argparse

from rich.text import Text

from shad import parsers
from shad.deps import Deps
from shad.errors import ShadError
from shad.output import Output
from shad.sessions import live, render
from shad.sessions.pick import pick


def register(sub: parsers.Subparsers) -> None:
    parser = parsers.command(sub, "stop", run=run, help="Kill running shad sessions")
    parser.add_argument(
        "name",
        nargs="*",
        metavar="NAME",
        help="Session or project names to kill; omit with --all or --pick",
    )
    parser.add_argument("--all", action="store_true", help="Kill every running session")
    parser.add_argument(
        "--pick", action="store_true", help="Choose the sessions in a picker (needs a terminal)"
    )


def run(args: argparse.Namespace, deps: Deps) -> None:
    out = deps.out
    tmux = deps.tmux
    running = live.collect(deps.config, tmux, deps.harnesses)
    current = tmux.current_session()
    rows = [item for item in running if item.session != current]
    if not rows:
        message = "no shad sessions are running"
        if running:
            message += " besides this one"
        out.print(Text(f"  {message}", style="dim"))
        return

    unmatched: list[str] = []
    if getattr(args, "pick", False):
        picked = pick(rows, (), title="stop sessions", accept="stop", hint="pass names or --all")
        if not picked:
            out.print(Text("  nothing stopped", style="dim"))
            return
        chosen = [rows[index] for index in sorted(picked)]
    elif getattr(args, "all", False):
        chosen = list(rows)
    else:
        names = list(getattr(args, "name", []))
        if not names:
            raise ShadError.usage(
                "no_selection",
                "name the sessions to stop, or pass --all, or --pick to choose in a terminal",
            )
        matched, unmatched = live.resolve_names(rows, names)
        chosen = [rows[index] for index in matched]

    for item in chosen:
        tmux.kill_session(item.session)
    if chosen:
        out.print(render.running_table("stopped", chosen, out.width))
    _report_unmatched(unmatched, out)
    if unmatched:
        raise ShadError.not_found(
            "no_such_session", f"no running shad session matches {', '.join(unmatched)}"
        )


def _report_unmatched(unmatched: list[str], out: Output) -> None:
    for name in unmatched:
        out.note(
            Text("  ✗ ", style="bold red")
            + Text(name, style="bright_white")
            + Text("  no running shad session by that name", style="dim")
        )
