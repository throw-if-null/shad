"""
`shad projects`: the parser, and which of list, open and status a line names.

    shad projects                          list every project and group
    shad projects <group>                  list the group
    shad projects [<group>] <name>         open the project
    shad projects [<group>] <name> status  print the project's status

One parser serves the three, because the line is a list of names followed
by an optional action. Resolution uses exact-match first, then unique prefix
match per level.
"""

from __future__ import annotations

import argparse

from shad import parsers
from shad.banner import print_banner
from shad.deps import Deps
from shad.errors import ShadError
from shad.output import Output
from shad.projects.list.command import ProjectList, list_projects
from shad.projects.list.command import render as render_list
from shad.projects.open.command import add_arguments, open_project
from shad.projects.status.command import Status, status
from shad.projects.status.command import render as render_status
from shad.shared.config import Config, Project, resolve_prefix

ACTIONS = ("status",)


def register(sub: parsers.Subparsers) -> None:
    parser = parsers.command(
        sub,
        "projects",
        run=run,
        render=render,
        help="List, open, or manage a project",
        description=(
            "List all projects, or target a specific project with an optional action.\n\n"
            "Actions:\n"
            "  (none)   open the project's tmux session (create if needed)\n"
            "  status   print a summary table for the project\n\n"
            "Examples:\n"
            "  shad projects                     list all projects\n"
            "  shad projects --json              the list as JSON\n"
            "  shad projects myapp               open myapp\n"
            "  shad projects tin shad            open grouped project\n"
            "  shad projects tin shad status     show status\n"
            "  shad projects myapp --harness claude   open with claude once\n\n"
            "Prefix matching is supported at each level. --json applies to the\n"
            "list and to status; opening a project hands the terminal to tmux."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "name",
        nargs="*",
        metavar="NAME",
        help="[group] [project] [action]  — the action is status",
    )
    add_arguments(parser)


def run(args: argparse.Namespace, deps: Deps) -> ProjectList | Status | int | None:
    """
    List, open, or report on what the names say. Returns the list or the
    status, or what `open_project` returns.
    """
    cfg = deps.config
    parts: list[str] = list(args.name)  # 0–3 tokens: [group] [name] [action]

    action: str | None = None
    if parts and parts[-1] in ACTIONS:
        action = parts.pop()

    if not parts:
        if action:
            raise ShadError.usage(
                "no_project", f"{action} needs a project: shad projects [<group>] <name> {action}"
            )
        return list_projects(cfg)

    if len(parts) == 1:
        token = parts[0]
        match = resolve_prefix(list(cfg.projects) + list(cfg.groups), token)
        if match is None:
            raise ShadError.not_found("no_such_project", f"no project or group matching '{token}'")
        if match in cfg.projects:
            return _act(cfg, cfg.projects[match], action, args, deps)
        if action:
            raise ShadError.usage(
                "group_needs_project",
                f"'{match}' is a group, not a project; specify a project within the group",
            )
        return list_projects(cfg, group=match)

    if len(parts) == 2:
        group_token, proj_token = parts
        group_match = resolve_prefix(list(cfg.groups), group_token)
        if group_match is None:
            if group_token in cfg.projects or any(
                k.startswith(group_token) for k in cfg.projects
            ):
                raise ShadError.not_found(
                    "no_such_group",
                    f"'{group_token}' resolves to a top-level project, not a group; "
                    f"did you mean: shad projects {group_token}?",
                )
            raise ShadError.not_found("no_such_group", f"no group matching '{group_token}'")

        group_projects = cfg.groups[group_match]
        proj_match = resolve_prefix(list(group_projects), proj_token)
        if proj_match is None:
            raise ShadError.not_found(
                "no_such_project",
                f"no project matching '{proj_token}' in group '{group_match}'; "
                f"available: {', '.join(sorted(group_projects))}",
            )
        return _act(cfg, group_projects[proj_match], action, args, deps)

    raise ShadError.usage(
        "too_many_arguments",
        f"too many arguments ({len(parts)}); usage: shad projects [<group>] [<name>] [status]",
    )


def _act(
    cfg: Config, project: Project, action: str | None, args: argparse.Namespace, deps: Deps
) -> Status | int | None:
    """Status, or open: the banner, then the tmux exit status, or None on cancel."""
    if action == "status":
        return status(project, deps.trace)
    if getattr(args, "json", False):
        raise ShadError.usage(
            "no_json", "shad projects <name> opens a session; --json applies to the list and status"
        )
    print_banner(deps.out)
    return open_project(project, cfg.defaults, harness=args.harness)


def render(result: ProjectList | Status, out: Output) -> None:
    if isinstance(result, ProjectList):
        render_list(result, out)
    else:
        render_status(result, out)
