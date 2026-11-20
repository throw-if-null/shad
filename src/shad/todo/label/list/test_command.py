from __future__ import annotations

from shad.todo.testing import TodoCase


class LabelListTests(TodoCase):
    """
    Feature:    todo/label/list
    Boundary:   command. `shad todo label list`, through main(argv) with
                SHAD_CONFIG and XDG_DATA_HOME under the test root. Contract:
                exit code + stdout + stderr. `label list` is a published
                surface: the completion script parses it as one plain label
                per line.
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
