"""
Project status reporting for shad.

Prints a human-readable summary as a series of titled tables:
  - tmux session state
  - git: branch, latest tag, last 3 commits, dirty file count
  - detected runtimes (Python, Node, Go, Rust, Deno) based on
    manifest files found in the project path, with latest available
    versions fetched in parallel
  - opencode version (since it is the default top_command)
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import urllib.error
import urllib.request
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.text import Text
from rich import box

from shad.config import Project
from shad.tmux import list_project_sessions, tmux_server_running

console = Console()


# ── subprocess / fetch helpers ────────────────────────────────────────────

def _run(args: list[str], *, cwd: Path | None = None) -> str:
    try:
        r = subprocess.run(args, capture_output=True, text=True, cwd=cwd)
        return r.stdout.strip() if r.returncode == 0 else ""
    except FileNotFoundError:
        return ""

def _fetch_json(url: str, timeout: int = 4) -> object:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        warnings.warn(f"shad: version fetch failed ({url}): {exc}", stacklevel=2)
        return None


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


# ── table helpers ─────────────────────────────────────────────────────────

def _make_table(title: str) -> Table:
    t = Table(
        title=title,
        box=box.ROUNDED,
        show_header=False,
        title_justify="left",
        title_style="bold cyan",
        border_style="bright_black",
        pad_edge=True,
        show_edge=True,
        padding=(0, 1),
    )
    return t


# ── section builders ──────────────────────────────────────────────────────

def _print_tmux(project: Project) -> None:
    t = _make_table("tmux")
    running = list_project_sessions(project.session)
    if not running:
        if not tmux_server_running():
            t.add_row(Text("session", style="dim"), Text(project.session), Text("tmux not running", style="dim"))
        else:
            t.add_row(Text("session", style="dim"), Text(project.session), Text("not running", style="dim"))
        console.print(t)
        return

    for index, session in enumerate(running):
        label = Text("session", style="dim") if index == 0 else Text("")
        display = Text(session)
        if session == project.session:
            display.append("  (base)", style="dim")
        t.add_row(label, display, Text("running", style="bold green"))

    console.print(t)


def _print_git(path: Path) -> None:
    if not (path / ".git").exists():
        console.print(Text("  (not a git repository)", style="dim"))
        return

    t = _make_table("git")

    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=path)
    t.add_row(Text("branch", style="dim"), Text(branch or "unknown", style="dim"))

    tag = _run(["git", "describe", "--tags", "--abbrev=0"], cwd=path)
    t.add_row(Text("latest tag", style="dim"), Text(tag if tag else "—", style="" if tag else "dim"))

    dirty = _run(["git", "status", "--short"], cwd=path)
    dirty_count = len([l for l in dirty.splitlines() if l.strip()])
    if dirty_count:
        dirty_val = Text(f"{dirty_count} file(s)", style="yellow")
    else:
        dirty_val = Text("clean", style="dim")
    t.add_row(Text("uncommitted", style="dim"), dirty_val)

    log = _run(["git", "log", "--format=%h\x1f%s\x1f%cr", "-3"], cwd=path)
    if log:
        for i, entry in enumerate(log.splitlines()):
            parts = entry.split("\x1f", 2)
            h, subj, age = (parts + ["", "", ""])[:3]
            label = Text("commits", style="dim") if i == 0 else Text("")
            row = Text()
            row.append(h, style="yellow")
            row.append("  ")
            row.append(subj)
            row.append("  ")
            row.append(age, style="dim")
            t.add_row(label, row)
    else:
        t.add_row(Text("commits", style="dim"), Text("none", style="dim"))

    console.print(t)


def _print_runtimes(path: Path) -> None:
    checks: list[tuple[str, list[str], list[str]]] = [
        ("python", ["pyproject.toml", "setup.py", "requirements.txt", ".python-version", "Pipfile"], ["python3", "--version"]),
        ("node",   ["package.json", ".nvmrc", ".node-version"], ["node", "--version"]),
        ("go",     ["go.mod"],        ["go", "version"]),
        ("rust",   ["Cargo.toml"],    ["rustc", "--version"]),
        ("deno",   ["deno.json", "deno.jsonc"], ["deno", "--version"]),
    ]

    detected: list[tuple[str, str, str]] = []
    for label, manifests, cmd in checks:
        if not any((path / m).exists() for m in manifests):
            continue
        version = _run(cmd)
        installed = version.splitlines()[0] if version else ""
        detected.append((label, installed, cmd[0]))

    # filter out runtimes not in PATH
    detected = [(l, v, b) for l, v, b in detected if v]
    if not detected:
        return

    # fetch latest versions in parallel
    latest: dict[str, str | None] = {}
    with ThreadPoolExecutor(max_workers=max(1, len(detected))) as pool:
        futures = {
            pool.submit(_LATEST_FETCHERS[label]): label  # type: ignore[operator]
            for label, _, _ in detected
            if label in _LATEST_FETCHERS
        }
        for future in as_completed(futures):
            lbl = futures[future]
            try:
                latest[lbl] = future.result()
            except Exception as exc:
                warnings.warn(f"shad: latest version fetch failed for {lbl}: {exc}", stacklevel=2)
                latest[lbl] = None

    def _semver(v: str) -> str:
        for part in v.split():
            s = part.lstrip("v")
            if s.startswith("go") and s[2:3].isdigit():
                return s[2:]
            if s[:1].isdigit():
                return s.split()[0]
        return v.strip()

    def _version_tuple(v: str) -> tuple[int, ...]:
        try:
            return tuple(int(x) for x in v.split("."))
        except ValueError:
            return ()

    def _version_style(installed_v: str, latest_v: str) -> str:
        i = _version_tuple(installed_v)
        latest = _version_tuple(latest_v)
        if not i or not latest or i == latest:
            return "dim"
        if latest[0] != i[0]:
            return "red"
        if len(latest) > 1 and len(i) > 1 and latest[1] != i[1]:
            return "yellow"
        return "green"

    t = _make_table("runtimes")
    t.add_column(style="dim")       # name
    t.add_column()                  # installed
    t.add_column()                  # latest
    t.add_column(style="dim")       # path

    for label, installed, binary in detected:
        bin_path = shutil.which(binary) or "—"
        installed_str = _semver(installed)
        lat = latest.get(label)
        if lat:
            latest_v = _semver(lat)
            style = _version_style(installed_str, latest_v)
            latest_text = Text(latest_v, style=style)
        else:
            latest_text = Text("—", style="dim")

        t.add_row(label, installed_str, latest_text, bin_path)

    console.print(t)


def _print_opencode() -> None:
    version = _run(["opencode", "--version"])
    if not version:
        return
    t = _make_table("opencode")
    t.add_row(Text("version", style="dim"), Text(version.splitlines()[0]))
    console.print(t)


# ── public entry point ────────────────────────────────────────────────────

def print_status(project: Project) -> None:
    console.print()
    console.print(
        Text(project.display_name, style="bold bright_white") +
        Text(f"  {project.path}", style="dim")
    )
    console.print()
    _print_tmux(project)
    console.print()
    _print_git(project.path)
    console.print()
    _print_runtimes(project.path)
    _print_opencode()
    console.print()
