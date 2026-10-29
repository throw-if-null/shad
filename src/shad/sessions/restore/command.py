"""
`shad sessions restore` — create each saved session that is not running.

`plan.py` decides what each saved entry needs; this module applies the
steps that create a tmux session, prints the outcome, opens a terminal tab
for each other session that was attached at save, and attaches.
"""

from __future__ import annotations

import argparse
import shlex

from rich.console import Console
from rich.text import Text

from shad.projects.open.layout import _create_session
from shad.sessions import live, render, store
from shad.sessions.restore import plan
from shad.sessions.restore.plan import Step
from shad.shared import terminal
from shad.shared.config import Config
from shad.shared.tmux import _attach, attach_command, attached_sessions

console = Console()


def restore_sessions(cfg: Config, args: argparse.Namespace) -> int | None:
    """Returns the tmux exit code when a session was attached, else None."""
    snapshot = store.read(store.snapshot_path())
    steps = plan.plan(cfg, snapshot, live.collect(cfg))
    for step in steps:
        if step.creates:
            assert step.project is not None
            assert step.command is not None
            assert step.session is not None
            _create_session(step.project, cfg.defaults, step.command, step.session)

    console.print(
        render.table("restored", [(step.entry, _outcome(step)) for step in steps], console.width)
    )

    if getattr(args, "no_attach", False):
        return None
    target = plan.attach_target(steps)
    if target is None:
        return None
    _open_tabs(plan.tab_targets(steps, target, attached_sessions()))
    return _attach(target)


def _open_tabs(steps: list[Step]) -> None:
    """
    One terminal tab per step, running the attach. After the first failure
    the rest are not tried, because the cause is the terminal and each try
    can wait out the timeout. Every session that got no tab is printed with
    the command that attaches it.
    """
    if not steps:
        return
    term = terminal.current()
    reason = "the terminal is not kitty" if term is None else None
    left: list[str] = []
    for step in steps:
        assert step.session is not None
        assert step.project is not None
        if term is not None and reason is None:
            reason = terminal.open_tab(term, attach_command(step.session), step.project.path)
        if reason is not None:
            left.append(step.session)
    if not left:
        return
    console.print(Text(f"no tab for {len(left)} session(s): {reason}", style="yellow"))
    console.print(Text("attach them with:"))
    for session in left:
        console.print(Text(f"  {shlex.join(attach_command(session))}"))


def _outcome(step: Step) -> Text:
    if step.outcome == "resume":
        return Text("resumed", style="bold green")
    if step.outcome == "new":
        return Text(f"new conversation; {step.reason}", style="yellow")
    if step.outcome == "running":
        return Text("already running", style="dim")
    return Text(f"skipped; {step.reason}", style="red")
