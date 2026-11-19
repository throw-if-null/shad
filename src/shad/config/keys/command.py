"""`shad config keys` — every settable key, one per line; the completion script parses it."""

from __future__ import annotations

import argparse

from shad import parsers
from shad.config import raw
from shad.config.schema import known_keys
from shad.deps import Deps


def register(sub: parsers.Subparsers) -> None:
    parsers.command(
        sub,
        "keys",
        run=run,
        help="Print every settable key, one per line (the machine form as it is)",
    )


def run(args: argparse.Namespace, deps: Deps) -> None:
    path = deps.config_file
    parsed = raw.parse(path.read_text()) if path.exists() else {}
    for key, _field in known_keys(raw.project_paths(parsed)):
        deps.out.plain(key)
