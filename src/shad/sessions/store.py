"""
Where the snapshot lives, and its one read and one write.

    <data dir>/sessions.json

The data dir, not the config dir: a config directory is often a dotfiles
repository, and a file that changes on every save does not belong in one.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from shad.sessions.model import Snapshot, parse, serialize
from shad.shared.config import default_data_dir
from shad.shared.errors import ShadError

FILENAME = "sessions.json"


def snapshot_path() -> Path:
    return default_data_dir() / FILENAME


def read(path: Path) -> Snapshot:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ShadError(f"no saved sessions at {path}; run `shad sessions save` first") from None
    return parse(text)


def write(path: Path, snapshot: Snapshot) -> None:
    """Replace the file in one step, so a reader never sees a partial snapshot."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(serialize(snapshot))
        tmp.chmod(0o644)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
