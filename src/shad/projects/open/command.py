"""
Open project command for shad.

Orchestrates: AI session picker → tmux session create/attach.
"""

from __future__ import annotations

import argparse

from shad.config import HARNESSES, Defaults, Project
from shad.harness import Harnesses
from shad.layout import create_session
from shad.projects.open.sessions import pick_target
from shad.tmux import Tmux, project_session_name


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
    project: Project,
    defaults: Defaults,
    tmux: Tmux,
    harnesses: Harnesses,
    harness: str | None = None,
) -> int | None:
    """Attach to project session, creating it with the configured layout if needed.

    *harness* overrides the project's configured harness for this open only;
    None keeps it. Config parsing already seeds every project with the
    [defaults] harness, so project.harness is the fallback.

    Returns the tmux exit code on success, or None if the user cancelled.
    """
    selected = harness or project.harness
    target = pick_target(harnesses.known[selected], project.path, selected)
    if target is None:
        return None

    session = project_session_name(project.session, target.session_prefix, target.session_key)

    if tmux.session_exists(session):
        if target.fresh:
            tmux.run("kill-session", "-t", session, check=False)
        else:
            return tmux.attach(session)

    create_session(tmux, project, defaults, target.command, session)
    return tmux.attach(session)
