from __future__ import annotations

import argparse

from shad.cli import cmd_config
from shad.config.testing import ConfigCase
from shad.shared.errors import ShadError


class ShowTests(ConfigCase):
    def test_raw_prints_the_file_verbatim(self) -> None:
        self.assertEqual(self._run("show", "--raw"), self.path.read_text())

    def test_renders_without_error(self) -> None:
        self._run("show")

    def test_is_the_default_action(self) -> None:
        self._run()

    def test_an_unknown_action_is_an_error(self) -> None:
        with self.assertRaises(ShadError):
            cmd_config(argparse.Namespace(config_action="frobnicate"), self.path)
