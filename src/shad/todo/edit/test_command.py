from __future__ import annotations

from shad.todo.testing import TodoCase


class EditTests(TodoCase):
    """
    Feature:    todo/edit
    Boundary:   command. `shad todo edit KEY`, through main(argv) with
                SHAD_CONFIG and XDG_DATA_HOME under the test root and EDITOR
                a real program. Contract: exit code + stdout + stderr.
    """

    def test_edit_opens_the_item_file_in_the_editor(self) -> None:
        """
        Criterion:  edit-opens-the-item-file-in-the-editor
          Given:    the item fix-panel-resize exists.
          When:     `shad todo edit fix`.
          Then:     exit 0, stdout and stderr empty, and the editor received
                    the item's file.
        """
        self._run("add", "Fix panel resize")
        editor = self.editor(None)
        self.assertEqual(self._run("edit", "fix"), "")
        self.assertEqual(editor.shown()[0][0], self._dir() / "fix-panel-resize.md")

    def test_edit_reports_what_the_saved_file_gets_wrong(self) -> None:
        """
        Criterion:  edit-reports-what-the-saved-file-gets-wrong
          Given:    EDITOR saves the item with an unknown status.
          When:     `shad todo edit fix`.
          Then:     exit 0, stdout empty, and stderr names the unknown
                    status.
        """
        self._run("add", "Fix panel resize")
        path = self._dir() / "fix-panel-resize.md"
        self.editor(path.read_text().replace("status: todo", "status: doing"))
        result = self._result("edit", "fix")
        self.assertEqual((result.code, result.out), (0, ""), result.err)
        self.assertIn("unknown status 'doing'", result.err)

    def test_edit_reports_a_failing_editor(self) -> None:
        """
        Criterion:  edit-reports-a-failing-editor
          Given:    EDITOR exits with status 1.
          When:     `shad todo edit fix`.
          Then:     exit 1, stdout empty, stderr one line `editor_failed:
                    <non-empty>` naming the status.
        """
        self._run("add", "Fix panel resize")
        self.editor(None, status=1)
        self.assertIn("status 1", self._fail("edit", "fix", code="editor_failed"))

    def test_edit_of_an_unknown_key_fails(self) -> None:
        """
        Criterion:  edit-of-an-unknown-key-fails
          When:     `shad todo edit nothing`.
          Then:     exit 1, stdout empty, stderr one line `no_such_todo:
                    <non-empty>` naming the key.
        """
        self.assertIn("nothing", self._fail("edit", "nothing", code="no_such_todo"))
