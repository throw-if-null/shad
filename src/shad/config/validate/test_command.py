from __future__ import annotations

from shad.config.testing import ConfigCase
from shad.shared.errors import ShadError


class ValidateTests(ConfigCase):
    def test_accepts_a_good_config(self) -> None:
        self._run("validate")

    def test_rejects_a_broken_config(self) -> None:
        self.path.write_text('[defaults]\noc_position = "sideways"\n')
        with self.assertRaises(ShadError):
            self._run("validate")
