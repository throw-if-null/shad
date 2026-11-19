"""
The arrow-key pickers shad draws in the terminal: one row, or a set of rows.

Both run on /dev/tty in cbreak mode and redraw a renderable in place, so
they work inside a tmux pane and leave nothing behind when they close. The
key loops, `select_one` and `select_many`, take an iterator of keys and a
draw callback, so tests drive them with a scripted key sequence and no
terminal.

cbreak, not raw: raw mode also turns off output processing, so a newline is
a bare line feed with no carriage return, and a panel line that fills the
pane then costs two rows. Each redraw moves the cursor up over the previous
frame and clears from there, instead of saving and restoring the cursor
position: a saved position is a screen row, and it points into the old
frame once the frame has scrolled the screen. The frame must therefore be
shorter than the terminal; `render` callers window their rows to make it so.
"""

from __future__ import annotations

import os
import select
import termios
import tty
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

_CLEAR = b"\033[J"
_ESCAPE_SETTLE = 0.05  # seconds a lone Escape waits for the rest of a sequence


class NoTerminal(Exception):
    """There is no terminal to draw a picker in: /dev/tty could not be opened or driven."""


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
        raise NoTerminal(str(exc)) from None


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
        raise NoTerminal(str(exc)) from None


class _Terminal:
    """/dev/tty in cbreak mode, with the picker redrawn over its previous frame."""

    def __enter__(self) -> Self:
        try:
            self.fd = os.open("/dev/tty", os.O_RDWR)
        except OSError as exc:
            raise NoTerminal(str(exc)) from None
        try:
            self.old = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)
        except termios.error:
            os.close(self.fd)
            raise
        self.lines = 0  # rows the current frame occupies
        return self

    def __exit__(self, *exc: object) -> None:
        try:
            os.write(self.fd, erase(self.lines))
        finally:
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)
            os.close(self.fd)

    def draw(self, content: bytes) -> None:
        os.write(self.fd, erase(self.lines) + content)
        self.lines = content.count(b"\n")

    def keys(self) -> Iterator[str]:
        while True:
            yield _read_key(self.fd)


def erase(lines: int) -> bytes:
    """The bytes that clear a frame of *lines* rows ending above the cursor."""
    if lines <= 0:
        return b""
    return b"\r" + f"\033[{lines}A".encode() + _CLEAR


def _read_key(fd: int) -> str:
    """
    One keypress, with an escape sequence read as one key. A lone Escape is
    told apart from the start of a sequence by a short wait for more bytes.
    """
    ch = os.read(fd, 1)
    if ch == b"\x1b":
        ready, _, _ = select.select([fd], [], [], _ESCAPE_SETTLE)
        if not ready:
            return "\x1b"
        try:
            rest = os.read(fd, 2)
            return (ch + rest).decode("utf-8", errors="replace")
        except OSError:
            return "\x1b"
    return ch.decode("utf-8", errors="replace")
