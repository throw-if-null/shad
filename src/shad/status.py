"""
Project status reporting for shad.

Prints a human-readable summary of:
  - tmux session state
  - git: branch, latest tag, last 3 commits, dirty file count
  - detected runtimes (Python, Node, Go, Rust, Deno) based on
    manifest files found in the project path, with latest available
    versions fetched in parallel
  - opencode version (since it is the default top_command)
"""

from __future__ import annotations

import json
import shutil
import subprocess
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from shad.config import Project
from shad.tmux import session_exists


# ── helpers ───────────────────────────────────────────────────────────────

def _run(args: list[str], *, cwd: Path | None = None) -> str:
    """Run a command and return stripped stdout, or '' on failure."""
    try:
        result = subprocess.run(args, capture_output=True, text=True, cwd=cwd)
        return result.stdout.strip() if result.returncode == 0 else ""
    except FileNotFoundError:
        return ""


def _fetch_json(url: str, timeout: int = 4) -> object:
    """Fetch a URL and parse JSON, returning None on any failure."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _section(title: str) -> str:
    return f"\n\033[1;34m{title}\033[0m"


def _row(label: str, value: str) -> str:
    return f"  \033[2m{label:<18}\033[0m {value}"


def _dim(text: str) -> str:
    return f"\033[2m{text}\033[0m"


def _latest_badge(installed: str, latest: str | None) -> str:
    """Return a coloured badge comparing installed vs latest."""
    if not latest:
        return installed

    # normalise: strip leading 'v', take first word
    def _norm(v: str) -> str:
        return v.lstrip("v").split()[0]

    inst_n = _norm(installed)
    lat_n = _norm(latest)

    if inst_n == lat_n:
        badge = f"\033[32m✓ latest ({latest})\033[0m"
    else:
        badge = f"\033[33m latest: {latest}\033[0m"

    return f"{installed}  {badge}"


# ── latest version fetchers ───────────────────────────────────────────────

def _latest_python() -> str | None:
    data = _fetch_json("https://endoflife.date/api/python.json")
    if isinstance(data, list) and data:
        return data[0].get("latest")
    return None


def _latest_node() -> str | None:
    data = _fetch_json("https://nodejs.org/dist/index.json")
    if isinstance(data, list) and data:
        return data[0].get("version")
    return None


def _latest_go() -> str | None:
    data = _fetch_json("https://go.dev/dl/?mode=json")
    if isinstance(data, list):
        stable = [r for r in data if not r.get("unstable", False)]
        if stable:
            return stable[0].get("version")
    return None


def _latest_rust() -> str | None:
    data = _fetch_json("https://api.github.com/repos/rust-lang/rust/releases/latest")
    if isinstance(data, dict):
        return data.get("tag_name")
    return None


def _latest_deno() -> str | None:
    data = _fetch_json("https://api.github.com/repos/denoland/deno/releases/latest")
    if isinstance(data, dict):
        return data.get("tag_name")
    return None


_LATEST_FETCHERS: dict[str, object] = {
    "python": _latest_python,
    "node":   _latest_node,
    "go":     _latest_go,
    "rust":   _latest_rust,
    "deno":   _latest_deno,
}


# ── tmux ──────────────────────────────────────────────────────────────────

def _tmux_status(project: Project) -> list[str]:
    running = session_exists(project.session)
    state = "\033[32mrunning\033[0m" if running else _dim("not running")
    return [
        _section("tmux"),
        _row("session", f"{project.session}  {state}"),
    ]


# ── git ───────────────────────────────────────────────────────────────────

def _git_status(path: Path) -> list[str]:
    if not (path / ".git").exists():
        return [_section("git"), "  " + _dim("not a git repository")]

    lines: list[str] = [_section("git")]

    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=path)
    lines.append(_row("branch", branch or _dim("unknown")))

    tag = _run(["git", "describe", "--tags", "--abbrev=0"], cwd=path)
    lines.append(_row("latest tag", tag or _dim("no tags")))

    dirty = _run(["git", "status", "--short"], cwd=path)
    dirty_count = len([l for l in dirty.splitlines() if l.strip()])
    if dirty_count:
        lines.append(_row("uncommitted", f"\033[33m{dirty_count} file(s)\033[0m"))
    else:
        lines.append(_row("uncommitted", _dim("clean")))

    log = _run(
        ["git", "log", "--format=%C(yellow)%h%Creset %s %C(dim)(%cr)%Creset", "-3"],
        cwd=path,
    )
    if log:
        lines.append(_row("last commits", ""))
        for entry in log.splitlines():
            lines.append(f"    {entry}")
    else:
        lines.append(_row("last commits", _dim("no commits")))

    return lines


# ── runtimes ──────────────────────────────────────────────────────────────

_RUNTIME_CHECKS: list[tuple[str, list[str], list[str]]] = [
    (
        "python",
        ["pyproject.toml", "setup.py", "requirements.txt", ".python-version", "Pipfile"],
        ["python3", "--version"],
    ),
    (
        "node",
        ["package.json", ".nvmrc", ".node-version"],
        ["node", "--version"],
    ),
    (
        "go",
        ["go.mod"],
        ["go", "version"],
    ),
    (
        "rust",
        ["Cargo.toml"],
        ["rustc", "--version"],
    ),
    (
        "deno",
        ["deno.json", "deno.jsonc"],
        ["deno", "--version"],
    ),
]


def _detect_runtimes(path: Path) -> list[str]:
    detected: list[tuple[str, str]] = []  # (label, installed_version)
    for label, manifests, cmd in _RUNTIME_CHECKS:
        if not any((path / m).exists() for m in manifests):
            continue
        version = _run(cmd)
        detected.append((label, version.splitlines()[0] if version else ""))

    if not detected:
        return []

    # fetch latest versions in parallel
    latest: dict[str, str | None] = {}
    with ThreadPoolExecutor(max_workers=len(detected)) as pool:
        futures = {
            pool.submit(_LATEST_FETCHERS[label]): label  # type: ignore[operator]
            for label, _ in detected
            if label in _LATEST_FETCHERS
        }
        for future in as_completed(futures):
            label = futures[future]
            try:
                latest[label] = future.result()
            except Exception:
                latest[label] = None

    lines: list[str] = [_section("runtimes")]
    for label, installed in detected:
        if not installed:
            lines.append(_row(label, _dim("not found in PATH")))
        else:
            # find the binary used for this runtime
            binary = _RUNTIME_CHECKS[[r[0] for r in _RUNTIME_CHECKS].index(label)][2][0]
            path_str = shutil.which(binary)
            location = f"  \033[2m{path_str}\033[0m" if path_str else ""
            lines.append(_row(label, _latest_badge(installed, latest.get(label)) + location))

    return lines


# ── opencode ──────────────────────────────────────────────────────────────

def _opencode_status() -> list[str]:
    version = _run(["opencode", "--version"])
    if not version:
        return []
    return [_section("opencode"), _row("version", version.splitlines()[0])]


# ── public entry point ────────────────────────────────────────────────────

def print_status(project: Project) -> None:
    path = project.path

    print(f"\033[1m{project.display_name}\033[0m  \033[2m{path}\033[0m")

    sections: list[list[str]] = [
        _tmux_status(project),
        _git_status(path),
        _detect_runtimes(path),
        _opencode_status(),
    ]

    for section in sections:
        for line in section:
            print(line)

    print()
