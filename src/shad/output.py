"""
The streams a command prints to.

The root constructs one Output per run and injects it. No module holds a
Console of its own, so a test that redirects the process streams captures
every line, and the root alone decides what reaches stdout.
"""

from __future__ import annotations

import json
from typing import IO

from rich.console import Console, RenderableType


class Output:
    """
    stdout for what a command produces; stderr for what it reports about
    the run, such as a session that could not be saved or a tab that could
    not be opened.
    """

    def __init__(
        self,
        stdout: IO[str] | None = None,
        stderr: IO[str] | None = None,
        *,
        width: int | None = None,
        color: bool | None = None,
    ) -> None:
        """
        *width* and *color* default to what the stream is: its terminal
        width, and color when it is a terminal. A Console with no file
        resolves sys.stdout at each print, so the streams in place when a
        command prints are the ones written to.
        """
        self.stdout = Console(file=stdout, width=width, force_terminal=color)
        self.stderr = Console(file=stderr, stderr=True, width=width, force_terminal=color)

    @property
    def width(self) -> int:
        """The width the stdout table layouts fit."""
        return self.stdout.width

    def print(self, *renderables: RenderableType) -> None:
        """Rich renderables on stdout, or an empty line with none."""
        self.stdout.print(*renderables)

    def note(self, *renderables: RenderableType) -> None:
        """Rich renderables on stderr: a report about the run, never the result."""
        self.stderr.print(*renderables)

    def plain(self, text: str) -> None:
        """
        *text* and a newline on stdout, byte for byte. The commands whose
        plain output is the machine form print through this: rich's print
        would read `[todo]` as markup and wrap a long line.
        """
        self.stdout.file.write(text + "\n")

    def json(self, document: object) -> None:
        """*document* as one JSON document on stdout, and nothing else."""
        self.stdout.file.write(json.dumps(document, indent=2, default=str) + "\n")
