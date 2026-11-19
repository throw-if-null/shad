"""
The two write mechanics every file-backed store shares: an exclusive
create, and a replacement through a temporary file and `os.replace`, so a
reader never sees a partial file. Nothing here knows a record format.

Pure functions; shared-and-safe.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path


def create(path: Path, text: str) -> None:
    """
    Create *path* holding *text*. Raises FileExistsError when the file is
    already there: two creates of one path cannot both succeed.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)


def replace(path: Path, text: str, *, check: Callable[[Path], None] | None = None) -> None:
    """
    Replace *path* with *text* in one step. The text goes to a temporary
    file beside *path* first; *check*, when given, is called with that file
    and may raise, in which case *path* is untouched. An existing file keeps
    its mode; a new one gets 0644.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        if check is not None:
            check(tmp)
        if path.exists():
            shutil.copymode(path, tmp)
        else:
            tmp.chmod(0o644)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
