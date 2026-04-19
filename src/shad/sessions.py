"""
OpenCode session picker for shad.

Queries the opencode SQLite database for recent sessions associated with a
project path, then presents a numbered prompt so the user can pick one (or
start a new session).

Public API
----------
pick_opencode_cmd(project_path, base_opencode_cmd) -> str
    Prints a session list, reads a choice, and returns the full opencode
    command string to run (e.g. "opencode" or "opencode -s <id>").
    Falls back to base_opencode_cmd if the DB is unavailable or there are
    no sessions.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
SESSION_LIMIT = 5

_NEW_SESSION_RE = re.compile(r"^New session\s*-\s*\d{4}-\d{2}-\d{2}T[\d:.]+Z$")


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
        if _NEW_SESSION_RE.match(self.title):
            return "(untitled)"
        return self.title


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


def pick_opencode_cmd(project_path: Path, base_cmd: str) -> str:
    """
    Print a session picker and return the opencode command to run.

    Returns *base_cmd* unchanged if there are no sessions or the user
    presses Ctrl-C / enters an invalid choice.
    """
    sessions = _query_sessions(project_path)
    if not sessions:
        return base_cmd

    print()
    print("  opencode session:")
    print("    n) New session")
    for i, s in enumerate(sessions, 1):
        title = s.display_title
        if len(title) > 50:
            title = title[:47] + "…"
        print(f"    {i}) {s.updated_str}  {title}")

    valid = {"n"} | {str(i) for i in range(1, len(sessions) + 1)}
    prompt = f"  Pick [n/{'/' .join(str(i) for i in range(1, len(sessions) + 1))}]: "

    try:
        choice = input(prompt).strip().lower()
    except (KeyboardInterrupt, EOFError):
        print()
        return base_cmd

    print()

    if choice == "n" or choice not in valid:
        return base_cmd

    idx = int(choice) - 1
    return f"{base_cmd} -s {sessions[idx].id}"
