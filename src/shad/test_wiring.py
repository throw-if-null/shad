from __future__ import annotations

import argparse
import io
import os
import unittest
from collections.abc import Callable, Iterator
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, get_type_hints
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


def _mismatches(run: Callable[..., Any]) -> list[str]:
    """
    Each name *run* declares whose annotation the provider's type does not
    satisfy: the same type, or a subclass of the annotated class. A missing
    annotation is a mismatch, because nothing then verifies the binding.
    """
    hints = get_type_hints(run)
    found = []
    for name in declared(run):
        provided, wanted = PROVIDED.get(name), hints.get(name)
        if provided is not None and provided == wanted:
            continue
        if isinstance(provided, type) and isinstance(wanted, type) and issubclass(provided, wanted):
            continue
        found.append(f"{name}: {wanted!r} is declared, {provided!r} is provided")
    return found


class RegisteredCommandTests(unittest.TestCase):
    """
    Every command the root can dispatch binds each declared name to one
    provider of a compatible type (`[DEPS-1]`). The root's one composition is
    the only supported configuration.
    """

    def test_every_command_declares_only_provided_names(self) -> None:
        runs = list(_runs(build_parser()))
        self.assertGreater(len(runs), 20)
        for path, run in runs:
            with self.subTest(command=" ".join(path)):
                self.assertLessEqual(set(declared(run)), set(PROVIDED))

    def test_every_declared_dependency_has_the_type_its_provider_supplies(self) -> None:
        for path, run in _runs(build_parser()):
            with self.subTest(command=" ".join(path)):
                self.assertEqual(_mismatches(run), [])

    def test_a_declared_type_the_provider_does_not_supply_is_a_mismatch(self) -> None:
        def run(args: argparse.Namespace, *, out: Output, tmux: Path, editor) -> None: ...  # type: ignore[no-untyped-def]

        self.assertEqual(
            [entry.split(":")[0] for entry in _mismatches(run)], ["tmux", "editor"]
        )


class ProvidedTests(unittest.TestCase):
    """`PROVIDED` is read from `Supply`, so every name has exactly one provider."""

    def test_every_provided_name_is_a_supply_attribute(self) -> None:
        supply = _supply()
        for name in ("out", "trace"):
            self.assertIs(PROVIDED[name], type(getattr(supply, name)))
        for name in set(PROVIDED) - {"out", "trace"}:
            with self.subTest(name=name):
                self.assertTrue(hasattr(Supply, name))


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
        self.assertIs(supply.harnesses, supply.harnesses)


if __name__ == "__main__":
    unittest.main()
