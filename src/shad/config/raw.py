"""
The config as the file spells it: the raw-dict codec and the queries over it.

An action addresses keys as the file writes them, before `load()` fills in
defaults, so it parses the text to a plain dict and asks these functions about
it. This module performs no file I/O: each action reads the file itself
(STATE-1); here is only the pure parse and the structural queries.
"""

from __future__ import annotations

import tomllib

from shad.errors import ShadError

MISSING = object()  # what lookup() returns for a key the file does not have


def parse(text: str) -> dict:
    """Parse config text to a raw dict, raising `invalid_config` on a TOML error."""
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ShadError.validation("invalid_config", f"not valid TOML: {exc}") from None


def lookup(raw: dict, parts: list[str]) -> object:
    """The value at the dotted key path *parts*, or MISSING when it is absent."""
    node: object = raw
    for part in parts:
        if not isinstance(node, dict) or part not in node:
            return MISSING
        node = node[part]
    return node


def project_paths(raw: dict) -> list[list[str]]:
    """Key paths of every configured project, e.g. [["kb"], ["alvr", "db"]]."""
    found: list[list[str]] = []
    for key, value in raw.get("projects", {}).items():
        if not isinstance(value, dict):
            continue
        if "path" in value:
            found.append([key])
            continue
        for sub_key, sub_value in value.items():
            if isinstance(sub_value, dict):
                found.append([key, sub_key])
    return sorted(found)
