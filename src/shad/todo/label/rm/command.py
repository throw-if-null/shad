"""`shad todo label rm` — remove a label from the `[todo] labels` vocabulary."""

from __future__ import annotations

import argparse
from pathlib import Path

from rich.text import Text

from shad import parsers
from shad.config.store import write_value
from shad.errors import ShadError
from shad.output import Output
from shad.todo import store
from shad.todo.label.names import label_name


def register(sub: parsers.Subparsers) -> None:
    parser = parsers.command(sub, "rm", run=run, help="Remove a label from [todo] labels")
    parser.add_argument("name", metavar="NAME")
    parser.add_argument(
        "--force", action="store_true", help="Remove the label even when items still carry it"
    )


def run(
    args: argparse.Namespace,
    *,
    out: Output,
    config_file: Path,
    todo_dir: Path,
    todo_labels: list[str],
) -> None:
    name = label_name(args)
    if name not in todo_labels:
        known = ", ".join(todo_labels) if todo_labels else "none"
        raise ShadError.not_found(
            "no_such_label", f"label '{name}' is not configured; configured labels: {known}"
        )
    usage = _usage(todo_dir, name)
    if usage and not getattr(args, "force", False):
        raise ShadError.conflict(
            "label_in_use",
            f"label '{name}' is still used by {usage} item(s); "
            f"remove it from those items first, or pass --force",
        )
    write_value(
        config_file, "todo.labels", [label for label in todo_labels if label != name]
    )
    out.print(Text("  ✓ ", style="bold green") + Text(f"removed label {name}"))


def _usage(directory: Path, label: str) -> int:
    """How many items in *directory* carry *label*. A file removed between the
    listing and its read is skipped."""
    count = 0
    for key in store.keys(directory):
        try:
            item = store.read_item(directory, key)
        except ShadError:
            continue
        if label in item.labels:
            count += 1
    return count
