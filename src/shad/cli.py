"""
shad CLI entry point: the composition root.

Commands
--------
shad --help
shad projects                            # list projects and groups
shad projects <name>                     # open top-level project or list group
shad projects <group> <name>             # open project inside a group
shad projects <name> <action>            # run action on top-level project
shad projects <group> <name> <action>    # run action on grouped project
shad projects <name> --harness <h>       # open with a one-off harness
shad config <action> [args]              # inspect or edit shad.toml
shad git sync [<group>] [<name>]         # git maintenance across projects
shad git panel [<group>] [<name>]        # read-only repository view
shad todo <action> [args]                # the todo list
shad sessions save|restore|stop|show     # the running shad sessions, as a snapshot
shad init | cheat | completion bash

Each package registers its own parser (`register`) and records the function
the root runs (`run(args, deps)`) and, for a read command, the one that
renders its result as text (`render(result, out)`). This module constructs
the crosscuts, parses, runs, renders, and maps errors; it holds no command
logic.

Config file: --config PATH, else $SHAD_CONFIG, else the per-OS default
(~/.config/shad/shad.toml on Linux). `shad config path` prints the resolved one.
--config precedes the subcommand; --debug and --json go before or after it.

A read command's result goes to stdout as text, or with --json as one JSON
document and nothing else. A command that is not a read rejects --json with
the usage error `no_json`.

Exit codes: 0 success, 2 invalid invocation, 1 every other failure. A failure
is one undecorated stderr line, `<code>: <message>`; --debug adds the
traceback. This module is the only place that renders an error.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from shad import (
    __version__,
    cheat,
    completion,
    config,
    git,
    init,
    projects,
    sessions,
    todo,
)
from shad.banner import print_banner
from shad.deps import Deps
from shad.errors import ShadError
from shad.output import Output
from shad.parsers import DEBUG, JSON
from shad.shared.config import config_path
from shad.trace import Trace

# The category to exit code map ([CLI-8]); every category not listed exits 1.
EXIT_CODES = {"usage": 2}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shad",
        description="Attach or create project-specific tmux sessions.",
        parents=[DEBUG, JSON],
    )
    parser.add_argument("--version", action="version", version=f"shad {__version__}")
    parser.add_argument(
        "--config",
        metavar="PATH",
        help=(
            "Config file to use, overriding $SHAD_CONFIG and the per-OS default. "
            "Must precede the subcommand."
        ),
    )

    sub = parser.add_subparsers(dest="command", metavar="<command>")
    for package in (projects, git, todo, sessions, completion, init, config, cheat):
        package.register(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    """The `shad` entry point. Returns the exit code, which the console
    script and `python -m shad` exit with.

    *argv* is the command line after the program name; None reads the
    process's own.
    """
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse has already printed: --help and --version exit 0, a bad
        # command line exits 2.
        return _exit_code(exc.code)

    out = Output()
    trace = Trace(enabled=getattr(args, "debug", False))

    if args.command is None:
        print_banner(out)
        parser.print_help()
        return 0

    try:
        return _dispatch(args, out, trace)
    except ShadError as exc:
        return _report(exc, exc, trace)
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 — the one place a failure of any type is rendered
        return _report(ShadError.internal("unexpected", f"{type(exc).__name__}: {exc}"), exc, trace)


def _dispatch(args: argparse.Namespace, out: Output, trace: Trace) -> int:
    """Run the command the parser chose and present what it returns."""
    render: Callable[[object, Output], None] | None = getattr(args, "render", None)
    as_json = getattr(args, "json", False)
    if as_json and render is None:
        raise ShadError.usage(
            "no_json", "--json applies to a read command, and this command has no result to encode"
        )

    # None means "resolve normally": config_path() applies $SHAD_CONFIG and
    # the per-OS default. Readers and writers get the same answer because
    # they all go through the one Deps.
    config_file = Path(args.config).expanduser() if args.config else config_path()
    deps = Deps(out=out, trace=trace, config_file=config_file)

    result = args.run(args, deps)
    if result is None:
        return 0
    if isinstance(result, int):
        return result  # the status of the process the command handed the terminal to
    if as_json:
        out.json(asdict(result))
        return 0
    assert render is not None  # a result comes only from a parser registered with one
    render(result, out)
    return 0


def _report(error: ShadError, cause: BaseException, trace: Trace) -> int:
    """
    Render *error* as the one stderr line, the traceback of *cause* when
    tracing, and return the exit code its category maps to.
    """
    print(f"{error.code}: {error.message}", file=sys.stderr)
    trace.exception(cause)
    return EXIT_CODES.get(error.category, 1)


def _exit_code(code: object) -> int:
    """The exit status a SystemExit carries: None is 0, a message is 1."""
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    return 1
