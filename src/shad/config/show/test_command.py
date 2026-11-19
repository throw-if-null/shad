from __future__ import annotations

import json

from shad.config.testing import ConfigCase


class ShowTests(ConfigCase):
    """
    Feature:    config/show
    Boundary:   command. `shad config [show] [--raw | --json]`, through
                main(argv) with SHAD_CONFIG set. Contract: exit code +
                stdout + stderr.
    """

    def test_show_json_carries_every_section(self) -> None:
        """
        Criterion:  show-json-carries-every-section
          Given:    shad.toml sets oc_position and panel_percent and holds
                    the projects kb and alvr db.
          When:     `shad config show --json`, and `shad config --json`.
          Then:     each exits 0 with stderr empty, and stdout is one JSON
                    object with `path`, `defaults` (each setting's `value`
                    and `origin`: set for panel_percent, default for
                    harness), `projects` (kb then alvr db, each with
                    `project` and `exists` true) and `todo` (`labels`,
                    `path`, `path_set` false).
        """
        for argv in (("show", "--json"), ("--json",)):
            with self.subTest(argv=argv):
                document = json.loads(self._run(*argv))
                self.assertEqual(document["path"], str(self.path))
                self.assertEqual(document["defaults"]["panel_percent"], {"value": 35, "origin": "set"})
                self.assertEqual(
                    document["defaults"]["harness"], {"value": "opencode", "origin": "default"}
                )
                self.assertEqual(
                    [(p["project"]["key"], p["project"]["group"], p["exists"]) for p in document["projects"]],
                    [("kb", None, True), ("db", "alvr", True)],
                )
                self.assertEqual(document["todo"]["labels"], [])
                self.assertFalse(document["todo"]["path_set"])
                self.assertTrue(document["todo"]["path"].endswith("/shad/todo"))

    def test_show_raw_with_json_is_a_usage_error(self) -> None:
        """
        Criterion:  show-raw-with-json-is-a-usage-error
          When:     `shad config show --raw --json`.
          Then:     exit 2, stdout empty, stderr is one line
                    `no_json: <non-empty>`.
        """
        result = self._result("show", "--raw", "--json")
        self.assertEqual((result.code, result.out), (2, ""), result.err)
        self.assertRegex(result.err, r"^no_json: .+\n$")

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
