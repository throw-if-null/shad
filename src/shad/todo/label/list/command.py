"""`shad todo label list` — print the configured labels, one per line.

This is a published surface: the completion script parses the output as one
plain label per line.
"""

from __future__ import annotations

import argparse

from shad import parsers
from shad.output import Output


def register(sub: parsers.Subparsers) -> None:
    parsers.command(
        sub,
        "list",
        run=run,
        help="Print the labels, one per line (the machine form as it is)",
    )


def run(args: argparse.Namespace, *, out: Output, todo_labels: list[str]) -> None:
    for label in todo_labels:
        out.plain(label)
