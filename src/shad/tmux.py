"""
tmux integration for shad.

Layout on first creation:
  ┌─────────────────────────────────┐
  │  top pane  (top_command)        │  65% height
  ├─────────────────────┬───────────┤
  │  bottom-left  (70%) │  gitui    │  35% height
  └─────────────────────┴───────────┘

If run inside an existing tmux session ($TMUX is set), uses
`switch-client` instead of `attach-session`.
"""

from __future__ import annotations

import os
import subprocess
import sys

from shad.config import Defaults, Project
from shad.sessions import show_session_menu


def _run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=check, capture_output=True, text=True)


def session_exists(name: str) -> bool:
    result = _run(["tmux", "has-session", "-t", name], check=False)
    return result.returncode == 0


def _base_opencode_cmd(top_command: str) -> str:
    """Strip any trailing session flags (-c / -s ...) from top_command."""
    cmd = top_command.rstrip()
    if cmd.endswith(" -c"):
        cmd = cmd[:-3].rstrip()
    return cmd


def _create_session(project: Project, defaults: Defaults) -> None:
    """Create a new tmux session with the standard 3-pane layout.

    The top pane is left as a plain shell — opencode is started separately
    via the session picker menu so the user can choose which session to open.
    """
    session = project.session
    cwd = str(project.path)

    # 1. Create session (detached), window name = session name
    _run([
        "tmux", "new-session",
        "-d",
        "-s", session,
        "-n", session,
        "-c", cwd,
    ])

    # 2. Disable automatic window rename
    _run(["tmux", "set-option", "-t", session, "allow-rename", "off"])

    # 3. Split top/bottom — bottom takes bottom_percent% of the window height
    _run([
        "tmux", "split-window",
        "-t", f"{session}:0.0",
        "-v",
        "-p", str(defaults.bottom_percent),
        "-c", cwd,
    ])

    # 4. Split bottom pane left/right — right takes right_percent%
    _run([
        "tmux", "split-window",
        "-t", f"{session}:0.1",
        "-h",
        "-p", str(defaults.right_percent),
        "-c", cwd,
    ])

    # 5. Run gitui in the bottom-right pane
    _run(["tmux", "send-keys", "-t", f"{session}:0.2", "gitui\n"])

    # 6. Run status in the bottom-left pane
    if project.group:
        status_cmd = f"shad projects {project.group} {project.key} status"
    else:
        status_cmd = f"shad projects {project.key} status"
    _run(["tmux", "send-keys", "-t", f"{session}:0.1", status_cmd + "\n"])

    # 7. Select the top pane so focus lands there on attach
    _run(["tmux", "select-pane", "-t", f"{session}:0.0"])


def _attach(session: str) -> None:
    """Attach or switch to the named tmux session."""
    inside_tmux = os.environ.get("TMUX") is not None

    if inside_tmux:
        cmd = ["tmux", "switch-client", "-t", session]
    else:
        cmd = ["tmux", "attach-session", "-t", session]

    result = subprocess.run(cmd)
    sys.exit(result.returncode)


def open_project(project: Project, defaults: Defaults) -> None:
    """Attach to project session, creating it with the default layout if needed."""
    if not session_exists(project.session):
        _create_session(project, defaults)

    # Derive the base opencode command (without any session flags)
    base_cmd = _base_opencode_cmd(defaults.top_command)

    # Show a tmux display-menu to pick an opencode session.
    # The menu sends the chosen opencode command directly to the top pane,
    # so opencode is already starting when the user arrives in the session.
    # Falls back gracefully (no-op) if outside tmux or DB is unavailable.
    show_session_menu(project.path, project.session, base_cmd)

    _attach(project.session)


def stop_project(project: Project) -> None:
    """Kill the tmux session for a project, if it is running."""
    if not session_exists(project.session):
        print(f"session '{project.session}' is not running")
        return
    _run(["tmux", "kill-session", "-t", project.session])
    print(f"session '{project.session}' stopped")
