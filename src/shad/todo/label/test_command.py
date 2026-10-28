from __future__ import annotations

import textwrap

from shad.shared.config import load
from shad.shared.errors import ShadError
from shad.todo.testing import CONFIG, TodoCase


class LabelTests(TodoCase):
    def test_list_prints_the_vocabulary(self) -> None:
        self.assertEqual(self._run("label", "list"), "chore\npoc\n")

    def test_add_appends_and_keeps_comments(self) -> None:
        self._run("label", "add", "docs")
        text = self.config.read_text()
        self.assertIn('labels = ["chore", "poc", "docs"]   # trailing comment', text)
        self.assertIn("# the vocabulary", text)
        self.assertIn('harness = "claude"   # keep me', text)
        self.assertEqual(load(self.config).todo_labels, ["chore", "poc", "docs"])

    def test_add_creates_the_table_when_missing(self) -> None:
        self.config.write_text(textwrap.dedent(f"""\
            [projects.kb]
            path = "{self.root}/kb"
            """))
        self.cfg = load(self.config)
        self._run("label", "add", "chore")
        self.assertEqual(load(self.config).todo_labels, ["chore"])

    def test_add_rejects_duplicates_and_bad_names(self) -> None:
        with self.assertRaises(ShadError):
            self._run("label", "add", "chore")
        with self.assertRaises(ShadError):
            self._run("label", "add", "Not Valid")

    def test_rm_removes_an_unused_label(self) -> None:
        self._run("label", "rm", "poc")
        self.assertEqual(load(self.config).todo_labels, ["chore"])

    def test_rm_refuses_a_label_in_use_unless_forced(self) -> None:
        self._run("add", "Uses it", "--label", "poc")
        with self.assertRaises(ShadError) as ctx:
            self._run("label", "rm", "poc")
        self.assertIn("1 item(s)", str(ctx.exception))
        self._run("label", "rm", "poc", "--force")
        self.assertEqual(load(self.config).todo_labels, ["chore"])

    def test_rm_counts_items_under_the_configured_todo_path(self) -> None:
        notes = self.root / "notes"
        self.config.write_text(f'{CONFIG.format(root=self.root)}path = "{notes}"\n')
        self.cfg = load(self.config)
        self._run("add", "Uses it", "--label", "poc")
        with self.assertRaises(ShadError) as ctx:
            self._run("label", "rm", "poc")
        self.assertIn("1 item(s)", str(ctx.exception))

    def test_rm_of_an_unknown_label_is_an_error(self) -> None:
        with self.assertRaises(ShadError):
            self._run("label", "rm", "nope")
