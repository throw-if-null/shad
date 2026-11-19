"""
The `todo` package. The panel's key bindings run the commands that own
each change through the names published here.
"""

from __future__ import annotations

from shad import parsers
from shad.todo.add.command import add_in_editor
from shad.todo.edit.command import edit_in_editor
from shad.todo.rm.command import remove
from shad.todo.status.command import set_status

__all__ = ["add_in_editor", "edit_in_editor", "register", "remove", "set_status"]


def register(sub: parsers.Subparsers) -> None:
    """Add this package's parsers to *sub*. Imported on call, so that a module
    of this package can be imported without the whole command tree."""
    from shad.todo.command import register as add

    add(sub)
