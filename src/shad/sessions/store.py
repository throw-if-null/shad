"""
Where the snapshot lives, and its one write.

    <data dir>/sessions.json

The data dir, not the config dir: a config directory is
often a dotfiles repository, and a file that changes on every save does not
belong in one.
"""

from __future__ import annotations

from pathlib import Path

from shad import atomic
from shad.sessions.model import Snapshot, serialize

FILENAME = "sessions.json"


def snapshot_path(data_dir: Path) -> Path:
    return data_dir / FILENAME


def write(path: Path, snapshot: Snapshot) -> None:
    """Replace the file in one step, so a reader never sees a partial snapshot."""
    atomic.replace(path, serialize(snapshot))
