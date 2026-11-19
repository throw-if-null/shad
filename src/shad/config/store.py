"""
The one validated write of the config file.

Every mutation — `commit`, `write_value`, `add_project` — goes through here:
the result is parsed and loaded from a temporary file first, so a failed edit
never replaces a working config. The actions read and parse the file
themselves (see `config/raw.py`); this module never reads it except to form
the text it is about to replace.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from shad import atomic
from shad.config import toml_edit
from shad.config.loader import load
from shad.config.schema import defaults_block
from shad.errors import ShadError


def commit(path: Path, text: str, *, hint: str | None = None) -> None:
    """
    Validate *text* in a temporary file, then atomically replace *path*.

    The write strategy is last-writer-wins: a writer edits the text it
    read and replaces the file, and two writers that edit at once keep the
    later one's text. One user edits one file; `shad config edit` holds it
    in an editor anyway, and a lost edit is visible in `shad config show`.
    """

    def check(tmp: Path) -> None:
        try:
            tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise ShadError.validation(
                "invalid_config", f"refusing to write {path}: result is not valid TOML: {exc}"
            ) from None
        try:
            load(tmp)
        except ShadError as exc:
            message = f"refusing to write {path}: resulting config is invalid — {exc}"
            if hint:
                message = f"{message}; {hint}"
            raise ShadError.validation("invalid_config", message) from None

    atomic.replace(path, text, check=check)


def write_value(path: Path, key: str, value: object) -> None:
    """
    Set *key* to *value* in the config file, keeping comments and layout.

    The entry point for commands that own a key the `set` schema does not
    cover, such as the `[todo] labels` array that `shad todo label` manages.
    The result is validated the same way as every other write.
    """
    text = path.read_text() if path.exists() else ""
    parts = toml_edit.split_dotted(key)
    commit(path, toml_edit.set_value(text, parts, toml_edit.format_value(value)))


def add_project(
    path: Path, *, key: str, group: str | None, project_path: Path, session: str
) -> None:
    """
    Append the table for a new project to the config file, creating the
    file with the commented defaults block when it does not exist. The
    values are written as TOML strings, so a path with a quote or a
    backslash reads back as it was given.
    """
    text = path.read_text() if path.exists() else defaults_block()
    header = toml_edit.format_key(["projects", *([group] if group else []), key])
    table = "\n".join(
        [
            "",
            f"[{header}]",
            f"path    = {toml_edit.format_value(str(project_path))}",
            f"session = {toml_edit.format_value(session)}",
            "",
        ]
    )
    if text and not text.endswith("\n"):
        text += "\n"
    commit(path, text + table, hint="for a new project, set its 'path' first.")
