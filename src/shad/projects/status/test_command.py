from __future__ import annotations

import unittest
from pathlib import Path

from shad.projects.status import command as C
from shad.projects.testing import ProjectsCase, git, plain


class StatusTests(ProjectsCase):
    """
    Feature:    projects/status
    Boundary:   command. `shad projects [<group>] <name> status` as a process
                with no terminal, against the test's tmux server and real
                repositories under the test root. Contract: exit code +
                stdout + stderr.
    """

    def test_status_reports_the_session_and_the_repository(self) -> None:
        """
        Criterion:  status-reports-the-session-and-the-repository
          Given:    kb is a repository on main with the commit "Add a thing"
                    and the tag v1.2.3, and a session kb runs.
          When:     `shad projects kb status`.
          Then:     exit 0, stderr empty, stdout names the project and its
                    path, the running session, branch main, the tag, a clean
                    tree, and the commit's subject.
        """
        self.repo("kb", tag="v1.2.3")
        self.server.new_session("kb", command="sleep 100000")
        result = self.run_detached("projects", "kb", "status")
        self.assertEqual((result.code, result.err), (0, ""), result.out)
        out = plain(result.out)
        self.assertIn(f"kb {self.root / 'kb'}", out)
        self.assertIn("session kb (base) running", out)
        self.assertIn("branch main", out)
        self.assertIn("latest tag v1.2.3", out)
        self.assertIn("uncommitted clean", out)
        self.assertIn("Add a thing", out)

    def test_status_of_a_grouped_project_resolves_prefixes(self) -> None:
        """
        Criterion:  status-of-a-grouped-project-resolves-prefixes
          Given:    tin shad is a repository, and no session runs.
          When:     `shad projects ti sh status`.
          Then:     exit 0, and stdout names tin shad and reports the
                    session as not running.
        """
        self.repo("tin/shad")
        result = self.run_detached("projects", "ti", "sh", "status")
        self.assertEqual((result.code, result.err), (0, ""), result.out)
        out = plain(result.out)
        self.assertIn("tin shad", out)
        self.assertIn("session tin-shad not running", out)

    def test_status_counts_changed_and_untracked_files(self) -> None:
        """
        Criterion:  status-counts-changed-and-untracked-files
          Given:    kb is a repository with one committed file that was then
                    changed, and one untracked file.
          When:     `shad projects kb status`.
          Then:     exit 0, and stdout reports 2 uncommitted files.
        """
        path = self.repo("kb")
        (path / "file-0.txt").write_text("changed\n")
        (path / "new.txt").write_text("new\n")
        out = plain(self.run_detached("projects", "kb", "status").out)
        self.assertIn("uncommitted 2 file(s)", out)

    def test_status_labels_a_detached_head_and_a_missing_tag(self) -> None:
        """
        Criterion:  status-labels-a-detached-head-and-a-missing-tag
          Given:    kb is a repository with no tag whose HEAD is detached.
          When:     `shad projects kb status`.
          Then:     exit 0, and stdout reports the branch as detached and
                    the tag as a dash.
        """
        path = self.repo("kb")
        git(path, "checkout", "-q", "--detach")
        out = plain(self.run_detached("projects", "kb", "status").out)
        self.assertIn("branch detached", out)
        self.assertIn("latest tag —", out)

    def test_status_of_a_directory_that_is_not_a_repository(self) -> None:
        """
        Criterion:  status-of-a-directory-that-is-not-a-repository
          Given:    kb is a plain directory.
          When:     `shad projects kb status`.
          Then:     exit 0, and stdout says it is not a git repository.
        """
        result = self.run_detached("projects", "kb", "status")
        self.assertEqual(result.code, 0, result.err)
        self.assertIn("(not a git repository)", result.out)

    def test_status_of_an_unknown_project_fails(self) -> None:
        """
        Criterion:  status-of-an-unknown-project-fails
          When:     `shad projects nope status`.
          Then:     exit 1, stdout empty, stderr names nope.
        """
        result = self.run_detached("projects", "nope", "status")
        self.assertEqual((result.code, result.out), (1, ""), result.err)
        self.assertIn("nope", result.err)

    def test_status_ignores_an_inherited_git_dir(self) -> None:
        """
        Criterion:  status-ignores-an-inherited-git-dir
          Given:    kb is a repository on main, and GIT_DIR names another
                    repository that is on a branch called elsewhere.
          When:     `shad projects kb status` with that GIT_DIR.
          Then:     exit 0, and stdout reports branch main.
        """
        self.repo("kb")
        other = self.repo("tin/coral")
        git(other, "checkout", "-q", "-b", "elsewhere")
        self.env["GIT_DIR"] = str(other / ".git")
        out = plain(self.run_detached("projects", "kb", "status").out)
        self.assertIn("branch main", out)
        self.assertNotIn("elsewhere", out)


class NoRawGitCallsTests(unittest.TestCase):
    def test_the_status_slice_shells_out_to_git_nowhere(self) -> None:
        """
        _capture applies no env scrubbing and no timeout and uses cwd=, so a
        git call through it reports whichever repository an inherited GIT_DIR
        names. Every git query must go through shad.git.run instead.
        """
        source = Path(C.__file__).read_text()
        self.assertNotIn('["git"', source)

