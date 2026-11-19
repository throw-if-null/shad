"""`shad config`: the group parser; each action registers on it. A bare `shad config` is `show`."""

from __future__ import annotations

import argparse

from shad import parsers
from shad.config.edit import command as edit
from shad.config.get import command as get
from shad.config.keys import command as keys
from shad.config.path import command as path
from shad.config.set import command as set_
from shad.config.show import command as show
from shad.config.unset import command as unset
from shad.config.validate import command as validate


def register(sub: parsers.Subparsers) -> None:
    _, actions = parsers.group(
        sub,
        "config",
        dest="config_action",
        run=show.run,
        render=show.render,
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
            "show, get and validate accept --json. The output of path and keys\n"
            "is the machine form as it is.\n\n"
            "Keys are dotted TOML paths:\n"
            "  defaults.oc_position\n"
            "  projects.kb.path\n"
            "  projects.alvr.db.session\n\n"
            "Examples:\n"
            "  shad config                          rendered summary\n"
            "  shad config show --raw               print shad.toml as-is\n"
            "  shad config show --json              the summary as JSON\n"
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
    for action in (show, path, keys, get, set_, unset, edit, validate):
        action.register(actions)
