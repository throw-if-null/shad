from __future__ import annotations

import textwrap

from shad.todo.testing import CONFIG, TodoCase


class LabelTests(TodoCase):
    """
    Feature:    todo/label
    Boundary:   command. `shad todo label add|rm|list`, through main(argv)
                with SHAD_CONFIG and XDG_DATA_HOME under the test root.
                Contract: exit code + stdout + stderr + the config file.
                `label list` is a published surface: the completion script
                parses it as one plain label per line.
    """

    def test_label_list_prints_the_vocabulary_one_per_line(self) -> None:
        """
        Criterion:  label-list-prints-the-vocabulary-one-per-line
          Given:    shad.toml lists the labels chore and poc.
          When:     `shad todo label list`.
          Then:     exit 0, stderr empty, stdout is `chore` and `poc`, one
                    per line, in file order, with no other text.
        """
        self.assertEqual(self._run("label", "list"), "chore\npoc\n")

    def test_label_add_appends_and_keeps_the_file_layout(self) -> None:
        """
        Criterion:  label-add-appends-and-keeps-the-file-layout
          When:     `shad todo label add docs`.
          Then:     exit 0, `shad todo label list` ends with docs, and the
                    comments in the file survive.
        """
        self._run("label", "add", "docs")
        self.assertEqual(self._run("label", "list"), "chore\npoc\ndocs\n")
        text = self.config.read_text()
        self.assertIn('labels = ["chore", "poc", "docs"]   # trailing comment', text)
        self.assertIn("# the vocabulary", text)
        self.assertIn('harness = "claude"   # keep me', text)

    def test_label_add_creates_the_table_when_missing(self) -> None:
        self.config.write_text(textwrap.dedent(f"""\
            [projects.kb]
            path = "{self.root}/kb"
            """))
        self._run("label", "add", "chore")
        self.assertEqual(self._run("label", "list"), "chore\n")

    def test_label_add_rejects_a_duplicate_and_a_bad_name(self) -> None:
        """
        Criterion:  label-add-rejects-a-duplicate-and-a-bad-name
          When:     `shad todo label add chore`, and
                    `shad todo label add "Not Valid"`.
          Then:     each exits 1 with stdout empty; the first is one line
                    `label_exists: <non-empty>`, the second one line
                    `invalid_label: <non-empty>`, each naming the label, and
                    the vocabulary is unchanged.
        """
        self.assertIn("chore", self._fail("label", "add", "chore", code="label_exists"))
        self.assertIn("Not Valid", self._fail("label", "add", "Not Valid", code="invalid_label"))
        self.assertEqual(self._run("label", "list"), "chore\npoc\n")

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
