from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from shad.git import apply
from shad.shared.errors import ShadError

REPO = Path("/tmp/repo")


def _completed(
    returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["git"], returncode=returncode, stdout=stdout, stderr=stderr
    )


class MutationTests(unittest.TestCase):
    def test_delete_branch_passes_force_only_when_asked(self) -> None:
        with patch.object(apply, "git", return_value=_completed()) as run:
            self.assertIsNone(apply.delete_branch(REPO, "feat", force=False))
        self.assertEqual(run.call_args.args[1], ["branch", "--delete", "feat"])

        with patch.object(apply, "git", return_value=_completed()) as run:
            self.assertIsNone(apply.delete_branch(REPO, "feat", force=True))
        self.assertEqual(run.call_args.args[1], ["branch", "--delete", "--force", "feat"])

    def test_delete_branch_refuses_an_option_like_name(self) -> None:
        with patch.object(apply, "git") as run:
            error = apply.delete_branch(REPO, "--all", force=True)
        run.assert_not_called()
        assert error is not None
        self.assertIn("starts with '-'", error)

    def test_delete_branch_reports_the_first_stderr_line(self) -> None:
        result = _completed(1, stderr="error: the branch 'feat' is not fully merged\nhint: x\n")
        with patch.object(apply, "git", return_value=result):
            self.assertEqual(
                apply.delete_branch(REPO, "feat", force=False),
                "error: the branch 'feat' is not fully merged",
            )

    def test_remove_worktree_never_passes_force(self) -> None:
        with patch.object(apply, "git", return_value=_completed()) as run:
            apply.remove_worktree(REPO, Path("/tmp/wt"))
        self.assertNotIn("--force", run.call_args.args[1])
        self.assertIn("--", run.call_args.args[1])

    def test_fetch_prunes_when_asked_and_never_prunes_tags(self) -> None:
        with patch.object(apply, "git", return_value=_completed()) as run:
            result = apply.fetch(REPO, "origin", prune=True)
        args = run.call_args.args[1]
        self.assertTrue(result.ok)
        self.assertIn("--prune", args)
        self.assertIn("--no-recurse-submodules", args)
        self.assertNotIn("--prune-tags", args)
        self.assertNotIn("--atomic", args)
        self.assertNotIn("--dry-run", args)
        self.assertEqual(args[-2:], ["--", "origin"])

    def test_fetch_without_prune_still_fetches_for_real(self) -> None:
        # The dry-run path fetches for real so the report is accurate, but must
        # not prune: a pruned ref takes its last-known OID with it.
        with patch.object(apply, "git", return_value=_completed()) as run:
            apply.fetch(REPO, "origin", prune=False)
        args = run.call_args.args[1]
        self.assertNotIn("--prune", args)
        self.assertNotIn("--dry-run", args)

    def test_fetch_failure_is_reported_not_raised(self) -> None:
        result = _completed(128, stderr="fatal: could not read from remote repository\n")
        with patch.object(apply, "git", return_value=result):
            outcome = apply.fetch(REPO, "origin", prune=True)
        self.assertFalse(outcome.ok)
        assert outcome.error is not None
        self.assertIn("could not read from remote", outcome.error)

    def test_fetch_timeout_is_reported_not_raised(self) -> None:
        with patch.object(apply, "git", side_effect=ShadError("git fetch timed out after 120s")):
            outcome = apply.fetch(REPO, "origin", prune=True)
        self.assertFalse(outcome.ok)
        assert outcome.error is not None
        self.assertIn("timed out", outcome.error)

    def test_fast_forward_unchecked_uses_a_non_forcing_local_refspec(self) -> None:
        with patch.object(apply, "git", return_value=_completed()) as run:
            apply.fast_forward_unchecked(REPO, "main", "refs/remotes/origin/main")
        args = run.call_args.args[1]
        self.assertIn(".", args)
        self.assertIn("refs/remotes/origin/main:refs/heads/main", args)
        self.assertFalse(any(a.startswith("+") for a in args))


if __name__ == "__main__":
    unittest.main()
