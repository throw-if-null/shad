"""`shad config get` — one value: from the file, else the value shad uses."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from shad import parsers
from shad.config import store, toml_edit
from shad.config.load import Config
from shad.config.render import display
from shad.config.schema import field_for
from shad.deps import Deps
from shad.errors import ShadError
from shad.output import Output
from shad.todo.store import todo_dir


@dataclass(frozen=True)
class ConfigValue:
    key: str
    value: object  # a scalar, a list, or a table as a nested object
    source: str  # "file", or "default" for the value shad uses when the file has none


def register(sub: parsers.Subparsers) -> None:
    parser = parsers.command(sub, "get", run=run, render=render, help="Print a single value")
    parser.add_argument("key", metavar="KEY", help="Dotted key, e.g. defaults.harness")


def run(args: argparse.Namespace, deps: Deps) -> ConfigValue:
    key: str = args.key
    parts = toml_edit.split_dotted(key)
    value = store.lookup(store.read_raw(deps.config_file), parts)
    source = "file"

    if value is store.MISSING:
        value = _effective(deps.config_file, parts, lambda: deps.config)
        source = "default"

    if value is store.MISSING:
        raise ShadError.not_found("no_such_key", f"key not found: {key}")

    return ConfigValue(key=key, value=value, source=source)


def render(result: ConfigValue, out: Output) -> None:
    if isinstance(result.value, dict):
        for dotted, leaf in _flatten(result.key, result.value):
            out.plain(f"{dotted} = {toml_edit.format_value(leaf)}")
        return
    out.plain(display(result.value))


def _flatten(prefix: str, node: dict) -> list[tuple[str, object]]:
    out: list[tuple[str, object]] = []
    for key, value in node.items():
        dotted = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.extend(_flatten(dotted, value))
        else:
            out.append((dotted, value))
    return out


def _effective(path: Path, parts: list[str], config: Callable[[], Config]) -> object:
    """
    Resolve a key that is absent from the file to the value shad actually uses.

    Covers `[defaults]` fields, the per-project `session` / `harness`
    fallbacks, and the default todo path. Returns store.MISSING when the
    key has no resolved value. *config* loads the file only when a value
    has to come from it.
    """
    if field_for(parts) is None:
        return store.MISSING

    cfg = config()

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
