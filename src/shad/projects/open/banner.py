from rich.console import Console
from rich.panel import Panel
from rich.text import Text

LETTER_COLOR = "bright_white"

SHAD_ART = [
    f"[{LETTER_COLOR}]    █[black on {LETTER_COLOR}]●[/black on {LETTER_COLOR}]█[black on {LETTER_COLOR}]●[/black on {LETTER_COLOR}]█[black on {LETTER_COLOR}]●[/black on {LETTER_COLOR}]█╗██╗  ██╗ █████╗ ██████╗[/{LETTER_COLOR}]",
    f"[{LETTER_COLOR}]    ██╔════╝██║  ██║██╔══██╗██╔══██╗[/{LETTER_COLOR}]",
    f"[{LETTER_COLOR}]    ███████╗███████║███████║██║  ██║[/{LETTER_COLOR}]",
    f"[{LETTER_COLOR}]    ╚════██║██╔══██║██╔══██║██║  ██║[/{LETTER_COLOR}]",
    f"[{LETTER_COLOR}]    ███████║██║  ██║██║  ██║██████╔╝[/{LETTER_COLOR}]",
    f"[{LETTER_COLOR}]    ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝     ><(((>[/{LETTER_COLOR}]",
]


def print_banner() -> None:
    console = Console()
    content = Text.from_markup("\n" + "\n".join(SHAD_ART) + "\n")
    console.print(Panel(content, border_style="white", expand=False))


if __name__ == "__main__":
    print_banner()
