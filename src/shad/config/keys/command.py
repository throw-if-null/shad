"""`shad config keys` — every settable key, one per line; the completion script parses it."""

from __future__ import annotations

from pathlib import Path

from shad.config import store
from shad.config.schema import known_keys


def print_config_keys(path: Path) -> None:
    raw = store.read_raw(path) if path.exists() else {}
    for key, _field in known_keys(store.project_paths(raw)):
        print(key)
