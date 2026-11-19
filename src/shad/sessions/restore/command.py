"""
`shad sessions restore` — create each saved session that is not running.

`plan.py` decides what each saved entry needs; this module applies the
steps that create a tmux session, prints the outcome, opens a terminal tab
for each other session that was attached at save, and attaches. A tab that
could not be opened is reported on stderr with the command that attaches
its session.
"""

from __future__ import annotations

import argparse
import shlex
from pathlib import Path

from rich.text import Text

from shad import parsers
from shad.deps import Deps
from shad.layout import create_session
from shad.output import Output
from shad.sessions import live, render, store
from shad.sessions.restore import plan, terminal
from shad.tmux import Tmux


def register(sub: parsers.Subparsers) -> None:
    parser = parsers.command(
        sub,
        "restore",
        run=run,
        help="Create the saved sessions that are not running, then attach (hands over to tmux)",
    )
    parser.add_argument(
        "--no-attach",
        action="store_true",
        help="Create the sessions without attaching to one or opening tabs",
    )


def run(args: argparse.Namespace, deps: Deps) -> int | None:
    """Returns the tmux exit code when a session was attached, else None."""
    cfg = deps.config
    out = deps.out
    tmux = deps.tmux
    snapshot = store.read(store.snapshot_path())
    steps = plan.plan(cfg, snapshot, live.collect(cfg, tmux), tmux)
    for step in steps:
        creation = step.creation
        if creation is not None:
            create_session(tmux, creation.project, cfg.defaults, creation.command, creation.session)

    out.print(
        render.table("restored", [(step.entry, _outcome(step)) for step in steps], out.width)
    )

    if getattr(args, "no_attach", False):
        return None
    target = plan.attach_target(steps)
    if target is None:
        return None
    _open_tabs(plan.tab_targets(steps, target, tmux.attached_sessions()), out)
    return tmux.attach(target)


def _open_tabs(tabs: list[tuple[str, Path]], out: Output) -> None:
    """
    One terminal tab per (session, directory), running the attach. After
    the first failure the rest are not tried, because the cause is the
    terminal and each try can wait out the timeout. Every session that got
    no tab is reported on stderr with the command that attaches it.
    """
    if not tabs:
        return
    term = terminal.current()
    reason = "the terminal is not kitty" if term is None else None
    left: list[str] = []
    for session, cwd in tabs:
        if term is not None and reason is None:
            reason = terminal.open_tab(term, Tmux.attach_command(session), cwd)
        if reason is not None:
            left.append(session)
    if not left:
        return
    out.note(Text(f"no tab for {len(left)} session(s): {reason}", style="yellow"))
    out.note(Text("attach them with:"))
    for session in left:
        out.note(Text(f"  {shlex.join(Tmux.attach_command(session))}"))


def _outcome(step: plan.Step) -> Text:
    if step.outcome == "resume":
        return Text("resumed", style="bold green")
    if step.outcome == "new":
        return Text(f"new conversation; {step.reason}", style="yellow")
    if step.outcome == "running":
        return Text("already running", style="dim")
    return Text(f"skipped; {step.reason}", style="red")
