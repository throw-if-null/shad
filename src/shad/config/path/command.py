"""`shad config path` — the config file path as resolved for this run."""

from __future__ import annotations

import argparse

from shad import parsers
from shad.deps import Deps


def register(sub: parsers.Subparsers) -> None:
    parsers.command(
        sub, "path", run=run, help="Print the config file path (the machine form as it is)"
    )


def run(args: argparse.Namespace, deps: Deps) -> None:
    deps.out.plain(str(deps.config_file))
