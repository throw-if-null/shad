"""Fixtures shared by the todo slices' tests. Not imported by any command."""

from __future__ import annotations

import contextlib
import io
import subprocess
import unittest
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from shad.cli import build_parser, cmd_todo
from shad.shared.config import load

CONFIG = """\
[defaults]
harness = "claude"   # keep me

[projects.kb]
path = "{root}/kb"

[projects.alvr.db]
path = "{root}/alvr/db"

[projects.alvr.api]
path = "{root}/alvr/api"

# the vocabulary
[todo]
labels = ["chore", "poc"]   # trailing comment
"""

DRAFT = """\
title: Fix panel resize
status: todo
labels: chore
# a help line

The resize handler fires twice.
"""


class TodoCase(unittest.TestCase):
    """A config with two labels, and the todo dir under a temporary data dir."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        for name in ("kb", "alvr/db", "alvr/api", "data"):
            (self.root / name).mkdir(parents=True)
        self.config = self.root / "shad.toml"
        self.config.write_text(CONFIG.format(root=self.root))
        self.cfg = load(self.config)

        patcher = patch("shad.todo.store.default_data_dir", return_value=self.root / "data")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self, *argv: str) -> str:
        """Run `shad todo <argv>` through the parser and the dispatcher; return stdout."""
        args = build_parser().parse_args(["todo", *argv])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cmd_todo(self.cfg, args, path=self.config)
        return out.getvalue()

    def _dir(self) -> Path:
        return self.root / "data" / "todo"

    @contextlib.contextmanager
    def _editor(
        self,
        *drafts: str | None,
        module: str = "shad.todo.add.command",
        confirm: tuple[bool, ...] = (),
        status: int = 0,
    ) -> Iterator[list[tuple[Path, str]]]:
        """
        A fake editor on a terminal, patched into *module*. Each run records
        the file it was given and the text it found there, then saves the next
        of *drafts* over it; None leaves the file as it was.
        """
        shown: list[tuple[Path, str]] = []
        queue = list(drafts)

        def edit(command: list[str], check: bool) -> subprocess.CompletedProcess[bytes]:
            path = Path(command[-1])
            shown.append((path, path.read_text()))
            draft = queue.pop(0)
            if draft is not None:
                path.write_text(draft)
            return subprocess.CompletedProcess(command, status)

        with (
            patch(f"{module}.resolve_editor", return_value="nano"),
            patch(f"{module}.subprocess.run", side_effect=edit),
            patch("shad.todo.add.command.sys.stdin") as stdin,
            patch("shad.todo.add.command.Confirm.ask", side_effect=list(confirm)),
        ):
            stdin.isatty.return_value = True
            yield shown
