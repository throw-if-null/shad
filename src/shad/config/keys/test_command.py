from __future__ import annotations

from shad.config.testing import ConfigCase


class KeysTests(ConfigCase):
    """
    Feature:    config/keys
    Boundary:   command. `shad config keys`, through main(argv) with
                SHAD_CONFIG set. Contract: exit code + stdout + stderr. The
                output is a published surface: the completion script parses
                it as one plain key per line.
    """

    def test_keys_lists_every_settable_key_one_per_line(self) -> None:
        """
        Criterion:  keys-lists-every-settable-key-one-per-line
          Given:    the projects kb and alvr db are configured.
          When:     `shad config keys`.
          Then:     exit 0, stderr empty, stdout is one dotted key per line
                    with no other text, and it holds every defaults field,
                    every field of both projects, and todo.path.
        """
        out = self._run("keys")
        keys = out.splitlines()
        self.assertEqual(out, "".join(f"{key}\n" for key in keys))
        self.assertTrue(all(" " not in key for key in keys), keys)
        for key in (
            "defaults.oc_position",
            "defaults.harness",
            "defaults.git_panel",
            "defaults.todo_panel",
            "projects.kb.path",
            "projects.kb.session",
            "projects.alvr.db.harness",
            "todo.path",
        ):
            self.assertIn(key, keys)

    def test_keys_without_a_file_lists_the_keys_that_need_none(self) -> None:
        """
        Criterion:  keys-without-a-file-lists-the-keys-that-need-none
          Given:    the config file does not exist.
          When:     `shad config keys`.
          Then:     exit 0, and stdout holds the defaults and todo keys and
                    no project key.
        """
        self.path.unlink()
        keys = self._run("keys").splitlines()
        self.assertIn("defaults.harness", keys)
        self.assertIn("todo.path", keys)
        self.assertEqual([key for key in keys if key.startswith("projects.")], [])
