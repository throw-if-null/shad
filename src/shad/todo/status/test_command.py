from __future__ import annotations

from shad.cli import build_parser
from shad.shared.errors import ShadError
from shad.todo import store
from shad.todo.testing import TodoCase


class StatusTests(TodoCase):
    def test_accepts_a_prefix_and_rewrites_the_file(self) -> None:
        self._run("add", "Fix panel resize")
        self._run("status", "fix", "in-progress")
        text = store.item_path(self._dir(), "fix-panel-resize").read_text()
        self.assertIn("status: in-progress", text)

    def test_rejects_a_value_outside_the_enum_at_parse_time(self) -> None:
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["todo", "status", "x", "doing"])

    def test_unknown_key_is_an_error(self) -> None:
        with self.assertRaises(ShadError):
            self._run("status", "nothing", "done")
