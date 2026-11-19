"""
`shad projects [<group>] <name> status` — one project's state, as a result.

The status is the tmux session state, the repository (branch, latest tag,
the last commits, the uncommitted file count), the runtimes the project's
manifest files name (Python, Node, Go, Rust, Deno) with the latest released
version of each fetched in parallel, and the opencode version. The root
renders it as titled tables, or as JSON.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from rich.text import Text

from shad.config import Project
from shad.git import (
    Commit,
    head_branch,
    is_clean,
    latest_tag,
    recent_commits,
    short_branch,
)
from shad.output import Output
from shad.style import make_table, relative_age
from shad.tmux import Tmux as TmuxClient
from shad.trace import Trace

RECENT_COMMITS = 3


@dataclass(frozen=True)
class Session:
    name: str
    base: bool  # the project's bare session name, as opposed to a scoped one


@dataclass(frozen=True)
class Tmux:
    server: bool  # a tmux server is running
    sessions: tuple[Session, ...]


@dataclass(frozen=True)
class Git:
    branch: str | None  # None when HEAD is detached
    tag: str | None  # the latest tag reachable from HEAD
    changed: int  # tracked files with uncommitted changes
    untracked: int
    commits: tuple[Commit, ...]  # newest first


@dataclass(frozen=True)
class Runtime:
    name: str
    installed: str
    latest: str | None  # None when the fetch failed
    path: str | None  # the binary, when it is on PATH


@dataclass(frozen=True)
class Status:
    project: Project
    tmux: Tmux
    git: Git | None  # None when the directory is not a repository
    runtimes: tuple[Runtime, ...]
    opencode: str | None


# ── subprocess / fetch helpers ────────────────────────────────────────────


def _capture(args: list[str], *, cwd: Path | None = None) -> str:
    """Run a non-git helper and return its stdout, or "" on any failure."""
    try:
        r = subprocess.run(args, capture_output=True, text=True, cwd=cwd, check=False)
        return r.stdout.strip() if r.returncode == 0 else ""
    except FileNotFoundError:
        return ""


def _fetch_json(url: str, timeout: int = 4) -> object:
    """The JSON at *url*. A network or decoding failure propagates to the caller."""
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read())


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


_LATEST_FETCHERS: dict[str, Callable[[], str | None]] = {
    "python": _latest_python,
    "node": _latest_node,
    "go": _latest_go,
    "rust": _latest_rust,
    "deno": _latest_deno,
}


# ── the readings ──────────────────────────────────────────────────────────


def _tmux(project: Project, tmux: TmuxClient) -> Tmux:
    running = tmux.list_project_sessions(project.session)
    if not running:
        return Tmux(server=tmux.server_running(), sessions=())
    return Tmux(
        server=True,
        sessions=tuple(Session(name=name, base=name == project.session) for name in running),
    )


def _git(path: Path) -> Git | None:
    """
    The repository at *path*, or None when there is none.

    Every query goes through shad.git.run.git rather than a bare subprocess:
    that wrapper scrubs an inherited GIT_DIR, which would otherwise make this
    describe whichever repository invoked shad — a git hook, or a tmux pane
    started by one — instead of the project. It also passes an explicit `-C`
    and a timeout, so a slow or wedged repository cannot hang the report.
    """
    if not (path / ".git").exists():
        return None
    head = head_branch(path)
    tag = latest_tag(path)
    # Counts every untracked file, where `status --short` collapsed an
    # untracked directory into a single entry. An untracked directory holding
    # two files reads as two, which is what the "file(s)" label claims.
    _clean, changed, untracked = is_clean(path, untracked=True)
    return Git(
        branch=short_branch(head) if head else None,
        tag=tag or None,
        changed=changed,
        untracked=untracked,
        commits=tuple(recent_commits(path, RECENT_COMMITS)),
    )


def _semver(v: str) -> str:
    for part in v.split():
        s = part.lstrip("v")
        if s.startswith("go") and s[2:3].isdigit():
            return s[2:]
        if s[:1].isdigit():
            return s.split()[0]
    return v.strip()


def _runtimes(path: Path, trace: Trace) -> tuple[Runtime, ...]:
    checks: list[tuple[str, list[str], list[str]]] = [
        (
            "python",
            [
                "pyproject.toml",
                "setup.py",
                "requirements.txt",
                ".python-version",
                "Pipfile",
            ],
            ["python3", "--version"],
        ),
        ("node", ["package.json", ".nvmrc", ".node-version"], ["node", "--version"]),
        ("go", ["go.mod"], ["go", "version"]),
        ("rust", ["Cargo.toml"], ["rustc", "--version"]),
        ("deno", ["deno.json", "deno.jsonc"], ["deno", "--version"]),
    ]

    detected: list[tuple[str, str, str]] = []
    for label, manifests, cmd in checks:
        if not any((path / m).exists() for m in manifests):
            continue
        version = _capture(cmd)
        installed = version.splitlines()[0] if version else ""
        if installed:  # a runtime that is not on PATH is left out
            detected.append((label, installed, cmd[0]))
    if not detected:
        return ()

    latest: dict[str, str | None] = {}
    with ThreadPoolExecutor(max_workers=max(1, len(detected))) as pool:
        futures = {
            pool.submit(_LATEST_FETCHERS[label]): label
            for label, _, _ in detected
            if label in _LATEST_FETCHERS
        }
        for future in as_completed(futures):
            lbl = futures[future]
            try:
                latest[lbl] = future.result()
            except Exception as exc:  # noqa: BLE001 — one failed fetch must not abort the rest
                trace.note(f"latest {lbl} version unknown: {exc}")
                latest[lbl] = None

    return tuple(
        Runtime(
            name=label,
            installed=_semver(installed),
            latest=_semver(found) if (found := latest.get(label)) else None,
            path=shutil.which(binary),
        )
        for label, installed, binary in detected
    )


def _opencode() -> str | None:
    version = _capture(["opencode", "--version"])
    return version.splitlines()[0] if version else None


def status(project: Project, tmux: TmuxClient, trace: Trace) -> Status:
    """The project's state now. *trace* receives the version-fetch failures."""
    return Status(
        project=project,
        tmux=_tmux(project, tmux),
        git=_git(project.path),
        runtimes=_runtimes(project.path, trace),
        opencode=_opencode(),
    )


# ── rendering ─────────────────────────────────────────────────────────────


def render(result: Status, out: Output) -> None:
    out.print()
    out.print(
        Text(result.project.display_name, style="bold bright_white")
        + Text(f"  {result.project.path}", style="dim")
    )
    out.print()
    _render_tmux(result, out)
    out.print()
    _render_git(result.git, out)
    out.print()
    _render_runtimes(result.runtimes, out)
    if result.opencode:
        t = make_table("opencode")
        t.add_row(Text("version", style="dim"), Text(result.opencode))
        out.print(t)
    out.print()


def _render_tmux(result: Status, out: Output) -> None:
    t = make_table("tmux")
    if not result.tmux.sessions:
        state = "not running" if result.tmux.server else "tmux not running"
        t.add_row(Text("session", style="dim"), Text(result.project.session), Text(state, style="dim"))
        out.print(t)
        return
    for index, session in enumerate(result.tmux.sessions):
        label = Text("session", style="dim") if index == 0 else Text("")
        display = Text(session.name)
        if session.base:
            display.append("  (base)", style="dim")
        t.add_row(label, display, Text("running", style="bold green"))
    out.print(t)


def _render_git(git: Git | None, out: Output) -> None:
    if git is None:
        out.print(Text("  (not a git repository)", style="dim"))
        return
    t = make_table("git")
    t.add_row(Text("branch", style="dim"), Text(git.branch or "detached", style="dim"))
    t.add_row(
        Text("latest tag", style="dim"),
        Text(git.tag if git.tag else "—", style="" if git.tag else "dim"),
    )
    dirty_count = git.changed + git.untracked
    if dirty_count:
        dirty_val = Text(f"{dirty_count} file(s)", style="yellow")
    else:
        dirty_val = Text("clean", style="dim")
    t.add_row(Text("uncommitted", style="dim"), dirty_val)
    if git.commits:
        for i, commit in enumerate(git.commits):
            label = Text("commits", style="dim") if i == 0 else Text("")
            row = Text()
            row.append(commit.short_oid, style="yellow")
            row.append("  ")
            row.append(commit.subject)
            row.append("  ")
            row.append(relative_age(commit.timestamp), style="dim")
            t.add_row(label, row)
    else:
        t.add_row(Text("commits", style="dim"), Text("none", style="dim"))
    out.print(t)


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


def _render_runtimes(runtimes: tuple[Runtime, ...], out: Output) -> None:
    if not runtimes:
        return
    t = make_table("runtimes")
    t.add_column(style="dim")  # name
    t.add_column()  # installed
    t.add_column()  # latest
    t.add_column(style="dim")  # path
    for runtime in runtimes:
        if runtime.latest:
            latest_text = Text(runtime.latest, style=_version_style(runtime.installed, runtime.latest))
        else:
            latest_text = Text("—", style="dim")
        t.add_row(runtime.name, runtime.installed, latest_text, runtime.path or "—")
    out.print(t)
