"""`shad config edit` — the file in the editor, then `validate`."""

from __future__ import annotations

import argparse
import subprocess

from shad import parsers
from shad.config.validate.command import render as render_validation
from shad.config.validate.command import validate
from shad.deps import Deps
from shad.errors import ShadError
from shad.shared.editor import resolve_editor


def register(sub: parsers.Subparsers) -> None:
    parsers.command(sub, "edit", run=run, help="Open the config file in $EDITOR")


def run(args: argparse.Namespace, deps: Deps) -> None:
    path = deps.config_file
    editor = resolve_editor()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)

    result = subprocess.run([*editor.split(), str(path)], check=False)
    if result.returncode != 0:
        raise ShadError.infrastructure(
            "editor_failed", f"editor exited with status {result.returncode}"
        )

    render_validation(validate(path), deps.out)
