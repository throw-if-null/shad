"""`shad config keys` — every settable key, one per line; the completion script parses it."""

from __future__ import annotations

import argparse

from shad import parsers
from shad.config import store
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
    raw = store.read_raw(path) if path.exists() else {}
    for key, _field in known_keys(store.project_paths(raw)):
        deps.out.plain(key)
