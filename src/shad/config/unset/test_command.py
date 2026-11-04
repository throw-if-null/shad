from __future__ import annotations

from shad.config.testing import ConfigCase


class UnsetTests(ConfigCase):
    """
    Feature:    config/unset
    Boundary:   command. `shad config unset KEY [--force]`, through
                main(argv) with SHAD_CONFIG set. Contract: exit code +
                stdout + stderr + the file.
    """

    def test_unset_removes_a_key(self) -> None:
        """
        Criterion:  unset-removes-a-key
          Given:    project kb sets session = "kb".
          When:     `shad config unset projects.kb.session`.
          Then:     exit 0, stderr empty, stdout names the key, and
                    `shad config get projects.kb.session` prints the derived
                    session, not the file's.
        """
        out = self._run("unset", "projects.kb.session")
        self.assertIn("projects.kb.session", out)
        self.assertNotIn("session", self._raw()["projects"]["kb"])
        self.assertEqual(self._run("get", "projects.kb.session"), "kb\n")

    def test_unset_removes_a_whole_project(self) -> None:
        """
        Criterion:  unset-removes-a-whole-project
          When:     `shad config unset projects.kb`.
          Then:     exit 0, and `shad config keys` lists no projects.kb key.
        """
        self._run("unset", "projects.kb")
        self.assertNotIn("kb", self._raw()["projects"])
        keys = self._run("keys").splitlines()
        self.assertEqual([key for key in keys if key.startswith("projects.kb.")], [])

    def test_unset_guards_a_required_key_unless_forced(self) -> None:
        """
        Criterion:  unset-guards-a-required-key-unless-forced
          When:     `shad config unset projects.kb.path`, then the same with
                    `--force` after the project's session was removed.
          Then:     the first exits 1 with stdout empty, stderr saying the
                    key is required, and the path still in the file; the
                    second exits 0 and leaves an empty project table.
        """
        self.assertIn("is required", self._fail("unset", "projects.kb.path"))
        self.assertIn(f"{self.root}/kb", self.path.read_text())
        self._run("unset", "projects.kb.session")
        self._run("unset", "--force", "projects.kb.path")
        self.assertEqual(self._raw()["projects"]["kb"], {})

    def test_a_forced_key_is_still_refused_when_it_breaks_the_config(self) -> None:
        before = self.path.read_text()
        self.assertIn(
            "resulting config is invalid", self._fail("unset", "--force", "projects.kb.path")
        )
        self.assertEqual(self.path.read_text(), before)

    def test_unset_of_an_unknown_key_fails(self) -> None:
        """
        Criterion:  unset-of-an-unknown-key-fails
          When:     `shad config unset projects.nothere`.
          Then:     exit 1, stdout empty, stderr non-empty.
        """
        self.assertNotEqual(self._fail("unset", "projects.nothere"), "")
