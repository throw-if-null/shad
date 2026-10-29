from __future__ import annotations

from shad.config.testing import ConfigCase
from shad.shared.errors import ShadError


class UnsetTests(ConfigCase):
    def test_removes_a_key(self) -> None:
        self._run("unset", "projects.kb.session")
        self.assertNotIn("session", self._raw()["projects"]["kb"])

    def test_removes_a_whole_project(self) -> None:
        self._run("unset", "projects.kb")
        self.assertNotIn("kb", self._raw()["projects"])

    def test_guards_a_required_project_path(self) -> None:
        with self.assertRaises(ShadError) as ctx:
            self._run("unset", "projects.kb.path")
        self.assertIn("is required", str(ctx.exception))
        self.assertIn(f"{self.root}/kb", self.path.read_text())

    def test_a_forced_required_key_is_removed(self) -> None:
        self._run("unset", "projects.kb.session")
        self._run("unset", "--force", "projects.kb.path")
        self.assertEqual(self._raw()["projects"]["kb"], {})

    def test_a_forced_key_is_still_refused_when_it_breaks_the_config(self) -> None:
        before = self.path.read_text()
        with self.assertRaises(ShadError) as ctx:
            self._run("unset", "--force", "projects.kb.path")
        self.assertIn("resulting config is invalid", str(ctx.exception))
        self.assertEqual(self.path.read_text(), before)

    def test_an_unknown_key_raises(self) -> None:
        with self.assertRaises(ShadError):
            self._run("unset", "projects.nothere")
