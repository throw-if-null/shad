"""`shad todo label`: the label-vocabulary group; each action registers on it.

The three actions act on one config key, `[todo] labels`, through the config
slice's `write_value`, so comments in the file survive.
"""

from __future__ import annotations

from shad import parsers
from shad.todo.label.add import command as add
from shad.todo.label.list import command as list_
from shad.todo.label.rm import command as rm


def register(sub: parsers.Subparsers) -> None:
    _, actions = parsers.group(
        sub, "label", dest="label_action", help="Manage the label vocabulary"
    )
    for action in (add, rm, list_):
        action.register(actions)
