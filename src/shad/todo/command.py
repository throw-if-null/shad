"""`shad todo`: the group parser; each action registers on it."""

from __future__ import annotations

import argparse

from shad import parsers
from shad.todo.add import command as add
from shad.todo.edit import command as edit
from shad.todo.label import command as label
from shad.todo.list import command as list_
from shad.todo.panel import command as panel
from shad.todo.rm import command as rm
from shad.todo.status import command as status


def register(sub: parsers.Subparsers) -> None:
    _, actions = parsers.group(
        sub,
        "todo",
        dest="todo_action",
        help="Manage the todo list",
        description=(
            "One todo list, not tied to a project: one text file per item,\n"
            "shown in the todo pane of every project session.\n\n"
            "Actions:\n"
            "  panel    the pane: list, status keys, add, delete, edit\n"
            "  add      create an item; its key is a slug of the title. With no\n"
            "           title, write the item in $EDITOR from a template\n"
            "  list     print the items (--json: as JSON; --keys: just the keys)\n"
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
            "  shad todo list --json\n"
            "  shad todo status fix-panel in-progress\n"
            "  shad todo edit fix-panel\n"
            "  shad todo rm fix-panel\n"
            "  shad todo label add investigation\n"
            "  shad todo panel"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    for action in (panel, add, list_, status, edit, rm, label):
        action.register(actions)
