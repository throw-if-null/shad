"""
Where the snapshot lives, and its one write.

    <data dir>/sessions.json

The data dir (`Config.data_dir`), not the config dir: a config directory is
often a dotfiles repository, and a file that changes on every save does not
belong in one.
"""

from __future__ import annotations

from pathlib import Path

from shad import atomic
from shad.config import Config
from shad.sessions.model import Snapshot, serialize

FILENAME = "sessions.json"


def snapshot_path(cfg: Config) -> Path:
    return cfg.data_dir / FILENAME


def write(path: Path, snapshot: Snapshot) -> None:
    """Replace the file in one step, so a reader never sees a partial snapshot."""
    atomic.replace(path, serialize(snapshot))
