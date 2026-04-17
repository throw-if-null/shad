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

from shad.config import CONFIG_PATH


def _prompt(label: str, default: str | None = None, required: bool = True) -> str:
    hint = f" [{default}]" if default else ""
    while True:
        raw = input(f"  {label}{hint}: ").strip()
        if raw:
            return raw
        if default is not None:
            return default
        if not required:
            return ""
        print(f"    ! {label} is required")


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
    print("\nshad init — add a new project\n")

    # --- path ---
    while True:
        raw_path = _prompt("path (e.g. ~/gh/myproject)")
        project_path = _expand(raw_path)
        if project_path.exists():
            break
        print(f"    ! path does not exist: {project_path}")

    default_key = project_path.name

    # --- group ---
    group = _prompt("group (leave blank for top-level)", default="", required=False) or None

    # --- key ---
    key = _prompt("key", default=default_key)

    # --- session ---
    default_session = f"{group}-{key}" if group else key
    session = _prompt("session name", default=default_session)

    # --- check for duplicates ---
    if _key_exists(CONFIG_PATH, group, key):
        loc = f"projects.{group}.{key}" if group else f"projects.{key}"
        print(f"\n  ! [{loc}] already exists in {CONFIG_PATH}", file=sys.stderr)
        sys.exit(1)

    # --- confirm ---
    print()
    if group:
        print(f"  [{f'projects.{group}.{key}'}]")
    else:
        print(f"  [projects.{key}]")
    print(f"  path    = {project_path}")
    print(f"  session = {session}")
    print()

    confirm = input("  Add to config? [Y/n]: ").strip().lower()
    if confirm not in ("", "y", "yes"):
        print("  Aborted.")
        sys.exit(0)

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _append_toml(CONFIG_PATH, group, key, project_path, session)

    print(f"\n  Done. Added to {CONFIG_PATH}")
    if group:
        print(f"  Open with: shad projects {group} {key}\n")
    else:
        print(f"  Open with: shad projects {key}\n")
