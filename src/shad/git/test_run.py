from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from shad.git import run
from shad.shared.errors import ShadError

REPO = Path("/tmp/repo")


def _completed(
    returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["git"], returncode=returncode, stdout=stdout, stderr=stderr
    )


class ReadOnlyDispatchTests(unittest.TestCase):
    def test_worktree_list_is_read_only_but_prune_and_remove_are_not(self) -> None:
        self.assertTrue(run._is_read_only(["worktree", "list", "--porcelain"]))
        self.assertFalse(run._is_read_only(["worktree", "prune"]))
        self.assertFalse(run._is_read_only(["worktree", "remove", "x"]))

    def test_reads_and_mutations_are_separated(self) -> None:
        self.assertTrue(run._is_read_only(["status", "--porcelain=v2"]))
        self.assertTrue(run._is_read_only(["for-each-ref"]))
        self.assertFalse(run._is_read_only(["fetch", "--prune"]))
        self.assertFalse(run._is_read_only(["branch", "-d", "x"]))
        self.assertFalse(run._is_read_only([]))


class EnvironmentTests(unittest.TestCase):
    def test_inherited_git_env_is_scrubbed(self) -> None:
        with patch.dict(
            "os.environ",
            {"GIT_DIR": "/elsewhere/.git", "GIT_WORK_TREE": "/elsewhere", "PATH": "/usr/bin"},
            clear=True,
        ):
            env = run._env(read_only=True)
        self.assertNotIn("GIT_DIR", env)
        self.assertNotIn("GIT_WORK_TREE", env)
        self.assertEqual(env["PATH"], "/usr/bin")

    def test_non_interactive_and_stable_locale_are_forced(self) -> None:
        env = run._env(read_only=False)
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")
        self.assertEqual(env["LC_ALL"], "C")
        self.assertEqual(env["LANGUAGE"], "")
        self.assertNotIn("GIT_OPTIONAL_LOCKS", env)

    def test_optional_locks_are_dropped_for_reads_only(self) -> None:
        self.assertEqual(run._env(read_only=True)["GIT_OPTIONAL_LOCKS"], "0")

    def test_user_config_env_is_left_alone(self) -> None:
        env = run._env(read_only=False)
        for name in ("GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_GLOBAL", "GIT_SSH_COMMAND"):
            self.assertNotIn(name, env)


class VersionTests(unittest.TestCase):
    def test_version_is_parsed_from_the_banner(self) -> None:
        with patch.object(run, "git", return_value=_completed(stdout="git version 2.55.0\n")):
            self.assertEqual(run.git_version(), (2, 55))

    def test_vendor_suffixes_are_tolerated(self) -> None:
        with patch.object(run, "git", return_value=_completed(stdout="git version 2.39.5 (Apple Git-154)\n")
        ):
            self.assertEqual(run.git_version(), (2, 39))

    def test_old_git_is_refused_with_the_found_version(self) -> None:
        with (
            patch.object(run, "git_version", return_value=(2, 30)),
            self.assertRaises(ShadError) as ctx,
        ):
            run.require_git()
        self.assertIn("2.30 is too old", str(ctx.exception))

    def test_missing_git_becomes_a_shad_error(self) -> None:
        with (
            patch.object(run, "git_version", side_effect=run.GitMissing("git is not installed")),
            self.assertRaises(ShadError) as ctx,
        ):
            run.require_git()
        self.assertIn("not installed", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
