"""`shad config set` — one validated value; comments and layout are kept."""

from __future__ import annotations

import argparse
from pathlib import Path

from rich.text import Text

from shad import parsers
from shad.config import raw, store, toml_edit
from shad.config.schema import PATH, coerce, field_for, infer
from shad.deps import Deps
from shad.errors import ShadError
from shad.output import Output


def register(sub: parsers.Subparsers) -> None:
    parser = parsers.command(sub, "set", run=run, help="Set a single value")
    parser.add_argument("key", metavar="KEY", help="Dotted key, e.g. defaults.harness")
    parser.add_argument("value", metavar="VALUE", help="New value")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip key and path checks (still requires the result to be a loadable config)",
    )


def run(args: argparse.Namespace, deps: Deps) -> None:
    set_config_value(
        deps.config_file, args.key, args.value, force=getattr(args, "force", False), out=deps.out
    )


def set_config_value(path: Path, key: str, raw_value: str, *, force: bool, out: Output) -> None:
    parts = toml_edit.split_dotted(key)
    field = field_for(parts)

    if field is None:
        if not force:
            raise ShadError.validation(
                "unknown_key",
                f"unknown key '{key}'; run 'shad config keys' to list settable keys, "
                f"or pass --force to write it anyway"
            )
        value, literal = infer(raw_value)
    else:
        value, literal = coerce(field, raw_value, key)
        if field.kind == PATH and not force and not Path(str(value)).is_dir():
            raise ShadError.validation(
                "path_missing",
                f"path does not exist: {value}; pass --force to set it anyway"
            )

    text = path.read_text() if path.exists() else ""
    updated = toml_edit.set_value(text, parts, literal)

    written = raw.lookup(raw.parse(updated), parts)
    if written != value:
        raise ShadError.conflict(
            "unsafe_edit",
            f"failed to set '{key}': the file could not be edited safely; "
            f"use 'shad config edit'"
        )

    project_hint = None
    if parts[:1] == ["projects"] and parts[-1] != "path":
        project_hint = "for a new project, set its 'path' first."

    store.commit(path, updated, hint=project_hint)

    out.print(
        Text("  ✓ ", style="bold green")
        + Text(key, style="cyan")
        + Text(" = ", style="dim")
        + Text(literal, style="bright_white")
    )
