"""
tmux cheat sheet popup for shad.

Usage:
    shad cheat

Inside tmux  → opens a floating popup (tmux display-popup), dismiss with q
Outside tmux → prints the cheat sheet to stdout
"""

from __future__ import annotations

import os
import subprocess
import sys

CHEAT_SHEET = """\
╔══════════════════════════════════════════════════════════════════════════════╗
║                          tmux  cheat sheet                                  ║
║                    prefix = Ctrl+b   (q to close)                           ║
╠══════════════════╦══════════════════════════════════════════════════════════╣
║  PANES           ║                                                          ║
╠══════════════════╬══════════════════════════════════════════════════════════╣
║  prefix |        ║  split vertically (right)                                ║
║  prefix -        ║  split horizontally (below)                              ║
║  prefix h/j/k/l  ║  move left / down / up / right  (vim-style if set)      ║
║  prefix o        ║  cycle through panes                                     ║
║  prefix q        ║  show pane numbers, press number to jump                 ║
║  prefix x        ║  kill current pane                                       ║
║  prefix z        ║  zoom / unzoom current pane (toggle fullscreen)          ║
║  prefix {        ║  swap pane with the previous one                         ║
║  prefix }        ║  swap pane with the next one                             ║
║  prefix !        ║  break pane into its own window                          ║
╠══════════════════╬══════════════════════════════════════════════════════════╣
║  PANE RESIZE     ║                                                          ║
╠══════════════════╬══════════════════════════════════════════════════════════╣
║  prefix Ctrl+↑   ║  resize up                                               ║
║  prefix Ctrl+↓   ║  resize down                                             ║
║  prefix Ctrl+←   ║  resize left                                             ║
║  prefix Ctrl+→   ║  resize right                                            ║
╠══════════════════╬══════════════════════════════════════════════════════════╣
║  WINDOWS         ║                                                          ║
╠══════════════════╬══════════════════════════════════════════════════════════╣
║  prefix c        ║  create new window                                       ║
║  prefix ,        ║  rename current window                                   ║
║  prefix w        ║  interactive window list                                 ║
║  prefix n / p    ║  next / previous window                                  ║
║  prefix 0-9      ║  switch to window by number                              ║
║  prefix &        ║  kill current window (with confirmation)                 ║
╠══════════════════╬══════════════════════════════════════════════════════════╣
║  SESSIONS        ║                                                          ║
╠══════════════════╬══════════════════════════════════════════════════════════╣
║  prefix $        ║  rename current session                                  ║
║  prefix s        ║  interactive session list                                ║
║  prefix (  /  )  ║  previous / next session                                 ║
║  prefix d        ║  detach from session                                     ║
║  tmux ls         ║  list sessions (from shell)                              ║
╠══════════════════╬══════════════════════════════════════════════════════════╣
║  COPY MODE       ║                                                          ║
╠══════════════════╬══════════════════════════════════════════════════════════╣
║  prefix [        ║  enter copy mode                                         ║
║  Space           ║  start selection  (vi mode)                              ║
║  Enter           ║  copy selection and exit                                 ║
║  prefix ]        ║  paste                                                   ║
║  q / Esc         ║  exit copy mode                                          ║
╠══════════════════╬══════════════════════════════════════════════════════════╣
║  MISC            ║                                                          ║
╠══════════════════╬══════════════════════════════════════════════════════════╣
║  prefix :        ║  open tmux command prompt                                ║
║  prefix ?        ║  list all key bindings                                   ║
║  prefix t        ║  show a clock in the current pane                        ║
║  prefix r        ║  reload config  (if bound in ~/.tmux.conf)               ║
╚══════════════════╩══════════════════════════════════════════════════════════╝
"""


def cmd_cheat() -> None:
    inside_tmux = os.environ.get("TMUX") is not None

    if not inside_tmux:
        print(CHEAT_SHEET)
        return

    # Use display-popup; pipe the cheat sheet through less so the user can
    # scroll and dismiss with q.  The here-doc approach avoids temp files.
    escaped = CHEAT_SHEET.replace("'", "'\\''")
    shell_cmd = f"printf '%s' '{escaped}' | less -R"

    result = subprocess.run(
        [
            "tmux", "display-popup",
            "-E",
            "-w", "82",
            "-h", "36",
            shell_cmd,
        ],
    )
    sys.exit(result.returncode)
