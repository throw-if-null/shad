"""
tmux integration for shad.

Layout on first creation:
  ┌─────────────────────────────────┐
  │  top pane  (top_command)        │  65% height
  ├─────────────────────┬───────────┤
  │  bottom-left  (70%) │ right 30% │  35% height
  └─────────────────────┴───────────┘

If run inside an existing tmux session ($TMUX is set), uses
`switch-client` instead of `attach-session`.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from shad.config import Defaults, Project


def _run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=check, capture_output=True, text=True)


def session_exists(name: str) -> bool:
    result = _run(["tmux", "has-session", "-t", name], check=False)
    return result.returncode == 0


def _create_session(project: Project, defaults: Defaults) -> None:
    """Create a new tmux session with the standard 3-pane layout."""
    session = project.session
    cwd = str(project.path)

    # 1. Create session (detached), window name = session name
    _run([
        "tmux", "new-session",
        "-d",                   # detached
        "-s", session,
        "-n", session,
        "-c", cwd,
    ])

    # 2. Disable automatic window rename
    _run(["tmux", "set-option", "-t", session, "allow-rename", "off"])

    # 3. Run top_command in the initial (top) pane
    _run(["tmux", "send-keys", "-t", f"{session}:0.0", defaults.top_command + "\n"])

    # 4. Split top/bottom — bottom takes bottom_percent% of the window height
    _run([
        "tmux", "split-window",
        "-t", f"{session}:0.0",
        "-v",
        "-p", str(defaults.bottom_percent),
        "-c", cwd,
    ])
    # After split: pane 0 = top, pane 1 = bottom

    # 5. Split bottom pane left/right — right takes right_percent%
    _run([
        "tmux", "split-window",
        "-t", f"{session}:0.1",
        "-h",
        "-p", str(defaults.right_percent),
        "-c", cwd,
    ])
    # After split: pane 0 = top, pane 1 = bottom-left, pane 2 = bottom-right

    # 6. Select the top pane so focus lands there on attach
    _run(["tmux", "select-pane", "-t", f"{session}:0.0"])


def _attach(session: str) -> None:
    """Attach or switch to the named tmux session."""
    inside_tmux = os.environ.get("TMUX") is not None

    if inside_tmux:
        cmd = ["tmux", "switch-client", "-t", session]
    else:
        cmd = ["tmux", "attach-session", "-t", session]

    # exec-style: replace the current process so the terminal behaves naturally
    result = subprocess.run(cmd)
    sys.exit(result.returncode)


def open_project(project: Project, defaults: Defaults) -> None:
    """Attach to project session, creating it with the default layout if needed."""
    if not session_exists(project.session):
        _create_session(project, defaults)
    _attach(project.session)
