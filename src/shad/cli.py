"""
shad CLI entry point.

Commands
--------
shad --help
shad projects
shad projects <name>              # top-level project or group
shad projects <group> <name>      # project inside a group

Resolution uses exact-match first, then unique prefix match per level.
"""

from __future__ import annotations

import argparse
import sys

from shad import __version__
from shad.config import Config, load, resolve_prefix
from shad.tmux import open_project
from shad.status import print_status
from shad.completion import print_completion
from shad.init import cmd_init


# ---------------------------------------------------------------------------
# projects command helpers
# ---------------------------------------------------------------------------

def _list_all(cfg: Config) -> None:
    """Print every project and group to stdout."""
    items: list[str] = []

    for key in sorted(cfg.projects):
        items.append(key)

    for group in sorted(cfg.groups):
        items.append(group)          # group header
        for sub in sorted(cfg.groups[group]):
            items.append(f"  {group} {sub}")

    if not items:
        print("no projects configured")
    else:
        print("\n".join(items))


def _list_group(cfg: Config, group_name: str) -> None:
    """Print sub-projects belonging to *group_name*."""
    group = cfg.groups[group_name]
    if not group:
        print(f"group '{group_name}' has no sub-projects")
    else:
        for key in sorted(group):
            print(f"{group_name} {key}")


def cmd_projects(cfg: Config, args: argparse.Namespace) -> None:
    parts: list[str] = args.name  # 0, 1, or 2 tokens

    # --- no args: list everything ---
    if not parts:
        _list_all(cfg)
        return

    # --- one token: top-level project OR group ---
    if len(parts) == 1:
        token = parts[0]

        # Try top-level projects first
        top_candidates = list(cfg.projects) + list(cfg.groups)
        match = resolve_prefix(top_candidates, token)

        if match is None:
            print(
                f"error: no project or group matching '{token}'",
                file=sys.stderr,
            )
            sys.exit(1)

        if match in cfg.projects:
            if args.status:
                print_status(cfg.projects[match])
            else:
                open_project(cfg.projects[match], cfg.defaults)
        else:
            # it's a group — list its sub-projects
            _list_group(cfg, match)
        return

    # --- two tokens: group + project ---
    if len(parts) == 2:
        group_token, proj_token = parts

        # Resolve group
        group_match = resolve_prefix(list(cfg.groups), group_token)
        if group_match is None:
            # Maybe they meant a top-level project? Give a helpful message.
            if group_token in cfg.projects or any(
                k.startswith(group_token) for k in cfg.projects
            ):
                print(
                    f"error: '{group_token}' resolves to a top-level project, "
                    f"not a group; did you mean: shad projects {group_token}?",
                    file=sys.stderr,
                )
            else:
                print(
                    f"error: no group matching '{group_token}'",
                    file=sys.stderr,
                )
            sys.exit(1)

        # Resolve project within group
        group_projects = cfg.groups[group_match]
        proj_match = resolve_prefix(list(group_projects), proj_token)
        if proj_match is None:
            print(
                f"error: no project matching '{proj_token}' in group '{group_match}'; "
                f"available: {', '.join(sorted(group_projects))}",
                file=sys.stderr,
            )
            sys.exit(1)

        if args.status:
            print_status(group_projects[proj_match])
        else:
            open_project(group_projects[proj_match], cfg.defaults)
        return

    # --- too many tokens ---
    print(
        f"error: too many arguments ({len(parts)}); "
        "usage: shad projects [<group>] [<name>]",
        file=sys.stderr,
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shad",
        description="Attach or create project-specific tmux sessions.",
    )
    parser.add_argument(
        "--version", action="version", version=f"shad {__version__}"
    )

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p_projects = sub.add_parser(
        "projects",
        help="List or open a project",
    )
    p_projects.add_argument(
        "name",
        nargs="*",
        metavar="NAME",
        help=(
            "Project name (or group + project name). "
            "Omit to list all projects. "
            "Prefix matching is supported per level."
        ),
    )
    p_projects.add_argument(
        "--status",
        action="store_true",
        help="Print project status instead of opening a tmux session.",
    )

    p_completion = sub.add_parser(
        "completion",
        help="Print shell completion script",
    )
    p_completion.add_argument(
        "shell",
        choices=["bash", "zsh"],
        help="Shell to generate completions for",
    )

    sub.add_parser(
        "init",
        help="Add a new project to the config interactively",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if args.command == "completion":
        print_completion(args.shell)
        return

    if args.command == "init":
        cmd_init()
        return

    cfg: Config = load()

    if args.command == "projects":
        cmd_projects(cfg, args)
