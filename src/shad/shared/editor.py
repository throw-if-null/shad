"""The editor shad hands a file to."""

from __future__ import annotations

import os
import shutil

from shad.shared.errors import ShadError

_FALLBACKS = ("nvim", "vim", "vi", "nano")


def resolve_editor() -> str:
    """$VISUAL, then $EDITOR, then the first installed fallback."""
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if editor:
        return editor
    for candidate in _FALLBACKS:
        if shutil.which(candidate):
            return candidate
    raise ShadError("no editor found; set $EDITOR")
