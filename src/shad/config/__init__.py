"""
The `config` package owns `shad.toml`: the schema, the loader, and every
write. Another package reads the configuration through the names published
here; `shad init` and `shad todo label` write through `add_project` and
`write_value`.
"""

from __future__ import annotations

from shad import parsers
from shad.config.loader import (
    Config,
    Defaults,
    Project,
    ProjectTable,
    config_path,
    default_data_dir,
    load,
)
from shad.config.schema import HARNESSES, LABEL_RE, OC_POSITIONS
from shad.config.store import add_project, write_value

__all__ = [
    "HARNESSES",
    "LABEL_RE",
    "OC_POSITIONS",
    "Config",
    "Defaults",
    "Project",
    "ProjectTable",
    "add_project",
    "config_path",
    "default_data_dir",
    "load",
    "register",
    "write_value",
]


def register(sub: parsers.Subparsers) -> None:
    """Add this package's parsers to *sub*. Imported on call, so that a module
    of this package can be imported without the whole command tree."""
    from shad.config.command import register as add

    add(sub)
