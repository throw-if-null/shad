from __future__ import annotations

from shad.shared.errors import ShadError
from shad.todo import store
from shad.todo.testing import TodoCase

_MODULE = "shad.todo.edit.command"


class EditTests(TodoCase):
    def test_opens_the_item_file_in_the_editor(self) -> None:
        self._run("add", "Fix panel resize")
        with self._editor(None, module=_MODULE) as shown:
            out = self._run("edit", "fix")
        self.assertEqual(shown[0][0], store.item_path(self._dir(), "fix-panel-resize"))
        self.assertEqual(out, "")

    def test_reports_what_the_saved_file_gets_wrong(self) -> None:
        self._run("add", "Fix panel resize")
        path = store.item_path(self._dir(), "fix-panel-resize")
        broken = path.read_text().replace("status: todo", "status: doing")
        with self._editor(broken, module=_MODULE):
            out = self._run("edit", "fix")
        self.assertIn("unknown status 'doing'", out)

    def test_a_failing_editor_is_an_error(self) -> None:
        self._run("add", "Fix panel resize")
        with self._editor(None, module=_MODULE, status=1), self.assertRaises(ShadError) as ctx:
            self._run("edit", "fix")
        self.assertIn("status 1", str(ctx.exception))

    def test_unknown_key_is_an_error(self) -> None:
        with self.assertRaises(ShadError):
            self._run("edit", "nothing")
