from __future__ import annotations

from shad.config.testing import ConfigCase


class GetTests(ConfigCase):
    """
    Feature:    config/get
    Boundary:   command. `shad config get KEY`, through main(argv) with
                SHAD_CONFIG set and XDG_DATA_HOME under the test root.
                Contract: exit code + stdout + stderr.
    """

    def test_get_prints_a_value_from_the_file(self) -> None:
        """
        Criterion:  get-prints-a-value-from-the-file
          Given:    shad.toml sets panel_percent = 35.
          When:     `shad config get defaults.panel_percent`.
          Then:     exit 0, stderr empty, stdout is `35`.
        """
        self.assertEqual(self._run("get", "defaults.panel_percent"), "35\n")

    def test_get_expands_a_table_into_dotted_lines(self) -> None:
        """
        Criterion:  get-expands-a-table-into-dotted-lines
          Given:    the group alvr holds the project db.
          When:     `shad config get projects.alvr`.
          Then:     exit 0, and stdout holds one `key = value` line per leaf,
                    including projects.alvr.db.path.
        """
        output = self._run("get", "projects.alvr")
        self.assertIn(f'projects.alvr.db.path = "{self.root}/alvr/db"', output)

    def test_get_falls_back_to_the_value_shad_uses(self) -> None:
        """
        Criterion:  get-falls-back-to-the-value-shad-uses
          Given:    shad.toml sets no oc_position, no session for alvr db,
                    no harness for kb, and no todo path.
          When:     `shad config get` for each of those keys.
          Then:     exit 0 each time, and stdout is the default, the derived
                    session, the default harness, and `$XDG_DATA_HOME/shad/todo`.
        """
        self.path.write_text(
            f'[projects.kb]\npath = "{self.root}/kb"\n'
            f'[projects.alvr.db]\npath = "{self.root}/alvr/db"\n'
        )
        self.assertEqual(self._run("get", "defaults.oc_position"), "top\n")
        self.assertEqual(self._run("get", "projects.alvr.db.session"), "alvr-db\n")
        self.assertEqual(self._run("get", "projects.kb.harness"), "opencode\n")
        self.assertEqual(self._run("get", "todo.path"), f"{self.root / 'data' / 'shad' / 'todo'}\n")

    def test_prints_a_panel_switch_in_toml_spelling(self) -> None:
        self.assertEqual(self._run("get", "defaults.git_panel"), "true\n")
        self.path.write_text(self.path.read_text().replace(
            "[defaults]\n", "[defaults]\ntodo_panel = false\n"
        ))
        self.assertEqual(self._run("get", "defaults.todo_panel"), "false\n")

    def test_get_of_an_unknown_key_fails(self) -> None:
        """
        Criterion:  get-of-an-unknown-key-fails
          When:     `shad config get defaults.nope`, and
                    `shad config get projects.nope.session`.
          Then:     exit 1, stdout empty, stderr one line `no_such_key:
                    <non-empty>`.
        """
        self.assertIn("key not found", self._fail("get", "defaults.nope", code="no_such_key"))
        self.assertIn("nope", self._fail("get", "projects.nope.session", code="no_such_key"))

    def test_get_without_a_file_names_shad_init(self) -> None:
        """
        Criterion:  get-without-a-file-names-shad-init
          Given:    the config file does not exist.
          When:     `shad config get defaults.harness`.
          Then:     exit 1, stdout empty, stderr one line `no_config_file:
                    <non-empty>` that names `shad init`.
        """
        self.path.unlink()
        self.assertIn("shad init", self._fail("get", "defaults.harness", code="no_config_file"))
