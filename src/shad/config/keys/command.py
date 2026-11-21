"""`shad config keys` — every settable key, one per line; the completion script parses it."""

from __future__ import annotations

import argparse
from pathlib import Path

from shad import parsers
from shad.config import raw
from shad.config.schema import known_keys
from shad.output import Output


def register(sub: parsers.Subparsers) -> None:
    parsers.command(
        sub,
        "keys",
        run=run,
        help="Print every settable key, one per line (the machine form as it is)",
    )


def run(args: argparse.Namespace, *, out: Output, config_file: Path) -> None:
    path = config_file
    parsed = raw.parse(path.read_text()) if path.exists() else {}
    for key, _field in known_keys(raw.project_paths(parsed)):
        out.plain(key)
