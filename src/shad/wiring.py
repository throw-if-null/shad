"""
What the root supplies to a command's `run`, by the names the command declares.

A command declares each dependency it uses as a keyword-only parameter of
`run`, after the parsed arguments, named after one of `PROVIDED` and
annotated with its type:

    def run(args: argparse.Namespace, *, out: Output, todo_dir: Path) -> None:

The signature is the complete list of what the command can reach
(`[DEPS-1]`). The root constructs only what the chosen command declares, and
constructs it before the command runs: a command that does not declare
`config` runs when the file does not load, and one that does fails before it
has done anything (`[CONFIG-3]`).

`Supply` is the one definition of what the root provides: `PROVIDED` is read
from its annotated attributes and the return types of its cached properties,
so a name cannot be provided without a provider. `test_wiring.py` checks every
registered command against `PROVIDED`, by name and by type, because mypy does
not see through `**arguments(run, supply)`.

Part of the composition root (`[MODEL-1]`), not a crosscut: `cli` is its one
caller, and no command imports it. A `Supply` is constructed per run.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from functools import cached_property
from pathlib import Path
from typing import Any, get_type_hints

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


class Supply:
    """
    The values the root can supply to one run, each constructed on first
    request and kept for the run. *environ* is read here and nowhere below.
    """

    out: Output
    trace: Trace

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


def _provided() -> dict[str, Any]:
    """Each name `Supply` provides, mapped to the type of its value."""
    hints = get_type_hints(Supply)
    provided = {name: kind for name, kind in hints.items() if not name.startswith("_")}
    for name, member in vars(Supply).items():
        if isinstance(member, cached_property):
            provided[name] = get_type_hints(member.func)["return"]
    return provided


PROVIDED = _provided()


def declared(run: Callable[..., Any]) -> list[str]:
    """
    The names *run* declares after its first parameter, the parsed arguments.

    The root calls `run(args, **arguments(run, supply))`, so the first
    parameter takes a positional argument, and every later parameter is
    keyword-only, annotated, and named in `PROVIDED`. A positional or
    variadic dependency parameter would accept a value the root never binds
    by name, or none. Any other signature is `internal`/`unexpected`, raised
    before anything is constructed. The types are compared with `PROVIDED`
    by `test_wiring.py`, not here: resolving annotations costs every run and
    adds nothing the test of every registered command does not establish.
    """
    parameters = list(inspect.signature(run).parameters.values())
    positional = (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    problems = []
    if not parameters or parameters[0].kind not in positional:
        problems.append("no positional first parameter for the parsed arguments")
    for p in parameters[1:]:
        if p.kind is not inspect.Parameter.KEYWORD_ONLY:
            problems.append(f"{p.name} is {p.kind.description}, not keyword-only")
        elif p.annotation is inspect.Parameter.empty:
            problems.append(f"{p.name} has no annotation")
        elif p.name not in PROVIDED:
            problems.append(f"{p.name} is not provided by the root")
    if problems:
        name = f"{run.__module__}.{run.__qualname__}"
        raise ShadError.internal("unexpected", f"{name}: {'; '.join(problems)}")
    return [p.name for p in parameters[1:]]


def arguments(run: Callable[..., Any], supply: Supply) -> dict[str, object]:
    """
    The keyword arguments *run* declares, constructed from *supply*. A
    signature `declared` rejects raises before anything is constructed.
    """
    return {name: getattr(supply, name) for name in declared(run)}
