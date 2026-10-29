"""`shad config get` — one value: from the file, else the value shad uses."""

from __future__ import annotations

from pathlib import Path

from shad.config import store, toml_edit
from shad.config.render import display
from shad.config.schema import field_for
from shad.shared.config import load
from shad.shared.errors import ShadError
from shad.todo.store import todo_dir


def get_config_value(path: Path, key: str) -> None:
    parts = toml_edit.split_dotted(key)
    value = store.lookup(store.read_raw(path), parts)

    if value is store.MISSING:
        value = _effective(path, parts)

    if value is store.MISSING:
        raise ShadError(f"key not found: {key}")

    if isinstance(value, dict):
        for dotted, leaf in _flatten(key, value):
            print(f"{dotted} = {toml_edit.format_value(leaf)}")
        return

    print(display(value))


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
    fallbacks, and the default todo path.  Returns store.MISSING when the
    key has no resolved value.
    """
    if field_for(parts) is None:
        return store.MISSING

    cfg = load(path)

    if parts[0] == "defaults":
        return getattr(cfg.defaults, parts[1], store.MISSING)

    if parts[0] == "todo":
        return str(todo_dir(cfg))

    if len(parts) == 3:
        project = cfg.projects.get(parts[1])
    else:
        project = cfg.groups.get(parts[1], {}).get(parts[2])

    if project is None:
        return store.MISSING

    value = getattr(project, parts[-1], store.MISSING)
    return str(value) if isinstance(value, Path) else value
