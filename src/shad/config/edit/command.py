"""`shad config edit` — the file in the editor, then `validate`."""

from __future__ import annotations

import argparse

from shad import parsers
from shad.config.validate.command import render as render_validation
from shad.config.validate.command import validate
from shad.deps import Deps


def register(sub: parsers.Subparsers) -> None:
    parsers.command(sub, "edit", run=run, help="Open the config file in $EDITOR")


def run(args: argparse.Namespace, deps: Deps) -> None:
    path = deps.config_file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    deps.editor.open(path)
    render_validation(validate(path), deps.out)
