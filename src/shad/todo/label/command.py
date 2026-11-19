"""
`shad todo label` — add, rm, list: the label vocabulary in shad.toml.

The three act on one config key, `[todo] labels`, through the config
slice's `write_value`, so comments in the file survive.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from rich.console import Console
from rich.text import Text

from shad.config.store import write_value
from shad.errors import ShadError
from shad.shared.config import LABEL_RE, Config
from shad.todo import store

console = Console()

LABEL_ACTIONS = ("add", "rm", "list")


def manage_labels(cfg: Config, args: argparse.Namespace, path: Path) -> None:
    """*path* is the config file the vocabulary is written to."""
    action = getattr(args, "label_action", None)
    if action is None:
        raise ShadError.usage(
            "no_action", f"no label action given; available: {', '.join(LABEL_ACTIONS)}"
        )

    if action == "list":
        for label in cfg.todo_labels:
            print(label)
        return

    name: str = args.name.strip()
    if not LABEL_RE.match(name):
        raise ShadError.validation(
            "invalid_label", f"invalid label {name!r}; use lowercase letters, digits and hyphens"
        )

    if action == "add":
        if name in cfg.todo_labels:
            raise ShadError.conflict("label_exists", f"label '{name}' is already configured")
        write_value(path, "todo.labels", [*cfg.todo_labels, name])
        console.print(Text("  ✓ ", style="bold green") + Text(f"added label {name}"))
        return

    if action == "rm":
        if name not in cfg.todo_labels:
            known = ", ".join(cfg.todo_labels) if cfg.todo_labels else "none"
            raise ShadError.not_found(
                "no_such_label", f"label '{name}' is not configured; configured labels: {known}"
            )
        usage = store.label_usage(store.todo_dir(cfg), name)
        if usage and not getattr(args, "force", False):
            raise ShadError.conflict(
                "label_in_use",
                f"label '{name}' is still used by {usage} item(s); "
                f"remove it from those items first, or pass --force"
            )
        write_value(path, "todo.labels", [label for label in cfg.todo_labels if label != name])
        console.print(Text("  ✓ ", style="bold green") + Text(f"removed label {name}"))
        return

    raise ShadError.usage(
        "unknown_action", f"unknown label action '{action}'; available: {', '.join(LABEL_ACTIONS)}"
    )
