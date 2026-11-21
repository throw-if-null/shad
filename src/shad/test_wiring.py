from __future__ import annotations

import argparse
import io
import os
import unittest
from collections.abc import Callable, Iterator
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import MagicMock, patch

from shad.cli import build_parser
from shad.errors import ShadError
from shad.output import Output
from shad.trace import Trace
from shad.wiring import PROVIDED, Supply, arguments, declared


def _supply(config_arg: str | None = None) -> Supply:
    return Supply(
        out=Output(stdout=io.StringIO(), stderr=io.StringIO()),
        trace=Trace(),
        config_arg=config_arg,
        environ=dict(os.environ),
    )


def _runs(
    parser: argparse.ArgumentParser, path: tuple[str, ...] = ()
) -> Iterator[tuple[tuple[str, ...], Callable[..., Any]]]:
    run = parser.get_default("run")
    if run is not None:
        yield path, run
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                yield from _runs(sub, (*path, name))


class RegisteredCommandTests(unittest.TestCase):
    """Every command the root can dispatch declares only what the root provides."""

    def test_every_command_declares_only_provided_names(self) -> None:
        runs = list(_runs(build_parser()))
        self.assertGreater(len(runs), 20)
        for path, run in runs:
            with self.subTest(command=" ".join(path)):
                self.assertLessEqual(set(declared(run)), set(PROVIDED))


class ArgumentsTests(unittest.TestCase):
    """How the root turns a `run` signature into its arguments. `[TEST-3]` unit tests."""

    def test_a_command_receives_exactly_what_it_declares(self) -> None:
        def run(args: argparse.Namespace, *, out: Output, config_file: Path) -> None: ...

        supply = _supply("/tmp/shad-wiring.toml")
        supplied = arguments(run, supply)
        self.assertEqual(set(supplied), {"out", "config_file"})
        self.assertIs(supplied["out"], supply.out)
        self.assertEqual(supplied["config_file"], Path("/tmp/shad-wiring.toml"))

    def test_what_a_command_does_not_declare_is_not_constructed(self) -> None:
        def run(args: argparse.Namespace, *, out: Output) -> None: ...

        with (
            patch("shad.wiring.load") as load,
            patch("shad.wiring.Tmux") as tmux,
            patch("shad.wiring.Editor") as editor,
            patch("shad.wiring.Harnesses") as harnesses,
        ):
            arguments(run, _supply())
        for constructor in (load, tmux, editor.from_env, harnesses.from_env):
            constructor.assert_not_called()

    def test_a_declared_config_that_does_not_load_fails_before_the_command_runs(self) -> None:
        def run(args: argparse.Namespace, *, config: object) -> None: ...

        with TemporaryDirectory() as tmp:
            path = Path(tmp, "shad.toml")
            path.write_text("[defaults\n")
            with self.assertRaises(ShadError) as raised:
                arguments(run, _supply(str(path)))
        self.assertEqual(raised.exception.category, "validation")

    def test_an_unknown_name_is_internal_and_names_it(self) -> None:
        def run(args: argparse.Namespace, *, out: Output, nope: object) -> None: ...

        with self.assertRaises(ShadError) as raised:
            arguments(run, _supply())
        self.assertEqual(
            (raised.exception.category, raised.exception.code), ("internal", "unexpected")
        )
        self.assertIn("nope", raised.exception.message)

    def test_a_signature_with_only_variadic_parameters_receives_nothing(self) -> None:
        self.assertEqual(arguments(MagicMock(), _supply()), {})

    def test_each_value_is_constructed_once_per_run(self) -> None:
        supply = _supply()
        self.assertIs(supply.tmux, supply.tmux)
        self.assertIs(supply.deps, supply.deps)
        self.assertIs(supply.deps.tmux, supply.tmux)


if __name__ == "__main__":
    unittest.main()
