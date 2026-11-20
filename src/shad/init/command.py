"""
Add a project to the config file.

`shad init --path DIR [--group G] [--key K] [--session S] [--harness H]`
adds the entry non-interactively; `shad init --wizard` prompts for the same
fields. init is idempotent: the same entry again is a no-op, and a different
path for an existing key is a conflict. The file is created with the
commented defaults block when it does not exist.

`--install-deps` installs the dependencies the harness in use needs: tmux
always, and opencode when it is the harness. For Claude Code it checks PATH
and points at the official installer, because shad bundles no Claude Code
installer. It is Fedora-only and must run as root.

Every write goes through `config.store.add_project`; init writes no file
directly.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import shutil
import subprocess
import tempfile
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.text import Text

from shad import parsers
from shad.config import raw, store
from shad.config.schema import HARNESSES, field_for
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

# shad bundles no Claude Code installer; it points the user at the official one.
CLAUDE_INSTALL_COMMAND = "npm install -g @anthropic-ai/claude-code"
CLAUDE_INSTALL_DOCS = "https://docs.claude.com/claude-code"


@dataclass(frozen=True)
class Dependency:
    binary: str
    package: str | None = None
    installer: Callable[[Output], None] | None = field(default=None, compare=False, hash=False)


def _expand(p: str) -> Path:
    return Path(p).expanduser().resolve()


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


def _default_harness() -> str:
    spec = field_for(["defaults", "harness"])
    return str(spec.default) if spec is not None else "opencode"


def _effective_harness(config_file: Path, override: str | None) -> str:
    """
    The harness `--install-deps` installs for: *override* when given, else the
    file's `[defaults] harness`, else the schema default. Reads the file
    tolerantly, so install-deps works before any project is configured.
    """
    if override:
        return override
    if config_file.exists():
        value = raw.lookup(raw.parse(config_file.read_text()), ["defaults", "harness"])
        if isinstance(value, str):
            return value
    return _default_harness()


def _dependencies_for(harness: str) -> list[Dependency]:
    """tmux always; the harness binary only when shad installs it. Claude Code
    is not here: shad bundles no installer for it."""
    deps = [Dependency(binary="tmux", package="tmux", installer=_install_via_dnf("tmux"))]
    if harness == "opencode":
        deps.append(Dependency(binary="opencode", installer=_install_opencode_systemwide))
    return deps


def ensure_dependencies_installed(out: Output, harness: str) -> None:
    installable = _dependencies_for(harness)
    missing = [dep for dep in installable if shutil.which(dep.binary) is None]

    if missing:
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
    else:
        out.print(Text("  ✓ dependencies already installed", style="bold green"))

    if harness == "claude" and shutil.which("claude") is None:
        out.print(Text("  ! Claude Code is not installed; shad bundles no installer.", style="yellow"))
        out.print(Text(f"    Install it with: {CLAUDE_INSTALL_COMMAND}", style="cyan"))
        out.print(Text(f"    Or see {CLAUDE_INSTALL_DOCS}", style="dim"))


def _toml_key(group: str | None, key: str) -> str:
    """Return the dotted TOML key for a project entry."""
    return f"projects.{group}.{key}" if group else f"projects.{key}"


def _project_parts(group: str | None, key: str) -> list[str]:
    return ["projects", *([group] if group else []), key]


def _key_exists(config_file: Path, group: str | None, key: str) -> bool:
    """Whether the project key already exists in the config."""
    if not config_file.exists():
        return False
    parsed = raw.parse(config_file.read_text())
    return raw.lookup(parsed, _project_parts(group, key)) is not raw.MISSING


def _existing_path(config_file: Path, group: str | None, key: str) -> str | None:
    """The `path` the config records for *key*, or None when it has none."""
    if not config_file.exists():
        return None
    parsed = raw.parse(config_file.read_text())
    value = raw.lookup(parsed, [*_project_parts(group, key), "path"])
    return value if isinstance(value, str) else None


# ── register / dispatch ───────────────────────────────────────────────────

def register(sub: parsers.Subparsers) -> None:
    parser = parsers.command(
        sub,
        "init",
        run=run,
        help="Add a project to the config",
        description=(
            "Add a new project to the resolved config file.\n"
            "Creates the file with a commented [defaults] block when it does not exist yet.\n\n"
            "Non-interactive (default):\n"
            "  shad init --path DIR [--group G] [--key K] [--session S] [--harness H]\n"
            "  init is idempotent: the same entry again is a no-op; a different path for\n"
            "  an existing key is a conflict.\n\n"
            "Interactive:\n"
            "  shad init --wizard            prompt for each field\n\n"
            "Dependencies:\n"
            "  sudo shad init --install-deps install the harness in use's deps on Fedora\n\n"
            "Examples:\n"
            "  shad init --path ~/gh/kb\n"
            "  shad init --path ~/gh/shad --group tin\n"
            "  sudo shad init --install-deps"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--path", metavar="DIR", help="Project root; absolute or ~ (required unless --wizard)")
    parser.add_argument("--group", metavar="GROUP", help="Optional group; omit for a top-level project")
    parser.add_argument("--key", metavar="KEY", help="Project key; defaults to the directory name")
    parser.add_argument("--session", metavar="NAME", help="tmux session name; defaults to <key> or <group>-<key>")
    parser.add_argument(
        "--harness", choices=sorted(HARNESSES), help="Harness for this project; defaults to [defaults] harness"
    )
    parser.add_argument("--wizard", action="store_true", help="Prompt for the fields instead of taking them as flags")
    parser.add_argument(
        "--install-deps",
        action="store_true",
        help="Install the harness in use's dependencies on Fedora before adding",
    )


def run(args: argparse.Namespace, deps: Deps) -> None:
    if args.install_deps:
        ensure_dependencies_installed(deps.out, _effective_harness(deps.config_file, args.harness))
        deps.out.print()

    if args.wizard:
        init_wizard(deps.config_file, deps.out)
        return

    if args.path is None:
        if args.install_deps:
            return
        raise ShadError.usage("missing_path", "give --path DIR, or --wizard to be prompted")

    add_project_entry(
        deps.config_file,
        deps.out,
        path=args.path,
        group=args.group,
        key=args.key,
        session=args.session,
        harness=args.harness,
    )


def add_project_entry(
    target: Path,
    out: Output,
    *,
    path: str,
    group: str | None,
    key: str | None,
    session: str | None,
    harness: str | None,
) -> None:
    """Add one project from flags. A re-add of the same path is a no-op; a
    different path for the same key is `project_exists`."""
    project_path = _expand(path)
    if not project_path.exists():
        raise ShadError.validation("path_missing", f"path does not exist: {project_path}")
    key = key or project_path.name
    session = session or (f"{group}-{key}" if group else key)

    existing = _existing_path(target, group, key)
    if existing is not None:
        if _expand(existing) == project_path:
            out.print(Text(f"  ✓ {_toml_key(group, key)} already configured", style="bold green"))
            return
        raise ShadError.conflict(
            "project_exists",
            f"[{_toml_key(group, key)}] already configured with a different path: {existing}",
        )

    store.add_project(
        target, key=key, group=group, project_path=project_path, session=session, harness=harness
    )
    _report_added(out, target, group, key)


def _report_added(out: Output, target: Path, group: str | None, key: str) -> None:
    out.print(Text(f"  ✓ Added to {target}", style="bold green"))
    open_cmd = f"shad projects {group} {key}" if group else f"shad projects {key}"
    out.print(Text("  Open with: ", style="dim") + Text(open_cmd, style="cyan"))


# ── interactive wizard ────────────────────────────────────────────────────

def init_wizard(target: Path, out: Output) -> None:
    """Prompt for a project, then append it to *target*."""
    out.print()
    out.print(Text("shad init", style="bold cyan") + Text(" — add a new project", style="dim"))
    out.print()

    while True:
        raw_path = Prompt.ask("[cyan]  path[/cyan] [dim](e.g. ~/gh/myproject)[/dim]")
        project_path = _expand(raw_path)
        if project_path.exists():
            break
        out.note(Text(f"  ✗ path does not exist: {project_path}", style="bold red"))

    default_key = project_path.name
    group = Prompt.ask("[cyan]  group[/cyan] [dim](leave blank for top-level)[/dim]", default="") or None

    while True:
        key = Prompt.ask("[cyan]  key[/cyan]", default=default_key)
        if not _key_exists(target, group, key):
            break
        out.note(Text(f"  ✗ [{_toml_key(group, key)}] already exists in {target}", style="bold red"))

    default_session = f"{group}-{key}" if group else key
    session = Prompt.ask("[cyan]  session name[/cyan]", default=default_session)

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

    store.add_project(target, key=key, group=group, project_path=project_path, session=session)

    out.print()
    _report_added(out, target, group, key)
    out.print()
