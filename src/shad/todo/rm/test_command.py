from __future__ import annotations

from shad.todo.testing import TodoCase


class RemoveTests(TodoCase):
    """
    Feature:    todo/rm
    Boundary:   command. `shad todo rm KEY`, through main(argv) with
                SHAD_CONFIG and XDG_DATA_HOME under the test root. Contract:
                exit code + stdout + stderr + the todo directory.
    """

    def test_rm_deletes_the_item(self) -> None:
        """
        Criterion:  rm-deletes-the-item
          Given:    the item gone exists.
          When:     `shad todo rm go`.
          Then:     exit 0, stderr empty, stdout names the key, and
                    `shad todo list --keys` prints nothing.
        """
        self._run("add", "Gone")
        self.assertIn("gone", self._run("rm", "go"))
        self.assertEqual(self._run("list", "--keys"), "")

    def test_rm_of_an_unknown_key_fails(self) -> None:
        """
        Criterion:  rm-of-an-unknown-key-fails
          When:     `shad todo rm nothing`.
          Then:     exit 1, stdout empty, stderr one line `no_such_todo:
                    <non-empty>` naming the key.
        """
        self.assertIn("nothing", self._fail("rm", "nothing", code="no_such_todo"))
