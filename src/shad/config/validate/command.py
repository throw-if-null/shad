"""`shad config validate` — load the file and report what it holds."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.text import Text

from shad.shared.config import load

console = Console()


def validate_config(path: Path) -> None:
    cfg = load(path)
    count = len(cfg.projects) + sum(len(group) for group in cfg.groups.values())
    console.print(
        Text("  ✓ ", style="bold green")
        + Text(f"{path} is valid", style="bright_white")
        + Text(f"  ({count} project(s), {len(cfg.groups)} group(s))", style="dim")
    )
