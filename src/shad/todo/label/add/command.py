"""`shad todo label add` — add a label to the `[todo] labels` vocabulary."""

from __future__ import annotations

import argparse
from pathlib import Path

from rich.text import Text

from shad import parsers
from shad.config.store import write_value
from shad.errors import ShadError
from shad.output import Output
from shad.todo.label.names import label_name


def register(sub: parsers.Subparsers) -> None:
    parser = parsers.command(sub, "add", run=run, help="Add a label to [todo] labels")
    parser.add_argument("name", metavar="NAME")


def run(
    args: argparse.Namespace,
    *,
    out: Output,
    config_file: Path,
    todo_labels: list[str],
) -> None:
    name = label_name(args)
    if name in todo_labels:
        raise ShadError.conflict("label_exists", f"label '{name}' is already configured")
    write_value(config_file, "todo.labels", [*todo_labels, name])
    out.print(Text("  ✓ ", style="bold green") + Text(f"added label {name}"))
