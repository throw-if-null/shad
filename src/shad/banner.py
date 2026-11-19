"""The banner `shad` prints before its help and before it opens a project. Pure; shared-and-safe."""

from __future__ import annotations

from rich.panel import Panel
from rich.text import Text

from shad.output import Output

LETTER_COLOR = "bright_white"

SHAD_ART = [
    f"[{LETTER_COLOR}]    █[black on {LETTER_COLOR}]●[/black on {LETTER_COLOR}]█[black on {LETTER_COLOR}]●[/black on {LETTER_COLOR}]█[black on {LETTER_COLOR}]●[/black on {LETTER_COLOR}]█╗██╗  ██╗ █████╗ ██████╗[/{LETTER_COLOR}]",
    f"[{LETTER_COLOR}]    ██╔════╝██║  ██║██╔══██╗██╔══██╗[/{LETTER_COLOR}]",
    f"[{LETTER_COLOR}]    ███████╗███████║███████║██║  ██║[/{LETTER_COLOR}]",
    f"[{LETTER_COLOR}]    ╚════██║██╔══██║██╔══██║██║  ██║[/{LETTER_COLOR}]",
    f"[{LETTER_COLOR}]    ███████║██║  ██║██║  ██║██████╔╝[/{LETTER_COLOR}]",
    f"[{LETTER_COLOR}]    ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝     ><(((>[/{LETTER_COLOR}]",
]


def print_banner(out: Output) -> None:
    content = Text.from_markup("\n" + "\n".join(SHAD_ART) + "\n")
    out.print(Panel(content, border_style="white", expand=False))
