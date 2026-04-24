"""
tmux integration for shad.

Layout (oc_position = "top", the default):
  ┌─────────────────────────────────┐
  │  opencode          (top pane)   │  ~65% height
  ├─────────────────────┬───────────┤
  │  bash         (~65%)│  gitui    │  ~35% height
  └─────────────────────┴───────────┘

oc_position = "bottom":
  ┌─────────────────────┬───────────┐
  │  bash         (~65%)│  gitui    │  ~65% height
  ├─────────────────────┴───────────┤
  │  opencode                       │  ~35% height
  └─────────────────────────────────┘

oc_position = "left":
  ┌──────────┬──────────────────────┐
  │          │  bash                │  ~65% of bundle height
  │opencode  ├──────────────────────┤
  │          │  gitui               │  ~35% of bundle height
  └──────────┴──────────────────────┘

panel_percent controls how much of the window the git+bash bundle takes.
split_percent controls how much of the bundle gitui takes (bash gets the rest).

If run inside an existing tmux session ($TMUX is set), uses
`switch-client` instead of `attach-session`.
"""

from __future__ import annotations

import os
import re
import subprocess

from rich.console import Console
from rich.text import Text

from shad.config import Defaults, Project
from shad.sessions import OpencodeTarget, pick_opencode_target

console = Console()


_SESSION_KEY_RE = re.compile(r"[^A-Za-z0-9_-]+")


def _run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=check, capture_output=True, text=True)


def session_exists(name: str) -> bool:
    result = _run(["tmux", "has-session", "-t", name], check=False)
    return result.returncode == 0


def project_session_name(base_session: str, target: OpencodeTarget) -> str:
    """Resolve the tmux session name for a project and opencode target."""
    if not target.session_key:
        return base_session

    session_key = _SESSION_KEY_RE.sub("_", target.session_key).strip("_")
    if not session_key:
        session_key = "session"

    return f"{base_session}--oc-{session_key}"


def tmux_server_running() -> bool:
    """Return True if a tmux server is currently running."""
    result = _run(["tmux", "list-sessions"], check=False)
    if result.returncode == 0:
        return True
    # tmux exits 1 with "no server running" or "no sessions" when the server
    # is not up. Only treat the explicit "no server" message as server-down;
    # any other non-zero exit (e.g. socket permission error) is left as True
    # so the caller gets a real tmux error rather than a misleading status.
    return "no server running" not in result.stderr.lower()


def list_project_sessions(base_session: str) -> list[str]:
    """Return tmux sessions belonging to the project's base session name."""
    result = _run(["tmux", "list-sessions", "-F", "#S"], check=False)
    if result.returncode != 0:
        return []

    prefix = f"{base_session}--oc-"
    return [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip() == base_session or line.strip().startswith(prefix)
    ]


def _create_session(project: Project, defaults: Defaults, oc_command: str, session: str) -> None:
    """Create a new tmux session with the configured layout."""
    cwd = str(project.path)
    pos = defaults.oc_position
    panel_percent = defaults.panel_percent   # bundle's share of the window
    split_percent = defaults.split_percent   # gitui's share inside the bundle

    # 1. Create session (detached)
    _run(["tmux", "new-session", "-d", "-s", session, "-n", session, "-c", cwd])
    _run(["tmux", "set-option", "-t", session, "allow-rename", "off"])

    if pos == "top":
        # OC top, bundle below — horizontal split within bundle
        _run(["tmux", "send-keys", "-t", f"{session}:0.0", oc_command + "\n"])
        _run(["tmux", "split-window", "-t", f"{session}:0.0",
              "-v", "-p", str(panel_percent), "-c", cwd])
        _run(["tmux", "split-window", "-t", f"{session}:0.1",
              "-h", "-p", str(split_percent), "-c", cwd])
        oc_pane, bash_pane, git_pane = f"{session}:0.0", f"{session}:0.1", f"{session}:0.2"

    elif pos == "bottom":
        # Bundle on top, OC below.
        # Split the initial pane vertically — OC goes below, bundle stays above.
        oc_percent = 100 - panel_percent
        _run(["tmux", "split-window", "-t", f"{session}:0.0",
              "-v", "-p", str(oc_percent), "-c", cwd])
        # pane 0 = bash (top-left of bundle), pane 1 = OC (bottom)
        # Now split pane 0 horizontally to add gitui on the right of the bundle
        _run(["tmux", "split-window", "-t", f"{session}:0.0",
              "-h", "-p", str(split_percent), "-c", cwd])
        # pane 0 = bash, pane 1 = git, pane 2 = OC
        bash_pane, git_pane, oc_pane = f"{session}:0.0", f"{session}:0.1", f"{session}:0.2"
        _run(["tmux", "send-keys", "-t", oc_pane, oc_command + "\n"])

    else:  # left
        # OC on left, bundle on right — vertical split within bundle (bash top, gitui bottom)
        _run(["tmux", "send-keys", "-t", f"{session}:0.0", oc_command + "\n"])
        _run(["tmux", "split-window", "-t", f"{session}:0.0",
              "-h", "-p", str(panel_percent), "-c", cwd])
        _run(["tmux", "split-window", "-t", f"{session}:0.1",
              "-v", "-p", str(split_percent), "-c", cwd])
        oc_pane, bash_pane, git_pane = f"{session}:0.0", f"{session}:0.1", f"{session}:0.2"

    # Launch gitui and shad status
    _run(["tmux", "send-keys", "-t", git_pane, "gitui\n"])

    if project.group:
        status_cmd = f"shad projects {project.group} {project.key} status"
    else:
        status_cmd = f"shad projects {project.key} status"
    _run(["tmux", "send-keys", "-t", bash_pane, status_cmd + "\n"])

    # Focus the OC pane
    _run(["tmux", "select-pane", "-t", oc_pane])


def _attach(session: str) -> int:
    """Attach or switch to the named tmux session. Returns the exit code."""
    inside_tmux = os.environ.get("TMUX") is not None

    if inside_tmux:
        cmd = ["tmux", "switch-client", "-t", session]
    else:
        cmd = ["tmux", "attach-session", "-t", session]

    result = subprocess.run(cmd)
    return result.returncode


def open_project(project: Project, defaults: Defaults) -> int | None:
    """Attach to project session, creating it with the configured layout if needed.

    Returns the tmux exit code on success, or None if the user cancelled.
    """
    target = pick_opencode_target(project.path, "opencode")

    if target is None:
        return None

    session = project_session_name(project.session, target)

    if not session_exists(session):
        _create_session(project, defaults, target.command, session)

    return _attach(session)


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
