"""
`shad config` — inspect and edit ~/.config/shad/shad.toml.

Actions
-------
  show [--raw]        rendered summary, or the raw file text
  path                print the config file path
  keys                print every settable key, one per line
  get <key>           print a single value
  set <key> <value>   set a value (validated, comments preserved)
  unset <key>         remove a key or a whole project table
  edit                open the file in $EDITOR
  validate            check that the file parses and loads

Keys are dotted TOML paths, e.g. `defaults.oc_position`, `projects.kb.path`,
`projects.alvr.db.session`.  Every write goes to a temporary file that is
parsed and loaded first, so a failed edit never replaces a working config.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path

from rich.console import Console
from rich.text import Text

from shad.config import toml_edit
from shad.config.schema import PATH, coerce, field_for, infer, known_keys
from shad.shared.config import Config, config_path, load
from shad.shared.errors import ShadError
from shad.shared.render import make_table
from shad.todo.store import todo_dir

console = Console()
err_console = Console(stderr=True)

ACTIONS = ("show", "path", "keys", "get", "set", "unset", "edit", "validate")

_MISSING = object()

_EDITOR_FALLBACKS = ("nvim", "vim", "vi", "nano")


# ── raw file helpers ──────────────────────────────────────────────────────


def _read_text(path: Path) -> str:
    if not path.exists():
        raise ShadError(
            f"config file not found: {path}\n"
            f"       run 'shad init' to create it."
        )
    return path.read_text()


def _read_raw(path: Path) -> dict:
    try:
        return tomllib.loads(_read_text(path))
    except tomllib.TOMLDecodeError as exc:
        raise ShadError(f"{path} is not valid TOML: {exc}") from None


def _lookup(raw: dict, parts: list[str]) -> object:
    node: object = raw
    for part in parts:
        if not isinstance(node, dict) or part not in node:
            return _MISSING
        node = node[part]
    return node


def _project_paths(raw: dict) -> list[list[str]]:
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


def _commit(path: Path, text: str, *, hint: str | None = None) -> None:
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
    _commit(path, toml_edit.set_value(text, parts, toml_edit.format_value(value)))


# ── show ──────────────────────────────────────────────────────────────────


def _print_defaults(cfg: Config, raw: dict) -> None:
    table = make_table("defaults")
    configured = raw.get("defaults", {})
    if not isinstance(configured, dict):
        configured = {}

    for name in (
        "oc_position",
        "panel_percent",
        "split_percent",
        "git_panel",
        "todo_panel",
        "todo_percent",
        "harness",
    ):
        value = getattr(cfg.defaults, name)
        origin = "set" if name in configured else "default"
        table.add_row(
            Text(name, style="dim"),
            Text(_display(value), style="bright_white"),
            Text(origin, style="dim"),
        )
    console.print(table)


def _print_projects(cfg: Config) -> None:
    table = make_table("projects")
    table.add_column(style="bright_white")   # name
    table.add_column(overflow="fold")        # path
    table.add_column(style="dim")            # session
    table.add_column(style="dim")            # harness

    projects = sorted(cfg.projects.values(), key=lambda p: p.key)
    grouped = [
        project
        for group in sorted(cfg.groups)
        for project in sorted(cfg.groups[group].values(), key=lambda p: p.key)
    ]
    everything = projects + grouped

    if not everything:
        table.add_row(Text("no projects configured", style="dim"), "", "", "")
        console.print(table)
        return

    for project in everything:
        exists = project.path.is_dir()
        path_text = Text(str(project.path), style="" if exists else "red")
        if not exists:
            path_text.append("  ✗ missing", style="red")
        table.add_row(project.display_name, path_text, project.session, project.harness)

    console.print(table)


def _print_todo(cfg: Config) -> None:
    table = make_table("todo")
    labels = ", ".join(cfg.todo_labels) if cfg.todo_labels else "none"
    table.add_row(
        Text("labels", style="dim"),
        Text(labels, style="bright_white" if cfg.todo_labels else "dim"),
    )
    path = Text(str(todo_dir(cfg)), style="bright_white", overflow="fold")
    if cfg.todo_path is None:
        path.append("  default", style="dim")
    table.add_row(Text("path", style="dim"), path)
    console.print(table)


def _show(path: Path, *, raw_output: bool) -> None:
    if raw_output:
        text = _read_text(path)
        print(text, end="" if text.endswith("\n") else "\n")
        return

    raw = _read_raw(path)
    cfg = load(path)

    console.print()
    console.print(Text("shad config", style="bold bright_white") + Text(f"  {path}", style="dim"))
    console.print()
    _print_defaults(cfg, raw)
    console.print()
    _print_projects(cfg)
    console.print()
    _print_todo(cfg)
    console.print()


# ── keys / get ────────────────────────────────────────────────────────────


def _keys(path: Path) -> None:
    raw = _read_raw(path) if path.exists() else {}
    for key, _field in known_keys(_project_paths(raw)):
        print(key)


def _flatten(prefix: str, node: dict) -> list[tuple[str, object]]:
    out: list[tuple[str, object]] = []
    for key, value in node.items():
        dotted = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.extend(_flatten(dotted, value))
        else:
            out.append((dotted, value))
    return out


def _effective(path: Path, parts: list[str]) -> object:
    """
    Resolve a key that is absent from the file to the value shad actually uses.

    Covers `[defaults]` fields, the per-project `session` / `harness`
    fallbacks, and the default todo path.  Returns _MISSING when the key has
    no resolved value.
    """
    if field_for(parts) is None:
        return _MISSING

    cfg = load(path)

    if parts[0] == "defaults":
        return getattr(cfg.defaults, parts[1], _MISSING)

    if parts[0] == "todo":
        return str(todo_dir(cfg))

    if len(parts) == 3:
        project = cfg.projects.get(parts[1])
    else:
        project = cfg.groups.get(parts[1], {}).get(parts[2])

    if project is None:
        return _MISSING

    value = getattr(project, parts[-1], _MISSING)
    return str(value) if isinstance(value, Path) else value


def _get(path: Path, key: str) -> None:
    parts = toml_edit.split_dotted(key)
    value = _lookup(_read_raw(path), parts)

    if value is _MISSING:
        value = _effective(path, parts)

    if value is _MISSING:
        raise ShadError(f"key not found: {key}")

    if isinstance(value, dict):
        for dotted, leaf in _flatten(key, value):
            print(f"{dotted} = {toml_edit.format_value(leaf)}")
        return

    print(_display(value))


def _display(value: object) -> str:
    """A scalar as `get` and `show` print it: a bool in its TOML spelling, which `set` accepts."""
    return toml_edit.format_value(value) if isinstance(value, bool) else str(value)


# ── set / unset ───────────────────────────────────────────────────────────


def _set(path: Path, key: str, raw_value: str, *, force: bool) -> None:
    parts = toml_edit.split_dotted(key)
    field = field_for(parts)

    if field is None:
        if not force:
            raise ShadError(
                f"unknown key '{key}'; run 'shad config keys' to list settable keys, "
                f"or pass --force to write it anyway"
            )
        value, literal = infer(raw_value)
    else:
        value, literal = coerce(field, raw_value, key)
        if field.kind == PATH and not force and not Path(str(value)).is_dir():
            raise ShadError(
                f"path does not exist: {value}\n"
                f"       pass --force to set it anyway."
            )

    text = _read_text(path) if path.exists() else ""
    updated = toml_edit.set_value(text, parts, literal)

    written = _lookup(_parse_or_fail(updated), parts)
    if written != value:
        raise ShadError(
            f"failed to set '{key}': the file could not be edited safely; "
            f"use 'shad config edit'"
        )

    project_hint = None
    if parts[:1] == ["projects"] and parts[-1] != "path":
        project_hint = "for a new project, set its 'path' first."

    _commit(path, updated, hint=project_hint)

    console.print(
        Text("  ✓ ", style="bold green")
        + Text(key, style="cyan")
        + Text(" = ", style="dim")
        + Text(literal, style="bright_white")
    )


def _unset(path: Path, key: str, *, force: bool = False) -> None:
    parts = toml_edit.split_dotted(key)

    if not force and parts[:1] == ["projects"] and len(parts) in (3, 4) and parts[-1] == "path":
        table = ".".join(parts[:-1])
        raise ShadError(
            f"'{key}' is required; removing it would drop the project silently\n"
            f"       run 'shad config unset {table}' to remove the project, "
            f"or pass --force."
        )

    text = _read_text(path)
    updated = toml_edit.remove_path(text, parts)

    if _lookup(_parse_or_fail(updated), parts) is not _MISSING:
        raise ShadError(
            f"failed to unset '{key}': the file could not be edited safely; "
            f"use 'shad config edit'"
        )

    _commit(path, updated)
    console.print(Text("  ✓ removed ", style="bold green") + Text(key, style="cyan"))


def _parse_or_fail(text: str) -> dict:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ShadError(f"refusing to write: result is not valid TOML: {exc}") from None


# ── edit / validate ───────────────────────────────────────────────────────


def resolve_editor() -> str:
    """$VISUAL, then $EDITOR, then the first installed fallback."""
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if editor:
        return editor
    for candidate in _EDITOR_FALLBACKS:
        if shutil.which(candidate):
            return candidate
    raise ShadError("no editor found; set $EDITOR")


def _edit(path: Path) -> None:
    editor = resolve_editor()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)

    result = subprocess.run([*editor.split(), str(path)], check=False)
    if result.returncode != 0:
        raise ShadError(f"editor exited with status {result.returncode}")

    _validate(path)


def _validate(path: Path) -> None:
    cfg = load(path)
    count = len(cfg.projects) + sum(len(group) for group in cfg.groups.values())
    console.print(
        Text("  ✓ ", style="bold green")
        + Text(f"{path} is valid", style="bright_white")
        + Text(f"  ({count} project(s), {len(cfg.groups)} group(s))", style="dim")
    )


# ── dispatch ──────────────────────────────────────────────────────────────


def cmd_config(args: argparse.Namespace, path: Path | None = None) -> None:
    target = path or config_path()
    action = getattr(args, "config_action", None) or "show"

    if action == "show":
        _show(target, raw_output=getattr(args, "raw", False))
    elif action == "path":
        print(target)
    elif action == "keys":
        _keys(target)
    elif action == "get":
        _get(target, args.key)
    elif action == "set":
        _set(target, args.key, args.value, force=getattr(args, "force", False))
    elif action == "unset":
        _unset(target, args.key, force=getattr(args, "force", False))
    elif action == "edit":
        _edit(target)
    elif action == "validate":
        _validate(target)
    else:
        raise ShadError(f"unknown config action '{action}'; available: {', '.join(ACTIONS)}")
