"""
`shad todo label` — add, rm, list: the label vocabulary in shad.toml.

The three act on one config key, `[todo] labels`, through the config
slice's `write_value`, so comments in the file survive.
"""

from __future__ import annotations

import argparse

from rich.text import Text

from shad import parsers
from shad.config import LABEL_RE
from shad.config.store import write_value
from shad.deps import Deps
from shad.errors import ShadError
from shad.todo import store


def register(sub: parsers.Subparsers) -> None:
    _, actions = parsers.group(
        sub, "label", dest="label_action", help="Manage the label vocabulary"
    )
    add = parsers.command(actions, "add", run=run_add, help="Add a label to [todo] labels")
    add.add_argument("name", metavar="NAME")
    rm = parsers.command(actions, "rm", run=run_rm, help="Remove a label from [todo] labels")
    rm.add_argument("name", metavar="NAME")
    rm.add_argument(
        "--force", action="store_true", help="Remove the label even when items still carry it"
    )
    parsers.command(
        actions,
        "list",
        run=run_list,
        help="Print the labels, one per line (the machine form as it is)",
    )


def run_list(args: argparse.Namespace, deps: Deps) -> None:
    for label in deps.config.todo_labels:
        deps.out.plain(label)


def run_add(args: argparse.Namespace, deps: Deps) -> None:
    cfg = deps.config
    name = _name(args)
    if name in cfg.todo_labels:
        raise ShadError.conflict("label_exists", f"label '{name}' is already configured")
    write_value(deps.config_file, "todo.labels", [*cfg.todo_labels, name])
    deps.out.print(Text("  ✓ ", style="bold green") + Text(f"added label {name}"))


def run_rm(args: argparse.Namespace, deps: Deps) -> None:
    cfg = deps.config
    name = _name(args)
    if name not in cfg.todo_labels:
        known = ", ".join(cfg.todo_labels) if cfg.todo_labels else "none"
        raise ShadError.not_found(
            "no_such_label", f"label '{name}' is not configured; configured labels: {known}"
        )
    usage = store.label_usage(cfg.todo_dir, name)
    if usage and not getattr(args, "force", False):
        raise ShadError.conflict(
            "label_in_use",
            f"label '{name}' is still used by {usage} item(s); "
            f"remove it from those items first, or pass --force",
        )
    write_value(
        deps.config_file, "todo.labels", [label for label in cfg.todo_labels if label != name]
    )
    deps.out.print(Text("  ✓ ", style="bold green") + Text(f"removed label {name}"))


def _name(args: argparse.Namespace) -> str:
    name: str = args.name.strip()
    if not LABEL_RE.match(name):
        raise ShadError.validation(
            "invalid_label", f"invalid label {name!r}; use lowercase letters, digits and hyphens"
        )
    return name
