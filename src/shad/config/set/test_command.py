from __future__ import annotations

from shad.config.testing import ConfigCase


class SetTests(ConfigCase):
    """
    Feature:    config/set
    Boundary:   command. `shad config set KEY VALUE [--force]`, through
                main(argv) with SHAD_CONFIG set and HOME at the test root.
                Contract: exit code + stdout + stderr + the file.
    """

    def test_set_writes_the_value_and_keeps_the_file_layout(self) -> None:
        """
        Criterion:  set-writes-the-value-and-keeps-the-file-layout
          Given:    shad.toml sets `panel_percent = 35  # bundle width`.
          When:     `shad config set defaults.panel_percent 42`.
          Then:     exit 0, stderr empty, stdout names the key and value,
                    `shad config get defaults.panel_percent` prints 42, and
                    the comment on that line survives.
        """
        out = self._run("set", "defaults.panel_percent", "42")
        self.assertIn("defaults.panel_percent", out)
        self.assertIn("42", out)
        self.assertEqual(self._run("get", "defaults.panel_percent"), "42\n")
        self.assertIn("panel_percent = 42  # bundle width", self.path.read_text())

    def test_normalises_enum_case(self) -> None:
        self._run("set", "defaults.harness", "CLAUDE")
        self.assertEqual(self._raw()["defaults"]["harness"], "claude")

    def test_set_rejects_an_invalid_value_and_leaves_the_file_unchanged(self) -> None:
        """
        Criterion:  set-rejects-an-invalid-value-and-leaves-the-file-unchanged
          Given:    shad.toml sets oc_position = "top".
          When:     `shad config set defaults.oc_position sideways`.
          Then:     exit 1, stdout empty, stderr one line `invalid_value:
                    <non-empty>` that lists the allowed values, and the file
                    is byte-identical.
        """
        before = self.path.read_text()
        self.assertIn(
            "must be one of",
            self._fail("set", "defaults.oc_position", "sideways", code="invalid_value"),
        )
        self.assertEqual(self.path.read_text(), before)

    def test_rejects_a_percent_out_of_range(self) -> None:
        self._fail("set", "defaults.split_percent", "200", code="invalid_value")

    def test_rejects_a_non_integer_percent(self) -> None:
        self._fail("set", "defaults.panel_percent", "wide", code="invalid_value")

    def test_rejects_a_zero_todo_percent(self) -> None:
        self._fail("set", "defaults.todo_percent", "0", code="invalid_value")

    def test_writes_a_panel_switch_as_a_toml_boolean(self) -> None:
        self._run("set", "defaults.git_panel", "False")
        self.assertIs(self._raw()["defaults"]["git_panel"], False)
        self.assertIn("git_panel = false", self.path.read_text())

    def test_rejects_a_panel_switch_that_is_not_true_or_false(self) -> None:
        self.assertIn(
            "true or false", self._fail("set", "defaults.todo_panel", "off", code="invalid_value")
        )

    def test_set_of_an_unknown_key_fails_unless_forced(self) -> None:
        """
        Criterion:  set-of-an-unknown-key-fails-unless-forced
          When:     `shad config set defaults.nope 7`, then the same with
                    `--force`.
          Then:     the first exits 1 with stdout empty and stderr one line
                    `unknown_key: <non-empty>` naming the key; the second
                    exits 0 and writes 7 as an integer.
        """
        self.assertIn("unknown key", self._fail("set", "defaults.nope", "7", code="unknown_key"))
        self._run("set", "--force", "defaults.nope", "7")
        self.assertEqual(self._raw()["defaults"]["nope"], 7)

    def test_rejects_a_missing_project_path(self) -> None:
        self.assertIn(
            "path does not exist",
            self._fail("set", "projects.kb.path", str(self.root / "gone"), code="path_missing"),
        )

    def test_a_forced_missing_project_path_is_written(self) -> None:
        target = self.root / "gone"
        self._run("set", "--force", "projects.kb.path", str(target))
        self.assertEqual(self._raw()["projects"]["kb"]["path"], str(target))

    def test_set_expands_a_tilde_against_home(self) -> None:
        """
        Criterion:  set-expands-a-tilde-against-home
          Given:    HOME is the test root, which holds the directory kb.
          When:     `shad config set projects.kb.path ~/kb`.
          Then:     exit 0, and the file holds the expanded path.
        """
        self._run("set", "projects.kb.path", "~/kb")
        self.assertEqual(self._raw()["projects"]["kb"]["path"], str(self.root / "kb"))

    def test_todo_path_creates_the_todo_table(self) -> None:
        notes = self.root / "notes"
        notes.mkdir()
        self._run("set", "todo.path", str(notes))
        self.assertEqual(self._raw()["todo"]["path"], str(notes))
        self.assertEqual(self._run("get", "todo.path"), f"{notes}\n")

    def test_rejects_a_missing_todo_path(self) -> None:
        self.assertIn(
            "path does not exist",
            self._fail("set", "todo.path", str(self.root / "gone"), code="path_missing"),
        )

    def test_creates_a_new_project_table(self) -> None:
        fresh = self.root / "fresh"
        fresh.mkdir()
        self._run("set", "projects.fresh.path", str(fresh))
        self.assertEqual(self._raw()["projects"]["fresh"]["path"], str(fresh))

    def test_set_refuses_a_result_that_does_not_load(self) -> None:
        """
        Criterion:  set-refuses-a-result-that-does-not-load
          Given:    project kb is at <root>/kb.
          When:     `shad config set projects.fresh.path <root>/kb`, and
                    `shad config set --force projects.alvr.db.path <root>/kb`,
                    and `shad config set projects.grp.sub.session x`.
          Then:     each exits 1 with stdout empty and stderr one line
                    `invalid_config: <non-empty>` naming the problem, and the
                    file is byte-identical after each.
        """
        before = self.path.read_text()
        self.assertIn(
            "both point at",
            self._fail("set", "projects.fresh.path", str(self.root / "kb"), code="invalid_config"),
        )
        self.assertEqual(self.path.read_text(), before)
        self.assertIn(
            "both point at",
            self._fail(
                "set",
                "--force",
                "projects.alvr.db.path",
                str(self.root / "kb"),
                code="invalid_config",
            ),
        )
        self.assertEqual(self.path.read_text(), before)
        self.assertIn(
            "set its 'path' first",
            self._fail("set", "projects.grp.sub.session", "x", code="invalid_config"),
        )
        self.assertEqual(self.path.read_text(), before)

    def test_set_keeps_the_file_mode_and_leaves_no_temporary_file(self) -> None:
        """
        Criterion:  set-keeps-the-file-mode-and-leaves-no-temporary-file
          Given:    shad.toml has mode 0600.
          When:     `shad config set defaults.panel_percent 40`.
          Then:     exit 0, the file still has mode 0600, and no `.shad.toml*`
                    file sits beside it.
        """
        self.path.chmod(0o600)
        self._run("set", "defaults.panel_percent", "40")
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(
            [p.name for p in self.root.iterdir() if p.name.startswith(".shad.toml")], []
        )
