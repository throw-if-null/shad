from __future__ import annotations

from shad.config.testing import ConfigCase


class PathTests(ConfigCase):
    """
    Feature:    config/path
    Boundary:   command. `shad config path`, through main(argv) with
                SHAD_CONFIG set. Contract: exit code + stdout + stderr.
    """

    def test_path_prints_the_resolved_config_file(self) -> None:
        """
        Criterion:  path-prints-the-resolved-config-file
          Given:    SHAD_CONFIG names <tmp>/shad.toml.
          When:     `shad config path`.
          Then:     exit 0, stderr empty, stdout is that path and a newline.
        """
        self.assertEqual(self._run("path"), f"{self.path}\n")

    def test_path_needs_no_file(self) -> None:
        """
        Criterion:  path-needs-no-file
          Given:    SHAD_CONFIG names a file that does not exist.
          When:     `shad config path`.
          Then:     exit 0, and stdout is that path.
        """
        self.path.unlink()
        self.assertEqual(self._run("path"), f"{self.path}\n")
