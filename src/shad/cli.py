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

from rich.console import Console
from rich.text import Text

from shad import __version__
from shad.config import Config, load, resolve_prefix
from shad.tmux import open_project, stop_project
from shad.status import print_status
from shad.completion import print_completion
from shad.init import cmd_init
from shad.cheat import cmd_cheat
from shad.banner import print_banner

console = Console()
err_console = Console(stderr=True)

ACTIONS = ("status", "stop")


# ---------------------------------------------------------------------------
# projects command helpers
# ---------------------------------------------------------------------------

def _list_all(cfg: Config) -> None:
    """Print every project and group to stdout."""
    if not cfg.projects and not cfg.groups:
        console.print(Text("no projects configured", style="dim"))
        return

    for key in sorted(cfg.projects):
        console.print(Text("  ● ", style="cyan") + Text(key, style="bright_white"))

    for group in sorted(cfg.groups):
        console.print(Text(f"  ◆ {group}", style="bold cyan"))
        for sub in sorted(cfg.groups[group]):
            console.print(Text("    ● ", style="cyan") + Text(f"{group} {sub}", style="white"))


def _list_group(cfg: Config, group_name: str) -> None:
    """Print sub-projects belonging to *group_name*."""
    group = cfg.groups[group_name]
    if not group:
        console.print(Text(f"group '{group_name}' has no sub-projects", style="dim"))
    else:
        console.print(Text(f"  ◆ {group_name}", style="bold cyan"))
        for key in sorted(group):
            console.print(Text("    ● ", style="cyan") + Text(f"{group_name} {key}", style="white"))


def _run_action(cfg: Config, project, action: str | None) -> None:
    """Dispatch open / status / stop for a resolved project."""
    if action is None or action == "open":
        print_banner()
        open_project(project, cfg.defaults)
    elif action == "status":
        print_status(project)
    elif action == "stop":
        stop_project(project)
    else:
        err_console.print(Text(f"✗ unknown action '{action}'; available: status, stop", style="bold red"))
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
            err_console.print(Text(f"✗ no project or group matching '{token}'", style="bold red"))
            sys.exit(1)

        if match in cfg.projects:
            _run_action(cfg, cfg.projects[match], action)
        else:
            if action:
                err_console.print(Text(f"✗ '{match}' is a group, not a project; specify a project within the group", style="bold red"))
                sys.exit(1)
            _list_group(cfg, match)
        return

    # --- two tokens: group + project ---
    if len(parts) == 2:
        group_token, proj_token = parts

        group_match = resolve_prefix(list(cfg.groups), group_token)
        if group_match is None:
            if group_token in cfg.projects or any(k.startswith(group_token) for k in cfg.projects):
                err_console.print(Text(
                    f"✗ '{group_token}' resolves to a top-level project, not a group; "
                    f"did you mean: shad projects {group_token}?",
                    style="bold red",
                ))
            else:
                err_console.print(Text(f"✗ no group matching '{group_token}'", style="bold red"))
            sys.exit(1)

        group_projects = cfg.groups[group_match]
        proj_match = resolve_prefix(list(group_projects), proj_token)
        if proj_match is None:
            err_console.print(Text(
                f"✗ no project matching '{proj_token}' in group '{group_match}'; "
                f"available: {', '.join(sorted(group_projects))}",
                style="bold red",
            ))
            sys.exit(1)

        _run_action(cfg, group_projects[proj_match], action)
        return

    # --- too many tokens ---
    err_console.print(Text(
        f"✗ too many arguments ({len(parts)}); "
        "usage: shad projects [<group>] [<name>] [status|stop]",
        style="bold red",
    ))
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

    p_init = sub.add_parser(
        "init",
        help="Add a new project to the config interactively",
        description=(
            "Interactive wizard that adds a new project to ~/.config/shad/shad.toml.\n"
            "Creates the config file with a commented [defaults] block if it does not exist yet.\n\n"
            "Options:\n"
            "  --install-deps  install missing tmux, opencode, and gitui dependencies on Fedora\n\n"
            "Prompts:\n"
            "  path         Absolute path to the project root (must exist)\n"
            "  group        Optional group name; leave blank for a top-level project\n"
            "  key          Short project name; defaults to the directory name\n"
            "  session      tmux session name; defaults to <key> or <group>-<key>\n\n"
            "Examples:\n"
            "  shad init                         add a top-level project\n"
            "  sudo shad init --install-deps     install Fedora deps, then run init\n"
            "  shad init                         add a grouped project (enter group at prompt)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_init.add_argument(
        "--install-deps",
        action="store_true",
        help="Install missing tmux, opencode, and gitui dependencies on Fedora before prompting",
    )

    sub.add_parser(
        "cheat",
        help="Show a tmux cheat sheet in a popup (or stdout if outside tmux)",
        description=(
            "Display a tmux key-binding reference.\n\n"
            "Inside tmux  : opens a floating popup; dismiss with q\n"
            "Outside tmux : prints the cheat sheet to stdout\n\n"
            "Recommended ~/.tmux.conf binding:\n"
            "  bind-key F12 run-shell \"shad cheat\""
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
        cmd_init(install_deps=args.install_deps)
        return

    if args.command == "cheat":
        cmd_cheat()
        return

    cfg: Config = load()

    if args.command == "projects":
        cmd_projects(cfg, args)
