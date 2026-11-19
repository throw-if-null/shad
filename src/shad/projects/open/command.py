"""
Open project command for shad.

Orchestrates: AI session picker → tmux session create/attach.
"""

from __future__ import annotations

import argparse

from shad.projects.open.layout import _create_session
from shad.projects.open.sessions import pick_claude_target, pick_opencode_target
from shad.shared.config import HARNESSES, Defaults, Project
from shad.shared.tmux import _attach, _run, project_session_name, session_exists


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """The options of the `projects` line that open alone reads."""
    parser.add_argument(
        "--harness",
        choices=HARNESSES,
        help=(
            "Open with this harness instead of the project's configured one. "
            "Applies to open only; status ignores it."
        ),
    )


def open_project(
    project: Project, defaults: Defaults, harness: str | None = None
) -> int | None:
    """Attach to project session, creating it with the configured layout if needed.

    *harness* overrides the project's configured harness for this open only;
    None keeps it. Config parsing already seeds every project with the
    [defaults] harness, so project.harness is the fallback.

    Returns the tmux exit code on success, or None if the user cancelled.
    """
    selected = harness or project.harness

    if selected == "claude":
        target = pick_claude_target(project.path, selected)
    else:
        target = pick_opencode_target(project.path, selected)

    if target is None:
        return None

    session = project_session_name(project.session, target)

    if session_exists(session):
        if target.fresh:
            _run(["tmux", "kill-session", "-t", session], check=False)
        else:
            return _attach(session)

    _create_session(project, defaults, target.command, session)
    return _attach(session)
