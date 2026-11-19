from __future__ import annotations

from shad.todo.testing import TodoCase


class StatusTests(TodoCase):
    """
    Feature:    todo/status
    Boundary:   command. `shad todo status KEY STATUS`, through main(argv)
                with SHAD_CONFIG and XDG_DATA_HOME under the test root.
                Contract: exit code + stdout + stderr + the item file.
    """

    def test_status_accepts_a_prefix_and_rewrites_the_file(self) -> None:
        """
        Criterion:  status-accepts-a-prefix-and-rewrites-the-file
          Given:    the item fix-panel-resize exists with status todo.
          When:     `shad todo status fix in-progress`.
          Then:     exit 0, stderr empty, stdout names the key and the new
                    status, and the item file reads `status: in-progress`.
        """
        self._run("add", "Fix panel resize")
        out = self._run("status", "fix", "in-progress")
        self.assertIn("fix-panel-resize", out)
        self.assertIn("in-progress", out)
        text = (self._dir() / "fix-panel-resize.md").read_text()
        self.assertIn("status: in-progress", text)

    def test_status_rejects_a_value_outside_the_enum(self) -> None:
        """
        Criterion:  status-rejects-a-value-outside-the-enum
          When:     `shad todo status x doing`.
          Then:     exit 2, stdout empty, stderr lists the allowed values.
        """
        result = self._result("status", "x", "doing")
        self.assertEqual((result.code, result.out), (2, ""))
        self.assertIn("in-progress", result.err)

    def test_status_of_an_unknown_key_fails(self) -> None:
        """
        Criterion:  status-of-an-unknown-key-fails
          Given:    no item exists.
          When:     `shad todo status nothing done`.
          Then:     exit 1, stdout empty, stderr one line `no_such_todo:
                    <non-empty>` naming the key.
        """
        self.assertIn("nothing", self._fail("status", "nothing", "done", code="no_such_todo"))
