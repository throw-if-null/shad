"""
What the root supplies to a command's `run`, by the names the command declares.

A command declares each dependency it uses as a keyword-only parameter of
`run`, after the parsed arguments, named after one of `PROVIDED`:

    def run(args: argparse.Namespace, *, out: Output, todo_dir: Path) -> None:

The signature is the complete list of what the command can reach
(`[DEPS-1]`). The root constructs only what the chosen command declares, and
constructs it before the command runs: a command that does not declare
`config` runs when the file does not load, and one that does fails before it
has done anything (`[CONFIG-3]`).

Part of the composition root (`[MODEL-1]`), not a crosscut: `cli` is its one
caller, and no command imports it. A `Supply` is constructed per run.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from functools import cached_property
from pathlib import Path
from typing import Any

from shad.config import (
    Config,
    Defaults,
    ProjectTable,
    config_path,
    default_data_dir,
    load,
)
from shad.editor import Editor
from shad.errors import ShadError
from shad.harness import Harnesses
from shad.output import Output
from shad.tmux import Tmux
from shad.trace import Trace

PROVIDED = (
    "out",
    "trace",
    "tmux",
    "editor",
    "harnesses",
    "config_file",
    "data_dir",
    "config",
    "defaults",
    "projects",
    "todo_dir",
    "todo_labels",
)


class Supply:
    """
    The values the root can supply to one run, each constructed on first
    request and kept for the run. *environ* is read here and nowhere below.
    """

    def __init__(
        self, *, out: Output, trace: Trace, config_arg: str | None, environ: Mapping[str, str]
    ) -> None:
        self.out = out
        self.trace = trace
        self._config_arg = config_arg
        self._environ = environ

    @cached_property
    def tmux(self) -> Tmux:
        return Tmux(self._environ)

    @cached_property
    def editor(self) -> Editor:
        return Editor.from_env(self._environ)

    @cached_property
    def harnesses(self) -> Harnesses:
        return Harnesses.from_env(self._environ)

    @cached_property
    def config_file(self) -> Path:
        """
        --config, else $SHAD_CONFIG, else the per-OS default. The config
        actions and `init` edit this file and every other command receives
        values loaded from it, so readers and writers resolve the same file.
        """
        if self._config_arg:
            return Path(self._config_arg).expanduser()
        return config_path(self._environ)

    @cached_property
    def data_dir(self) -> Path:
        return default_data_dir(self._environ)

    @cached_property
    def config(self) -> Config:
        """The file loaded and validated. Raises as `load` does."""
        return load(self.config_file, data_dir=self.data_dir)

    @cached_property
    def defaults(self) -> Defaults:
        return self.config.defaults

    @cached_property
    def projects(self) -> ProjectTable:
        return self.config.project_table

    @cached_property
    def todo_dir(self) -> Path:
        return self.config.todo_dir

    @cached_property
    def todo_labels(self) -> list[str]:
        return self.config.todo_labels


def declared(run: Callable[..., Any]) -> list[str]:
    """The names *run* declares after its first parameter, the parsed arguments."""
    parameters = list(inspect.signature(run).parameters.values())[1:]
    variadic = (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
    return [p.name for p in parameters if p.kind not in variadic]


def arguments(run: Callable[..., Any], supply: Supply) -> dict[str, object]:
    """
    The keyword arguments *run* declares, constructed from *supply*. A name
    outside `PROVIDED` is `internal`/`unexpected`, raised before anything is
    constructed.
    """
    names = declared(run)
    unknown = [name for name in names if name not in PROVIDED]
    if unknown:
        raise ShadError.internal(
            "unexpected",
            f"{run.__module__}.{run.__qualname__} declares {', '.join(unknown)}, "
            "which the root does not provide",
        )
    return {name: getattr(supply, name) for name in names}
