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

import argparse
import hashlib
import os
import platform
import shutil
import subprocess
import tempfile
import tomllib
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.text import Text

from shad import parsers
from shad.config import store
from shad.deps import Deps
from shad.errors import ShadError
from shad.output import Output

# A pinned release, so the archive can be checked against a known SHA-256. Change the version and
# the checksum together, from the release's asset digest.
OPENCODE_VERSION = "1.19.5"
OPENCODE_LINUX_X64_SHA256 = "588310a336fa3b9df36b3f0225b26f679d453efaad0cf3d66c3651ef3ec1647a"
OPENCODE_INSTALL_URL = (
    "https://github.com/anomalyco/opencode/releases/download/"
    f"v{OPENCODE_VERSION}/opencode-linux-x64.tar.gz"
)


@dataclass(frozen=True)
class Dependency:
    binary: str
    package: str | None = None
    installer: Callable[[Output], None] | None = field(default=None, compare=False, hash=False)


def _expand(p: str) -> Path:
    return Path(p).expanduser().resolve()


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


def _run_install_command(out: Output, command: list[str], description: str) -> None:
    out.print(Text(f"  → {description}", style="cyan"))
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        raise ShadError.infrastructure("install_failed", f"command failed: {' '.join(command)}")


def _install_via_dnf(package: str) -> Callable[[Output], None]:
    """Return an installer callable that installs a single dnf package."""
    def _install(out: Output) -> None:
        _run_install_command(
            out, ["dnf", "install", "-y", package], f"installing {package} with dnf"
        )
    return _install


def _install_opencode_systemwide(out: Output) -> None:
    if platform.machine() != "x86_64":
        raise ShadError.infrastructure(
            "unsupported_platform",
            f"--install-deps installs opencode on x86_64 only, not on {platform.machine()}",
        )

    # This runs as root. A predictable directory under /tmp lets another local user create it
    # first and replace the binary before `install` copies it into /usr/local/bin.
    tmp_dir = Path(tempfile.mkdtemp(prefix="shad-opencode-"))
    archive = tmp_dir / OPENCODE_INSTALL_URL.rsplit("/", 1)[-1]
    binary = tmp_dir / "opencode"

    try:
        out.print(Text(f"  → installing opencode {OPENCODE_VERSION} to /usr/local/bin/opencode", style="cyan"))
        with urllib.request.urlopen(OPENCODE_INSTALL_URL) as response, archive.open("wb") as fh:
            shutil.copyfileobj(response, fh)

        with archive.open("rb") as fh:
            digest = hashlib.file_digest(fh, "sha256").hexdigest()
        if digest != OPENCODE_LINUX_X64_SHA256:
            raise ShadError.infrastructure(
                "checksum_mismatch",
                f"opencode archive checksum mismatch: expected {OPENCODE_LINUX_X64_SHA256}, got {digest}"
            )

        _run_install_command(
            out, ["tar", "-xzf", str(archive), "-C", str(tmp_dir)], "extracting opencode release"
        )
        _run_install_command(
            out, ["install", "-m", "0755", str(binary), "/usr/local/bin/opencode"], "copying opencode binary"
        )
    except ShadError:
        raise
    except Exception as exc:
        raise ShadError.infrastructure(
            "install_failed", f"failed to install opencode: {exc}"
        ) from exc
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


def ensure_dependencies_installed(out: Output) -> None:
    missing = _missing_dependencies()
    if not missing:
        out.print(Text("  ✓ dependencies already installed", style="bold green"))
        return

    if not _detect_fedora():
        raise ShadError.infrastructure(
            "unsupported_platform", "--install-deps currently supports Fedora only"
        )

    if not _is_root():
        raise ShadError.infrastructure(
            "not_root",
            "--install-deps must be run with sudo on Fedora; try: sudo shad init --install-deps"
        )

    for dep in missing:
        if dep.installer is not None:
            dep.installer(out)

    out.print(Text("  ✓ dependencies installed", style="bold green"))


def _toml_key(group: str | None, key: str) -> str:
    """Return the dotted TOML key for a project entry."""
    return f"projects.{group}.{key}" if group else f"projects.{key}"


# ── interactive wizard ────────────────────────────────────────────────────

def register(sub: parsers.Subparsers) -> None:
    parser = parsers.command(
        sub,
        "init",
        run=run,
        help="Add a new project to the config interactively",
        description=(
            "Interactive wizard that adds a new project to the resolved config file.\n"
            "Creates the config file with a commented [defaults] block if it does not exist yet.\n\n"
            "Options:\n"
            "  --install-deps  install missing tmux and opencode dependencies on Fedora\n\n"
            "Prompts:\n"
            "  path         Absolute path to the project root (must exist)\n"
            "  group        Optional group name; leave blank for a top-level project\n"
            "  key          Short project name; defaults to the directory name\n"
            "  session      tmux session name; defaults to <key> or <group>-<key>\n\n"
            "Examples:\n"
            "  shad init                         add a top-level project\n"
            "  sudo shad init --install-deps     install Fedora deps, then run init\n"
            "  shad init                         add a grouped project (enter group at prompt)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--install-deps",
        action="store_true",
        help="Install missing tmux and opencode dependencies on Fedora before prompting",
    )


def run(args: argparse.Namespace, deps: Deps) -> None:
    init_project(deps.config_file, deps.out, install_deps=args.install_deps)


def init_project(target: Path, out: Output, *, install_deps: bool = False) -> None:
    """The wizard: prompt for the project, then append it to *target*."""
    out.print()
    out.print(Text("shad init", style="bold cyan") + Text(" — add a new project", style="dim"))
    out.print()

    if install_deps:
        ensure_dependencies_installed(out)
        out.print()

    # --- path ---
    while True:
        raw_path = Prompt.ask("[cyan]  path[/cyan] [dim](e.g. ~/gh/myproject)[/dim]")
        project_path = _expand(raw_path)
        if project_path.exists():
            break
        out.note(Text(f"  ✗ path does not exist: {project_path}", style="bold red"))

    default_key = project_path.name

    # --- group ---
    group = Prompt.ask("[cyan]  group[/cyan] [dim](leave blank for top-level)[/dim]", default="") or None

    # --- key ---
    while True:
        key = Prompt.ask("[cyan]  key[/cyan]", default=default_key)
        if not _key_exists(target, group, key):
            break
        out.note(Text(f"  ✗ [{_toml_key(group, key)}] already exists in {target}", style="bold red"))

    # --- session ---
    default_session = f"{group}-{key}" if group else key
    session = Prompt.ask("[cyan]  session name[/cyan]", default=default_session)

    # --- confirm ---
    toml_key = _toml_key(group, key)
    out.print()
    out.print(Panel(
        f"[dim]\\[{toml_key}][/dim]\n"
        f"[dim]path    =[/dim] [bright_white]{project_path}[/bright_white]\n"
        f"[dim]session =[/dim] [bright_white]{session}[/bright_white]",
        border_style="cyan",
        padding=(0, 2),
    ))

    if not Confirm.ask("  Add to config?", default=True):
        out.print(Text("  Aborted.", style="dim"))
        return

    store.add_project(
        target, key=key, group=group, project_path=project_path, session=session
    )

    out.print()
    out.print(Text(f"  ✓ Added to {target}", style="bold green"))
    open_cmd = f"shad projects {group} {key}" if group else f"shad projects {key}"
    out.print(Text("  Open with: ", style="dim") + Text(open_cmd, style="cyan"))
    out.print()
