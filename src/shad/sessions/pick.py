"""
The multi-select picker over running sessions, as `save` and `stop` use it.

One function: the terminal size, the frame, and the error when there is no
terminal to draw in. The key handling is `shad.picker`.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterable, Sequence

from shad.errors import ShadError
from shad.picker import NoTerminal, pick_many
from shad.sessions import render
from shad.sessions.live import Running


def pick(
    rows: Sequence[Running], checked: Iterable[int], *, title: str, accept: str, hint: str
) -> frozenset[int] | None:
    """
    The indexes of *rows* the user accepts, or None on cancel. *hint* is
    appended to the error when there is no terminal.
    """
    width, height = shutil.get_terminal_size()

    def draw(cursor: int, chosen: frozenset[int]) -> bytes:
        return render.picker(
            rows, cursor, chosen, title=title, accept=accept, width=width, height=height
        )

    try:
        return pick_many(draw, len(rows), checked)
    except NoTerminal:
        raise ShadError.infrastructure("no_terminal", f"no terminal to pick in; {hint}") from None
