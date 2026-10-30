"""Fixtures shared by the config slice's tests. Not imported by any command."""

from __future__ import annotations

import io
import tomllib
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from shad.cli import build_parser, cmd_config

CONFIG = """\
[defaults]
oc_position   = "top"
panel_percent = 35  # bundle width

[projects.kb]
path    = "{root}/kb"
session = "kb"

[projects.alvr.db]
path    = "{root}/alvr/db"
"""


class ConfigCase(unittest.TestCase):
    """A config with a bare and a grouped project, both directories present."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "kb").mkdir()
        (self.root / "alvr" / "db").mkdir(parents=True)
        self.path = self.root / "shad.toml"
        self.path.write_text(CONFIG.format(root=self.root))

    def _run(self, *argv: str) -> str:
        """Run `shad config <argv>` through the parser and the dispatcher; return stdout."""
        args = build_parser().parse_args(["config", *argv])
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            cmd_config(args, self.path)
        return buffer.getvalue()

    def _raw(self) -> dict:
        with self.path.open("rb") as fh:
            return tomllib.load(fh)
