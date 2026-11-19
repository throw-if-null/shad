"""The editor shad hands a file to."""

from __future__ import annotations

import os
import shutil

from shad.errors import ShadError

_FALLBACKS = ("nvim", "vim", "vi", "nano")


def resolve_editor() -> str:
    """$VISUAL, then $EDITOR, then the first installed fallback."""
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if editor:
        return editor
    for candidate in _FALLBACKS:
        if shutil.which(candidate):
            return candidate
    raise ShadError.infrastructure("no_editor", "no editor found; set $EDITOR")
