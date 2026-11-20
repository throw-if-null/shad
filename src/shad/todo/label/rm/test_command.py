from __future__ import annotations

from shad.todo.testing import CONFIG, TodoCase


class LabelRmTests(TodoCase):
    """
    Feature:    todo/label/rm
    Boundary:   command. `shad todo label rm`, through main(argv) with
                SHAD_CONFIG and XDG_DATA_HOME under the test root. Contract:
                exit code + stdout + stderr + the config file. The in-use
                count reads the item files under the configured todo path.
    """

    def test_label_rm_removes_an_unused_label(self) -> None:
        """
        Criterion:  label-rm-removes-an-unused-label
          Given:    no item carries poc.
          When:     `shad todo label rm poc`.
          Then:     exit 0, and `shad todo label list` no longer lists poc.
        """
        self._run("label", "rm", "poc")
        self.assertEqual(self._run("label", "list"), "chore\n")

    def test_label_rm_refuses_a_label_in_use_unless_forced(self) -> None:
        """
        Criterion:  label-rm-refuses-a-label-in-use-unless-forced
          Given:    one item carries poc.
          When:     `shad todo label rm poc`, then the same with `--force`.
          Then:     the first exits 1 with stdout empty and stderr one line
                    `label_in_use: <non-empty>` counting one item; the second
                    exits 0 and removes the label.
        """
        self._run("add", "Uses it", "--label", "poc")
        self.assertIn("1 item(s)", self._fail("label", "rm", "poc", code="label_in_use"))
        self._run("label", "rm", "poc", "--force")
        self.assertEqual(self._run("label", "list"), "chore\n")

    def test_label_rm_counts_items_under_the_configured_todo_path(self) -> None:
        notes = self.root / "notes"
        self.config.write_text(f'{CONFIG.format(root=self.root)}path = "{notes}"\n')
        self._run("add", "Uses it", "--label", "poc")
        self.assertIn("1 item(s)", self._fail("label", "rm", "poc", code="label_in_use"))

    def test_label_rm_of_an_unknown_label_fails(self) -> None:
        """
        Criterion:  label-rm-of-an-unknown-label-fails
          When:     `shad todo label rm nope`.
          Then:     exit 1, stdout empty, stderr one line `no_such_label:
                    <non-empty>` naming the label.
        """
        self.assertIn("nope", self._fail("label", "rm", "nope", code="no_such_label"))
