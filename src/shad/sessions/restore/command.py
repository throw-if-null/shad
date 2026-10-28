"""
`shad sessions restore` — create each saved session that is not running.

`plan.py` decides what each saved entry needs; this module applies the
steps that create a tmux session, prints the outcome, and attaches.
"""

from __future__ import annotations

import argparse

from rich.console import Console
from rich.text import Text

from shad.projects.open.layout import _create_session
from shad.sessions import live, render, store
from shad.sessions.restore import plan
from shad.sessions.restore.plan import Step
from shad.shared.config import Config
from shad.shared.tmux import _attach

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
    return _attach(target)


def _outcome(step: Step) -> Text:
    if step.outcome == "resume":
        return Text("resumed", style="bold green")
    if step.outcome == "new":
        return Text(f"new conversation; {step.reason}", style="yellow")
    if step.outcome == "running":
        return Text("already running", style="dim")
    return Text(f"skipped; {step.reason}", style="red")
