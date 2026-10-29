"""`shad config set` — one validated value; comments and layout are kept."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.text import Text

from shad.config import store, toml_edit
from shad.config.schema import PATH, coerce, field_for, infer
from shad.shared.errors import ShadError

console = Console()


def set_config_value(path: Path, key: str, raw_value: str, *, force: bool) -> None:
    parts = toml_edit.split_dotted(key)
    field = field_for(parts)

    if field is None:
        if not force:
            raise ShadError(
                f"unknown key '{key}'; run 'shad config keys' to list settable keys, "
                f"or pass --force to write it anyway"
            )
        value, literal = infer(raw_value)
    else:
        value, literal = coerce(field, raw_value, key)
        if field.kind == PATH and not force and not Path(str(value)).is_dir():
            raise ShadError(
                f"path does not exist: {value}\n"
                f"       pass --force to set it anyway."
            )

    text = store.read_text(path) if path.exists() else ""
    updated = toml_edit.set_value(text, parts, literal)

    written = store.lookup(store.parse_or_fail(updated), parts)
    if written != value:
        raise ShadError(
            f"failed to set '{key}': the file could not be edited safely; "
            f"use 'shad config edit'"
        )

    project_hint = None
    if parts[:1] == ["projects"] and parts[-1] != "path":
        project_hint = "for a new project, set its 'path' first."

    store.commit(path, updated, hint=project_hint)

    console.print(
        Text("  ✓ ", style="bold green")
        + Text(key, style="cyan")
        + Text(" = ", style="dim")
        + Text(literal, style="bright_white")
    )
