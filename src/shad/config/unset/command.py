"""`shad config unset` — remove a key, or a whole project table."""

from __future__ import annotations

import argparse
from pathlib import Path

from rich.text import Text

from shad import parsers
from shad.config import store, toml_edit
from shad.deps import Deps
from shad.errors import ShadError
from shad.output import Output


def register(sub: parsers.Subparsers) -> None:
    parser = parsers.command(sub, "unset", run=run, help="Remove a key or a project table")
    parser.add_argument("key", metavar="KEY", help="Dotted key, e.g. projects.kb")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow removing a required key such as a project's path",
    )


def run(args: argparse.Namespace, deps: Deps) -> None:
    unset_config_value(deps.config_file, args.key, force=getattr(args, "force", False), out=deps.out)


def unset_config_value(path: Path, key: str, *, force: bool = False, out: Output) -> None:
    parts = toml_edit.split_dotted(key)

    if not force and parts[:1] == ["projects"] and len(parts) in (3, 4) and parts[-1] == "path":
        table = ".".join(parts[:-1])
        raise ShadError.validation(
            "required_key",
            f"'{key}' is required, and removing it would drop the project silently; "
            f"run 'shad config unset {table}' to remove the project, or pass --force"
        )

    text = store.read_text(path)
    updated = toml_edit.remove_path(text, parts)

    if store.lookup(store.parse_or_fail(updated), parts) is not store.MISSING:
        raise ShadError.conflict(
            "unsafe_edit",
            f"failed to unset '{key}': the file could not be edited safely; "
            f"use 'shad config edit'"
        )

    store.commit(path, updated)
    out.print(Text("  ✓ removed ", style="bold green") + Text(key, style="cyan"))
