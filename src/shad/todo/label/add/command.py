"""`shad todo label add` — add a label to the `[todo] labels` vocabulary."""

from __future__ import annotations

import argparse

from rich.text import Text

from shad import parsers
from shad.config.store import write_value
from shad.deps import Deps
from shad.errors import ShadError
from shad.todo.label.names import label_name


def register(sub: parsers.Subparsers) -> None:
    parser = parsers.command(sub, "add", run=run, help="Add a label to [todo] labels")
    parser.add_argument("name", metavar="NAME")


def run(args: argparse.Namespace, deps: Deps) -> None:
    cfg = deps.config
    name = label_name(args)
    if name in cfg.todo_labels:
        raise ShadError.conflict("label_exists", f"label '{name}' is already configured")
    write_value(deps.config_file, "todo.labels", [*cfg.todo_labels, name])
    deps.out.print(Text("  ✓ ", style="bold green") + Text(f"added label {name}"))
