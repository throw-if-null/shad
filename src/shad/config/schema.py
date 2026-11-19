"""
Settable config keys for `shad config`.

The key namespace mirrors the TOML layout:

  defaults.<field>                     oc_position, panel_percent, split_percent,
                                       git_panel, todo_panel, todo_percent, harness
  projects.<key>.<field>               path, session, harness
  projects.<group>.<key>.<field>       path, session, harness
  todo.<field>                         path

`set` accepts only these keys unless --force is given, so a typo cannot
silently add dead config.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from shad.config.load import HARNESSES, OC_POSITIONS
from shad.config.toml_edit import format_value
from shad.errors import ShadError

ENUM = "enum"
BOOL = "bool"
PERCENT = "percent"
PATH = "path"
STRING = "string"


@dataclass(frozen=True)
class Field:
    name: str
    kind: str
    choices: tuple[str, ...] = ()
    description: str = ""

    @property
    def hint(self) -> str:
        if self.kind == ENUM:
            return " | ".join(self.choices)
        if self.kind == BOOL:
            return "true | false"
        if self.kind == PERCENT:
            return "integer 1-99"
        if self.kind == PATH:
            return "directory path"
        return "string"


DEFAULTS_FIELDS: tuple[Field, ...] = (
    Field(
        "oc_position",
        ENUM,
        OC_POSITIONS,
        "side of the window the harness pane occupies",
    ),
    Field("panel_percent", PERCENT, description="% of the window the git+bash bundle takes"),
    Field("split_percent", PERCENT, description="% of the bundle the git panel takes"),
    Field("git_panel", BOOL, description="show the git panel"),
    Field("todo_panel", BOOL, description="show the todo pane"),
    Field("todo_percent", PERCENT, description="% of the window width the todo column takes"),
    Field("harness", ENUM, HARNESSES, "default harness for projects"),
)

PROJECT_FIELDS: tuple[Field, ...] = (
    Field("path", PATH, description="absolute path to the project root"),
    Field("session", STRING, description="tmux session name"),
    Field("harness", ENUM, HARNESSES, "harness for this project"),
)

TODO_FIELDS: tuple[Field, ...] = (
    Field("path", PATH, description="directory that holds the todo files"),
)

_DEFAULTS_BY_NAME = {field.name: field for field in DEFAULTS_FIELDS}
_PROJECT_BY_NAME = {field.name: field for field in PROJECT_FIELDS}
_TODO_BY_NAME = {field.name: field for field in TODO_FIELDS}


def field_for(parts: list[str]) -> Field | None:
    """Return the schema field for a dotted key path, or None when unknown."""
    if parts[:1] == ["defaults"] and len(parts) == 2:
        return _DEFAULTS_BY_NAME.get(parts[1])
    if parts[:1] == ["projects"] and len(parts) in (3, 4):
        return _PROJECT_BY_NAME.get(parts[-1])
    if parts[:1] == ["todo"] and len(parts) == 2:
        return _TODO_BY_NAME.get(parts[1])
    return None


def known_keys(projects: list[list[str]]) -> list[tuple[str, Field]]:
    """
    Build the full settable key namespace.

    *projects* holds the key path of every configured project, e.g.
    ``[["kb"], ["alvr", "db"]]``.
    """
    keys: list[tuple[str, Field]] = [
        (f"defaults.{field.name}", field) for field in DEFAULTS_FIELDS
    ]
    for project in projects:
        prefix = ".".join(["projects", *project])
        keys.extend((f"{prefix}.{field.name}", field) for field in PROJECT_FIELDS)
    keys.extend((f"todo.{field.name}", field) for field in TODO_FIELDS)
    return keys


def coerce(field: Field, raw: str, key: str) -> tuple[object, str]:
    """
    Validate and convert a command-line value for *field*.

    Returns (Python value, TOML literal).
    """
    value = raw.strip()

    if field.kind == ENUM:
        lowered = value.lower()
        if lowered not in field.choices:
            raise ShadError.validation(
                "invalid_value",
                f"invalid value for '{key}': {raw!r}; "
                f"must be one of: {', '.join(field.choices)}"
            )
        return lowered, format_value(lowered)

    if field.kind == BOOL:
        lowered = value.lower()
        if lowered not in ("true", "false"):
            raise ShadError.validation(
                "invalid_value", f"invalid value for '{key}': {raw!r}; must be true or false"
            )
        flag = lowered == "true"
        return flag, format_value(flag)

    if field.kind == PERCENT:
        try:
            number = int(value)
        except ValueError:
            raise ShadError.validation(
                "invalid_value",
                f"invalid value for '{key}': {raw!r}; expected an integer"
            ) from None
        if not 1 <= number <= 99:
            raise ShadError.validation(
                "invalid_value",
                f"invalid value for '{key}': {number}; must be between 1 and 99"
            )
        return number, format_value(number)

    if field.kind == PATH:
        if not value:
            raise ShadError.validation(
                "invalid_value", f"invalid value for '{key}': path must not be empty"
            )
        expanded = Path(value).expanduser()
        resolved = str(expanded.resolve() if expanded.is_absolute() or expanded.exists() else expanded)
        return resolved, format_value(resolved)

    if not value:
        raise ShadError.validation(
            "invalid_value", f"invalid value for '{key}': value must not be empty"
        )
    return value, format_value(value)


def infer(raw: str) -> tuple[object, str]:
    """
    Convert an unvalidated value (--force) to a TOML literal.

    Integers and booleans are written bare; everything else is quoted.
    """
    value = raw.strip()
    if value.lower() in ("true", "false"):
        return value.lower() == "true", format_value(value.lower() == "true")
    try:
        number = int(value)
    except ValueError:
        return value, format_value(value)
    return number, format_value(number)
