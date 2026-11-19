"""
The session pickers `shad projects <name>` shows, one per harness: the
conversations the harness has on disk for the project, with "New session"
first. What each harness keeps and how a conversation is resumed or started
is `shad.harness`; this module draws and asks.
"""

from __future__ import annotations

import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

from rich.panel import Panel
from rich.text import Text

from shad.errors import ShadError
from shad.harness import (
    Harness,
    Recorded,
    Target,
    Unreadable,
    fresh_target,
    resume_target,
)
from shad.picker import NoTerminal, pick_one, render_bytes

_NEW_SESSION_RE = re.compile(r"^New session\s*-\s*\d{4}-\d{2}-\d{2}T[\d:.]+Z$")

_TITLE_MAX = 52
_NAME_WIDTH = 26


def updated_str(session: Recorded) -> str:
    """The session's last update, in local time."""
    return datetime.fromtimestamp(session.updated / 1000, tz=UTC).astimezone().strftime(
        "%Y-%m-%d %H:%M"
    )


def display_title(session: Recorded) -> str:
    """The title, or "(untitled)" for the one opencode generates."""
    if _NEW_SESSION_RE.match(session.title):
        return "(untitled)"
    return session.title


def _truncate(text: str, max_len: int) -> str:
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def _render_picker(
    sessions: list[Recorded],
    selected: int,
    project_name: str,
    label: str,
    note: str | None = None,
) -> Panel:
    """The picker frame for *selected*. *note* is a problem shown above the key help."""
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
            date_part = updated_str(item) + "  "
            label_style = "bold bright_white" if is_sel else "white"

            row = Text()
            row.append(pointer, style="bold bright_green" if is_sel else "")
            row.append(date_part, style="dim")
            if item.name:
                name_part = _truncate(item.name, _NAME_WIDTH).ljust(_NAME_WIDTH)
                row.append(name_part + "  ", style=label_style)
                row.append(_truncate(display_title(item), _TITLE_MAX), style="dim")
            else:
                row.append(_truncate(display_title(item), _TITLE_MAX), style=label_style)

        lines.append_text(row)
        lines.append("\n")

    if note:
        lines.append(f"\n {note}\n", style="yellow")
    footer = Text("\n ↑↓ / j k  navigate   Enter  select   q  cancel", style="dim")
    lines.append_text(footer)
    # A row with a name is wider than an 80-column terminal; crop it rather
    # than wrap it onto the next row.
    lines.no_wrap = True
    lines.overflow = "ellipsis"

    return Panel(
        lines,
        title=f"[bold cyan]{label} session[/bold cyan]  [dim]─[/dim]  [bright_white]{project_name}[/bright_white]",
        border_style="cyan",
        padding=(0, 1),
    )


def _run_picker(
    sessions: list[Recorded],
    project_name: str,
    label: str,
    note: str | None = None,
) -> int | None:
    """
    Session picker.
    Returns index into [NEW_SESSION] + sessions, or None if cancelled.
    Index 0 = New session, 1..n = sessions[0..n-1].
    """
    items = [None] + sessions
    term_width = shutil.get_terminal_size().columns

    def render(selected: int) -> bytes:
        return render_bytes(
            _render_picker(sessions, selected, project_name, label, note), term_width
        )

    return pick_one(render, len(items))


# ── Public API ─────────────────────────────────────────────────────────────


def pick_target(harness: Harness, project_path: Path, base_cmd: str) -> Target | None:
    """
    Show the session picker for *harness* and return the target to run.

    Returns None if the user explicitly cancelled (q / Esc). With no
    recorded conversation the target is a fresh one without a picker. A
    session store that cannot be read is reported in the picker instead.
    """
    sessions, note = recorded_or_note(harness, project_path)
    if not sessions and note is None:
        return fresh_target(harness, base_cmd)

    try:
        chosen = _run_picker(sessions, project_path.name, label=harness.name, note=note)
    except NoTerminal as exc:
        raise ShadError.infrastructure(
            "no_terminal", f"no terminal to open the picker in; {exc}"
        ) from None
    if chosen is None:
        return None  # user cancelled — caller should abort
    if chosen == 0:
        return fresh_target(harness, base_cmd)
    return resume_target(harness, base_cmd, sessions[chosen - 1].id)


def recorded_or_note(
    harness: Harness, project_path: Path
) -> tuple[list[Recorded], str | None]:
    """*harness*'s recorded conversations, or none and why the store could not be read."""
    try:
        return harness.recorded(project_path), None
    except Unreadable as exc:
        return [], str(exc)
