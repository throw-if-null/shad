from __future__ import annotations

from shad.todo import store
from shad.todo.testing import TodoCase


class ListTests(TodoCase):
    def test_keys_prints_one_key_per_line(self) -> None:
        self._run("add", "Beta")
        self._run("add", "Alpha")
        self.assertEqual(self._run("list", "--keys"), "alpha\nbeta\n")

    def test_renders_every_item_and_flags_problems(self) -> None:
        self._run("add", "Good one", "--label", "poc")
        path = store.item_path(self._dir(), "good-one")
        path.write_text(path.read_text().replace("status: todo", "status: doing"))
        out = self._run("list")
        self.assertIn("good-one", out)
        self.assertIn("Good one", out)
        self.assertIn("unknown status 'doing'", out)

    def test_nothing_says_so(self) -> None:
        self.assertIn("no todos", self._run("list"))
