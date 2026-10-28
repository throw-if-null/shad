"""
Rich rendering shared by `shad sessions` save, stop, show and their picker.

One row per session: project, harness, the short conversation id, the
conversation's name and first prompt, and its state. Widths are computed
here rather than left to rich: when a table is wider than the terminal,
rich shrinks every no-wrap column evenly, which truncates the id and the
state. Here the name and the first prompt absorb the shortage, the first
prompt before the name, and a column with no room left is dropped. Nothing
here reads tmux or a harness.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from shad.sessions.live import Running, duplicates
from shad.sessions.model import Entry
from shad.shared.picker import render_bytes
from shad.shared.render import make_table, relative_age

ID_WIDTH = 8
NAME_WIDTH = 24
TITLE_WIDTH = 40
_MIN_TEXT = 6  # a name or title column narrower than this is dropped
# The picker panel's rows besides the session rows: two borders, the blank
# line and the footer, and the terminal row the cursor rests on below it.
_CHROME = 5
_INDICATORS = 2  # the "more above" and "more below" lines of a windowed list


@dataclass(frozen=True)
class Columns:
    """The width of each cell column; a name or title width of 0 drops it."""

    project: int
    harness: int
    id: int
    name: int
    title: int

    @property
    def widths(self) -> list[int]:
        return [w for w in (self.project, self.harness, self.id, self.name, self.title) if w]


def columns(entries: Sequence[Entry], width: int, *, taken: int) -> Columns:
    """
    Widths for *entries* that fit a line of *width*, of which *taken* is
    used by other columns, padding and borders.
    """
    project = max((len(entry.display_name) for entry in entries), default=1)
    harness = max((len(entry.harness) for entry in entries), default=1)
    ident = ID_WIDTH if any(entry.session_id for entry in entries) else 1
    longest_name = max((len(entry.name or "") for entry in entries), default=0)
    longest_title = max((len(entry.title or "") for entry in entries), default=0)

    remaining = width - taken - project - harness - ident
    name = min(NAME_WIDTH, longest_name)
    title = min(TITLE_WIDTH, longest_title)
    if name + title > remaining:
        title = max(0, min(title, remaining - name))
        if title < min(_MIN_TEXT, longest_title):
            title = 0
            name = max(0, min(name, remaining))
    if name < min(_MIN_TEXT, longest_name):
        name = 0
    return Columns(project=project, harness=harness, id=ident, name=name, title=title)


def _fit(
    entries: Sequence[Entry], width: int, *, overhead: int, state_width: int
) -> tuple[Columns, int]:
    """
    The columns and the state width that together fit *width*. *overhead*
    is every other character on the line. The state column gives last,
    when not even the fixed columns fit.
    """
    cols = columns(entries, width, taken=overhead + state_width)
    used = overhead + sum(cols.widths)
    return cols, max(1, min(state_width, width - used))


def cells(entry: Entry, cols: Columns) -> list[Text]:
    """One Text per non-empty column of *cols*."""
    session_id = entry.session_id[:ID_WIDTH] if entry.session_id else "—"
    texts = [
        Text(entry.display_name, style="bright_white"),
        Text(entry.harness, style="dim"),
        Text(session_id, style="yellow" if entry.session_id else "dim"),
    ]
    if cols.name:
        texts.append(Text(_truncate(entry.name or "", cols.name)))
    if cols.title:
        texts.append(Text(_truncate(entry.title or "", cols.title), style="dim"))
    return texts


def state(live: Running, *, duplicate: bool, now: float | None = None) -> Text:
    """
    attached or detached; then busy, or idle and for how long, or that the
    harness has exited; then duplicate when another live session holds the
    same conversation.
    """
    text = Text()
    if live.attached:
        text.append("attached", style="green")
    else:
        text.append("detached", style="dim")
    conversation = live.conversation
    if not live.harness_running:
        text.append("  harness exited", style="red")
    elif conversation is not None and conversation.status == "busy":
        text.append("  busy", style="bold yellow")
    elif conversation is not None and conversation.status == "idle":
        if conversation.status_since:
            text.append(f"  idle {relative_age(conversation.status_since, now=now)}", style="dim")
        else:
            text.append("  idle", style="dim")
    if live.unsupported:
        text.append(f"  {live.unsupported}", style="dim")
    if duplicate:
        text.append("  duplicate", style="red")
    return text


def table(title: str, rows: Sequence[tuple[Entry, Text]], width: int) -> Table:
    """
    The result table: the cells, then one state column, fitted to *width*.
    An empty *rows* renders one dim line.
    """
    result = make_table(title)
    if not rows:
        result.add_column()
        result.add_row(Text("no sessions", style="dim"))
        return result
    entries = [entry for entry, _ in rows]
    # A boxed table costs two edges, then two padding cells and one separator
    # per column, the last separator being the right edge.
    count = len(columns(entries, width, taken=0).widths) + 1
    cols, state_width = _fit(
        entries,
        width,
        overhead=3 * count + 1,
        state_width=max(len(text.plain) for _, text in rows),
    )
    for col_width in cols.widths:
        result.add_column(width=col_width, no_wrap=True, overflow="ellipsis")
    result.add_column(width=state_width, no_wrap=True, overflow="ellipsis")
    for entry, text in rows:
        result.add_row(*cells(entry, cols), text)
    return result


def window(total: int, cursor: int, height: int | None) -> tuple[int, int]:
    """
    The [start, stop) rows a picker of *total* rows shows in a terminal of
    *height* lines, keeping *cursor* in view. Every row when they fit, or
    with *height* unknown. The frame must stay shorter than the terminal,
    because the picker redraws by moving the cursor up over it.
    """
    if height is None or total <= height - _CHROME:
        return 0, total
    visible = max(1, height - _CHROME - _INDICATORS)
    start = min(max(0, cursor - visible // 2), total - visible)
    return start, start + visible


def picker(
    rows: Sequence[Running],
    cursor: int,
    checked: frozenset[int],
    *,
    title: str,
    accept: str,
    width: int,
    height: int | None = None,
) -> bytes:
    """The multi-select picker over *rows*, as terminal bytes."""
    duplicate = duplicates(rows)
    start, stop = window(len(rows), cursor, height)
    entries = [live.entry for live in rows]
    states = [state(live, duplicate=live.session in duplicate) for live in rows]
    # The panel costs two borders and two padding cells; the grid has no
    # edge padding and two padding cells between neighbouring columns. The
    # pointer and the box take one and three.
    count = len(columns(entries, width, taken=0).widths) + 3
    cols, state_width = _fit(
        entries,
        width,
        overhead=4 + 2 * (count - 1) + 1 + 3,
        state_width=max(len(text.plain) for text in states),
    )

    grid = Table(box=None, show_header=False, pad_edge=False, padding=(0, 1))
    for col_width in (1, 3, *cols.widths, state_width):
        grid.add_column(width=col_width, no_wrap=True, overflow="ellipsis")
    for index in range(start, stop):
        live = rows[index]
        selected = index == cursor
        pointer = Text("❯", style="bold bright_green") if selected else Text(" ")
        box = Text("[x]", style="bold green") if index in checked else Text("[ ]", style="dim")
        row = cells(live.entry, cols)
        if selected:
            row[0].stylize("bold")
        grid.add_row(pointer, box, *row, states[index])
    parts: list[Text | Table] = [grid]
    if (start, stop) != (0, len(rows)):
        above = f"  ↑ {start} more" if start else ""
        below = f"  ↓ {len(rows) - stop} more" if stop < len(rows) else ""
        parts = [Text(above, style="dim"), grid, Text(below, style="dim")]
    footer = Text(
        f"\n↑↓ / j k  move   space  toggle   a  all   Enter  {accept}   q  cancel",
        style="dim",
    )
    footer.no_wrap = True
    footer.overflow = "ellipsis"
    panel = Panel(
        Group(*parts, footer),
        title=f"[bold cyan]{title}[/bold cyan]",
        title_align="left",
        border_style="cyan",
        padding=(0, 1),
    )
    return render_bytes(panel, width)


def _truncate(text: str, max_len: int) -> str:
    return text if len(text) <= max_len else text[: max_len - 1] + "…"
