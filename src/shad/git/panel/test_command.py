from __future__ import annotations

import unittest

from shad.git.testing import GitCase, words


class PanelTests(GitCase):
    """
    Feature:    git/panel
    Boundary:   command. `shad git panel [<group>] [<name>] [--no-fetch]` in
                a terminal pane of the test's tmux server, or as a process
                with no terminal where it fails before the view opens.
                Contract: exit code + screen or stderr.
    """

    def test_panel_shows_the_repository_and_quits(self) -> None:
        """
        Criterion:  panel-shows-the-repository-and-quits
          Given:    kb is a clone on main.
          When:     `shad git panel kb` in a terminal, then `q`.
          Then:     the view shows the sections and the branch main, and the
                    command exits 0.
        """
        self.clone("kb")
        pane = self.pane("git", "panel", "kb")
        screen = pane.wait_for("worktrees")
        self.assertIn("branches", screen)
        pane.wait_for("main")
        pane.send("q")
        self.assertEqual(pane.wait_exit(), 0)

    def test_panel_without_a_name_uses_the_current_directory(self) -> None:
        """
        Criterion:  panel-without-a-name-uses-the-current-directory
          Given:    the current directory is tin coral's clone, which is not
                    named on the command line.
          When:     `shad git panel --no-fetch` in a terminal there, then `q`.
          Then:     the view shows the branch main, and the command exits 0.
        """
        path = self.clone("tin/coral")
        pane = self.pane("git", "panel", "--no-fetch", cwd=path)
        pane.wait_for("main")
        pane.send("q")
        self.assertEqual(pane.wait_exit(), 0)

    def test_panel_of_a_group_with_several_projects_fails(self) -> None:
        """
        Criterion:  panel-of-a-group-with-several-projects-fails
          When:     `shad git panel tin`.
          Then:     exit 2, stdout empty, stderr one line
                    `ambiguous_target: <non-empty>` that says the panel shows
                    one repository and that tin matches 2 projects.
        """
        result = self.run_detached("git", "panel", "tin")
        self.assertEqual((result.code, result.out), (2, ""), result.err)
        self.assertRegex(result.err, r"^ambiguous_target: .+\n$")
        self.assertIn("matches 2 projects", result.err)
        self.assertIn("shows one repository", words(result.err))

    def test_panel_of_a_plain_directory_fails(self) -> None:
        """
        Criterion:  panel-of-a-plain-directory-fails
          Given:    kb is a plain directory.
          When:     `shad git panel kb`.
          Then:     exit 1, stdout empty, stderr one line `no_repository:
                    <non-empty>`.
        """
        self.path("kb").mkdir()
        result = self.run_detached("git", "panel", "kb")
        self.assertEqual((result.code, result.out), (1, ""), result.err)
        self.assertRegex(result.err, r"^no_repository: .+\n$")


if __name__ == "__main__":
    unittest.main()
