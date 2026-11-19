"""
The project session layout: the tmux session `projects open` and
`sessions restore` both create, over the injected Tmux.

Pure functions over Tmux; shared-and-safe.

defaults.git_panel and defaults.todo_panel (both on by default) choose the
panes; defaults.oc_position chooses where the harness sits.

With the todo pane on, a todo column of todo_percent of the window width runs
down the right edge:

  top (bottom mirrors it vertically):
    ┌─────────────────────┬───────────┐
    │  opencode           │ todo      │  100 - panel_percent
    ├─────────────────────┼───────────┤
    │  bash               │ git panel │  panel_percent
    └─────────────────────┴───────────┘
       100 - todo_percent  todo_percent

  left (the bundle takes panel_percent of the width beside the todo column):
    ┌──────────┬────────────┬─────────┐
    │          │  bash      │         │
    │opencode  ├────────────┤ todo    │
    │          │  git panel │         │  split_percent of the bundle
    └──────────┴────────────┴─────────┘

With the git panel off, its pane is not split off: with top and bottom the
todo pane fills the todo column, and with left bash fills the bundle.

With the todo pane off, the git panel sits beside or below bash in the bundle:

  top:
    ┌─────────────────────────────────┐
    │  opencode          (top pane)   │  ~65% height
    ├─────────────────────┬───────────┤
    │  bash         (~80%)│ git panel │  ~35% height
    └─────────────────────┴───────────┘

  bottom:
    ┌─────────────────────┬───────────┐
    │  bash         (~80%)│ git panel │  ~35% height
    ├─────────────────────┴───────────┤
    │  opencode                       │  ~65% height
    └─────────────────────────────────┘

  left:
    ┌──────────┬──────────────────────┐
    │          │  bash                │  ~80% of bundle height
    │opencode  ├──────────────────────┤
    │          │  git panel           │  ~20% of bundle height
    └──────────┴──────────────────────┘

With the git panel off too, bash takes the whole bundle.

The layouts with a todo pane address panes by id ("%3"), captured from each
split, rather than by index: a fourth split makes the index of every later
pane depend on the order of the earlier ones.
"""

from __future__ import annotations

from shad.config.load import Defaults, Project
from shad.tmux import Tmux


def create_session(
    tmux: Tmux, project: Project, defaults: Defaults, oc_command: str, session: str
) -> None:
    """Create the tmux session *session* for *project* with the configured layout."""
    cwd = str(project.path)
    pos = defaults.oc_position
    panel_percent = defaults.panel_percent  # bundle's share of the window
    split_percent = defaults.split_percent  # the git panel's share inside the bundle

    # 1. Create session (detached)
    window_title = f"{project.group}|{project.key}" if project.group else project.key
    tmux.run("new-session", "-d", "-s", session, "-n", window_title, "-c", cwd)
    tmux.run("set-option", "-t", session, "allow-rename", "off")
    tmux.run("set-option", "-t", session, "set-titles", "on")
    tmux.run("set-option", "-t", session, "set-titles-string", window_title)

    if defaults.todo_panel:
        _layout_with_todo(tmux, project, defaults, oc_command, session, cwd)
        return

    git_pane: str | None = None

    if pos == "top":
        # OC top, bundle below — horizontal split within bundle
        tmux.run("send-keys", "-t", f"{session}:0.0", oc_command + "\n")
        tmux.run("split-window", "-t", f"{session}:0.0", "-v", *_size(panel_percent), "-c", cwd)
        if defaults.git_panel:
            tmux.run("split-window", "-t", f"{session}:0.1", "-h", *_size(split_percent), "-c", cwd)
            git_pane = f"{session}:0.2"
        oc_pane, bash_pane = f"{session}:0.0", f"{session}:0.1"

    elif pos == "bottom":
        # Bundle on top, OC below.
        # Split the initial pane vertically — OC goes below, bundle stays above.
        oc_percent = 100 - panel_percent
        tmux.run("split-window", "-t", f"{session}:0.0", "-v", *_size(oc_percent), "-c", cwd)
        # pane 0 = bash (top-left of bundle), pane 1 = OC (bottom)
        bash_pane, oc_pane = f"{session}:0.0", f"{session}:0.1"
        if defaults.git_panel:
            # Split pane 0 horizontally to add the git panel on the right of the bundle
            tmux.run("split-window", "-t", f"{session}:0.0", "-h", *_size(split_percent), "-c", cwd)
            # pane 0 = bash, pane 1 = git, pane 2 = OC
            git_pane, oc_pane = f"{session}:0.1", f"{session}:0.2"
        tmux.run("send-keys", "-t", oc_pane, oc_command + "\n")

    else:  # left
        # OC on left, bundle on right — vertical split within bundle (bash top, git panel bottom)
        tmux.run("send-keys", "-t", f"{session}:0.0", oc_command + "\n")
        tmux.run("split-window", "-t", f"{session}:0.0", "-h", *_size(panel_percent), "-c", cwd)
        if defaults.git_panel:
            tmux.run("split-window", "-t", f"{session}:0.1", "-v", *_size(split_percent), "-c", cwd)
            git_pane = f"{session}:0.2"
        oc_pane, bash_pane = f"{session}:0.0", f"{session}:0.1"

    # Launch the git panel and shad status
    target = _target(project)
    if git_pane:
        tmux.run("send-keys", "-t", git_pane, f"shad git panel {target}\n")
    tmux.run("send-keys", "-t", bash_pane, f"shad projects {target} status\n")

    # Focus the OC pane
    tmux.run("select-pane", "-t", oc_pane)


def _layout_with_todo(
    tmux: Tmux, project: Project, defaults: Defaults, oc_command: str, session: str, cwd: str
) -> None:
    """
    The layouts with a todo column on the right edge of the window.

    With top or bottom, the git panel shares the todo column and the todo pane
    shares the harness's row. With left, the git panel stays in the bundle.
    Without the git panel, the todo pane takes the full height of its column.
    """
    target = _target(project)
    pp = defaults.panel_percent
    git: str | None = None

    first = tmux.run("display-message", "-p", "-t", f"{session}:0.0", "#{pane_id}").stdout.strip()
    todo = _split(tmux, first, "-h", defaults.todo_percent, cwd)

    if defaults.oc_position == "top":
        main = first
        shell = _split(tmux, first, "-v", pp, cwd)
        if defaults.git_panel:
            git = _split(tmux, todo, "-v", pp, cwd)
    elif defaults.oc_position == "bottom":
        # The new, lower panes are the harness and the todo pane.
        shell = first
        main = _split(tmux, first, "-v", 100 - pp, cwd)
        if defaults.git_panel:
            git, todo = todo, _split(tmux, todo, "-v", 100 - pp, cwd)
    else:  # left
        main = first
        shell = _split(tmux, first, "-h", pp, cwd)
        if defaults.git_panel:
            git = _split(tmux, shell, "-v", defaults.split_percent, cwd)

    tmux.run("send-keys", "-t", main, oc_command + "\n")
    if git:
        tmux.run("send-keys", "-t", git, f"shad git panel {target}\n")
    tmux.run("send-keys", "-t", todo, "shad todo panel\n")
    tmux.run("send-keys", "-t", shell, f"shad projects {target} status\n")
    tmux.run("select-pane", "-t", main)


def _size(percent: int) -> list[str]:
    """
    The split-window size for *percent* of the pane. tmux 3.4 rejects the
    older `-p percent` with "size missing"; `-l` with a percentage is
    accepted by every tmux since 3.1.
    """
    return ["-l", f"{percent}%"]


def _split(tmux: Tmux, pane: str, direction: str, percent: int, cwd: str) -> str:
    """Split *pane* and return the new pane's id."""
    result = tmux.run(
        "split-window", "-t", pane, direction, *_size(percent), "-c", cwd, "-P", "-F", "#{pane_id}"
    )
    return result.stdout.strip()


def _target(project: Project) -> str:
    return f"{project.group} {project.key}" if project.group else project.key
