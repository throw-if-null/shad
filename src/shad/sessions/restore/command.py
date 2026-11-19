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
from shad.errors import ShadError
from shad.layout import create_session
from shad.output import Output
from shad.sessions import live, render, store
from shad.sessions.model import parse
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
    harnesses = deps.harnesses
    snapshot = parse(_read(store.snapshot_path(cfg)))
    steps = plan.plan(cfg, snapshot, live.collect(cfg, tmux, harnesses), tmux, harnesses)
    failures: list[str] = []
    for step in steps:
        creation = step.creation
        if creation is None:
            continue
        try:
            create_session(tmux, creation.project, cfg.defaults, creation.command, creation.session)
        except ShadError as exc:
            # One session that cannot be created must not abort the rest
            # ([ERR-4]); it is reported and the run exits 1.
            failures.append(f"{step.entry.display_name}: {exc.message}")
            deps.trace.exception(exc)

    out.print(
        render.table("restored", [(step.entry, _outcome(step)) for step in steps], out.width)
    )
    for failure in failures:
        out.note(Text("  ✗ ", style="bold red") + Text(failure, style="dim"))
    if failures:
        raise ShadError.infrastructure(
            "partial_failure", f"{len(failures)} session(s) could not be restored"
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


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ShadError.not_found(
            "no_snapshot", f"no saved sessions at {path}; run `shad sessions save` first"
        ) from None


def _outcome(step: plan.Step) -> Text:
    if step.outcome == "resume":
        return Text("resumed", style="bold green")
    if step.outcome == "new":
        return Text(f"new conversation; {step.reason}", style="yellow")
    if step.outcome == "running":
        return Text("already running", style="dim")
    return Text(f"skipped; {step.reason}", style="red")
