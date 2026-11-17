from __future__ import annotations

from shad.config.testing import ConfigCase


class ShowTests(ConfigCase):
    """
    Feature:    config/show
    Boundary:   command. `shad config [show] [--raw]`, through main(argv) with
                SHAD_CONFIG set. Contract: exit code + stdout + stderr.
    """

    def test_show_raw_prints_the_file_verbatim(self) -> None:
        """
        Criterion:  show-raw-prints-the-file-verbatim
          Given:    shad.toml holds a defaults block and two projects.
          When:     `shad config show --raw`.
          Then:     exit 0, stderr empty, stdout is the file text byte for byte.
        """
        self.assertEqual(self._run("show", "--raw"), self.path.read_text())

    def test_show_renders_every_section(self) -> None:
        """
        Criterion:  show-renders-every-section
          Given:    shad.toml holds a defaults block and the projects kb and
                    alvr db.
          When:     `shad config show`.
          Then:     exit 0, stderr empty, stdout names the file, each default,
                    each project and the todo settings.
        """
        out = self._run("show")
        for text in (str(self.path), "oc_position", "panel_percent", "kb", "alvr db", "labels"):
            self.assertIn(text, out)

    def test_show_is_the_default_action(self) -> None:
        """
        Criterion:  show-is-the-default-action
          When:     `shad config`.
          Then:     exit 0, and stdout is what `shad config show` prints.
        """
        self.assertEqual(self._run(), self._run("show"))

    def test_an_unknown_action_is_a_usage_error(self) -> None:
        """
        Criterion:  unknown-action-is-a-usage-error
          When:     `shad config frobnicate`.
          Then:     exit 2, stdout empty, stderr names `frobnicate`.
        """
        result = self._result("frobnicate")
        self.assertEqual((result.code, result.out), (2, ""))
        self.assertIn("frobnicate", result.err)
