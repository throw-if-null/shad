from __future__ import annotations

from shad.shared.errors import ShadError
from shad.todo import store
from shad.todo.testing import TodoCase


class RemoveTests(TodoCase):
    def test_deletes_the_file(self) -> None:
        self._run("add", "Gone")
        self._run("rm", "go")
        self.assertEqual(store.keys(self._dir()), [])

    def test_unknown_key_is_an_error(self) -> None:
        with self.assertRaises(ShadError):
            self._run("rm", "nothing")
