"""
OpenCode session picker for shad.

Queries the opencode SQLite database for recent sessions associated with a
project path, then presents an interactive arrow-key picker rendered with Rich.

Public API
----------
pick_opencode_cmd(project_path, base_opencode_cmd) -> str
    Shows an interactive picker and returns the full opencode command string
    to run (e.g. "opencode" or "opencode -s <id>").
    Falls back to base_opencode_cmd if the DB is unavailable or there are
    no sessions.
"""

from __future__ import annotations

import re
import sqlite3
import sys
import os
import tty
import termios
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from io import StringIO

from rich.console import Console
from rich.text import Text
from rich.panel import Panel

DB_PATH = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
SESSION_LIMIT = 5

_NEW_SESSION_RE = re.compile(r"^New session\s*-\s*\d{4}-\d{2}-\d{2}T[\d:.]+Z$")

_TITLE_MAX = 52


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


def _truncate(text: str, max_len: int) -> str:
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def _render_picker(sessions: list[OcSession], selected: int, project_name: str) -> Panel:
    """Build the Rich renderable for the current picker state."""
    items = [None] + sessions  # index 0 = new session sentinel

    lines = Text()
    for i, item in enumerate(items):
        is_sel = i == selected
        pointer = "❯ " if is_sel else "  "

        if item is None:
            row = Text()
            row.append(pointer, style="bold bright_green" if is_sel else "dim")
            row.append("+ New session", style="bold" if is_sel else "dim")
        else:
            date_part = item.updated_str + "  "
            title_part = _truncate(item.display_title, _TITLE_MAX)

            row = Text()
            row.append(pointer, style="bold bright_green" if is_sel else "")
            row.append(date_part, style="dim")
            row.append(title_part, style="bold bright_white" if is_sel else "white")

        lines.append_text(row)
        lines.append("\n")

    footer = Text("\n ↑↓ / j k  navigate   Enter  select   q  cancel", style="dim")
    lines.append_text(footer)

    return Panel(
        lines,
        title=f"[bold cyan]opencode session[/bold cyan]  [dim]─[/dim]  [bright_white]{project_name}[/bright_white]",
        border_style="cyan",
        padding=(0, 1),
    )


def _read_key(fd: int) -> str:
    """Read a single keypress (including escape sequences) from file descriptor."""
    ch = os.read(fd, 1)
    if ch == b"\x1b":
        # try to read escape sequence
        try:
            rest = os.read(fd, 2)
            return (ch + rest).decode("utf-8", errors="replace")
        except Exception:
            return "\x1b"
    return ch.decode("utf-8", errors="replace")


def _render_panel(sessions: list[OcSession], selected: int, project_name: str, width: int) -> bytes:
    """Render picker panel to ANSI bytes."""
    buf = StringIO()
    Console(file=buf, force_terminal=True, width=width, highlight=False).print(
        _render_picker(sessions, selected, project_name)
    )
    return buf.getvalue().encode()


def _run_picker(sessions: list[OcSession], project_name: str) -> int | None:
    """
    Picker using cursor-save/restore redraw via os.write directly to tty fd.
    Returns index into [NEW_SESSION] + sessions, or None if cancelled.
    Index 0 = New session, 1..n = sessions[0..n-1].
    """
    import shutil as _shutil

    items = [None] + sessions
    total = len(items)
    selected = 0

    try:
        tty_fd = os.open("/dev/tty", os.O_RDWR)
    except OSError:
        return None

    term_width = _shutil.get_terminal_size().columns
    old_settings = termios.tcgetattr(tty_fd)

    SAVE    = b"\033[s"       # save cursor position
    RESTORE = b"\033[u"       # restore cursor position
    CLEAR   = b"\033[J"       # clear from cursor to end of screen

    def draw(first: bool = False) -> None:
        content = _render_panel(sessions, selected, project_name, term_width)
        if first:
            os.write(tty_fd, SAVE + content)
        else:
            os.write(tty_fd, RESTORE + CLEAR + content)

    def cleanup() -> None:
        os.write(tty_fd, RESTORE + CLEAR)
        termios.tcsetattr(tty_fd, termios.TCSADRAIN, old_settings)
        os.close(tty_fd)

    try:
        tty.setraw(tty_fd)
        draw(first=True)

        while True:
            key = _read_key(tty_fd)

            if key in ("\x1b[A", "k"):
                selected = (selected - 1) % total
                draw()
            elif key in ("\x1b[B", "j"):
                selected = (selected + 1) % total
                draw()
            elif key in ("\r", "\n"):
                cleanup()
                return selected
            elif key in ("q", "Q", "\x1b"):
                cleanup()
                return None
    except Exception:
        termios.tcsetattr(tty_fd, termios.TCSADRAIN, old_settings)
        os.close(tty_fd)
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
    chosen = _run_picker(sessions, project_name)

    if chosen is None:
        return base_cmd
    if chosen == 0:
        return base_cmd

    session = sessions[chosen - 1]
    return f"{base_cmd} -s {session.id}"
