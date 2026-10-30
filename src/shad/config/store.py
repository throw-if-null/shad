"""
The config file as text: every read, and the one write.

The actions read the raw TOML themselves rather than through
`shared.config.load()`, because they address keys as the file spells them
and `load()` fills in defaults. `commit` is the write every action and
`write_value` go through: the result is parsed and loaded from a temporary
file first, so a failed edit never replaces a working config.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import tomllib
from pathlib import Path

from shad.config import toml_edit
from shad.shared.config import load
from shad.shared.errors import ShadError

MISSING = object()  # what lookup() returns for a key the file does not have


def read_text(path: Path) -> str:
    if not path.exists():
        raise ShadError(
            f"config file not found: {path}\n"
            f"       run 'shad init' to create it."
        )
    return path.read_text()


def read_raw(path: Path) -> dict:
    try:
        return tomllib.loads(read_text(path))
    except tomllib.TOMLDecodeError as exc:
        raise ShadError(f"{path} is not valid TOML: {exc}") from None


def lookup(raw: dict, parts: list[str]) -> object:
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


def parse_or_fail(text: str) -> dict:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ShadError(f"refusing to write: result is not valid TOML: {exc}") from None


def commit(path: Path, text: str, *, hint: str | None = None) -> None:
    """Validate *text* in a temporary file, then atomically replace *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".shad.toml.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)

        try:
            tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise ShadError(f"refusing to write {path}: result is not valid TOML: {exc}") from None

        try:
            load(tmp)
        except ShadError as exc:
            message = f"refusing to write {path}: resulting config is invalid — {exc}"
            if hint:
                message = f"{message}\n       {hint}"
            raise ShadError(message) from None

        if path.exists():
            shutil.copymode(path, tmp)
        else:
            tmp.chmod(0o644)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


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
