from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from shad.git import discover, refs
from shad.git.model import Worktree

REPO = Path("/tmp/repo")


def _completed(
    returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["git"], returncode=returncode, stdout=stdout, stderr=stderr
    )


class DiscoverTests(unittest.TestCase):
    def _flags(self, bare: str, work: str, gitdir: str, shallow: str) -> str:
        return f"{bare}\n{work}\n{gitdir}\n{shallow}\n"

    def test_missing_directory_is_refused(self) -> None:
        with self.assertRaises(discover.NotUsable) as ctx:
            discover.discover(Path("/tmp/definitely-not-here-shad"))
        self.assertIn("path does not exist", str(ctx.exception))

    def test_non_repository_is_refused(self) -> None:
        result = _completed(128, stderr="fatal: not a git repository (or any parent)\n")
        with (
            patch.object(Path, "is_dir", return_value=True),
            patch.object(discover, "git", return_value=result),
            self.assertRaises(discover.NotUsable) as ctx,
        ):
            discover.discover(REPO)
        self.assertIn("not a git repository", str(ctx.exception))

    def test_dubious_ownership_suggests_safe_directory(self) -> None:
        result = _completed(128, stderr="fatal: detected dubious ownership in repository\n")
        with (
            patch.object(Path, "is_dir", return_value=True),
            patch.object(discover, "git", return_value=result),
            self.assertRaises(discover.NotUsable) as ctx,
        ):
            discover.discover(REPO)
        self.assertIn("safe.directory", str(ctx.exception))

    def test_bare_repository_is_refused(self) -> None:
        flags = self._flags("true", "false", "false", "false")
        with (
            patch.object(Path, "is_dir", return_value=True),
            patch.object(discover, "git", return_value=_completed(stdout=flags)),
            self.assertRaises(discover.NotUsable) as ctx,
        ):
            discover.discover(REPO)
        self.assertIn("bare repository", str(ctx.exception))

    def test_path_inside_the_git_directory_is_refused(self) -> None:
        flags = self._flags("false", "false", "true", "false")
        with (
            patch.object(Path, "is_dir", return_value=True),
            patch.object(discover, "git", return_value=_completed(stdout=flags)),
            self.assertRaises(discover.NotUsable) as ctx,
        ):
            discover.discover(REPO)
        self.assertIn("inside a .git directory", str(ctx.exception))

    def test_subdirectory_is_refused_and_never_retargeted(self) -> None:
        here = Path("/tmp/repo/src").resolve()
        top = Path("/tmp/repo").resolve()
        responses = [
            _completed(stdout=self._flags("false", "true", "false", "false")),
            _completed(stdout=f"{top}\n{top}/.git\n{top}/.git\n"),
        ]
        with (
            patch.object(Path, "is_dir", return_value=True),
            patch.object(discover, "git", side_effect=responses),
            self.assertRaises(discover.NotUsable) as ctx,
        ):
            discover.discover(here)
        self.assertIn("is not its root", str(ctx.exception))

    def test_shallow_repository_is_flagged_but_accepted(self) -> None:
        top = Path("/tmp/repo").resolve()
        responses = [
            _completed(stdout=self._flags("false", "true", "false", "true")),
            _completed(stdout=f"{top}\n{top}/.git\n{top}/.git\n"),
        ]
        with (
            patch.object(Path, "is_dir", return_value=True),
            patch.object(discover, "git", side_effect=responses),
        ):
            found = discover.discover(top)
        self.assertTrue(found.shallow)
        self.assertEqual(found.root, top)

    def test_linked_worktree_is_rerooted_onto_the_main_worktree(self) -> None:
        here = Path("/tmp/wt-feat").resolve()
        main = Path("/tmp/repo").resolve()
        responses = [
            _completed(stdout=self._flags("false", "true", "false", "false")),
            _completed(stdout=f"{here}\n{main}/.git/worktrees/wt-feat\n{main}/.git\n"),
        ]
        worktrees = [Worktree(path=main), Worktree(path=here)]
        with (
            patch.object(Path, "is_dir", return_value=True),
            patch.object(discover, "git", side_effect=responses),
            patch.object(refs, "list_worktrees", return_value=worktrees),
        ):
            found = discover.discover(here)
        self.assertEqual(found.root, main)
        self.assertEqual(found.relinked_from, here)
        self.assertEqual(found.common_dir, (main / ".git").resolve())


class InProgressFailureTests(unittest.TestCase):
    """'Cannot tell' has to fail the same direction as is_clean()."""

    def test_a_git_failure_reports_an_operation_rather_than_none(self) -> None:
        # Returning None here would let classify_worktree fall through to
        # is_clean — and a mid-rebase tree can be clean — so a worktree with a
        # live rebase would be queued for removal.
        with patch.object(discover, "git", return_value=_completed(128, stderr="boom")):
            self.assertEqual(
                discover.in_progress(REPO), discover.UNKNOWN_OPERATION
            )

    def test_short_output_reports_an_operation_rather_than_none(self) -> None:
        with patch.object(discover, "git", return_value=_completed(0, stdout="only-one\n")):
            self.assertEqual(
                discover.in_progress(REPO), discover.UNKNOWN_OPERATION
            )

    def test_a_quiet_worktree_still_reports_none(self) -> None:
        paths = "\n".join(f"/tmp/repo/.git/{m}" for m, _ in discover._IN_PROGRESS)
        with patch.object(discover, "git", return_value=_completed(0, stdout=paths + "\n")):
            self.assertIsNone(discover.in_progress(REPO))


if __name__ == "__main__":
    unittest.main()
