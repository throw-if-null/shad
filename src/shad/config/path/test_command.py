from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from shad.config.testing import ConfigCase
from shad.testing import run


class PathTests(ConfigCase):
    def test_prints_the_config_path(self) -> None:
        self.assertEqual(self._run("path").strip(), str(self.path))


class PathContractTests(unittest.TestCase):
    def test_path_prints_the_resolved_config_file(self) -> None:
        """
        Feature:    config/path
        Boundary:   command. `shad config path`, run through main(argv) with
                    SHAD_CONFIG set. Contract: exit code + stdout + stderr.
        Criterion:  path-prints-the-resolved-config-file
          Given:    SHAD_CONFIG names <tmp>/shad.toml.
          When:     `shad config path`.
          Then:     exit 0, stderr empty, stdout is that path and a newline.
        """
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "shad.toml"
            result = run(["config", "path"], env={"SHAD_CONFIG": str(path)})
        self.assertEqual(result.code, 0)
        self.assertEqual(result.err, "")
        self.assertEqual(result.out, f"{path}\n")
