"""`shad config unset` — remove a key, or a whole project table."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.text import Text

from shad.config import store, toml_edit
from shad.errors import ShadError

console = Console()


def unset_config_value(path: Path, key: str, *, force: bool = False) -> None:
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
    console.print(Text("  ✓ removed ", style="bold green") + Text(key, style="cyan"))
