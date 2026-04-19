"""
OpenCode session picker for shad — uses tmux display-menu (no extra deps).

The menu is shown in the current tmux pane BEFORE switching to the target
session.  Each item sends the appropriate `opencode` command directly into
pane 0 of the target tmux session, so opencode is already starting by the
time the user lands there.

Public API
----------
show_session_menu(project_path, tmux_session)
    Build and display the menu.  Returns immediately after the user makes a
    selection (or presses Escape).  No-ops gracefully if we're outside tmux
    or the opencode DB is unavailable.
"""

from __future__ import annotations

import os
import re
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_NEW_SESSION_RE = re.compile(r"^New session\s*-\s*\d{4}-\d{2}-\d{2}T[\d:.]+Z$")

DB_PATH = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
SESSION_LIMIT = 5


@dataclass
class OcSession:
    id: str
    title: str
    time_updated: int  # epoch ms

    @property
    def updated_str(self) -> str:
        dt = datetime.fromtimestamp(self.time_updated / 1000, tz=timezone.utc).astimezone()
        return dt.strftime("%Y-%m-%d %H:%M")

    @property
    def display_title(self) -> str:
        """Human-readable title — collapses unset 'New session - <iso>' placeholders."""
        if _NEW_SESSION_RE.match(self.title):
            return "(untitled)"
        return self.title

    @property
    def menu_label(self) -> str:
        """Short label for display-menu — date + title, truncated to fit."""
        title = self.display_title
        title = title if len(title) <= 45 else title[:42] + "…"
        return f"{self.updated_str}  {title}"


def _query_sessions(project_path: Path, limit: int = SESSION_LIMIT) -> list[OcSession]:
    """Return up to *limit* most-recent non-archived opencode sessions for *project_path*."""
    if not DB_PATH.exists():
        return []
    try:
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        cur = con.cursor()
        cur.execute(
            """
            SELECT s.id, s.title, s.time_updated
            FROM session s
            JOIN project p ON s.project_id = p.id
            WHERE p.worktree = ?
              AND s.time_archived IS NULL
            ORDER BY s.time_updated DESC
            LIMIT ?
            """,
            (str(project_path), limit),
        )
        rows = cur.fetchall()
        con.close()
        return [OcSession(id=r[0], title=r[1], time_updated=r[2]) for r in rows]
    except Exception:
        return []


def _send_cmd(tmux_session: str, cmd: str) -> str:
    """Return a tmux run-shell string that sends *cmd* to pane 0 of *tmux_session*."""
    escaped = cmd.replace("'", "'\\''")
    return f"run-shell 'tmux send-keys -t {tmux_session}:0.0 \"{escaped}\" Enter'"


def show_session_menu(project_path: Path, tmux_session: str, base_opencode_cmd: str) -> None:
    """
    Display a tmux menu to pick an opencode session.

    If we're outside tmux or no sessions exist the function is a no-op and
    the caller should fall back to starting opencode normally.
    """
    if not os.environ.get("TMUX"):
        return

    sessions = _query_sessions(project_path)

    # Build display-menu arguments:
    # format per item:  "label"  "shortcut-key"  "tmux-command"
    menu_args: list[str] = [
        "tmux", "display-menu",
        "-T", "#[bold]opencode session",
    ]

    # "New session" is always first
    new_cmd = _send_cmd(tmux_session, base_opencode_cmd)
    menu_args += ["New session", "n", new_cmd]

    if sessions:
        menu_args += ["", "", ""]  # separator
        for i, s in enumerate(sessions):
            key = str(i + 1)
            resume_cmd = _send_cmd(tmux_session, f"{base_opencode_cmd} -s {s.id}")
            menu_args += [s.menu_label, key, resume_cmd]

    subprocess.run(menu_args)
