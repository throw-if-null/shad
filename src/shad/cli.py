"""
shad CLI entry point.

Commands
--------
shad --help
shad projects
shad projects <name>                     # open top-level project or list group
shad projects <group> <name>             # open project inside a group
shad projects <name> <action>            # run action on top-level project
shad projects <group> <name> <action>    # run action on grouped project

Actions: status, stop

Resolution uses exact-match first, then unique prefix match per level.
"""

from __future__ import annotations

import argparse
import sys

from shad import __version__
from shad.config import Config, load, resolve_prefix
from shad.tmux import open_project, stop_project
from shad.status import print_status
from shad.completion import print_completion
from shad.init import cmd_init

ACTIONS = ("status", "stop")


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


def _run_action(cfg: Config, project, action: str | None) -> None:
    """Dispatch open / status / stop for a resolved project."""
    if action is None or action == "open":
        open_project(project, cfg.defaults)
    elif action == "status":
        print_status(project)
    elif action == "stop":
        stop_project(project)
    else:
        print(f"error: unknown action '{action}'; available: status, stop", file=sys.stderr)
        sys.exit(1)


def cmd_projects(cfg: Config, args: argparse.Namespace) -> None:
    parts: list[str] = args.name  # 0–3 tokens: [group] [name] [action]

    # --- no args: list everything ---
    if not parts:
        _list_all(cfg)
        return

    # Peel off a trailing action token if present
    action: str | None = None
    if parts[-1] in ACTIONS:
        action = parts[-1]
        parts = parts[:-1]

    # --- one token: top-level project OR group ---
    if len(parts) == 1:
        token = parts[0]

        top_candidates = list(cfg.projects) + list(cfg.groups)
        match = resolve_prefix(top_candidates, token)

        if match is None:
            print(f"error: no project or group matching '{token}'", file=sys.stderr)
            sys.exit(1)

        if match in cfg.projects:
            _run_action(cfg, cfg.projects[match], action)
        else:
            if action:
                print(f"error: '{match}' is a group, not a project; specify a project within the group", file=sys.stderr)
                sys.exit(1)
            _list_group(cfg, match)
        return

    # --- two tokens: group + project ---
    if len(parts) == 2:
        group_token, proj_token = parts

        group_match = resolve_prefix(list(cfg.groups), group_token)
        if group_match is None:
            if group_token in cfg.projects or any(k.startswith(group_token) for k in cfg.projects):
                print(
                    f"error: '{group_token}' resolves to a top-level project, "
                    f"not a group; did you mean: shad projects {group_token}?",
                    file=sys.stderr,
                )
            else:
                print(f"error: no group matching '{group_token}'", file=sys.stderr)
            sys.exit(1)

        group_projects = cfg.groups[group_match]
        proj_match = resolve_prefix(list(group_projects), proj_token)
        if proj_match is None:
            print(
                f"error: no project matching '{proj_token}' in group '{group_match}'; "
                f"available: {', '.join(sorted(group_projects))}",
                file=sys.stderr,
            )
            sys.exit(1)

        _run_action(cfg, group_projects[proj_match], action)
        return

    # --- too many tokens ---
    print(
        f"error: too many arguments ({len(parts)}); "
        "usage: shad projects [<group>] [<name>] [status|stop]",
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
        help="List, open, or manage a project",
        description=(
            "List all projects, or target a specific project with an optional action.\n\n"
            "Actions:\n"
            "  (none)   open the project's tmux session (create if needed)\n"
            "  status   print a summary table for the project\n"
            "  stop     kill the project's tmux session\n\n"
            "Examples:\n"
            "  shad projects                     list all projects\n"
            "  shad projects myapp               open myapp\n"
            "  shad projects tin shad            open grouped project\n"
            "  shad projects tin shad status     show status\n"
            "  shad projects tin shad stop       kill session\n\n"
            "Prefix matching is supported at each level."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_projects.add_argument(
        "name",
        nargs="*",
        metavar="NAME",
        help="[group] [project] [action]  — action is one of: status, stop",
    )

    p_completion = sub.add_parser(
        "completion",
        help="Print shell completion script",
        description=(
            "Print a shell completion script to stdout.\n\n"
            "To install:\n"
            "  shad completion bash >> ~/.bashrc && source ~/.bashrc\n"
            "  shad completion zsh  >> ~/.zshrc  && source ~/.zshrc"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_completion.add_argument(
        "shell",
        choices=["bash", "zsh"],
        help="Shell to generate completions for",
    )

    sub.add_parser(
        "init",
        help="Add a new project to the config interactively",
        description=(
            "Interactive wizard that prompts for project details and appends\n"
            f"a new entry to ~/.config/shad/shad.toml."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
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
