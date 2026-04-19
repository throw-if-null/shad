"""
Interactive wizard to add a new project to shad.toml.

Prompts for:
  - path (required, must exist)
  - group  (optional; leave blank for top-level)
  - key    (defaults to directory name)
  - session name (defaults to key or group-key)

Then appends the new [projects.*] entry to shad.toml.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

from rich.console import Console
from rich.text import Text
from rich.panel import Panel
from rich.prompt import Prompt, Confirm

from shad.config import CONFIG_PATH

console = Console()
err_console = Console(stderr=True)


def _expand(p: str) -> Path:
    return Path(p).expanduser().resolve()


def _append_toml(config_path: Path, group: str | None, key: str, path: Path, session: str) -> None:
    """Append a new project entry to shad.toml as raw TOML text."""
    if group:
        header = f"[projects.{group}.{key}]"
    else:
        header = f"[projects.{key}]"

    lines = [
        "",
        header,
        f'path    = "{path}"',
        f'session = "{session}"',
        "",
    ]

    with config_path.open("a") as fh:
        fh.write("\n".join(lines) + "\n")


def _key_exists(config_path: Path, group: str | None, key: str) -> bool:
    """Check whether the project key already exists in the config."""
    if not config_path.exists():
        return False
    with config_path.open("rb") as fh:
        raw = tomllib.load(fh)
    projects = raw.get("projects", {})
    if group:
        return key in projects.get(group, {})
    return key in projects


def cmd_init() -> None:
    console.print()
    console.print(Text("shad init", style="bold cyan") + Text(" — add a new project", style="dim"))
    console.print()

    # --- path ---
    while True:
        raw_path = Prompt.ask("[cyan]  path[/cyan] [dim](e.g. ~/gh/myproject)[/dim]")
        project_path = _expand(raw_path)
        if project_path.exists():
            break
        err_console.print(Text(f"  ✗ path does not exist: {project_path}", style="bold red"))

    default_key = project_path.name

    # --- group ---
    group = Prompt.ask("[cyan]  group[/cyan] [dim](leave blank for top-level)[/dim]", default="") or None

    # --- key ---
    key = Prompt.ask("[cyan]  key[/cyan]", default=default_key)

    # --- session ---
    default_session = f"{group}-{key}" if group else key
    session = Prompt.ask("[cyan]  session name[/cyan]", default=default_session)

    # --- check for duplicates ---
    if _key_exists(CONFIG_PATH, group, key):
        loc = f"projects.{group}.{key}" if group else f"projects.{key}"
        err_console.print(Text(f"\n  ✗ [{loc}] already exists in {CONFIG_PATH}", style="bold red"))
        sys.exit(1)

    # --- confirm ---
    toml_key = f"projects.{group}.{key}" if group else f"projects.{key}"
    console.print()
    console.print(Panel(
        f"[dim]\\[{toml_key}][/dim]\n"
        f"[dim]path    =[/dim] [bright_white]{project_path}[/bright_white]\n"
        f"[dim]session =[/dim] [bright_white]{session}[/bright_white]",
        border_style="cyan",
        padding=(0, 2),
    ))

    if not Confirm.ask("  Add to config?", default=True):
        console.print(Text("  Aborted.", style="dim"))
        sys.exit(0)

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _append_toml(CONFIG_PATH, group, key, project_path, session)

    console.print()
    console.print(Text(f"  ✓ Added to {CONFIG_PATH}", style="bold green"))
    open_cmd = f"shad projects {group} {key}" if group else f"shad projects {key}"
    console.print(Text(f"  Open with: ", style="dim") + Text(open_cmd, style="cyan"))
    console.print()
