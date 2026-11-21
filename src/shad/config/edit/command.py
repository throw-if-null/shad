"""`shad config edit` — the file in the editor, then `validate`."""

from __future__ import annotations

import argparse
from pathlib import Path

from shad import parsers
from shad.config.validate.command import render as render_validation
from shad.config.validate.command import validate
from shad.editor import Editor
from shad.output import Output


def register(sub: parsers.Subparsers) -> None:
    parsers.command(sub, "edit", run=run, help="Open the config file in $EDITOR")


def run(args: argparse.Namespace, *, out: Output, editor: Editor, config_file: Path) -> None:
    path = config_file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    editor.open(path)
    render_validation(validate(path), out)
