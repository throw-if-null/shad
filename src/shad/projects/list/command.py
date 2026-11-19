"""`shad projects` and `shad projects <group>` — the configured projects."""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text

from shad.config.load import Config, Project
from shad.output import Output


@dataclass(frozen=True)
class ProjectList:
    group: str | None  # the group listed, or None for every project
    projects: tuple[Project, ...]


def list_projects(cfg: Config, group: str | None = None) -> ProjectList:
    """Every project, top-level first then by group, or the projects of *group*."""
    if group is not None:
        members = cfg.groups[group]
        return ProjectList(group=group, projects=tuple(members[key] for key in sorted(members)))
    top = [cfg.projects[key] for key in sorted(cfg.projects)]
    grouped = [
        cfg.groups[name][key] for name in sorted(cfg.groups) for key in sorted(cfg.groups[name])
    ]
    return ProjectList(group=None, projects=tuple(top + grouped))


def render(result: ProjectList, out: Output) -> None:
    if result.group is not None:
        if not result.projects:
            out.print(Text(f"group '{result.group}' has no sub-projects", style="dim"))
            return
        _render_group(result.group, result.projects, out)
        return

    if not result.projects:
        out.print(Text("no projects configured", style="dim"))
        return
    for project in result.projects:
        if project.group is None:
            out.print(Text("  ● ", style="cyan") + Text(project.key, style="bright_white"))
    for group in dict.fromkeys(p.group for p in result.projects if p.group is not None):
        _render_group(group, [p for p in result.projects if p.group == group], out)


def _render_group(group: str, projects: list[Project] | tuple[Project, ...], out: Output) -> None:
    out.print(Text(f"  ◆ {group}", style="bold cyan"))
    for project in projects:
        out.print(Text("    ● ", style="cyan") + Text(f"{group} {project.key}", style="white"))
