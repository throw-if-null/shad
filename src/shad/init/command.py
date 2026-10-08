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
import platform
import shutil
import subprocess
import tomllib
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.text import Text

from shad.shared.config import config_path
from shad.shared.errors import ShadError

console = Console()
err_console = Console(stderr=True)

OPENCODE_INSTALL_URL = (
    "https://github.com/anomalyco/opencode/releases/latest/download/"
    f"opencode-linux-{platform.machine().replace('x86_64', 'x64')}.tar.gz"
)


@dataclass(frozen=True)
class Dependency:
    binary: str
    package: str | None = None
    installer: Callable[[], None] | None = field(default=None, compare=False, hash=False)


_DEFAULTS_BLOCK = """\
# ~/.config/shad/shad.toml

[defaults]
# Which side opencode occupies. The git+bash bundle takes the opposite side.
# Allowed values: top | bottom | left
# oc_position = "top"

# How much of the window the git+bash bundle takes (%).
# panel_percent = 35

# How much of the bundle the git panel takes (%). Bash gets the rest.
# split_percent = 35

# How much of the window width the todo column takes (%). 0 = no todo pane.
# Needs oc_position top or bottom; split_percent is then ignored.
# todo_percent = 0

# The labels `shad todo add --label` accepts. Managed by `shad todo label`.
# [todo]
# labels = ["chore", "documentation", "investigation", "poc"]

"""


# ── config helpers ────────────────────────────────────────────────────────

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


# ── dependency installation ───────────────────────────────────────────────

def _detect_fedora() -> bool:
    os_release = Path("/etc/os-release")
    if not os_release.exists():
        return False
    text = os_release.read_text()
    lines = {line.strip() for line in text.splitlines()}
    return (
        "ID=fedora" in lines
        or 'ID_LIKE="fedora"' in lines
        or "ID_LIKE=fedora" in lines
    )


def _is_root() -> bool:
    geteuid = getattr(os, "geteuid", None)
    if geteuid is None:
        return False
    return geteuid() == 0


def _run_install_command(command: list[str], description: str) -> None:
    console.print(Text(f"  → {description}", style="cyan"))
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        raise ShadError(f"command failed: {' '.join(command)}")


def _install_via_dnf(package: str) -> Callable[[], None]:
    """Return an installer callable that installs a single dnf package."""
    def _install() -> None:
        _run_install_command(["dnf", "install", "-y", package], f"installing {package} with dnf")
    return _install


def _install_opencode_systemwide() -> None:
    tmp_dir = Path("/tmp") / f"shad-opencode-{os.getpid()}"
    archive = tmp_dir / OPENCODE_INSTALL_URL.rsplit("/", 1)[-1]
    binary = tmp_dir / "opencode"

    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        console.print(Text("  → installing opencode to /usr/local/bin/opencode", style="cyan"))
        with urllib.request.urlopen(OPENCODE_INSTALL_URL) as response, archive.open("wb") as fh:
            shutil.copyfileobj(response, fh)

        _run_install_command(["tar", "-xzf", str(archive), "-C", str(tmp_dir)], "extracting opencode release")
        _run_install_command(["install", "-m", "0755", str(binary), "/usr/local/bin/opencode"], "copying opencode binary")
    except ShadError:
        raise
    except Exception as exc:
        raise ShadError(f"failed to install opencode: {exc}") from exc
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _build_dependencies() -> tuple[Dependency, ...]:
    """Build the dependency list with per-dep install strategies."""
    return (
        Dependency(binary="tmux", package="tmux", installer=_install_via_dnf("tmux")),
        Dependency(binary="opencode", installer=_install_opencode_systemwide),
    )


def _missing_dependencies() -> list[Dependency]:
    return [dep for dep in _build_dependencies() if shutil.which(dep.binary) is None]


def ensure_dependencies_installed() -> None:
    missing = _missing_dependencies()
    if not missing:
        console.print(Text("  ✓ dependencies already installed", style="bold green"))
        return

    if not _detect_fedora():
        raise ShadError("--install-deps currently supports Fedora only")

    if not _is_root():
        raise ShadError(
            "--install-deps must be run with sudo on Fedora\n"
            "    try: sudo shad init --install-deps"
        )

    for dep in missing:
        if dep.installer is not None:
            dep.installer()

    console.print(Text("  ✓ dependencies installed", style="bold green"))


def _toml_key(group: str | None, key: str) -> str:
    """Return the dotted TOML key for a project entry."""
    return f"projects.{group}.{key}" if group else f"projects.{key}"


# ── interactive wizard ────────────────────────────────────────────────────

def cmd_init(*, install_deps: bool = False, path: Path | None = None) -> None:
    target = path or config_path()

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
    while True:
        key = Prompt.ask("[cyan]  key[/cyan]", default=default_key)
        if not _key_exists(target, group, key):
            break
        err_console.print(Text(f"  ✗ [{_toml_key(group, key)}] already exists in {target}", style="bold red"))

    # --- session ---
    default_session = f"{group}-{key}" if group else key
    session = Prompt.ask("[cyan]  session name[/cyan]", default=default_session)

    # --- confirm ---
    toml_key = _toml_key(group, key)
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
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    is_new_file = not target.exists()
    if is_new_file:
        _write_defaults_block(target)
    _append_toml(target, group, key, project_path, session)

    console.print()
    console.print(Text(f"  ✓ Added to {target}", style="bold green"))
    open_cmd = f"shad projects {group} {key}" if group else f"shad projects {key}"
    console.print(Text("  Open with: ", style="dim") + Text(open_cmd, style="cyan"))
    console.print()
