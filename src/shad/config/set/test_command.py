from __future__ import annotations

from unittest.mock import patch

from shad.config.testing import ConfigCase
from shad.shared.errors import ShadError


class SetTests(ConfigCase):
    def test_updates_the_value_and_keeps_the_comment(self) -> None:
        self._run("set", "defaults.panel_percent", "42")
        self.assertEqual(self._raw()["defaults"]["panel_percent"], 42)
        self.assertIn("panel_percent = 42  # bundle width", self.path.read_text())

    def test_normalises_enum_case(self) -> None:
        self._run("set", "defaults.harness", "CLAUDE")
        self.assertEqual(self._raw()["defaults"]["harness"], "claude")

    def test_rejects_an_invalid_enum(self) -> None:
        with self.assertRaises(ShadError) as ctx:
            self._run("set", "defaults.oc_position", "sideways")
        self.assertIn("must be one of", str(ctx.exception))
        self.assertEqual(self._raw()["defaults"]["oc_position"], "top")

    def test_rejects_a_percent_out_of_range(self) -> None:
        with self.assertRaises(ShadError):
            self._run("set", "defaults.split_percent", "200")

    def test_rejects_a_non_integer_percent(self) -> None:
        with self.assertRaises(ShadError):
            self._run("set", "defaults.panel_percent", "wide")

    def test_rejects_a_zero_todo_percent(self) -> None:
        with self.assertRaises(ShadError):
            self._run("set", "defaults.todo_percent", "0")

    def test_writes_a_panel_switch_as_a_toml_boolean(self) -> None:
        self._run("set", "defaults.git_panel", "False")
        self.assertIs(self._raw()["defaults"]["git_panel"], False)
        self.assertIn("git_panel = false", self.path.read_text())

    def test_rejects_a_panel_switch_that_is_not_true_or_false(self) -> None:
        with self.assertRaises(ShadError) as ctx:
            self._run("set", "defaults.todo_panel", "off")
        self.assertIn("true or false", str(ctx.exception))

    def test_rejects_an_unknown_key_without_force(self) -> None:
        with self.assertRaises(ShadError) as ctx:
            self._run("set", "defaults.nope", "1")
        self.assertIn("unknown key", str(ctx.exception))

    def test_a_forced_unknown_key_infers_its_type(self) -> None:
        self._run("set", "--force", "defaults.nope", "7")
        self.assertEqual(self._raw()["defaults"]["nope"], 7)

    def test_rejects_a_missing_project_path(self) -> None:
        with self.assertRaises(ShadError) as ctx:
            self._run("set", "projects.kb.path", str(self.root / "gone"))
        self.assertIn("path does not exist", str(ctx.exception))

    def test_a_forced_missing_project_path_is_written(self) -> None:
        target = self.root / "gone"
        self._run("set", "--force", "projects.kb.path", str(target))
        self.assertEqual(self._raw()["projects"]["kb"]["path"], str(target))

    def test_expands_user_in_paths(self) -> None:
        with patch.dict("os.environ", {"HOME": str(self.root)}):
            self._run("set", "projects.kb.path", "~/kb")
        self.assertEqual(self._raw()["projects"]["kb"]["path"], str(self.root / "kb"))

    def test_todo_path_creates_the_todo_table(self) -> None:
        notes = self.root / "notes"
        notes.mkdir()
        self._run("set", "todo.path", str(notes))
        self.assertEqual(self._raw()["todo"]["path"], str(notes))
        self.assertEqual(self._run("get", "todo.path").strip(), str(notes))

    def test_rejects_a_missing_todo_path(self) -> None:
        with self.assertRaises(ShadError) as ctx:
            self._run("set", "todo.path", str(self.root / "gone"))
        self.assertIn("path does not exist", str(ctx.exception))

    def test_creates_a_new_project_table(self) -> None:
        fresh = self.root / "fresh"
        fresh.mkdir()
        self._run("set", "projects.fresh.path", str(fresh))
        self.assertEqual(self._raw()["projects"]["fresh"]["path"], str(fresh))

    def test_refuses_a_path_another_project_already_uses(self) -> None:
        # store.commit validates through load() before replacing the file, so
        # the duplicate-directory rule is enforced on writes without extra wiring.
        before = self.path.read_text()
        with self.assertRaises(ShadError) as ctx:
            self._run("set", "projects.fresh.path", str(self.root / "kb"))
        self.assertIn("both point at", str(ctx.exception))
        self.assertEqual(self.path.read_text(), before)

    def test_refuses_to_point_a_project_at_another_projects_path(self) -> None:
        before = self.path.read_text()
        with self.assertRaises(ShadError) as ctx:
            self._run("set", "--force", "projects.alvr.db.path", str(self.root / "kb"))
        self.assertIn("both point at", str(ctx.exception))
        self.assertEqual(self.path.read_text(), before)

    def test_refuses_a_project_without_a_path(self) -> None:
        before = self.path.read_text()
        with self.assertRaises(ShadError) as ctx:
            self._run("set", "projects.grp.sub.session", "x")
        self.assertIn("set its 'path' first", str(ctx.exception))
        self.assertEqual(self.path.read_text(), before)

    def test_keeps_the_file_mode(self) -> None:
        self.path.chmod(0o600)
        self._run("set", "defaults.panel_percent", "40")
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_leaves_no_temporary_files_behind(self) -> None:
        self._run("set", "defaults.panel_percent", "40")
        self.assertEqual(
            [p.name for p in self.root.iterdir() if p.name.startswith(".shad.toml")], []
        )
