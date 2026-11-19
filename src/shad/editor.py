"""
The editor shad hands a file to.

`Editor` is constructed once per run by the root from the environment and
injected: $VISUAL, else $EDITOR, read at construction. When neither is set,
the first of the fallbacks found on PATH is used when a file is opened, so a
run that opens no file needs no editor. Holds the command only; per run.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path

from shad.errors import ShadError

FALLBACKS = ("nvim", "vim", "vi", "nano")


class Editor:
    def __init__(self, command: str | None) -> None:
        """*command* is the editor's command line, or None to probe the fallbacks."""
        self._command = command or None

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Editor:
        """$VISUAL, then $EDITOR."""
        return cls(env.get("VISUAL") or env.get("EDITOR"))

    def resolve(self) -> str:
        """The command line, or `infrastructure`/`no_editor` when there is none."""
        if self._command:
            return self._command
        for candidate in FALLBACKS:
            if shutil.which(candidate):
                return candidate
        raise ShadError.infrastructure("no_editor", "no editor found; set $EDITOR")

    def open(self, path: Path) -> None:
        """
        Hand *path* to the editor and wait for it. The editor takes the
        terminal over. A non-zero exit is `infrastructure`/`editor_failed`.
        """
        result = subprocess.run([*self.resolve().split(), str(path)], check=False)
        if result.returncode != 0:
            raise ShadError.infrastructure(
                "editor_failed", f"editor exited with status {result.returncode}"
            )
