"""
shad exception hierarchy.

Raise ShadError (or a subclass) from any business-logic module to signal a
fatal user-facing error.  The top-level main() function is the single place
that catches ShadError, prints it, and returns exit code 1.
"""

from __future__ import annotations


class ShadError(Exception):
    """Fatal, user-facing error.  Message is printed as-is to stderr."""
