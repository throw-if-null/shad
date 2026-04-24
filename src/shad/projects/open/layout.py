"""
tmux session layout builder for shad.

Owns _create_session(): constructs the 3-pane tmux layout for a project.

Layout variants (controlled by defaults.oc_position):

  top:
    ┌─────────────────────────────────┐
    │  opencode          (top pane)   │  ~65% height
    ├─────────────────────┬───────────┤
    │  bash         (~65%)│  gitui    │  ~35% height
    └─────────────────────┴───────────┘

  bottom:
    ┌─────────────────────┬───────────┐
    │  bash         (~65%)│  gitui    │  ~65% height
    ├─────────────────────┴───────────┤
    │  opencode                       │  ~35% height
    └─────────────────────────────────┘

  left:
    ┌──────────┬──────────────────────┐
    │          │  bash                │  ~65% of bundle height
    │opencode  ├──────────────────────┤
    │          │  gitui               │  ~35% of bundle height
    └──────────┴──────────────────────┘
"""

from __future__ import annotations

from shad.shared.config import Defaults, Project
from shad.shared.tmux import _run


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
