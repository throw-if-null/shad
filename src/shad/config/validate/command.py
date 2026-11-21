"""`shad config validate` — load the file and report what it holds."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from rich.text import Text

from shad import parsers
from shad.config import load
from shad.output import Output


@dataclass(frozen=True)
class ConfigValidation:
    path: str
    valid: bool  # always True: a file that does not load raises instead
    projects: int
    groups: int


def register(sub: parsers.Subparsers) -> None:
    parsers.command(
        sub, "validate", run=run, render=render, help="Check that the config parses and loads"
    )


def run(args: argparse.Namespace, *, config_file: Path) -> ConfigValidation:
    return validate(config_file)


def validate(path: Path) -> ConfigValidation:
    """Load *path*, raising as `load` does, and count what it holds."""
    cfg = load(path)
    count = len(cfg.projects) + sum(len(group) for group in cfg.groups.values())
    return ConfigValidation(path=str(path), valid=True, projects=count, groups=len(cfg.groups))


def render(result: ConfigValidation, out: Output) -> None:
    out.print(
        Text("  ✓ ", style="bold green")
        + Text(f"{result.path} is valid", style="bright_white")
        + Text(f"  ({result.projects} project(s), {result.groups} group(s))", style="dim")
    )
