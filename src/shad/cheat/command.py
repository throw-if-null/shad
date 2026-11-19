"""
tmux cheat sheet popup for shad.

Usage:
    shad cheat

Inside tmux  → opens a floating popup (tmux display-popup), dismiss with q
Outside tmux → prints the cheat sheet to stdout
"""

from __future__ import annotations

import argparse

from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

from shad import parsers
from shad.deps import Deps
from shad.output import Output
from shad.tmux import Tmux

_SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
    ("PANES", [
        ("prefix |",       "split vertically (right)"),
        ("prefix -",       "split horizontally (below)"),
        ("prefix h/j/k/l", "move left / down / up / right  (vim-style if set)"),
        ("prefix o",       "cycle through panes"),
        ("prefix q",       "show pane numbers, press number to jump"),
        ("prefix x",       "kill current pane"),
        ("prefix z",       "zoom / unzoom current pane (toggle fullscreen)"),
        ("prefix {",       "swap pane with the previous one"),
        ("prefix }",       "swap pane with the next one"),
        ("prefix !",       "break pane into its own window"),
    ]),
    ("PANE RESIZE", [
        ("prefix Ctrl+↑",  "resize up"),
        ("prefix Ctrl+↓",  "resize down"),
        ("prefix Ctrl+←",  "resize left"),
        ("prefix Ctrl+→",  "resize right"),
    ]),
    ("WINDOWS", [
        ("prefix c",       "create new window"),
        ("prefix ,",       "rename current window"),
        ("prefix w",       "interactive window list"),
        ("prefix n / p",   "next / previous window"),
        ("prefix 0-9",     "switch to window by number"),
        ("prefix &",       "kill current window (with confirmation)"),
    ]),
    ("SESSIONS", [
        ("prefix $",       "rename current session"),
        ("prefix s",       "interactive session list"),
        ("prefix ( / )",   "previous / next session"),
        ("prefix d",       "detach from session"),
        ("tmux ls",        "list sessions (from shell)"),
    ]),
    ("COPY MODE", [
        ("prefix [",       "enter copy mode"),
        ("Space",          "start selection  (vi mode)"),
        ("Enter",          "copy selection and exit"),
        ("prefix ]",       "paste"),
        ("q / Esc",        "exit copy mode"),
    ]),
    ("MISC", [
        ("prefix :",       "open tmux command prompt"),
        ("prefix ?",       "list all key bindings"),
        ("prefix t",       "show a clock in the current pane"),
        ("prefix r",       "reload config  (if bound in ~/.tmux.conf)"),
    ]),
]


_ROW_STYLES = ["on grey3", "on grey7"]  # alternating section backgrounds


def _build_table() -> Table:
    t = Table(
        title="[bold cyan]tmux cheat sheet[/bold cyan]  [dim]prefix = Ctrl+b   (q to close)[/dim]",
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style="bold cyan",
        border_style="bright_black",
        title_justify="center",
        padding=(0, 2),
        expand=False,
    )
    t.add_column("binding", style="bold bright_white", no_wrap=True)
    t.add_column("description", style="white")

    for section_idx, (section, bindings) in enumerate(_SECTIONS):
        row_style = _ROW_STYLES[section_idx % len(_ROW_STYLES)]

        # Section header row
        t.add_row(
            Text(f"  {section}", style=f"bold cyan {row_style}"),
            Text("", style=row_style),
            style=row_style,
        )
        # Binding rows
        for key, desc in bindings:
            t.add_row(
                Text(f"    {key}", style=f"bright_white {row_style}"),
                Text(desc, style=f"white {row_style}"),
                style=row_style,
            )

    return t


def register(sub: parsers.Subparsers) -> None:
    parsers.command(
        sub,
        "cheat",
        run=run,
        help="Show a tmux cheat sheet in a popup (or stdout if outside tmux)",
        description=(
            "Display a tmux key-binding reference.\n\n"
            "Inside tmux  : opens a floating popup; dismiss with q\n"
            "Outside tmux : prints the cheat sheet to stdout\n\n"
            "Recommended ~/.tmux.conf binding:\n"
            '  bind-key F12 run-shell "shad cheat"'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )


def run(args: argparse.Namespace, deps: Deps) -> int:
    return cheat(deps.out, deps.tmux)


def cheat(out: Output, tmux: Tmux) -> int:
    """The sheet on *out*, or in a tmux popup; returns the popup's exit status."""
    if not tmux.inside:
        out.print(_build_table())
        return 0

    # Rendered to a string with color forced on, because the popup's pager
    # is what shows it, then piped through less inside the popup.
    from io import StringIO
    buf = StringIO()
    Console(file=buf, force_terminal=True, width=82).print(_build_table())
    rendered = buf.getvalue()

    escaped = rendered.replace("'", "'\\''")
    shell_cmd = f"printf '%s' '{escaped}' | less -R"

    return tmux.popup(shell_cmd, width=88, height=40)
