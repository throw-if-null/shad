"""`shad config path` — the config file path as resolved for this run."""

from __future__ import annotations

import argparse
from pathlib import Path

from shad import parsers
from shad.output import Output


def register(sub: parsers.Subparsers) -> None:
    parsers.command(
        sub, "path", run=run, help="Print the config file path (the machine form as it is)"
    )


def run(args: argparse.Namespace, *, out: Output, config_file: Path) -> None:
    out.plain(str(config_file))
