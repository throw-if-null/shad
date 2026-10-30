from __future__ import annotations

from unittest.mock import patch

from shad.config.testing import ConfigCase
from shad.shared.errors import ShadError


class GetTests(ConfigCase):
    def test_prints_a_scalar_value(self) -> None:
        self.assertEqual(self._run("get", "defaults.panel_percent").strip(), "35")

    def test_expands_a_table_into_dotted_lines(self) -> None:
        output = self._run("get", "projects.alvr")
        self.assertIn(f'projects.alvr.db.path = "{self.root}/alvr/db"', output)

    def test_falls_back_to_the_effective_default(self) -> None:
        self.path.write_text(f'[projects.kb]\npath = "{self.root}/kb"\n')
        self.assertEqual(self._run("get", "defaults.oc_position").strip(), "top")

    def test_prints_a_panel_switch_in_toml_spelling(self) -> None:
        self.assertEqual(self._run("get", "defaults.git_panel").strip(), "true")
        self.path.write_text(self.path.read_text().replace(
            "[defaults]\n", "[defaults]\ntodo_panel = false\n"
        ))
        self.assertEqual(self._run("get", "defaults.todo_panel").strip(), "false")

    def test_falls_back_to_the_derived_session(self) -> None:
        self.assertEqual(self._run("get", "projects.alvr.db.session").strip(), "alvr-db")

    def test_falls_back_to_the_default_harness(self) -> None:
        self.assertEqual(self._run("get", "projects.kb.harness").strip(), "opencode")

    def test_falls_back_to_the_default_todo_path(self) -> None:
        with patch("shad.todo.store.default_data_dir", return_value=self.root / "data"):
            output = self._run("get", "todo.path")
        self.assertEqual(output.strip(), str(self.root / "data" / "todo"))

    def test_unknown_project_raises(self) -> None:
        with self.assertRaises(ShadError):
            self._run("get", "projects.nope.session")

    def test_unknown_key_raises(self) -> None:
        with self.assertRaises(ShadError) as ctx:
            self._run("get", "defaults.nope")
        self.assertIn("key not found", str(ctx.exception))

    def test_missing_file_reports_the_init_hint(self) -> None:
        self.path.unlink()
        with self.assertRaises(ShadError) as ctx:
            self._run("get", "defaults.harness")
        self.assertIn("shad init", str(ctx.exception))
