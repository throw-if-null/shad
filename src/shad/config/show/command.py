"""`shad config show` — the rendered summary, or the file text with --raw."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.text import Text

from shad.config import store
from shad.config.render import display
from shad.shared.config import Config, load
from shad.shared.render import make_table
from shad.todo.store import todo_dir

console = Console()


def show_config(path: Path, *, raw_output: bool) -> None:
    if raw_output:
        text = store.read_text(path)
        print(text, end="" if text.endswith("\n") else "\n")
        return

    raw = store.read_raw(path)
    cfg = load(path)

    console.print()
    console.print(Text("shad config", style="bold bright_white") + Text(f"  {path}", style="dim"))
    console.print()
    _print_defaults(cfg, raw)
    console.print()
    _print_projects(cfg)
    console.print()
    _print_todo(cfg)
    console.print()


def _print_defaults(cfg: Config, raw: dict) -> None:
    table = make_table("defaults")
    configured = raw.get("defaults", {})
    if not isinstance(configured, dict):
        configured = {}

    for name in (
        "oc_position",
        "panel_percent",
        "split_percent",
        "git_panel",
        "todo_panel",
        "todo_percent",
        "harness",
    ):
        value = getattr(cfg.defaults, name)
        origin = "set" if name in configured else "default"
        table.add_row(
            Text(name, style="dim"),
            Text(display(value), style="bright_white"),
            Text(origin, style="dim"),
        )
    console.print(table)


def _print_projects(cfg: Config) -> None:
    table = make_table("projects")
    table.add_column(style="bright_white")   # name
    table.add_column(overflow="fold")        # path
    table.add_column(style="dim")            # session
    table.add_column(style="dim")            # harness

    projects = sorted(cfg.projects.values(), key=lambda p: p.key)
    grouped = [
        project
        for group in sorted(cfg.groups)
        for project in sorted(cfg.groups[group].values(), key=lambda p: p.key)
    ]
    everything = projects + grouped

    if not everything:
        table.add_row(Text("no projects configured", style="dim"), "", "", "")
        console.print(table)
        return

    for project in everything:
        exists = project.path.is_dir()
        path_text = Text(str(project.path), style="" if exists else "red")
        if not exists:
            path_text.append("  ✗ missing", style="red")
        table.add_row(project.display_name, path_text, project.session, project.harness)

    console.print(table)


def _print_todo(cfg: Config) -> None:
    table = make_table("todo")
    labels = ", ".join(cfg.todo_labels) if cfg.todo_labels else "none"
    table.add_row(
        Text("labels", style="dim"),
        Text(labels, style="bright_white" if cfg.todo_labels else "dim"),
    )
    path = Text(str(todo_dir(cfg)), style="bright_white", overflow="fold")
    if cfg.todo_path is None:
        path.append("  default", style="dim")
    table.add_row(Text("path", style="dim"), path)
    console.print(table)
