"""How `show` and `get` print a value."""

from __future__ import annotations

from shad.config import toml_edit


def display(value: object) -> str:
    """A scalar as `get` and `show` print it: a bool in its TOML spelling, which `set` accepts."""
    return toml_edit.format_value(value) if isinstance(value, bool) else str(value)
