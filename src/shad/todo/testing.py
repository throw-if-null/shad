"""Fixtures shared by the todo slices' tests. Not imported by any command."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from shad.testing import FakeEditor, Result, TmuxCase, run

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


def write_config(root: Path, config: Path) -> None:
    """CONFIG at *config*, with its three project directories under *root*."""
    for name in ("kb", "alvr/db", "alvr/api"):
        (root / name).mkdir(parents=True, exist_ok=True)
    config.write_text(CONFIG.format(root=root))


class TodoCase(unittest.TestCase):
    """
    A config with two labels, and the todo dir under a temporary data dir.

    Every run goes through the entry point with SHAD_CONFIG at self.config,
    HOME and XDG_DATA_HOME under self.root, and no editor set until
    `editor` installs one.
    """

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.config = self.root / "shad.toml"
        write_config(self.root, self.config)
        self.env: dict[str, str | None] = {
            "SHAD_CONFIG": str(self.config),
            "HOME": str(self.root),
            "XDG_DATA_HOME": str(self.root / "data"),
            "VISUAL": None,
            "EDITOR": None,
        }

    def _result(self, *argv: str) -> Result:
        """`shad todo <argv>` through the entry point."""
        return run(["todo", *argv], env=self.env)

    def _run(self, *argv: str) -> str:
        """A run that must exit 0 with nothing on stderr. Returns stdout."""
        result = self._result(*argv)
        self.assertEqual((result.code, result.err), (0, ""), result.out)
        return result.out

    def _fail(self, *argv: str) -> str:
        """A run that must exit 1 with nothing on stdout. Returns stderr."""
        result = self._result(*argv)
        self.assertEqual((result.code, result.out), (1, ""), result.err)
        return result.err

    def _dir(self) -> Path:
        """Where the items land: the data directory's todo dir."""
        return self.root / "data" / "shad" / "todo"

    def editor(self, *drafts: str | None, status: int = 0) -> FakeEditor:
        """Install a FakeEditor as EDITOR for the runs that follow."""
        fake = FakeEditor(self.root / "editor-state", drafts, status=status)
        self.env["EDITOR"] = fake.command
        return fake


class TodoTerminalCase(TmuxCase):
    """The same config, for the commands that need a terminal."""

    def setUp(self) -> None:
        super().setUp()
        write_config(self.root, self.config)
        self.todo_dir = self.data / "shad" / "todo"

    def editor(self, *drafts: str | None, status: int = 0) -> FakeEditor:
        """Install a FakeEditor as EDITOR for the panes that follow."""
        fake = FakeEditor(self.root / "editor-state", drafts, status=status)
        self.env["EDITOR"] = fake.command
        return fake

    def keys(self) -> list[str]:
        """The item keys on disk, as `shad todo list --keys` would print them."""
        if not self.todo_dir.is_dir():
            return []
        return sorted(path.stem for path in self.todo_dir.glob("*.md"))
