from __future__ import annotations

import unittest
from importlib.metadata import version

from shad.testing import run


class VersionTests(unittest.TestCase):
    """
    Feature:    version
    Boundary:   command. `shad --version`.
                Contract: exit code + stdout + stderr.
    """

    def test_version_prints_the_installed_distribution_version(self) -> None:
        """
        Criterion:  version-prints-the-installed-distribution-version
          Given:    shad is installed.
          When:     `shad --version`.
          Then:     exit 0, stderr empty, stdout is `shad <version>`, where
                    <version> is the version the installed distribution
                    declares to pip.
        """
        result = run(["--version"])
        self.assertEqual((result.code, result.err), (0, ""))
        self.assertEqual(
            result.out,
            f"shad {version('shad')}\n",
            "an editable install keeps the version it was installed with; "
            "after a version change, run `make install`",
        )
