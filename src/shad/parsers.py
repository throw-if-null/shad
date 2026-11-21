"""
How a command registers its parser, and what the root dispatches on.

Every parser inherits `--debug` and `--json` through DEBUG and JSON, so
both flags are accepted before and after the subcommand, and the rejection
of `--json` on a command without a result is the root's `no_json` usage
error in every position, never argparse's. Both default to SUPPRESS, not
False: argparse applies a subparser's defaults after the root parsed, so a
False default on the subcommand would overwrite a flag given before it. The
root reads each flag with getattr.

The parents are built once at import and only read; shared-and-safe.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from shad.errors import ShadError

if TYPE_CHECKING:
    # Generic in typeshed only; annotations are strings, so the alias is never evaluated.
    Subparsers = argparse._SubParsersAction[argparse.ArgumentParser]
# run(args, **declared): None, an exit status a child process returned, or a result.
Run = Callable[..., Any]
# render(result, out): the result as text.
Render = Callable[..., None]


def _flag(name: str, help: str) -> argparse.ArgumentParser:
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(name, action="store_true", default=argparse.SUPPRESS, help=help)
    return parent


DEBUG = _flag("--debug", "Print the traceback of a failure and shad's diagnostics on stderr")
JSON = _flag("--json", "On a read command, print the result as one JSON document on stdout")


def command(
    sub: Subparsers, name: str, *, run: Run, render: Render | None = None, **kwargs: Any
) -> argparse.ArgumentParser:
    """
    Add the parser for *name* to *sub* and record what the root runs.

    *run* takes the parsed arguments, then, as keyword-only parameters, the
    dependencies it uses, each named after one of `shad.wiring.PROVIDED`;
    the root supplies them. A command whose
    `run` returns a result passes *render*, which prints it as text; with
    --json the root encodes the result instead. A command that prints as it
    goes, or hands the terminal over, passes no *render* and returns None
    or the exit status; the root then rejects --json for it.
    """
    parser = sub.add_parser(name, parents=[DEBUG, JSON], **kwargs)
    parser.set_defaults(run=run, render=render)
    return parser


def group(
    sub: Subparsers,
    name: str,
    *,
    dest: str,
    run: Run | None = None,
    render: Render | None = None,
    **kwargs: Any,
) -> tuple[argparse.ArgumentParser, Subparsers]:
    """
    Add the parser for the command group *name* and return it with the
    subparsers its actions register on. Without an action the group runs
    *run*, or raises the `no_action` usage error when there is none.
    """
    parser = sub.add_parser(name, parents=[DEBUG, JSON], **kwargs)
    actions = parser.add_subparsers(dest=dest, metavar="<action>")
    if run is None:

        def run(args: argparse.Namespace) -> None:
            available = ", ".join(actions.choices)
            raise ShadError.usage("no_action", f"no {name} action given; available: {available}")

    parser.set_defaults(run=run, render=render)
    return parser, actions
