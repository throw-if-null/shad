"""`shad config edit` — the file in the editor, then `validate`."""

from __future__ import annotations

import subprocess
from pathlib import Path

from shad.config.validate.command import validate_config
from shad.shared.editor import resolve_editor
from shad.shared.errors import ShadError


def edit_config(path: Path) -> None:
    editor = resolve_editor()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)

    result = subprocess.run([*editor.split(), str(path)], check=False)
    if result.returncode != 0:
        raise ShadError(f"editor exited with status {result.returncode}")

    validate_config(path)
