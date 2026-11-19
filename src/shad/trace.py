"""
Diagnostics that are off by default and go to stderr under `--debug`.

The root constructs one `Trace` from the flag and injects it; a slice never
decides on its own whether to print a diagnostic (`[CLI-10]`, `[CLI-11]`).
"""

from __future__ import annotations

import sys
import traceback
from typing import TextIO


class Trace:
    """Writes to *stream* only while *enabled*. Safe to share: it holds no state."""

    def __init__(self, enabled: bool = False, stream: TextIO | None = None) -> None:
        self.enabled = enabled
        self._stream = stream

    @property
    def stream(self) -> TextIO:
        # Resolved per call, not at construction: the test runner swaps
        # sys.stderr for the duration of one command.
        return self._stream if self._stream is not None else sys.stderr

    def note(self, message: str) -> None:
        if self.enabled:
            print(message, file=self.stream)

    def exception(self, exc: BaseException) -> None:
        """The traceback of *exc*, when enabled."""
        if self.enabled:
            traceback.print_exception(exc, file=self.stream)
