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
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from shad.config import Project
from shad.tmux import session_exists


# ── ANSI helpers ──────────────────────────────────────────────────────────

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def _vlen(s: str) -> int:
    """Visible length of a string, ignoring ANSI escape codes."""
    return len(_ANSI_RE.sub("", s))


def _vpad(s: str, width: int) -> str:
    """Pad *s* to *width* visible characters."""
    return s + " " * max(0, width - _vlen(s))


def _dim(text: str) -> str:
    return f"\033[2m{text}\033[0m"


def _green(text: str) -> str:
    return f"\033[32m{text}\033[0m"


def _yellow(text: str) -> str:
    return f"\033[33m{text}\033[0m"


def _bold(text: str) -> str:
    return f"\033[1m{text}\033[0m"


# ── Table renderer ────────────────────────────────────────────────────────

Row = list[str]  # one cell per column


def _render_table(title: str, rows: list[Row]) -> list[str]:
    """
    Render *rows* as a box-drawing table with a titled top border.

    ┌─ title ──────────────────┐
    │ col1   col2   col3       │
    │ ...                      │
    └──────────────────────────┘
    """
    if not rows:
        return []

    col_count = max(len(r) for r in rows)
    # normalise: all rows same length
    padded_rows = [r + [""] * (col_count - len(r)) for r in rows]

    col_widths = [0] * col_count
    for row in padded_rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], _vlen(cell))

    # content width = leading space + cells + 2-space separators + trailing space
    content_w = 1 + sum(col_widths) + 2 * (col_count - 1) + 1

    title_part = f"─ {title} "
    fill = max(0, content_w - len(title_part))
    top    = f"┌{title_part}{'─' * fill}┐"
    bottom = f"└{'─' * content_w}┘"

    lines = [top]
    for row in padded_rows:
        cells = [_vpad(cell, col_widths[i]) for i, cell in enumerate(row)]
        inner = "  ".join(cells).rstrip()
        lines.append(f"│ {_vpad(inner, content_w - 2)} │")
    lines.append(bottom)
    return lines


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
    except Exception:
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


# ── section builders ──────────────────────────────────────────────────────

def _tmux_rows(project: Project) -> list[Row]:
    running = session_exists(project.session)
    state = _green("running") if running else _dim("not running")
    return [["session", project.session, state]]


def _git_rows(path: Path) -> list[Row] | None:
    """Returns None if not a git repo."""
    if not (path / ".git").exists():
        return None

    rows: list[Row] = []

    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=path)
    rows.append(["branch", branch or _dim("unknown")])

    tag = _run(["git", "describe", "--tags", "--abbrev=0"], cwd=path)
    rows.append(["latest tag", tag or _dim("—")])

    dirty = _run(["git", "status", "--short"], cwd=path)
    dirty_count = len([l for l in dirty.splitlines() if l.strip()])
    rows.append([
        "uncommitted",
        _yellow(f"{dirty_count} file(s)") if dirty_count else _dim("clean"),
    ])

    # commits: separate columns for hash | subject | age
    log = _run(
        ["git", "log", "--format=%h\x1f%s\x1f%cr", "-3"],
        cwd=path,
    )
    if log:
        for i, entry in enumerate(log.splitlines()):
            parts = entry.split("\x1f", 2)
            h, subj, age = (parts + ["", "", ""])[:3]
            label = "commits" if i == 0 else ""
            rows.append([label, _yellow(h), subj, _dim(age)])
    else:
        rows.append(["commits", _dim("none")])

    return rows


def _runtime_rows(path: Path) -> list[Row]:
    checks: list[tuple[str, list[str], list[str]]] = [
        ("python", ["pyproject.toml", "setup.py", "requirements.txt", ".python-version", "Pipfile"], ["python3", "--version"]),
        ("node",   ["package.json", ".nvmrc", ".node-version"], ["node", "--version"]),
        ("go",     ["go.mod"],        ["go", "version"]),
        ("rust",   ["Cargo.toml"],    ["rustc", "--version"]),
        ("deno",   ["deno.json", "deno.jsonc"], ["deno", "--version"]),
    ]

    detected: list[tuple[str, str, str]] = []  # (label, installed, binary)
    for label, manifests, cmd in checks:
        if not any((path / m).exists() for m in manifests):
            continue
        version = _run(cmd)
        installed = version.splitlines()[0] if version else ""
        detected.append((label, installed, cmd[0]))

    if not detected:
        return []

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
            except Exception:
                latest[lbl] = None

    def _semver(v: str) -> str:
        """Strip leading 'v' and drop any extra words (e.g. 'Python 3.14.3' → '3.14.3')."""
        parts = v.lstrip("v").split()
        for p in parts:
            if p[0].isdigit():
                return p
        return parts[0] if parts else v

    rows: list[Row] = []
    for label, installed, binary in detected:
        bin_path = shutil.which(binary) or _dim("—")

        if not installed:
            rows.append([label, _dim("—"), _dim("—"), bin_path])
            continue

        installed_str = _semver(installed)
        lat = latest.get(label)
        latest_str = _semver(lat) if lat else _dim("—")

        rows.append([label, installed_str, latest_str, bin_path])

    return rows


def _opencode_rows() -> list[Row]:
    version = _run(["opencode", "--version"])
    if not version:
        return []
    return [["version", version.splitlines()[0]]]


# ── public entry point ────────────────────────────────────────────────────

def print_status(project: Project) -> None:
    print(f"\n{_bold(project.display_name)}  {_dim(str(project.path))}\n")

    # tmux
    for line in _render_table("tmux", _tmux_rows(project)):
        print(line)

    # git
    git_rows = _git_rows(project.path)
    if git_rows is None:
        print("\n" + _dim("  (not a git repository)"))
    else:
        print()
        for line in _render_table("git", git_rows):
            print(line)

    # runtimes
    runtime_rows = _runtime_rows(project.path)
    if runtime_rows:
        print()
        for line in _render_table("runtimes  name · installed · latest · path", runtime_rows):
            print(line)

    # opencode
    oc_rows = _opencode_rows()
    if oc_rows:
        print()
        for line in _render_table("opencode", oc_rows):
            print(line)

    print()
