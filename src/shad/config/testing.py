"""Fixtures shared by the config slice's tests. Not imported by any command."""

from __future__ import annotations

import tomllib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from shad.testing import Result, run

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
    """
    A config with a bare and a grouped project, both directories present.

    Every run goes through the entry point with SHAD_CONFIG at self.path,
    HOME and the data directory under self.root, and no editor set.
    """

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "kb").mkdir()
        (self.root / "alvr" / "db").mkdir(parents=True)
        self.path = self.root / "shad.toml"
        self.path.write_text(CONFIG.format(root=self.root))
        self.env: dict[str, str | None] = {
            "SHAD_CONFIG": str(self.path),
            "HOME": str(self.root),
            "XDG_DATA_HOME": str(self.root / "data"),
            "VISUAL": None,
            "EDITOR": None,
        }

    def _result(self, *argv: str, env: dict[str, str | None] | None = None) -> Result:
        """`shad config <argv>` through the entry point."""
        return run(["config", *argv], env={**self.env, **(env or {})})

    def _run(self, *argv: str, env: dict[str, str | None] | None = None) -> str:
        """A run that must exit 0 with nothing on stderr. Returns stdout."""
        result = self._result(*argv, env=env)
        self.assertEqual((result.code, result.err), (0, ""), result.out)
        return result.out

    def _fail(self, *argv: str, env: dict[str, str | None] | None = None) -> str:
        """A run that must exit 1 with nothing on stdout. Returns stderr."""
        result = self._result(*argv, env=env)
        self.assertEqual((result.code, result.out), (1, ""), result.err)
        return result.err

    def _raw(self) -> dict:
        with self.path.open("rb") as fh:
            return tomllib.load(fh)
