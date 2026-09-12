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

    def test_every_mutation_reports_a_timeout_instead_of_raising(self) -> None:
        # apply_plan runs on the main thread with no per-project guard, so a
        # ShadError escaping here aborts the deletions still queued for every
        # other project — after some have already been applied.
        boom = ShadError("git worktree remove timed out after 60s")
        cases = {
            "delete_branch": lambda: apply.delete_branch(REPO, "feat", force=False),
            "remove_worktree": lambda: apply.remove_worktree(REPO, Path("/tmp/wt")),
            "prune_worktrees": lambda: apply.prune_worktrees(REPO),
            "fast_forward_checked_out": lambda: apply.fast_forward_checked_out(
                REPO, "refs/remotes/origin/main"
            ),
            "fast_forward_unchecked": lambda: apply.fast_forward_unchecked(
                REPO, "main", "refs/remotes/origin/main"
            ),
        }
        for name, call in cases.items():
            with self.subTest(name), patch.object(apply, "git", side_effect=boom):
                error = call()
            assert error is not None
            self.assertIn("timed out", error)

class SwitchTests(unittest.TestCase):
    """--switch is the only working-tree mutation; every gate must skip, not force."""

    def _switch(self, checked_out: dict[str, Path] | None = None, **flags: bool):
        return apply.switch_default(
            REPO, "main", "refs/heads/main", checked_out or {}, dry_run=flags.get("dry_run", False)
        )

    def test_already_on_the_default_branch_is_a_no_op(self) -> None:
        with (
            patch.object(apply.discover, "head_branch", return_value="refs/heads/main"),
            patch.object(apply, "git") as run,
        ):
            result = self._switch()
        run.assert_not_called()
        self.assertEqual(result.status, "current")

    def test_a_detached_head_is_skipped(self) -> None:
        with (
            patch.object(apply.discover, "head_branch", return_value=None),
            patch.object(apply, "git") as run,
        ):
            result = self._switch()
        run.assert_not_called()
        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.detail, "HEAD is detached")

    def test_a_missing_local_default_branch_is_never_created(self) -> None:
        with (
            patch.object(apply.discover, "head_branch", return_value="refs/heads/feat"),
            patch.object(apply.refs, "ref_exists", return_value=False),
            patch.object(apply, "git") as run,
        ):
            result = self._switch()
        run.assert_not_called()
        self.assertEqual(result.detail, "no local main")

    def test_a_default_branch_held_by_another_worktree_is_skipped(self) -> None:
        with (
            patch.object(apply.discover, "head_branch", return_value="refs/heads/feat"),
            patch.object(apply.refs, "ref_exists", return_value=True),
            patch.object(apply, "git") as run,
        ):
            result = self._switch({"refs/heads/main": Path("/tmp/other-wt")})
        run.assert_not_called()
        assert result.detail is not None
        self.assertIn("checked out at /tmp/other-wt", result.detail)

    def test_a_dirty_tree_is_skipped_never_stashed(self) -> None:
        with (
            patch.object(apply.discover, "head_branch", return_value="refs/heads/feat"),
            patch.object(apply.refs, "ref_exists", return_value=True),
            patch.object(apply.discover, "is_clean", return_value=(False, 3, 0)),
            patch.object(apply, "git") as run,
        ):
            result = self._switch()
        run.assert_not_called()
        self.assertEqual(result.detail, "3 uncommitted change(s)")

    def test_dry_run_reports_the_move_without_making_it(self) -> None:
        with (
            patch.object(apply.discover, "head_branch", return_value="refs/heads/feat"),
            patch.object(apply.refs, "ref_exists", return_value=True),
            patch.object(apply.discover, "is_clean", return_value=(True, 0, 0)),
            patch.object(apply, "git") as run,
        ):
            result = self._switch(dry_run=True)
        run.assert_not_called()
        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.from_branch, "feat")
        self.assertEqual(result.detail, "would switch")

    def test_a_clean_tree_switches_with_no_guess(self) -> None:
        with (
            patch.object(apply.discover, "head_branch", return_value="refs/heads/feat"),
            patch.object(apply.refs, "ref_exists", return_value=True),
            patch.object(apply.discover, "is_clean", return_value=(True, 0, 0)),
            patch.object(apply, "git", return_value=_completed()) as run,
        ):
            result = self._switch()
        self.assertEqual(run.call_args.args[1], ["switch", "--no-guess", "main"])
        self.assertEqual(result.status, "switched")
        self.assertEqual(result.from_branch, "feat")

    def test_a_failed_switch_reports_the_reason_not_a_move(self) -> None:
        failure = _completed(1, stderr="error: cannot switch\n")
        with (
            patch.object(apply.discover, "head_branch", return_value="refs/heads/feat"),
            patch.object(apply.refs, "ref_exists", return_value=True),
            patch.object(apply.discover, "is_clean", return_value=(True, 0, 0)),
            patch.object(apply, "git", return_value=failure),
        ):
            result = self._switch()
        self.assertEqual(result.status, "skipped")
        # from_branch stays unset, or the report would render it as a move.
        self.assertIsNone(result.from_branch)
        self.assertEqual(result.detail, "error: cannot switch")


class FastForwardRefspecTests(unittest.TestCase):
    def test_fast_forward_unchecked_uses_a_non_forcing_local_refspec(self) -> None:
        with patch.object(apply, "git", return_value=_completed()) as run:
            apply.fast_forward_unchecked(REPO, "main", "refs/remotes/origin/main")
        args = run.call_args.args[1]
        self.assertIn(".", args)
        self.assertIn("refs/remotes/origin/main:refs/heads/main", args)
        self.assertFalse(any(a.startswith("+") for a in args))


if __name__ == "__main__":
    unittest.main()
