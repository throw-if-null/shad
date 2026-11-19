"""
The one definition of `shad.toml`: every key, its kind, its range, its
default and its description. `load.py` validates a file against it, `set`
validates a command-line value against it, `init` writes the defaults block
from it, and a test holds `shad.example.toml` to it.

The key namespace mirrors the TOML layout:

  defaults.<field>                     oc_position, panel_percent, split_percent,
                                       git_panel, todo_panel, todo_percent, harness
  projects.<key>.<field>               path, session, harness
  projects.<group>.<key>.<field>       path, session, harness
  todo.<field>                         path; labels is managed by `shad todo label`

`set` accepts only the settable keys unless --force is given, so a typo
cannot silently add dead config.

Pure values and functions; shared-and-safe.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from shad.config.toml_edit import format_value
from shad.errors import ShadError

OC_POSITIONS = ("top", "bottom", "left")
HARNESSES = ("opencode", "claude")

# A todo label is also a header value and a CLI argument, so it is kept to the
# characters that need no quoting anywhere: lowercase, digits, and hyphens.
LABEL_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

ENUM = "enum"
BOOL = "bool"
PERCENT = "percent"
PATH = "path"
STRING = "string"
LABELS = "labels"  # an array of label names; not settable from the command line

PERCENT_MIN, PERCENT_MAX = 1, 99


@dataclass(frozen=True)
class Field:
    name: str
    kind: str
    choices: tuple[str, ...] = ()
    description: str = ""
    default: object = None  # None: no default, the key is required or derived

    @property
    def hint(self) -> str:
        if self.kind == ENUM:
            return " | ".join(self.choices)
        if self.kind == BOOL:
            return "true | false"
        if self.kind == PERCENT:
            return f"integer {PERCENT_MIN}-{PERCENT_MAX}"
        if self.kind == PATH:
            return "directory path"
        if self.kind == LABELS:
            return "array of labels"
        return "string"

    @property
    def settable(self) -> bool:
        """Whether `shad config set` takes the key: an array is not a command-line value."""
        return self.kind != LABELS


DEFAULTS_FIELDS: tuple[Field, ...] = (
    Field(
        "oc_position",
        ENUM,
        OC_POSITIONS,
        "side of the window the harness pane occupies; the git+bash bundle takes the other",
        default="top",
    ),
    Field(
        "panel_percent", PERCENT, description="% of the window the git+bash bundle takes", default=35
    ),
    Field(
        "split_percent",
        PERCENT,
        description="% of the bundle the git panel takes; bash gets the rest",
        default=20,
    ),
    Field("git_panel", BOOL, description="show the git panel", default=True),
    Field("todo_panel", BOOL, description="show the todo pane", default=True),
    Field(
        "todo_percent",
        PERCENT,
        description="% of the window width the todo column takes",
        default=20,
    ),
    Field("harness", ENUM, HARNESSES, "default harness for projects", default="opencode"),
)

PROJECT_FIELDS: tuple[Field, ...] = (
    Field("path", PATH, description="absolute path to the project root"),
    Field("session", STRING, description="tmux session name; defaults to the key, or <group>-<key>"),
    Field("harness", ENUM, HARNESSES, "harness for this project; defaults to [defaults] harness"),
)

TODO_FIELDS: tuple[Field, ...] = (
    Field(
        "labels",
        LABELS,
        description="the labels `shad todo add --label` accepts; managed by `shad todo label`",
        default=(),
    ),
    Field(
        "path",
        PATH,
        description="directory that holds the todo files; omit to use the per-OS data dir",
    ),
)

_DEFAULTS_BY_NAME = {field.name: field for field in DEFAULTS_FIELDS}
_PROJECT_BY_NAME = {field.name: field for field in PROJECT_FIELDS}
_TODO_BY_NAME = {field.name: field for field in TODO_FIELDS if field.settable}


def field_for(parts: list[str]) -> Field | None:
    """Return the settable schema field for a dotted key path, or None when unknown."""
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
    keys.extend((f"todo.{field.name}", field) for field in TODO_FIELDS if field.settable)
    return keys


def check(field: Field, value: object, key: str) -> object:
    """
    Validate a value a TOML file holds for *field* and return it as the
    Config carries it: the same rules `coerce` applies to a command-line
    value, so `load` rejects every value `set` rejects.
    """
    if field.kind == ENUM:
        if not isinstance(value, str) or value not in field.choices:
            raise ShadError.validation(
                "invalid_config",
                f"invalid {key} {value!r}; must be one of: {', '.join(field.choices)}",
            )
        return value
    if field.kind == BOOL:
        if not isinstance(value, bool):
            raise ShadError.validation(
                "invalid_config",
                f"invalid value for '{key}': expected true or false, got {value!r}",
            )
        return value
    if field.kind == PERCENT:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ShadError.validation(
                "invalid_config",
                f"invalid value for '{key}': expected an integer, got {value!r}",
            )
        if not PERCENT_MIN <= value <= PERCENT_MAX:
            raise ShadError.validation(
                "invalid_config",
                f"invalid {key} {value}; must be between {PERCENT_MIN} and {PERCENT_MAX}",
            )
        return value
    if field.kind == PATH:
        if not isinstance(value, str) or not value.strip():
            raise ShadError.validation(
                "invalid_config", f"{key} must be a non-empty string"
            )
        return value
    if field.kind == LABELS:
        return check_labels(value, key)
    if not isinstance(value, str) or not value.strip():
        raise ShadError.validation("invalid_config", f"{key} must be a non-empty string")
    return value


def check_labels(value: object, key: str) -> list[str]:
    """An array of unique label names, each in the label vocabulary's spelling."""
    if not isinstance(value, list) or not all(isinstance(label, str) for label in value):
        raise ShadError.validation("invalid_config", f"{key} must be an array of strings")
    seen: set[str] = set()
    for label in value:
        if not LABEL_RE.match(label):
            raise ShadError.validation(
                "invalid_config",
                f"invalid todo label {label!r}; use lowercase letters, digits and hyphens",
            )
        if label in seen:
            raise ShadError.validation("invalid_config", f"duplicate todo label {label!r}")
        seen.add(label)
    return list(value)


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
        if not PERCENT_MIN <= number <= PERCENT_MAX:
            raise ShadError.validation(
                "invalid_value",
                f"invalid value for '{key}': {number}; "
                f"must be between {PERCENT_MIN} and {PERCENT_MAX}",
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


def defaults_block() -> str:
    """
    The commented `[defaults]` block `shad init` starts a new file with:
    every default setting with its description and its default, commented
    out, so the file documents what it does not set.
    """
    lines = ["# ~/.config/shad/shad.toml", "", "[defaults]"]
    for field in DEFAULTS_FIELDS:
        lines.append(f"# {field.description[0].upper()}{field.description[1:]}.")
        if field.kind == ENUM:
            lines.append(f"# Allowed values: {' | '.join(field.choices)}")
        lines.append(f"# {field.name} = {format_value(field.default)}")
        lines.append("")
    todo = next(field for field in TODO_FIELDS if field.kind == LABELS)
    lines.append(f"# {todo.description[0].upper()}{todo.description[1:]}.")
    lines.append("# [todo]")
    lines.append('# labels = ["chore", "documentation", "investigation", "poc"]')
    lines.append("")
    return "\n".join(lines) + "\n"
