"""
The arrow-key pickers shad draws in the terminal: one row, or a set of rows.

Both run on /dev/tty in raw mode and redraw a renderable at the cursor
position they started from, so they work inside a tmux pane and leave
nothing behind when they close. The key loops, `select_one` and
`select_many`, take an iterator of keys and a draw callback, so tests drive
them with a scripted key sequence and no terminal.
"""

from __future__ import annotations

import os
import termios
import tty
import warnings
from collections.abc import Callable, Iterable, Iterator
from io import StringIO
from typing import Self

from rich.console import Console, RenderableType

UP = ("\x1b[A", "k")
DOWN = ("\x1b[B", "j")
ACCEPT = ("\r", "\n")
CANCEL = ("q", "Q", "\x1b")
TOGGLE = (" ",)
TOGGLE_ALL = ("a",)

_SAVE = b"\033[s"
_RESTORE = b"\033[u"
_CLEAR = b"\033[J"


class NoTerminal(Exception):
    """/dev/tty could not be opened: there is no terminal to draw a picker in."""


def render_bytes(renderable: RenderableType, width: int) -> bytes:
    """*renderable* as the ANSI bytes a picker writes to the terminal."""
    buf = StringIO()
    Console(file=buf, force_terminal=True, width=width, highlight=False).print(renderable)
    return buf.getvalue().encode()


# ── key loops ─────────────────────────────────────────────────────────────


def select_one(keys: Iterator[str], total: int, draw: Callable[[int], None]) -> int | None:
    """
    The index the user accepts, or None on cancel or when *keys* ends.
    *draw* is called with the cursor before the first key and after every
    key that changes it.
    """
    if total < 1:
        raise ValueError("nothing to pick from")
    cursor = 0
    draw(cursor)
    for key in keys:
        if key in UP:
            cursor = (cursor - 1) % total
        elif key in DOWN:
            cursor = (cursor + 1) % total
        elif key in ACCEPT:
            return cursor
        elif key in CANCEL:
            return None
        else:
            continue
        draw(cursor)
    return None


def select_many(
    keys: Iterator[str],
    total: int,
    checked: Iterable[int],
    draw: Callable[[int, frozenset[int]], None],
) -> frozenset[int] | None:
    """
    The set of indexes checked when the user accepts, which may be empty,
    or None on cancel or when *keys* ends. Space toggles the row under the
    cursor; `a` checks every row, or clears them all when every row is
    checked.
    """
    if total < 1:
        raise ValueError("nothing to pick from")
    cursor = 0
    chosen = {index for index in checked if 0 <= index < total}
    draw(cursor, frozenset(chosen))
    for key in keys:
        if key in UP:
            cursor = (cursor - 1) % total
        elif key in DOWN:
            cursor = (cursor + 1) % total
        elif key in TOGGLE:
            chosen ^= {cursor}
        elif key in TOGGLE_ALL:
            chosen = set() if len(chosen) == total else set(range(total))
        elif key in ACCEPT:
            return frozenset(chosen)
        elif key in CANCEL:
            return None
        else:
            continue
        draw(cursor, frozenset(chosen))
    return None


# ── the terminal ──────────────────────────────────────────────────────────


def pick_one(render: Callable[[int], bytes], total: int) -> int | None:
    """
    Run `select_one` on /dev/tty. *render* draws the picker for a cursor.
    Raises NoTerminal when there is no terminal to draw in.
    """
    try:
        with _Terminal() as term:
            return select_one(term.keys(), total, lambda cursor: term.draw(render(cursor)))
    except (OSError, termios.error) as exc:
        warnings.warn(f"shad: picker failed: {exc}", stacklevel=2)
        return None


def pick_many(
    render: Callable[[int, frozenset[int]], bytes], total: int, checked: Iterable[int]
) -> frozenset[int] | None:
    """
    Run `select_many` on /dev/tty. *render* draws the picker for a cursor and
    the checked rows. Raises NoTerminal when there is no terminal to draw in.
    """
    try:
        with _Terminal() as term:
            return select_many(
                term.keys(),
                total,
                checked,
                lambda cursor, chosen: term.draw(render(cursor, chosen)),
            )
    except (OSError, termios.error) as exc:
        warnings.warn(f"shad: picker failed: {exc}", stacklevel=2)
        return None


class _Terminal:
    """/dev/tty in raw mode, with the picker drawn under a saved cursor position."""

    def __enter__(self) -> Self:
        try:
            self.fd = os.open("/dev/tty", os.O_RDWR)
        except OSError as exc:
            raise NoTerminal(str(exc)) from None
        try:
            self.old = termios.tcgetattr(self.fd)
            tty.setraw(self.fd)
        except termios.error:
            os.close(self.fd)
            raise
        self.drawn = False
        return self

    def __exit__(self, *exc: object) -> None:
        try:
            if self.drawn:
                os.write(self.fd, _RESTORE + _CLEAR)
        finally:
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)
            os.close(self.fd)

    def draw(self, content: bytes) -> None:
        if self.drawn:
            os.write(self.fd, _RESTORE + _CLEAR + content)
        else:
            os.write(self.fd, _SAVE + content)
            self.drawn = True

    def keys(self) -> Iterator[str]:
        while True:
            yield _read_key(self.fd)


def _read_key(fd: int) -> str:
    """One keypress, with an escape sequence read as one key."""
    ch = os.read(fd, 1)
    if ch == b"\x1b":
        try:
            rest = os.read(fd, 2)
            return (ch + rest).decode("utf-8", errors="replace")
        except OSError:
            return "\x1b"
    return ch.decode("utf-8", errors="replace")
