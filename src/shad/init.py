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

import os
import shutil
import subprocess
import sys
import tomllib
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.text import Text
from rich.panel import Panel
from rich.prompt import Prompt, Confirm

from shad.config import CONFIG_PATH

console = Console()
err_console = Console(stderr=True)

OPEN_CODE_INSTALL_URL = "https://github.com/anomalyco/opencode/releases/latest/download/opencode-linux-x64.tar.gz"


@dataclass(frozen=True)
class Dependency:
    binary: str
    package: str | None = None


_DEFAULTS_BLOCK = """\
# ~/.config/shad/shad.toml

[defaults]
# Which side opencode occupies. The git+bash bundle takes the opposite side.
# Allowed values: top | bottom | left
# oc_position = "top"

# How much of the window the git+bash bundle takes (%).
# panel_percent = 35

# How much of the bundle gitui takes (%). Bash gets the rest.
# split_percent = 35

"""

DEPENDENCIES = (
    Dependency(binary="tmux", package="tmux"),
    Dependency(binary="gitui", package="gitui"),
    Dependency(binary="opencode"),
)


def _write_defaults_block(config_path: Path) -> None:
    """Prepend a commented [defaults] block to a newly created config file."""
    with config_path.open("w") as fh:
        fh.write(_DEFAULTS_BLOCK)


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


def _detect_fedora() -> bool:
    os_release = Path("/etc/os-release")
    if not os_release.exists():
        return False

    text = os_release.read_text()
    return 'ID=fedora' in text or 'ID_LIKE="fedora"' in text or 'ID_LIKE=fedora' in text


def _is_root() -> bool:
    geteuid = getattr(os, "geteuid", None)
    if geteuid is None:
        return False
    return geteuid() == 0


def _missing_dependencies() -> list[Dependency]:
    return [dep for dep in DEPENDENCIES if shutil.which(dep.binary) is None]


def _run_install_command(command: list[str], description: str) -> None:
    console.print(Text(f"  → {description}", style="cyan"))
    result = subprocess.run(command)
    if result.returncode != 0:
        err_console.print(Text(f"  ✗ failed: {' '.join(command)}", style="bold red"))
        sys.exit(result.returncode or 1)


def _install_opencode_systemwide() -> None:
    tmp_dir = Path("/tmp") / f"shad-opencode-{os.getpid()}"
    archive = tmp_dir / "opencode-linux-x64.tar.gz"
    binary = tmp_dir / "opencode"

    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        console.print(Text("  → installing opencode to /usr/local/bin/opencode", style="cyan"))
        with urllib.request.urlopen(OPEN_CODE_INSTALL_URL) as response:
            archive.write_bytes(response.read())

        _run_install_command(["tar", "-xzf", str(archive), "-C", str(tmp_dir)], "extracting opencode release")
        _run_install_command(["install", "-m", "0755", str(binary), "/usr/local/bin/opencode"], "copying opencode binary")
    except Exception as exc:
        err_console.print(Text(f"  ✗ failed to install opencode: {exc}", style="bold red"))
        sys.exit(1)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def ensure_dependencies_installed() -> None:
    missing = _missing_dependencies()
    if not missing:
        console.print(Text("  ✓ dependencies already installed", style="bold green"))
        return

    if not _detect_fedora():
        err_console.print(Text("  ✗ --install-deps currently supports Fedora only", style="bold red"))
        sys.exit(1)

    if not _is_root():
        err_console.print(Text("  ✗ --install-deps must be run with sudo on Fedora", style="bold red"))
        err_console.print(Text("    try: sudo shad init --install-deps", style="dim"))
        sys.exit(1)

    packages = [dep.package for dep in missing if dep.package]
    if packages:
        _run_install_command(["dnf", "install", "-y", *packages], f"installing {', '.join(packages)} with dnf")

    if any(dep.binary == "opencode" for dep in missing):
        _install_opencode_systemwide()

    console.print(Text("  ✓ dependencies installed", style="bold green"))


def cmd_init(*, install_deps: bool = False) -> None:
    console.print()
    console.print(Text("shad init", style="bold cyan") + Text(" — add a new project", style="dim"))
    console.print()

    if install_deps:
        ensure_dependencies_installed()
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
    is_new_file = not CONFIG_PATH.exists()
    if is_new_file:
        _write_defaults_block(CONFIG_PATH)
    _append_toml(CONFIG_PATH, group, key, project_path, session)

    console.print()
    console.print(Text(f"  ✓ Added to {CONFIG_PATH}", style="bold green"))
    open_cmd = f"shad projects {group} {key}" if group else f"shad projects {key}"
    console.print(Text(f"  Open with: ", style="dim") + Text(open_cmd, style="cyan"))
    console.print()
