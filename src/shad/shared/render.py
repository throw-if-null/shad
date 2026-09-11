"""
Shared rich rendering helpers for shad.

Owns only presentation primitives that more than one command slice needs.
Command-specific layout stays in the slice that prints it.
"""

from __future__ import annotations

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
