from __future__ import annotations

from shad.config.testing import ConfigCase


class KeysTests(ConfigCase):
    def test_lists_defaults_and_every_project_field(self) -> None:
        keys = self._run("keys").split()
        self.assertIn("defaults.oc_position", keys)
        self.assertIn("defaults.harness", keys)
        self.assertIn("defaults.git_panel", keys)
        self.assertIn("defaults.todo_panel", keys)
        self.assertIn("projects.kb.session", keys)
        self.assertIn("projects.alvr.db.harness", keys)
        self.assertIn("todo.path", keys)
