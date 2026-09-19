"""
tmux session layout builder for shad.

Owns _create_session(): constructs the 3-pane tmux layout for a project.

Layout variants (controlled by defaults.oc_position):

  top:
    ┌─────────────────────────────────┐
    │  opencode          (top pane)   │  ~65% height
    ├─────────────────────┬───────────┤
    │  bash         (~65%)│ git panel │  ~35% height
    └─────────────────────┴───────────┘

  bottom:
    ┌─────────────────────┬───────────┐
    │  bash         (~65%)│ git panel │  ~65% height
    ├─────────────────────┴───────────┤
    │  opencode                       │  ~35% height
    └─────────────────────────────────┘

  left:
    ┌──────────┬──────────────────────┐
    │          │  bash                │  ~65% of bundle height
    │opencode  ├──────────────────────┤
    │          │  git panel           │  ~35% of bundle height
    └──────────┴──────────────────────┘
"""

from __future__ import annotations

from shad.shared.config import Defaults, Project
from shad.shared.tmux import _run


def _create_session(
    project: Project, defaults: Defaults, oc_command: str, session: str
) -> None:
    """Create a new tmux session with the configured layout."""
    cwd = str(project.path)
    pos = defaults.oc_position
    panel_percent = defaults.panel_percent  # bundle's share of the window
    split_percent = defaults.split_percent  # the git panel's share inside the bundle

    # 1. Create session (detached)
    window_title = f"{project.group}|{project.key}" if project.group else project.key
    _run(["tmux", "new-session", "-d", "-s", session, "-n", window_title, "-c", cwd])
    _run(["tmux", "set-option", "-t", session, "allow-rename", "off"])
    _run(["tmux", "set-option", "-t", session, "set-titles", "on"])
    _run(["tmux", "set-option", "-t", session, "set-titles-string", window_title])

    if pos == "top":
        # OC top, bundle below — horizontal split within bundle
        _run(["tmux", "send-keys", "-t", f"{session}:0.0", oc_command + "\n"])
        _run(
            [
                "tmux",
                "split-window",
                "-t",
                f"{session}:0.0",
                "-v",
                "-p",
                str(panel_percent),
                "-c",
                cwd,
            ]
        )
        _run(
            [
                "tmux",
                "split-window",
                "-t",
                f"{session}:0.1",
                "-h",
                "-p",
                str(split_percent),
                "-c",
                cwd,
            ]
        )
        oc_pane, bash_pane, git_pane = (
            f"{session}:0.0",
            f"{session}:0.1",
            f"{session}:0.2",
        )

    elif pos == "bottom":
        # Bundle on top, OC below.
        # Split the initial pane vertically — OC goes below, bundle stays above.
        oc_percent = 100 - panel_percent
        _run(
            [
                "tmux",
                "split-window",
                "-t",
                f"{session}:0.0",
                "-v",
                "-p",
                str(oc_percent),
                "-c",
                cwd,
            ]
        )
        # pane 0 = bash (top-left of bundle), pane 1 = OC (bottom)
        # Now split pane 0 horizontally to add the git panel on the right of the bundle
        _run(
            [
                "tmux",
                "split-window",
                "-t",
                f"{session}:0.0",
                "-h",
                "-p",
                str(split_percent),
                "-c",
                cwd,
            ]
        )
        # pane 0 = bash, pane 1 = git, pane 2 = OC
        bash_pane, git_pane, oc_pane = (
            f"{session}:0.0",
            f"{session}:0.1",
            f"{session}:0.2",
        )
        _run(["tmux", "send-keys", "-t", oc_pane, oc_command + "\n"])

    else:  # left
        # OC on left, bundle on right — vertical split within bundle (bash top, git panel bottom)
        _run(["tmux", "send-keys", "-t", f"{session}:0.0", oc_command + "\n"])
        _run(
            [
                "tmux",
                "split-window",
                "-t",
                f"{session}:0.0",
                "-h",
                "-p",
                str(panel_percent),
                "-c",
                cwd,
            ]
        )
        _run(
            [
                "tmux",
                "split-window",
                "-t",
                f"{session}:0.1",
                "-v",
                "-p",
                str(split_percent),
                "-c",
                cwd,
            ]
        )
        oc_pane, bash_pane, git_pane = (
            f"{session}:0.0",
            f"{session}:0.1",
            f"{session}:0.2",
        )

    # Launch the git panel and shad status
    if project.group:
        target = f"{project.group} {project.key}"
    else:
        target = project.key
    _run(["tmux", "send-keys", "-t", git_pane, f"shad git panel {target}\n"])
    _run(["tmux", "send-keys", "-t", bash_pane, f"shad projects {target} status\n"])

    # Focus the OC pane
    _run(["tmux", "select-pane", "-t", oc_pane])
