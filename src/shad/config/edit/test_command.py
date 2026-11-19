from __future__ import annotations

from shad.config.testing import ConfigCase


class EditTests(ConfigCase):
    """
    Feature:    config/edit
    Boundary:   command. `shad config edit`, through main(argv) with
                SHAD_CONFIG set and EDITOR naming a real command. Contract:
                exit code + stdout + stderr + the file.
    """

    def test_edit_runs_the_editor_on_the_file_then_validates(self) -> None:
        """
        Criterion:  edit-runs-the-editor-on-the-file-then-validates
          Given:    panel_percent is 35, and EDITOR is a command that
                    rewrites 35 to 45 in the file it is given.
          When:     `shad config edit`.
          Then:     exit 0, stderr empty, stdout says the file is valid, and
                    `shad config get defaults.panel_percent` prints 45.
        """
        out = self._run("edit", env={"EDITOR": "sed -i s/35/45/"})
        self.assertIn("is valid", out)
        self.assertEqual(self._run("get", "defaults.panel_percent"), "45\n")

    def test_edit_creates_a_missing_file(self) -> None:
        """
        Criterion:  edit-creates-a-missing-file
          Given:    the config file does not exist, and EDITOR is `true`.
          When:     `shad config edit`.
          Then:     exit 0, the file exists, and stdout says it is valid.
        """
        self.path.unlink()
        out = self._run("edit", env={"EDITOR": "true"})
        self.assertTrue(self.path.exists())
        self.assertIn("is valid", out)

    def test_edit_reports_an_editor_failure(self) -> None:
        """
        Criterion:  edit-reports-an-editor-failure
          Given:    EDITOR is `false`.
          When:     `shad config edit`.
          Then:     exit 1, stdout empty, stderr one line `editor_failed:
                    <non-empty>` that says the editor exited.
        """
        self.assertIn(
            "editor exited", self._fail("edit", code="editor_failed", env={"EDITOR": "false"})
        )

    def test_edit_reports_a_result_that_does_not_load(self) -> None:
        """
        Criterion:  edit-reports-a-result-that-does-not-load
          Given:    EDITOR is a command that sets oc_position to "sideways".
          When:     `shad config edit`.
          Then:     exit 1, stdout empty, stderr one line `invalid_config:
                    <non-empty>` that names `sideways`, and the edited file is
                    kept as the editor left it.
        """
        err = self._fail("edit", code="invalid_config", env={"EDITOR": "sed -i s/top/sideways/"})
        self.assertIn("sideways", err)
        self.assertIn('oc_position   = "sideways"', self.path.read_text())

    def test_edit_prefers_visual_to_editor(self) -> None:
        """
        Criterion:  edit-prefers-visual-to-editor
          Given:    VISUAL is `false` and EDITOR is `true`.
          When:     `shad config edit`.
          Then:     exit 1 with `editor_failed`: the VISUAL command ran.
        """
        self._fail("edit", code="editor_failed", env={"VISUAL": "false", "EDITOR": "true"})
