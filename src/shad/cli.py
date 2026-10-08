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
shad projects <name> --harness <h>       # open with a one-off harness
shad config <action> [args]              # inspect or edit shad.toml
shad git sync [<group>] [<name>]         # git maintenance across projects
shad git panel [<group>] [<name>]        # read-only repository view
shad todo <action> [args]                # the todo list

Config file: --config PATH, else $SHAD_CONFIG, else the per-OS default
(~/.config/shad/shad.toml on Linux). `shad config path` prints the resolved one.

Actions: status, stop

Resolution uses exact-match first, then unique prefix match per level.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.text import Text

from shad import __version__
from shad.cheat.command import cmd_cheat
from shad.completion.command import print_completion
from shad.config.command import cmd_config
from shad.git.command import cmd_git
from shad.init.command import cmd_init
from shad.projects.open.banner import print_banner
from shad.projects.open.command import open_project
from shad.projects.status.command import print_status
from shad.projects.stop.command import stop_project
from shad.shared.config import HARNESSES, Config, Project, load, resolve_prefix
from shad.shared.errors import ShadError
from shad.todo.command import cmd_todo
from shad.todo.model import STATUSES

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
            console.print(
                Text("    ● ", style="cyan") + Text(f"{group} {sub}", style="white")
            )


def _list_group(cfg: Config, group_name: str) -> None:
    """Print sub-projects belonging to *group_name*."""
    group = cfg.groups[group_name]
    if not group:
        console.print(Text(f"group '{group_name}' has no sub-projects", style="dim"))
    else:
        console.print(Text(f"  ◆ {group_name}", style="bold cyan"))
        for key in sorted(group):
            console.print(
                Text("    ● ", style="cyan")
                + Text(f"{group_name} {key}", style="white")
            )


def _run_action(
    cfg: Config, project: Project, action: str | None, harness: str | None
) -> None:
    """Dispatch open / status / stop for a resolved project.

    *harness* applies to open only; status and stop ignore it.
    """
    if action is None:
        print_banner()
        code = open_project(project, cfg.defaults, harness=harness)
        if code is None:
            return  # user cancelled the picker — exit cleanly
        sys.exit(code)
    elif action == "status":
        print_status(project)
    elif action == "stop":
        stop_project(project)
    else:
        raise ShadError(f"unknown action '{action}'; available: status, stop")


def cmd_projects(cfg: Config, args: argparse.Namespace) -> None:
    parts: list[str] = args.name  # 0–3 tokens: [group] [name] [action]
    harness: str | None = args.harness

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
            raise ShadError(f"no project or group matching '{token}'")

        if match in cfg.projects:
            _run_action(cfg, cfg.projects[match], action, harness)
        else:
            if action:
                raise ShadError(
                    f"'{match}' is a group, not a project; specify a project within the group"
                )
            _list_group(cfg, match)
        return

    # --- two tokens: group + project ---
    if len(parts) == 2:
        group_token, proj_token = parts

        group_match = resolve_prefix(list(cfg.groups), group_token)
        if group_match is None:
            if group_token in cfg.projects or any(
                k.startswith(group_token) for k in cfg.projects
            ):
                raise ShadError(
                    f"'{group_token}' resolves to a top-level project, not a group; "
                    f"did you mean: shad projects {group_token}?"
                )
            else:
                raise ShadError(f"no group matching '{group_token}'")

        group_projects = cfg.groups[group_match]
        proj_match = resolve_prefix(list(group_projects), proj_token)
        if proj_match is None:
            raise ShadError(
                f"no project matching '{proj_token}' in group '{group_match}'; "
                f"available: {', '.join(sorted(group_projects))}"
            )

        _run_action(cfg, group_projects[proj_match], action, harness)
        return

    # --- too many tokens ---
    raise ShadError(
        f"too many arguments ({len(parts)}); "
        "usage: shad projects [<group>] [<name>] [status|stop]"
    )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shad",
        description="Attach or create project-specific tmux sessions.",
    )
    parser.add_argument("--version", action="version", version=f"shad {__version__}")
    parser.add_argument(
        "--config",
        metavar="PATH",
        help=(
            "Config file to use, overriding $SHAD_CONFIG and the per-OS default. "
            "Must precede the subcommand."
        ),
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
            "  shad projects tin shad stop       kill session\n"
            "  shad projects myapp --harness claude   open with claude once\n\n"
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
    p_projects.add_argument(
        "--harness",
        choices=HARNESSES,
        help=(
            "Open with this harness instead of the project's configured one. "
            "Applies to open only; status and stop ignore it."
        ),
    )

    p_git = sub.add_parser(
        "git",
        help="Run git maintenance across configured projects",
        description=(
            "Git maintenance across one, some, or all configured projects.\n\n"
            "Actions:\n"
            "  sync     fetch, fast-forward, and prune dead branches and worktrees\n"
            "  panel    read-only branch, worktree and stash view for one repository\n\n"
            "Examples:\n"
            "  shad git sync                     every configured project\n"
            "  shad git sync kb                  one top-level project\n"
            "  shad git sync alvr                every project in the alvr group\n"
            "  shad git sync alvr db             one grouped project\n\n"
            "Prefix matching is supported at each level."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    git_sub = p_git.add_subparsers(dest="git_action", metavar="<action>")

    p_git_sync = git_sub.add_parser(
        "sync",
        help="Fetch, fast-forward, and prune dead branches and worktrees",
        description=(
            "For each targeted project:\n"
            "  1. git fetch --prune\n"
            "  2. fast-forward the default branch (skipped if diverged or dirty)\n"
            "  3. delete local branches that are merged, or whose upstream was\n"
            "     pruned in this run after every commit had been pushed\n"
            "  4. prune worktree records whose directory is gone, and remove\n"
            "     clean worktrees whose branch is being deleted\n\n"
            "Steps 1 and 2 are applied immediately and are NOT undone if you\n"
            "decline the prompt. Only the deletions in steps 3 and 4 are gated.\n\n"
            "Never deleted: the default branch, a branch checked out in a\n"
            "worktree that is staying, a branch with unpushed commits, a branch\n"
            "that never had an upstream, a locked worktree, or a worktree with\n"
            "local changes.\n\n"
            "Options:\n"
            "  --switch    check out the default branch in each main worktree\n"
            "  --yes       skip the confirmation prompt (use this in scripts)\n"
            "  --dry-run   report only; still fetches, but deletes nothing\n\n"
            "--switch is the only step that touches a working tree. A project\n"
            "is skipped, with the reason, when its tree is dirty, its HEAD is\n"
            "detached, the default branch is held by another worktree, or it\n"
            "has no local copy of that branch. Switching also un-pins the\n"
            "branch it leaves behind, so that branch can be deleted in the\n"
            "same run if it qualifies.\n\n"
            "Examples:\n"
            "  shad git sync\n"
            "  shad git sync tin shad --dry-run\n"
            "  shad git sync --switch\n"
            "  shad git sync --yes"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_git_sync.add_argument(
        "name",
        nargs="*",
        metavar="NAME",
        help="[group] [project]  — omit to target every configured project",
    )
    p_git_sync.add_argument(
        "--switch",
        action="store_true",
        help="Check out the default branch in each project's main worktree",
    )
    p_git_sync.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt and apply every listed deletion",
    )
    p_git_sync.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change; still fetches, but deletes nothing",
    )

    p_git_panel = git_sub.add_parser(
        "panel",
        help="Read-only branch, worktree and stash view for one repository",
        description=(
            "A read-only view of one repository, shown in shad's third pane.\n\n"
            "Sections:\n"
            "  branches    local branches, tracking state, and upstream\n"
            "  worktrees   path, branch, and locked/prunable/bare flags\n"
            "  stashes     ref, branch, message, and age\n\n"
            "The header carries the active branch, how far it is ahead of and\n"
            "behind upstream, the repository, and the git version — in that\n"
            "order, because a narrow pane truncates the tail.\n\n"
            "Unlike `sync`, no name means the current directory, not every\n"
            "configured project: this view shows one repository. A name that\n"
            "matches more than one project is an error.\n\n"
            "The panel fetches on open so the counts are accurate, and `r`\n"
            "fetches again. It never prunes and never writes to a working\n"
            "tree — nothing here changes the repository.\n\n"
            "Keys:\n"
            "  tab         move focus between the section list and the table\n"
            "  up/down     move the row cursor (j / k also work)\n"
            "  r           fetch and reload\n"
            "  q           quit\n\n"
            "Examples:\n"
            "  shad git panel\n"
            "  shad git panel shad\n"
            "  shad git panel tin shad\n"
            "  shad git panel --no-fetch"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_git_panel.add_argument(
        "name",
        nargs="*",
        metavar="NAME",
        help="[group] [project]  — omit to use the current directory",
    )
    p_git_panel.add_argument(
        "--no-fetch",
        action="store_true",
        help="Skip the fetch on open; show local state only",
    )

    p_todo = sub.add_parser(
        "todo",
        help="Manage the todo list",
        description=(
            "One todo list, not tied to a project: one text file per item,\n"
            "shown in shad's fourth pane when defaults.todo_percent is set.\n\n"
            "Actions:\n"
            "  panel    the pane: list, status keys, add, delete, edit\n"
            "  add      create an item; its key is a slug of the title. With no\n"
            "           title, write the item in $EDITOR from a template\n"
            "  list     print the items (--keys: just the keys, one per line)\n"
            "  status   set an item's status: todo | in-progress | done | wont-do\n"
            "  edit     open an item in $EDITOR\n"
            "  rm       delete an item's file\n"
            "  label    add, rm, list: the label vocabulary in shad.toml\n\n"
            "An item key accepts any unique prefix.\n\n"
            "Files live in <todo dir>/<item>.md, as a header block, a blank\n"
            "line, and the body. They are meant to be edited by hand. The todo\n"
            "dir is [todo] path in shad.toml, or $XDG_DATA_HOME/shad/todo\n"
            "(~/.local/share/shad/todo on Linux) when it is not set.\n\n"
            "Examples:\n"
            "  shad todo add\n"
            "  shad todo add \"Fix panel resize\" --label chore\n"
            "  shad todo list\n"
            "  shad todo status fix-panel in-progress\n"
            "  shad todo edit fix-panel\n"
            "  shad todo rm fix-panel\n"
            "  shad todo label add investigation\n"
            "  shad todo panel"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    todo_sub = p_todo.add_subparsers(dest="todo_action", metavar="<action>")

    todo_sub.add_parser("panel", help="Show the todo pane")

    p_todo_add = todo_sub.add_parser("add", help="Create an item")
    p_todo_add.add_argument(
        "title",
        metavar="TITLE",
        nargs="?",
        help="The item title; its key is a slug of it. Omit it to write the item in $EDITOR",
    )
    p_todo_add.add_argument(
        "--label",
        action="append",
        metavar="LABEL",
        help="A configured label; repeat for more than one",
    )

    p_todo_list = todo_sub.add_parser("list", help="Print the items")
    p_todo_list.add_argument(
        "--keys", action="store_true", help="Print only the item keys, one per line"
    )

    p_todo_status = todo_sub.add_parser("status", help="Set an item's status")
    p_todo_status.add_argument("key", metavar="KEY", help="Item key, or a unique prefix")
    p_todo_status.add_argument("status", metavar="STATUS", choices=STATUSES)

    p_todo_edit = todo_sub.add_parser("edit", help="Open an item in $EDITOR")
    p_todo_edit.add_argument("key", metavar="KEY", help="Item key, or a unique prefix")

    p_todo_rm = todo_sub.add_parser("rm", help="Delete an item")
    p_todo_rm.add_argument("key", metavar="KEY", help="Item key, or a unique prefix")

    p_todo_label = todo_sub.add_parser("label", help="Manage the label vocabulary")
    label_sub = p_todo_label.add_subparsers(dest="label_action", metavar="<action>")
    p_label_add = label_sub.add_parser("add", help="Add a label to [todo] labels")
    p_label_add.add_argument("name", metavar="NAME")
    p_label_rm = label_sub.add_parser("rm", help="Remove a label from [todo] labels")
    p_label_rm.add_argument("name", metavar="NAME")
    p_label_rm.add_argument(
        "--force", action="store_true", help="Remove the label even when items still carry it"
    )
    label_sub.add_parser("list", help="Print the labels, one per line")

    p_completion = sub.add_parser(
        "completion",
        help="Print the bash completion script",
        description=(
            "Print the bash completion script to stdout.\n\n"
            "To install:\n"
            "  echo 'source <(shad completion bash)' >> ~/.bashrc\n\n"
            "Source the script rather than pasting its text into a startup file.\n"
            "A pasted copy keeps completing the command surface that existed when\n"
            "it was written."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_completion.add_argument(
        "shell",
        choices=["bash"],
        help="Shell to generate completions for",
    )

    p_init = sub.add_parser(
        "init",
        help="Add a new project to the config interactively",
        description=(
            "Interactive wizard that adds a new project to the resolved config file.\n"
            "Creates the config file with a commented [defaults] block if it does not exist yet.\n\n"
            "Options:\n"
            "  --install-deps  install missing tmux and opencode dependencies on Fedora\n\n"
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
        help="Install missing tmux and opencode dependencies on Fedora before prompting",
    )

    p_config = sub.add_parser(
        "config",
        help="Inspect or edit the shad config file",
        description=(
            "Inspect and edit the shad config file.\n\n"
            "Actions:\n"
            "  show       print a rendered summary (default; --raw prints the file)\n"
            "  path       print the config file path\n"
            "  keys       print every settable key, one per line\n"
            "  get        print a single value\n"
            "  set        set a value; comments and formatting are preserved\n"
            "  unset      remove a key, or a whole project table\n"
            "  edit       open the file in $EDITOR, then validate it\n"
            "  validate   check that the file parses and loads\n\n"
            "Keys are dotted TOML paths:\n"
            "  defaults.oc_position\n"
            "  projects.kb.path\n"
            "  projects.alvr.db.session\n\n"
            "Examples:\n"
            "  shad config                          rendered summary\n"
            "  shad config show --raw               print shad.toml as-is\n"
            "  shad config path                     print the file path\n"
            "  shad config keys                     list settable keys\n"
            "  shad config get defaults.harness     read one value\n"
            "  shad config set defaults.harness claude\n"
            "  shad config set projects.kb.path ~/gh/kb\n"
            "  shad config unset projects.kb        remove the project\n\n"
            "Writes are validated before they replace the file."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    config_sub = p_config.add_subparsers(dest="config_action", metavar="<action>")

    p_config_show = config_sub.add_parser("show", help="Print a rendered config summary")
    p_config_show.add_argument(
        "--raw", action="store_true", help="Print the raw file contents instead"
    )

    config_sub.add_parser("path", help="Print the config file path")
    config_sub.add_parser("keys", help="Print every settable key, one per line")

    p_config_get = config_sub.add_parser("get", help="Print a single value")
    p_config_get.add_argument("key", metavar="KEY", help="Dotted key, e.g. defaults.harness")

    p_config_set = config_sub.add_parser("set", help="Set a single value")
    p_config_set.add_argument("key", metavar="KEY", help="Dotted key, e.g. defaults.harness")
    p_config_set.add_argument("value", metavar="VALUE", help="New value")
    p_config_set.add_argument(
        "--force",
        action="store_true",
        help="Skip key and path checks (still requires the result to be a loadable config)",
    )

    p_config_unset = config_sub.add_parser("unset", help="Remove a key or a project table")
    p_config_unset.add_argument("key", metavar="KEY", help="Dotted key, e.g. projects.kb")
    p_config_unset.add_argument(
        "--force",
        action="store_true",
        help="Allow removing a required key such as a project's path",
    )

    config_sub.add_parser("edit", help="Open the config file in $EDITOR")
    config_sub.add_parser("validate", help="Check that the config parses and loads")

    sub.add_parser(
        "cheat",
        help="Show a tmux cheat sheet in a popup (or stdout if outside tmux)",
        description=(
            "Display a tmux key-binding reference.\n\n"
            "Inside tmux  : opens a floating popup; dismiss with q\n"
            "Outside tmux : prints the cheat sheet to stdout\n\n"
            "Recommended ~/.tmux.conf binding:\n"
            '  bind-key F12 run-shell "shad cheat"'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # None means "resolve normally"; shared.config.config_path() then applies
    # $SHAD_CONFIG and the per-OS default. Readers and writers get the same
    # answer because they all go through it.
    override = Path(args.config).expanduser() if args.config else None

    if args.command is None:
        print_banner()
        parser.print_help()
        sys.exit(0)

    try:
        if args.command == "completion":
            print_completion(args.shell)
            return

        if args.command == "init":
            cmd_init(install_deps=args.install_deps, path=override)
            return

        if args.command == "cheat":
            sys.exit(cmd_cheat())

        if args.command == "config":
            cmd_config(args, path=override)
            return

        cfg: Config = load(override)

        if args.command == "projects":
            cmd_projects(cfg, args)
        elif args.command == "git":
            cmd_git(cfg, args)
        elif args.command == "todo":
            cmd_todo(cfg, args, path=override)

    except ShadError as exc:
        err_console.print(Text(f"✗ {exc}", style="bold red"))
        sys.exit(1)
    except (KeyboardInterrupt, EOFError):
        err_console.print(Text("\nAborted.", style="dim"))
        sys.exit(130)
