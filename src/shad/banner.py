from rich.console import Console
from rich.text import Text

LETTER_COLOR = "bright_white"

SHAD_ART = [
    f"[{LETTER_COLOR}]█[black on {LETTER_COLOR}]●[/black on {LETTER_COLOR}]█[black on {LETTER_COLOR}]●[/black on {LETTER_COLOR}]█[black on {LETTER_COLOR}]●[/black on {LETTER_COLOR}]█╗██╗  ██╗ █████╗ ██████╗[/{LETTER_COLOR}]",
    f"[{LETTER_COLOR}]██╔════╝██║  ██║██╔══██╗██╔══██╗[/{LETTER_COLOR}]",
    f"[{LETTER_COLOR}]███████╗███████║███████║██║  ██║[/{LETTER_COLOR}]",
    f"[{LETTER_COLOR}]╚════██║██╔══██║██╔══██║██║  ██║[/{LETTER_COLOR}]",
    f"[{LETTER_COLOR}]███████║██║  ██║██║  ██║██████╔╝[/{LETTER_COLOR}]",
    f"[{LETTER_COLOR}]╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝[/{LETTER_COLOR}]",
    f"[{LETTER_COLOR}]                  ><(((>[/{LETTER_COLOR}]",
]


def print_banner() -> None:
    console = Console()
    for line in SHAD_ART:
        console.print(line)


if __name__ == "__main__":
    print_banner()
