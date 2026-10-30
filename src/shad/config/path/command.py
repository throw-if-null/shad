"""`shad config path` — the config file path as resolved for this run."""

from __future__ import annotations

from pathlib import Path


def print_config_path(path: Path) -> None:
    print(path)
