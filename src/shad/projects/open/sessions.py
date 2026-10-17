"""
AI session pickers for shad.

Provides interactive arrow-key pickers for each supported AI harness:
- pick_opencode_target: queries the OpenCode SQLite DB for recent sessions
- pick_claude_target: reads the Claude Code transcript directory for recent sessions

Both pickers resolve a concrete session id before returning, because the caller
derives the tmux session name from it. A picker that returned a constant key
would map every resumed conversation onto one tmux session.

Public API
----------
pick_opencode_target(project_path, base_opencode_cmd) -> OpencodeTarget | None
pick_claude_target(project_path, base_claude_cmd) -> OpencodeTarget | None
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import termios
import time
import tty
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

DB_PATH = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
SESSION_LIMIT = 5

# Claude Code writes one transcript per session. The first prompt is in the
# opening entries, so that scan stops well before the end of a long file.
_CLAUDE_TITLE_SCAN_LINES = 200

# The entry types that name a session: a /rename, and the name Claude Code
# generates. The name scan matches these bytes before it parses a line, because
# a transcript can be tens of megabytes.
_CLAUDE_NAME_FIELDS = {"custom-title": "customTitle", "ai-title": "aiTitle"}
_CLAUDE_NAME_MARKERS = tuple(f'"{kind}"'.encode() for kind in _CLAUDE_NAME_FIELDS)

_CLAUDE_SLUG_RE = re.compile(r"[^A-Za-z0-9]")

# Slash commands, hook output and pasted attachments are recorded as user
# entries wrapped in these tags. None of them is a prompt the user typed.
_CLAUDE_WRAPPER_RE = re.compile(
    r"^<(local-command-caveat|local-command-stdout|command-name|command-message"
    r"|command-args|bash-input|bash-stdout|bash-stderr|system-reminder)\b"
)

_NEW_SESSION_RE = re.compile(r"^New session\s*-\s*\d{4}-\d{2}-\d{2}T[\d:.]+Z$")

_TITLE_MAX = 52
_NAME_WIDTH = 26


@dataclass
class OcSession:
    id: str
    title: str
    time_updated: int  # epoch ms
    name: str | None = None  # Claude Code only; opencode's title is its name

    @property
    def updated_str(self) -> str:
        dt = datetime.fromtimestamp(
            self.time_updated / 1000, tz=UTC
        ).astimezone()
        return dt.strftime("%Y-%m-%d %H:%M")

    @property
    def display_title(self) -> str:
        if _NEW_SESSION_RE.match(self.title):
            return "(untitled)"
        return self.title


@dataclass(frozen=True)
class OpencodeTarget:
    command: str
    session_key: str | None = None
    fresh: bool = False
    session_prefix: str = "oc"


def _query_sessions(project_path: Path, limit: int = SESSION_LIMIT) -> list[OcSession]:
    """Return up to *limit* most-recent non-archived opencode sessions for *project_path*."""
    if not DB_PATH.exists():
        return []
    try:
        with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True) as con:
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
        return [OcSession(id=r[0], title=r[1], time_updated=r[2]) for r in rows]
    except sqlite3.DatabaseError as exc:
        warnings.warn(f"shad: could not read opencode session DB: {exc}", stacklevel=2)
        return []


def _claude_project_dir(project_path: Path) -> Path:
    """Return the Claude Code transcript directory for *project_path*.

    Claude Code derives the directory name from the working directory by
    replacing every character outside [A-Za-z0-9] with a hyphen.
    """
    return CLAUDE_PROJECTS_DIR / _CLAUDE_SLUG_RE.sub("-", str(project_path))


def _claude_session_title(transcript: Path) -> str | None:
    """Return the first real user prompt in *transcript*, or None if it has none.

    Entries flagged ``isMeta`` and the command wrappers Claude Code records for
    slash commands are not prompts the user typed, so they are skipped. A
    transcript with no prompt at all is an empty session and is not offered.
    """
    try:
        with transcript.open(encoding="utf-8") as handle:
            for _, line in zip(range(_CLAUDE_TITLE_SCAN_LINES), handle, strict=False):
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("type") != "user" or entry.get("isMeta"):
                    continue
                text = _claude_entry_text(entry)
                if text:
                    return text
    except OSError:
        return None
    return None


def _claude_session_name(transcript: Path) -> str | None:
    """Return the session's name, or None if it has none.

    The name is the last ``custom-title`` entry (set by /rename), else the last
    ``ai-title`` entry. Either can be appended anywhere in the transcript, so
    the whole file is read.
    """
    latest: dict[str, str] = {}
    try:
        with transcript.open("rb") as handle:
            for line in handle:
                if not any(marker in line for marker in _CLAUDE_NAME_MARKERS):
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict):
                    continue
                kind = entry.get("type")
                if kind not in _CLAUDE_NAME_FIELDS:
                    continue
                value = entry.get(_CLAUDE_NAME_FIELDS[kind])
                if isinstance(value, str) and value.strip():
                    latest[kind] = " ".join(value.split())
    except OSError:
        return None
    return latest.get("custom-title") or latest.get("ai-title")


def _claude_entry_text(entry: dict) -> str | None:
    """Return the prompt text of a transcript user entry, or None."""
    content = entry.get("message", {}).get("content")
    if isinstance(content, str):
        blocks = [content]
    elif isinstance(content, list):
        blocks = [b.get("text", "") for b in content if b.get("type") == "text"]
    else:
        return None

    for block in blocks:
        text = " ".join(block.split())
        if text and not _CLAUDE_WRAPPER_RE.match(text):
            return text
    return None


def _query_claude_sessions(
    project_path: Path, limit: int = SESSION_LIMIT
) -> list[OcSession]:
    """Return up to *limit* most-recent Claude Code sessions for *project_path*."""
    directory = _claude_project_dir(project_path)
    try:
        transcripts = sorted(
            directory.glob("*.jsonl"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
    except OSError as exc:
        warnings.warn(
            f"shad: could not read claude session directory: {exc}", stacklevel=2
        )
        return []

    sessions: list[OcSession] = []
    for transcript in transcripts:
        if len(sessions) == limit:
            break
        title = _claude_session_title(transcript)
        if title is None:
            continue
        sessions.append(
            OcSession(
                id=transcript.stem,
                title=title,
                time_updated=int(transcript.stat().st_mtime * 1000),
                name=_claude_session_name(transcript),
            )
        )
    return sessions


def _truncate(text: str, max_len: int) -> str:
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def _render_picker(
    sessions: list[OcSession], selected: int, project_name: str, harness: str
) -> Panel:
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
            label_style = "bold bright_white" if is_sel else "white"

            row = Text()
            row.append(pointer, style="bold bright_green" if is_sel else "")
            row.append(date_part, style="dim")
            if item.name:
                name_part = _truncate(item.name, _NAME_WIDTH).ljust(_NAME_WIDTH)
                row.append(name_part + "  ", style=label_style)
                row.append(_truncate(item.display_title, _TITLE_MAX), style="dim")
            else:
                row.append(_truncate(item.display_title, _TITLE_MAX), style=label_style)

        lines.append_text(row)
        lines.append("\n")

    footer = Text("\n ↑↓ / j k  navigate   Enter  select   q  cancel", style="dim")
    lines.append_text(footer)
    # A row with a name is wider than an 80-column terminal; crop it rather
    # than wrap it onto the next row.
    lines.no_wrap = True
    lines.overflow = "ellipsis"

    return Panel(
        lines,
        title=f"[bold cyan]{harness} session[/bold cyan]  [dim]─[/dim]  [bright_white]{project_name}[/bright_white]",
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
        except OSError:
            return "\x1b"
    return ch.decode("utf-8", errors="replace")


def _render_panel(
    sessions: list[OcSession],
    selected: int,
    project_name: str,
    width: int,
    harness: str,
) -> bytes:
    """Render picker panel to ANSI bytes."""
    buf = StringIO()
    Console(file=buf, force_terminal=True, width=width, highlight=False).print(
        _render_picker(sessions, selected, project_name, harness)
    )
    return buf.getvalue().encode()


def _generic_picker(render_fn: Callable[[int], bytes], total: int) -> int | None:
    """
    Core arrow-key picker backed by raw tty I/O and cursor save/restore.
    Returns the selected index (0-based) or None if cancelled.
    """
    selected = 0

    try:
        tty_fd = os.open("/dev/tty", os.O_RDWR)
    except OSError:
        return None

    old_settings = termios.tcgetattr(tty_fd)
    SAVE = b"\033[s"
    RESTORE = b"\033[u"
    CLEAR = b"\033[J"

    def draw(first: bool = False) -> None:
        content = render_fn(selected)
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
    except (OSError, termios.error) as exc:
        warnings.warn(f"shad: picker failed: {exc}", stacklevel=2)
        try:
            termios.tcsetattr(tty_fd, termios.TCSADRAIN, old_settings)
            os.close(tty_fd)
        except OSError:
            pass
        return None


def _run_picker(
    sessions: list[OcSession], project_name: str, harness: str = "opencode"
) -> int | None:
    """
    Session picker.
    Returns index into [NEW_SESSION] + sessions, or None if cancelled.
    Index 0 = New session, 1..n = sessions[0..n-1].
    """
    items = [None] + sessions
    term_width = shutil.get_terminal_size().columns

    def render(selected: int) -> bytes:
        return _render_panel(sessions, selected, project_name, term_width, harness)

    return _generic_picker(render, len(items))


# ── Public API ─────────────────────────────────────────────────────────────


def pick_opencode_target(project_path: Path, base_cmd: str) -> OpencodeTarget | None:
    """
    Show an interactive session picker and return the opencode target to run.

    Returns None if the user explicitly cancelled (q / Esc).
    Falls back to base_cmd on error or no sessions.
    """
    sessions = _query_sessions(project_path)
    if not sessions:
        fresh_key = f"fresh-{int(time.time())}"
        return OpencodeTarget(command=base_cmd, session_key=fresh_key, fresh=True)

    project_name = project_path.name
    chosen = _run_picker(sessions, project_name)

    if chosen is None:
        return None  # user cancelled — caller should abort
    if chosen == 0:
        fresh_key = f"fresh-{int(time.time())}"
        return OpencodeTarget(command=base_cmd, session_key=fresh_key, fresh=True)

    session = sessions[chosen - 1]
    return OpencodeTarget(command=f"{base_cmd} -s {session.id}", session_key=session.id)


def pick_claude_target(
    project_path: Path, base_cmd: str = "claude"
) -> OpencodeTarget | None:
    """
    Show an interactive session picker and return the Claude Code target to run.

    Returns None if the user explicitly cancelled (q / Esc).
    Falls back to base_cmd when the project has no recorded sessions.
    """
    sessions = _query_claude_sessions(project_path)
    if not sessions:
        return _fresh_claude_target(base_cmd)

    chosen = _run_picker(sessions, project_path.name, harness="claude")

    if chosen is None:
        return None  # user cancelled — caller should abort
    if chosen == 0:
        return _fresh_claude_target(base_cmd)

    session = sessions[chosen - 1]
    return OpencodeTarget(
        command=f"{base_cmd} --resume {session.id}",
        session_key=session.id,
        session_prefix="cc",
    )


def _fresh_claude_target(base_cmd: str) -> OpencodeTarget:
    return OpencodeTarget(
        command=base_cmd,
        session_key=f"fresh-{int(time.time())}",
        fresh=True,
        session_prefix="cc",
    )
