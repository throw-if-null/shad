"""`shad config show` — the rendered summary, or the file text with --raw."""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from rich.text import Text

from shad import parsers
from shad.config import store
from shad.config.render import display
from shad.deps import Deps
from shad.errors import ShadError
from shad.output import Output
from shad.shared.config import Config, Project
from shad.shared.render import make_table
from shad.todo.store import todo_dir

DEFAULTS = (
    "oc_position",
    "panel_percent",
    "split_percent",
    "git_panel",
    "todo_panel",
    "todo_percent",
    "harness",
)


@dataclass(frozen=True)
class Setting:
    value: bool | int | str
    origin: str  # "set" in the file, or "default"


@dataclass(frozen=True)
class ProjectView:
    project: Project
    exists: bool  # the path is a directory


@dataclass(frozen=True)
class TodoView:
    labels: tuple[str, ...]
    path: str
    path_set: bool  # [todo] path is in the file, as opposed to the per-OS default


@dataclass(frozen=True)
class ConfigView:
    path: str
    defaults: dict[str, Setting]
    projects: tuple[ProjectView, ...]
    todo: TodoView


@dataclass(frozen=True)
class ConfigText:
    """The file as it is, for --raw."""

    path: str
    text: str


def register(sub: parsers.Subparsers) -> None:
    parser = parsers.command(
        sub, "show", run=run, render=render, help="Print a rendered config summary"
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Print the raw file contents instead; the file is the machine form, so no --json",
    )


def run(args: argparse.Namespace, deps: Deps) -> ConfigView | ConfigText:
    path = deps.config_file
    if getattr(args, "raw", False):
        if getattr(args, "json", False):
            raise ShadError.usage("no_json", "--raw prints the file itself; it has no --json form")
        return ConfigText(path=str(path), text=store.read_text(path))

    raw = store.read_raw(path)
    cfg = deps.config
    configured = raw.get("defaults", {})
    if not isinstance(configured, dict):
        configured = {}
    defaults = {
        name: Setting(
            value=getattr(cfg.defaults, name),
            origin="set" if name in configured else "default",
        )
        for name in DEFAULTS
    }
    return ConfigView(
        path=str(path),
        defaults=defaults,
        projects=tuple(ProjectView(project=p, exists=p.path.is_dir()) for p in _ordered(cfg)),
        todo=TodoView(
            labels=tuple(cfg.todo_labels),
            path=str(todo_dir(cfg)),
            path_set=cfg.todo_path is not None,
        ),
    )


def _ordered(cfg: Config) -> list[Project]:
    projects = sorted(cfg.projects.values(), key=lambda p: p.key)
    grouped = [
        project
        for group in sorted(cfg.groups)
        for project in sorted(cfg.groups[group].values(), key=lambda p: p.key)
    ]
    return projects + grouped


def render(result: ConfigView | ConfigText, out: Output) -> None:
    if isinstance(result, ConfigText):
        out.plain(result.text.removesuffix("\n"))
        return
    out.print()
    out.print(Text("shad config", style="bold bright_white") + Text(f"  {result.path}", style="dim"))
    out.print()
    _render_defaults(result.defaults, out)
    out.print()
    _render_projects(result.projects, out)
    out.print()
    _render_todo(result.todo, out)
    out.print()


def _render_defaults(defaults: dict[str, Setting], out: Output) -> None:
    table = make_table("defaults")
    for name, setting in defaults.items():
        table.add_row(
            Text(name, style="dim"),
            Text(display(setting.value), style="bright_white"),
            Text(setting.origin, style="dim"),
        )
    out.print(table)


def _render_projects(projects: tuple[ProjectView, ...], out: Output) -> None:
    table = make_table("projects")
    table.add_column(style="bright_white")   # name
    table.add_column(overflow="fold")        # path
    table.add_column(style="dim")            # session
    table.add_column(style="dim")            # harness

    if not projects:
        table.add_row(Text("no projects configured", style="dim"), "", "", "")
        out.print(table)
        return

    for view in projects:
        project = view.project
        path_text = Text(str(project.path), style="" if view.exists else "red")
        if not view.exists:
            path_text.append("  ✗ missing", style="red")
        table.add_row(project.display_name, path_text, project.session, project.harness)
    out.print(table)


def _render_todo(todo: TodoView, out: Output) -> None:
    table = make_table("todo")
    labels = ", ".join(todo.labels) if todo.labels else "none"
    table.add_row(
        Text("labels", style="dim"),
        Text(labels, style="bright_white" if todo.labels else "dim"),
    )
    path = Text(todo.path, style="bright_white", overflow="fold")
    if not todo.path_set:
        path.append("  default", style="dim")
    table.add_row(Text("path", style="dim"), path)
    out.print(table)
