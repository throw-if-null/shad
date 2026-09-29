"""
Open project command for shad.

Orchestrates: AI session picker → tmux session create/attach.
"""

from __future__ import annotations

from shad.projects.open.layout import _create_session
from shad.projects.open.sessions import pick_claude_target, pick_opencode_target
from shad.shared.config import Defaults, Project
from shad.shared.tmux import _attach, _run, project_session_name, session_exists


def open_project(project: Project, defaults: Defaults) -> int | None:
    """Attach to project session, creating it with the configured layout if needed.

    Returns the tmux exit code on success, or None if the user cancelled.
    """
    if project.harness == "claude":
        target = pick_claude_target(project.path, "claude")
    else:
        target = pick_opencode_target(project.path, "opencode")

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
