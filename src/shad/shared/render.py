"""
Shared rich rendering helpers for shad.

Owns only presentation primitives that more than one command slice needs.
Command-specific layout stays in the slice that prints it.
"""

from __future__ import annotations

import time

from rich import box
from rich.table import Table


def make_table(title: str) -> Table:
    """Return the standard borderless-header table used by every shad command."""
    return Table(
        title=title,
        box=box.ROUNDED,
        show_header=False,
        title_justify="left",
        title_style="bold cyan",
        border_style="bright_black",
        pad_edge=True,
        show_edge=True,
        padding=(0, 1),
    )


def relative_age(timestamp: int, *, now: float | None = None) -> str:
    """
    A unix timestamp as a compact age: 5m, 3h, 2d, 6w, 14mo, 3y.

    Computed here rather than read from git's %cr, which is gettext-translated.
    Kept short because the git panel renders it in a column about 4 characters
    wide; `shad projects ... status` uses the same form so the two agree.
    """
    if timestamp <= 0:
        return "—"
    seconds = int((time.time() if now is None else now) - timestamp)
    if seconds < 0:
        return "now"
    for limit, divisor, suffix in (
        (60, 1, "s"),
        (3600, 60, "m"),
        (86400, 3600, "h"),
        (604800, 86400, "d"),
        (2592000, 604800, "w"),
        (31536000, 2592000, "mo"),
    ):
        if seconds < limit:
            return f"{seconds // divisor}{suffix}"
    return f"{seconds // 31536000}y"
