from __future__ import annotations

from shad.config.testing import ConfigCase


class PathTests(ConfigCase):
    def test_prints_the_config_path(self) -> None:
        self.assertEqual(self._run("path").strip(), str(self.path))
