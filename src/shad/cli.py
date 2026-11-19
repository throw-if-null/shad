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
shad sessions save|restore|stop|show     # the running shad sessions, as a snapshot

Config file: --config PATH, else $SHAD_CONFIG, else the per-OS default
(~/.config/shad/shad.toml on Linux). `shad config path` prints the resolved one.
--config precedes the subcommand; --debug goes before or after it.

Exit codes: 0 success, 2 invalid invocation, 1 every other failure. A failure
is one undecorated stderr line, `<code>: <message>`; --debug adds the
traceback. This module is the only place that renders an error.

Actions: status

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
from shad.config.edit.command import edit_config
from shad.config.get.command import get_config_value
from shad.config.keys.command import print_config_keys
from shad.config.path.command import print_config_path
from shad.config.set.command import set_config_value
from shad.config.show.command import show_config
from shad.config.unset.command import unset_config_value
from shad.config.validate.command import validate_config
from shad.errors import ShadError
from shad.git.command import cmd_git
from shad.init.command import cmd_init
from shad.projects.open.banner import print_banner
from shad.projects.open.command import open_project
from shad.projects.status.command import print_status
from shad.sessions.restore.command import restore_sessions
from shad.sessions.save.command import save_sessions
from shad.sessions.show.command import show_sessions
from shad.sessions.stop.command import stop_sessions
from shad.shared.config import (
    HARNESSES,
    Config,
    Project,
    config_path,
    load,
    resolve_prefix,
)
from shad.todo.add.command import add_todo
from shad.todo.edit.command import edit_todo
from shad.todo.label.command import manage_labels
from shad.todo.list.command import list_todos
from shad.todo.model import STATUSES
from shad.todo.panel.command import open_todo_panel
from shad.todo.rm.command import remove_todo
from shad.todo.status.command import set_todo_status
from shad.trace import Trace

console = Console()

# The category to exit code map ([CLI-8]); every category not listed exits 1.
EXIT_CODES = {"usage": 2}

ACTIONS = ("status",)
CONFIG_ACTIONS = ("show", "path", "keys", "get", "set", "unset", "edit", "validate")
SESSIONS_ACTIONS = ("save", "restore", "stop", "show")
TODO_ACTIONS = ("panel", "add", "list", "status", "edit", "rm", "label")


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
    cfg: Config, project: Project, action: str | None, harness: str | None, trace: Trace
) -> int | None:
    """Dispatch open / status for a resolved project. Returns the tmux exit
    code when the project was opened, None otherwise.

    *harness* applies to open only; status ignores it.
    """
    if action is None:
        print_banner()
        return open_project(project, cfg.defaults, harness=harness)
    if action == "status":
        print_status(project, trace)
        return None
    raise ShadError.usage("unknown_action", f"unknown action '{action}'; available: status")


def cmd_projects(
    cfg: Config, args: argparse.Namespace, trace: Trace | None = None
) -> int | None:
    """List, or run an action on one project. Returns what _run_action returns."""
    parts: list[str] = args.name  # 0–3 tokens: [group] [name] [action]
    harness: str | None = args.harness
    trace = trace or Trace()

    # --- no args: list everything ---
    if not parts:
        _list_all(cfg)
        return None

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
            raise ShadError.not_found("no_such_project", f"no project or group matching '{token}'")

        if match in cfg.projects:
            return _run_action(cfg, cfg.projects[match], action, harness, trace)
        if action:
            raise ShadError.usage(
                "group_needs_project",
                f"'{match}' is a group, not a project; specify a project within the group"
            )
        _list_group(cfg, match)
        return None

    # --- two tokens: group + project ---
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
                    f"did you mean: shad projects {group_token}?"
                )
            else:
                raise ShadError.not_found("no_such_group", f"no group matching '{group_token}'")

        group_projects = cfg.groups[group_match]
        proj_match = resolve_prefix(list(group_projects), proj_token)
        if proj_match is None:
            raise ShadError.not_found(
                "no_such_project",
                f"no project matching '{proj_token}' in group '{group_match}'; "
                f"available: {', '.join(sorted(group_projects))}"
            )

        return _run_action(cfg, group_projects[proj_match], action, harness, trace)

    # --- too many tokens ---
    raise ShadError.usage(
        "too_many_arguments",
        f"too many arguments ({len(parts)}); "
        "usage: shad projects [<group>] [<name>] [status]"
    )


# ---------------------------------------------------------------------------
# sessions command
# ---------------------------------------------------------------------------


def cmd_sessions(cfg: Config, args: argparse.Namespace) -> int | None:
    """Dispatch save / restore / stop / show. Returns restore's attach exit code."""
    action = getattr(args, "sessions_action", None)
    if action is None:
        raise ShadError.usage(
            "no_action", f"no sessions action given; available: {', '.join(SESSIONS_ACTIONS)}"
        )
    if action == "save":
        save_sessions(cfg, args)
    elif action == "restore":
        return restore_sessions(cfg, args)
    elif action == "stop":
        stop_sessions(cfg, args)
    elif action == "show":
        show_sessions(cfg, args)
    else:
        raise ShadError.usage(
            "unknown_action",
            f"unknown sessions action '{action}'; available: {', '.join(SESSIONS_ACTIONS)}"
        )
    return None


# ---------------------------------------------------------------------------
# todo command
# ---------------------------------------------------------------------------


def cmd_todo(cfg: Config, args: argparse.Namespace, path: Path | None = None) -> None:
    """Dispatch the todo actions. *path* is the config file `label` writes to."""
    action = getattr(args, "todo_action", None)
    if action is None:
        raise ShadError.usage(
            "no_action", f"no todo action given; available: {', '.join(TODO_ACTIONS)}"
        )
    if action == "panel":
        open_todo_panel(cfg, args)
    elif action == "add":
        add_todo(cfg, args)
    elif action == "list":
        list_todos(cfg, args)
    elif action == "status":
        set_todo_status(cfg, args)
    elif action == "edit":
        edit_todo(cfg, args)
    elif action == "rm":
        remove_todo(cfg, args)
    elif action == "label":
        manage_labels(cfg, args, path or config_path())
    else:
        raise ShadError.usage(
            "unknown_action",
            f"unknown todo action '{action}'; available: {', '.join(TODO_ACTIONS)}",
        )


def cmd_config(args: argparse.Namespace, path: Path | None = None) -> None:
    """Dispatch the config actions; a bare `shad config` is `show`. *path* overrides config_path()."""
    target = path or config_path()
    action = getattr(args, "config_action", None) or "show"
    if action == "show":
        show_config(target, raw_output=getattr(args, "raw", False))
    elif action == "path":
        print_config_path(target)
    elif action == "keys":
        print_config_keys(target)
    elif action == "get":
        get_config_value(target, args.key)
    elif action == "set":
        set_config_value(target, args.key, args.value, force=getattr(args, "force", False))
    elif action == "unset":
        unset_config_value(target, args.key, force=getattr(args, "force", False))
    elif action == "edit":
        edit_config(target)
    elif action == "validate":
        validate_config(target)
    else:
        raise ShadError.usage(
            "unknown_action",
            f"unknown config action '{action}'; available: {', '.join(CONFIG_ACTIONS)}"
        )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def _debug_parent() -> argparse.ArgumentParser:
    """
    The parser every subcommand inherits `--debug` from, so the flag is
    accepted before and after the subcommand. The default is SUPPRESS, not
    False: argparse applies a subparser's defaults after the root parsed, so
    a False default on the subcommand would overwrite a `--debug` given
    before it. `main` reads the flag with getattr.
    """
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "--debug",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Print the traceback of a failure and shad's diagnostics on stderr",
    )
    return parent


def _subcommand(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
    name: str,
    **kwargs: object,
) -> argparse.ArgumentParser:
    """A subcommand parser that also accepts --debug."""
    return sub.add_parser(name, parents=[_DEBUG], **kwargs)  # type: ignore[arg-type]


_DEBUG = _debug_parent()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shad",
        description="Attach or create project-specific tmux sessions.",
        parents=[_DEBUG],
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

    p_projects = _subcommand(sub, 
        "projects",
        help="List, open, or manage a project",
        description=(
            "List all projects, or target a specific project with an optional action.\n\n"
            "Actions:\n"
            "  (none)   open the project's tmux session (create if needed)\n"
            "  status   print a summary table for the project\n\n"
            "Examples:\n"
            "  shad projects                     list all projects\n"
            "  shad projects myapp               open myapp\n"
            "  shad projects tin shad            open grouped project\n"
            "  shad projects tin shad status     show status\n"
            "  shad projects myapp --harness claude   open with claude once\n\n"
            "Prefix matching is supported at each level."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_projects.add_argument(
        "name",
        nargs="*",
        metavar="NAME",
        help="[group] [project] [action]  — the action is status",
    )
    p_projects.add_argument(
        "--harness",
        choices=HARNESSES,
        help=(
            "Open with this harness instead of the project's configured one. "
            "Applies to open only; status ignores it."
        ),
    )

    p_git = _subcommand(sub, 
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

    p_git_sync = _subcommand(git_sub, 
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

    p_git_panel = _subcommand(git_sub, 
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

    p_todo = _subcommand(sub, 
        "todo",
        help="Manage the todo list",
        description=(
            "One todo list, not tied to a project: one text file per item,\n"
            "shown in the todo pane of every project session.\n\n"
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

    _subcommand(todo_sub, "panel", help="Show the todo pane")

    p_todo_add = _subcommand(todo_sub, "add", help="Create an item")
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

    p_todo_list = _subcommand(todo_sub, "list", help="Print the items")
    p_todo_list.add_argument(
        "--keys", action="store_true", help="Print only the item keys, one per line"
    )

    p_todo_status = _subcommand(todo_sub, "status", help="Set an item's status")
    p_todo_status.add_argument("key", metavar="KEY", help="Item key, or a unique prefix")
    p_todo_status.add_argument("status", metavar="STATUS", choices=STATUSES)

    p_todo_edit = _subcommand(todo_sub, "edit", help="Open an item in $EDITOR")
    p_todo_edit.add_argument("key", metavar="KEY", help="Item key, or a unique prefix")

    p_todo_rm = _subcommand(todo_sub, "rm", help="Delete an item")
    p_todo_rm.add_argument("key", metavar="KEY", help="Item key, or a unique prefix")

    p_todo_label = _subcommand(todo_sub, "label", help="Manage the label vocabulary")
    label_sub = p_todo_label.add_subparsers(dest="label_action", metavar="<action>")
    p_label_add = _subcommand(label_sub, "add", help="Add a label to [todo] labels")
    p_label_add.add_argument("name", metavar="NAME")
    p_label_rm = _subcommand(label_sub, "rm", help="Remove a label from [todo] labels")
    p_label_rm.add_argument("name", metavar="NAME")
    p_label_rm.add_argument(
        "--force", action="store_true", help="Remove the label even when items still carry it"
    )
    _subcommand(label_sub, "list", help="Print the labels, one per line")

    p_sessions = _subcommand(sub, 
        "sessions",
        help="Save the running shad sessions, bring them back, or stop them",
        description=(
            "Save which shad sessions are running and recreate them later,\n"
            "for example after a reboot; or pick running sessions to stop.\n\n"
            "Actions:\n"
            "  save      pick the running sessions to record, with the\n"
            "            conversation each harness pane holds\n"
            "  restore   create each saved session that is not running, with\n"
            "            the harness resuming its conversation, then attach\n"
            "  stop      pick running sessions and kill them\n"
            "  show      print what is saved\n\n"
            "save and stop show the same picker: one row per running session\n"
            "with the conversation's name and first prompt, whether it is\n"
            "attached, and whether its harness is busy, idle, or gone. Space\n"
            "toggles a row, a toggles all, Enter accepts, q cancels. In save\n"
            "the rows already in the snapshot start checked, or every row when\n"
            "there is no snapshot yet; the snapshot becomes exactly the\n"
            "selection. In stop nothing starts checked, and the session the\n"
            "command runs in is not listed.\n\n"
            "The snapshot is taken when save runs. Nothing keeps it current\n"
            "afterwards, and stop does not change it.\n\n"
            "Supported harness: claude. A session running opencode can be\n"
            "stopped but not saved; save lists it with the reason.\n\n"
            "restore attaches to the session that was attached when the\n"
            "snapshot was saved, else the first one. In kitty, each other\n"
            "session that was attached at save gets a tab of its own; this\n"
            "needs allow_remote_control yes in kitty.conf. --no-attach\n"
            "creates the sessions and returns, for use from a script.\n\n"
            "Examples:\n"
            "  shad sessions save\n"
            "  shad sessions save --all          every running session, no picker\n"
            "  shad sessions restore\n"
            "  shad sessions restore --no-attach\n"
            "  shad sessions stop\n"
            "  shad sessions show"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sessions_sub = p_sessions.add_subparsers(dest="sessions_action", metavar="<action>")
    p_sessions_save = _subcommand(sessions_sub, 
        "save", help="Pick the running shad sessions to record"
    )
    p_sessions_save.add_argument(
        "--all",
        action="store_true",
        help="Record every running session without the picker; works without a terminal",
    )
    p_sessions_restore = _subcommand(sessions_sub, 
        "restore", help="Create the saved sessions that are not running, then attach"
    )
    p_sessions_restore.add_argument(
        "--no-attach",
        action="store_true",
        help="Create the sessions without attaching to one or opening tabs",
    )
    _subcommand(sessions_sub, "stop", help="Pick running shad sessions and kill them")
    _subcommand(sessions_sub, "show", help="Print the saved sessions")

    p_completion = _subcommand(sub, 
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

    p_init = _subcommand(sub, 
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

    p_config = _subcommand(sub, 
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

    p_config_show = _subcommand(config_sub, "show", help="Print a rendered config summary")
    p_config_show.add_argument(
        "--raw", action="store_true", help="Print the raw file contents instead"
    )

    _subcommand(config_sub, "path", help="Print the config file path")
    _subcommand(config_sub, "keys", help="Print every settable key, one per line")

    p_config_get = _subcommand(config_sub, "get", help="Print a single value")
    p_config_get.add_argument("key", metavar="KEY", help="Dotted key, e.g. defaults.harness")

    p_config_set = _subcommand(config_sub, "set", help="Set a single value")
    p_config_set.add_argument("key", metavar="KEY", help="Dotted key, e.g. defaults.harness")
    p_config_set.add_argument("value", metavar="VALUE", help="New value")
    p_config_set.add_argument(
        "--force",
        action="store_true",
        help="Skip key and path checks (still requires the result to be a loadable config)",
    )

    p_config_unset = _subcommand(config_sub, "unset", help="Remove a key or a project table")
    p_config_unset.add_argument("key", metavar="KEY", help="Dotted key, e.g. projects.kb")
    p_config_unset.add_argument(
        "--force",
        action="store_true",
        help="Allow removing a required key such as a project's path",
    )

    _subcommand(config_sub, "edit", help="Open the config file in $EDITOR")
    _subcommand(config_sub, "validate", help="Check that the config parses and loads")

    _subcommand(sub, 
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


def main(argv: list[str] | None = None) -> int:
    """The `shad` entry point. Returns the exit code, which the console
    script and `python -m shad` exit with.

    *argv* is the command line after the program name; None reads the
    process's own.
    """
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse has already printed: --help and --version exit 0, a bad
        # command line exits 2.
        return _exit_code(exc.code)

    trace = Trace(enabled=getattr(args, "debug", False))

    # None means "resolve normally"; shared.config.config_path() then applies
    # $SHAD_CONFIG and the per-OS default. Readers and writers get the same
    # answer because they all go through it.
    override = Path(args.config).expanduser() if args.config else None

    if args.command is None:
        print_banner()
        parser.print_help()
        return 0

    try:
        if args.command == "completion":
            print_completion(args.shell)
            return 0

        if args.command == "init":
            cmd_init(install_deps=args.install_deps, path=override)
            return 0

        if args.command == "cheat":
            return cmd_cheat()

        if args.command == "config":
            cmd_config(args, path=override)
            return 0

        cfg: Config = load(override)

        code: int | None = None
        if args.command == "projects":
            code = cmd_projects(cfg, args, trace)
        elif args.command == "git":
            cmd_git(cfg, args, trace)
        elif args.command == "todo":
            cmd_todo(cfg, args, path=override)
        elif args.command == "sessions":
            code = cmd_sessions(cfg, args)
        return 0 if code is None else code

    except ShadError as exc:
        return _report(exc, exc, trace)
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 — the one place a failure of any type is rendered
        return _report(ShadError.internal("unexpected", f"{type(exc).__name__}: {exc}"), exc, trace)


def _report(error: ShadError, cause: BaseException, trace: Trace) -> int:
    """
    Render *error* as the one stderr line, the traceback of *cause* when
    tracing, and return the exit code its category maps to.
    """
    print(f"{error.code}: {error.message}", file=sys.stderr)
    trace.exception(cause)
    return EXIT_CODES.get(error.category, 1)


def _exit_code(code: object) -> int:
    """The exit status a SystemExit carries: None is 0, a message is 1."""
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    return 1
