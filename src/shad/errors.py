"""
The error model: one `ShadError` with a category, a code and a message.

A slice raises through one of the six constructors and owns the `code` it
passes. The root renders: it maps the category to an exit code and prints
`<code>: <message>` on stderr. No other module prints an error.
"""

from __future__ import annotations

from typing import Literal

Category = Literal["usage", "validation", "not_found", "conflict", "infrastructure", "internal"]

CATEGORIES: tuple[Category, ...] = (
    "usage",
    "validation",
    "not_found",
    "conflict",
    "infrastructure",
    "internal",
)


class ShadError(Exception):
    """
    A failure that leaves a slice. `category` is one of `CATEGORIES`, `code`
    is a stable snake_case word a script can match on, and `message` is the
    human line.
    """

    def __init__(self, category: Category, code: str, message: str) -> None:
        if category not in CATEGORIES:
            raise ValueError(f"{category!r} is not an error category")
        super().__init__(message)
        self.category: Category = category
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return self.message

    @classmethod
    def usage(cls, code: str, message: str) -> ShadError:
        """An invalid invocation: the command line, not the state, is wrong."""
        return cls("usage", code, message)

    @classmethod
    def validation(cls, code: str, message: str) -> ShadError:
        """Well-formed input that breaks a rule shad enforces."""
        return cls("validation", code, message)

    @classmethod
    def not_found(cls, code: str, message: str) -> ShadError:
        """A named project, group, item, key or file that does not exist."""
        return cls("not_found", code, message)

    @classmethod
    def conflict(cls, code: str, message: str) -> ShadError:
        """The current state refuses the request: already exists, still in use."""
        return cls("conflict", code, message)

    @classmethod
    def infrastructure(cls, code: str, message: str) -> ShadError:
        """A program, a file system, a terminal or the environment failed."""
        return cls("infrastructure", code, message)

    @classmethod
    def internal(cls, code: str, message: str) -> ShadError:
        """A defect in shad."""
        return cls("internal", code, message)
