"""
OpenCode session picker for shad.

Queries the opencode SQLite database for recent sessions associated with a
project path, then presents an interactive arrow-key picker (via curses).

Public API
----------
pick_opencode_cmd(project_path, base_opencode_cmd) -> str
    Shows an interactive picker and returns the full opencode command string
    to run (e.g. "opencode" or "opencode -s <id>").
    Falls back to base_opencode_cmd if the DB is unavailable or there are
    no sessions.
"""

from __future__ import annotations

import curses
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
SESSION_LIMIT = 5

_NEW_SESSION_RE = re.compile(r"^New session\s*-\s*\d{4}-\d{2}-\d{2}T[\d:.]+Z$")

# ── ANSI colour helpers (used outside curses for fallback) ─────────────────
_RESET  = "\033[0m"
_BOLD   = "\033[1m"
_DIM    = "\033[2m"
_CYAN   = "\033[36m"
_GREEN  = "\033[32m"


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


# ── Curses picker ──────────────────────────────────────────────────────────

_TITLE_MAX = 52  # max title chars before truncation


def _truncate(text: str, max_len: int) -> str:
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def _run_picker(stdscr, sessions: list[OcSession], project_name: str) -> int | None:
    """
    Curses UI.  Returns the index into [NEW_SESSION] + sessions, or None if
    cancelled.  Index 0 = New session, 1..n = sessions[0..n-1].
    """
    curses.curs_set(0)
    curses.use_default_colors()

    # colour pairs
    curses.init_pair(1, curses.COLOR_CYAN,  -1)   # header
    curses.init_pair(2, curses.COLOR_GREEN, -1)   # selected row pointer
    curses.init_pair(3, curses.COLOR_WHITE, -1)   # dim date

    items = [None] + sessions   # index 0 = new session sentinel

    selected = 0
    total = len(items)

    while True:
        stdscr.erase()
        height, width = stdscr.getmaxyx()

        # ── header ──
        header = f" opencode session  ─  {project_name} "
        stdscr.addstr(0, 0, header, curses.color_pair(1) | curses.A_BOLD)
        stdscr.addstr(1, 0, " " + "─" * (len(header) - 2))

        # ── rows ──
        for i, item in enumerate(items):
            row = 3 + i
            if row >= height - 2:
                break

            is_sel = i == selected
            pointer = "❯ " if is_sel else "  "

            if item is None:
                label = "+ New session"
                attr = curses.A_BOLD if is_sel else curses.A_DIM
                stdscr.addstr(row, 2, pointer + label, attr)
            else:
                date_part = item.updated_str + "  "
                title_part = _truncate(item.display_title, _TITLE_MAX)

                if is_sel:
                    stdscr.addstr(row, 2, pointer, curses.color_pair(2) | curses.A_BOLD)
                    stdscr.addstr(row, 4, date_part, curses.A_DIM)
                    stdscr.addstr(row, 4 + len(date_part), title_part, curses.A_BOLD)
                else:
                    stdscr.addstr(row, 2, pointer)
                    stdscr.addstr(row, 4, date_part, curses.A_DIM)
                    stdscr.addstr(row, 4 + len(date_part), title_part)

        # ── footer ──
        footer = " ↑↓ navigate   Enter select   q cancel "
        stdscr.addstr(height - 1, 0, footer, curses.A_DIM)

        stdscr.refresh()

        key = stdscr.getch()

        if key in (curses.KEY_UP, ord("k")):
            selected = (selected - 1) % total
        elif key in (curses.KEY_DOWN, ord("j")):
            selected = (selected + 1) % total
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            return selected
        elif key in (ord("q"), ord("Q"), 27):  # 27 = Esc
            return None


def _pick_with_curses(sessions: list[OcSession], project_name: str) -> int | None:
    """Wrapper that opens curses on /dev/tty so it works even when stdout is piped."""
    import os

    try:
        # Open the controlling terminal directly so curses has a real TTY
        tty_fd = os.open("/dev/tty", os.O_RDWR)
        tty = open(tty_fd, "rb+", buffering=0)
        old_stdin  = sys.stdin
        old_stdout = sys.stdout
        sys.stdin  = open("/dev/tty", "r")
        sys.stdout = open("/dev/tty", "w")

        result = curses.wrapper(lambda s: _run_picker(s, sessions, project_name))

        sys.stdin  = old_stdin
        sys.stdout = old_stdout
        tty.close()
        return result
    except Exception:
        return None


# ── Public API ─────────────────────────────────────────────────────────────

def pick_opencode_cmd(project_path: Path, base_cmd: str) -> str:
    """
    Show an interactive session picker and return the opencode command to run.

    Falls back to *base_cmd* (new session) on cancel, error, or no sessions.
    """
    sessions = _query_sessions(project_path)
    if not sessions:
        return base_cmd

    project_name = project_path.name
    chosen = _pick_with_curses(sessions, project_name)

    if chosen is None:
        # cancelled
        return base_cmd
    if chosen == 0:
        # New session
        return base_cmd

    session = sessions[chosen - 1]
    return f"{base_cmd} -s {session.id}"
