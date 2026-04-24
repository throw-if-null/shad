"""
Stop project command for shad.

Kills all tmux sessions belonging to a project.
"""

from __future__ import annotations

from rich.console import Console
from rich.text import Text

from shad.shared.config import Project
from shad.shared.tmux import _run, list_project_sessions

console = Console()


def stop_project(project: Project) -> None:
    """Kill tmux sessions for a project, if any are running."""
    sessions = list_project_sessions(project.session)
    if not sessions:
        console.print(Text(f"session '{project.session}' is not running", style="dim"))
        return

    for session in sessions:
        _run(["tmux", "kill-session", "-t", session])

    if len(sessions) == 1:
        console.print(Text(f"session '{sessions[0]}' stopped", style="bold green"))
    else:
        console.print(Text(f"stopped {len(sessions)} sessions for '{project.session}'", style="bold green"))
