from __future__ import annotations

import textwrap

from shad.todo.testing import TodoCase


class LabelAddTests(TodoCase):
    """
    Feature:    todo/label/add
    Boundary:   command. `shad todo label add`, through main(argv) with
                SHAD_CONFIG and XDG_DATA_HOME under the test root. Contract:
                exit code + stdout + stderr + the config file.
    """

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
