from __future__ import annotations

import contextlib
import io
import unittest
from unittest.mock import patch

from shad.shared.config import load
from shad.shared.errors import ShadError
from shad.todo import store
from shad.todo.model import template
from shad.todo.testing import CONFIG, DRAFT, TodoCase


class AddTests(TodoCase):
    def test_add_writes_into_the_todo_dir(self) -> None:
        out = self._run("add", "Fix panel resize", "--label", "chore")
        self.assertIn("fix-panel-resize", out)
        self.assertTrue((self._dir() / "fix-panel-resize.md").exists())

    def test_the_project_flag_is_not_accepted(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self._run("add", "Elsewhere", "--project", "kb")

    def test_add_rejects_an_unknown_label(self) -> None:
        with self.assertRaises(ShadError):
            self._run("add", "x", "--label", "nope")

    def test_add_writes_under_the_configured_todo_path(self) -> None:
        notes = self.root / "notes"
        self.config.write_text(f'{CONFIG.format(root=self.root)}path = "{notes}"\n')
        self.cfg = load(self.config)
        self._run("add", "Fix panel resize")
        self.assertTrue((notes / "fix-panel-resize.md").exists())
        self.assertFalse(self._dir().exists())

    def test_add_with_a_title_never_opens_the_editor(self) -> None:
        with patch("shad.todo.add.command.subprocess.run") as run:
            self._run("add", "Plain")
        run.assert_not_called()


class AddInEditorTests(TodoCase):
    def test_creates_the_item_from_the_editor(self) -> None:
        with self._editor(DRAFT) as shown:
            out = self._run("add")
        self.assertIn("fix-panel-resize", out)
        draft, text = shown[0]
        self.assertEqual(draft.suffix, ".md")
        self.assertTrue(text.startswith("title: \n"))
        self.assertIn("# labels: chore, poc", text)
        self.assertFalse(draft.exists())

        item = store.read_item(self._dir(), "fix-panel-resize")
        self.assertEqual((item.title, item.status), ("Fix panel resize", "todo"))
        self.assertEqual(item.labels, ("chore",))
        self.assertEqual(item.body, "The resize handler fires twice.\n")
        self.assertNotIn("#", store.item_path(self._dir(), item.key).read_text())

    def test_label_flag_fills_in_the_template(self) -> None:
        with self._editor(DRAFT) as shown:
            self._run("add", "--label", "poc")
        self.assertIn("\nlabels: poc\n", shown[0][1])

    def test_label_flag_is_checked_before_the_editor_opens(self) -> None:
        with self._editor() as shown, self.assertRaises(ShadError):
            self._run("add", "--label", "nope")
        self.assertEqual(shown, [])

    def test_an_untouched_template_creates_nothing(self) -> None:
        with self._editor(None) as shown, self.assertRaises(ShadError) as ctx:
            self._run("add")
        self.assertEqual(shown[0][1], template([], ["chore", "poc"]))
        self.assertIn("no todo created", str(ctx.exception))
        self.assertEqual(store.keys(self._dir()), [])
        self.assertFalse(shown[0][0].exists())

    def test_an_invalid_draft_reopens_with_the_typed_text(self) -> None:
        bad = DRAFT.replace("labels: chore", "labels: nope")
        with self._editor(bad, DRAFT, confirm=(True,)) as shown:
            self._run("add")
        self.assertEqual(shown[1], (shown[0][0], bad))
        self.assertEqual(store.keys(self._dir()), ["fix-panel-resize"])
        self.assertFalse(shown[0][0].exists())

    def test_a_body_without_a_title_is_not_discarded(self) -> None:
        untitled = DRAFT.replace("Fix panel resize", "")
        with self._editor(untitled, DRAFT, confirm=(True,)) as shown:
            self._run("add")
        self.assertEqual(shown[1][1], untitled)
        self.assertEqual(store.keys(self._dir()), ["fix-panel-resize"])

    def test_declining_to_edit_again_keeps_the_draft(self) -> None:
        bad = DRAFT.replace("status: todo", "status: doing")
        with self._editor(bad, confirm=(False,)) as shown, self.assertRaises(ShadError) as ctx:
            self._run("add")
        draft = shown[0][0]
        self.addCleanup(draft.unlink, missing_ok=True)
        self.assertIn(str(draft), str(ctx.exception))
        self.assertEqual(draft.read_text(), bad)
        self.assertEqual(store.keys(self._dir()), [])

    def test_a_failing_editor_creates_nothing(self) -> None:
        with self._editor(DRAFT, status=1) as shown, self.assertRaises(ShadError) as ctx:
            self._run("add")
        self.assertIn("status 1", str(ctx.exception))
        self.assertEqual(store.keys(self._dir()), [])
        self.assertFalse(shown[0][0].exists())

    def test_without_a_terminal_does_not_open_an_editor(self) -> None:
        with (
            patch("shad.todo.add.command.sys.stdin") as stdin,
            patch("shad.todo.add.command.subprocess.run") as run,
            self.assertRaises(ShadError) as ctx,
        ):
            stdin.isatty.return_value = False
            self._run("add")
        self.assertIn("not a terminal", str(ctx.exception))
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
