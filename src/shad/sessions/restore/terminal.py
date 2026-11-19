"""
The terminal emulator shad runs in, for the one thing shad asks of it:
open a tab that runs a command.

kitty is the one terminal implemented. It is recognised by the
KITTY_WINDOW_ID variable it sets in its children, and driven through its
remote control, `kitten @ launch`, which answers only when kitty.conf has
`allow_remote_control yes`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

# Without a socket (`listen_on` in kitty.conf, which sets KITTY_LISTEN_ON),
# kitten @ talks to kitty through the tty, and a tty that is not kitty's own,
# such as a tmux pane, never answers. The timeout turns that into a report.
_TIMEOUT = 10


def current() -> str | None:
    """The terminal shad can open tabs in: "kitty", or None."""
    if os.environ.get("KITTY_WINDOW_ID") and shutil.which("kitten"):
        return "kitty"
    return None


def open_tab(terminal: str, command: list[str], cwd: Path) -> str | None:
    """
    Open a tab in *terminal* running *command*, without taking focus.
    Returns None when the tab was opened, else the reason it was not.
    """
    if terminal != "kitty":
        raise ValueError(f"{terminal!r} is not a terminal shad can open tabs in")
    args = ["kitten", "@", "launch", "--type=tab", "--keep-focus", f"--cwd={cwd}", *command]
    try:
        result = subprocess.run(
            args, check=False, capture_output=True, text=True, timeout=_TIMEOUT
        )
    except subprocess.TimeoutExpired:
        return (
            "kitty did not answer; allow_remote_control is off in kitty.conf, "
            "or this shell runs inside tmux and kitty.conf has no listen_on"
        )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        return detail or f"kitten @ launch exited with {result.returncode}"
    return None
