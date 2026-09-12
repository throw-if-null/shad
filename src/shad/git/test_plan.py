from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from shad.git import discover, refs
from shad.git import plan as planning
from shad.git.model import (
    BranchInfo,
    BranchKept,
    BranchRef,
    Worktree,
    WorktreeInfo,
    WorktreeKept,
)

REPO = Path("/tmp/repo")


def _completed(
    returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["git"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _branch(
    name: str,
    *,
    oid: str = "a" * 40,
    upstream: str = "",
    remotename: str = "",
    trackshort: str = "",
) -> BranchRef:
    return BranchRef(
        refname=f"refs/heads/{name}",
        oid=oid,
        upstream=upstream,
        remotename=remotename,
        trackshort=trackshort,
    )


class ClassifyBranchTests(unittest.TestCase):
    def _classify(
        self,
        branch: BranchRef,
        *,
        merged: bool | None = False,
        pushed: bool | None = None,
        pruned_oids: dict[str, str] | None = None,
        upstream_exists: bool = True,
        checked_out: dict[str, Path] | None = None,
        gone_allowed: bool = True,
        shallow: bool = False,
    ) -> BranchInfo | BranchKept:
        with (
            patch.object(refs, "is_ancestor", return_value=pushed),
            patch.object(refs, "ref_exists", return_value=upstream_exists),
        ):
            return planning.classify_branch(
                REPO,
                branch,
                merged={branch.refname} if merged else set(),
                checked_out=checked_out or {},
                pruned_oids=pruned_oids or {},
                gone_allowed=gone_allowed,
                shallow=shallow,
            )

    def test_merged_branch_is_deleted_without_force(self) -> None:
        verdict = self._classify(_branch("feat", upstream="refs/remotes/origin/feat",
                                         remotename="origin"), merged=True)
        assert isinstance(verdict, BranchInfo)
        self.assertEqual(verdict.reason, "merged")
        self.assertFalse(verdict.force)

    def test_pushed_then_gone_branch_is_force_deleted(self) -> None:
        verdict = self._classify(
            _branch("feat", upstream="refs/remotes/origin/feat", remotename="origin"),
            merged=False,
            pushed=True,
            pruned_oids={"refs/remotes/origin/feat": "last-known"},
        )
        assert isinstance(verdict, BranchInfo)
        self.assertEqual(verdict.reason, "pushed-then-gone")
        self.assertTrue(verdict.force)

    def test_gone_branch_with_unpushed_commits_is_kept(self) -> None:
        verdict = self._classify(
            _branch("feat", upstream="refs/remotes/origin/feat", remotename="origin"),
            pushed=False,
            pruned_oids={"refs/remotes/origin/feat": "last-known"},
        )
        assert isinstance(verdict, BranchKept)
        self.assertIn("unpushed", verdict.reason)

    def test_gone_branch_with_unknown_ancestry_is_kept(self) -> None:
        verdict = self._classify(
            _branch("feat", upstream="refs/remotes/origin/feat", remotename="origin"),
            pushed=None,
            pruned_oids={"refs/remotes/origin/feat": "last-known"},
        )
        assert isinstance(verdict, BranchKept)
        self.assertIn("last-known state unavailable", verdict.reason)

    def test_branch_pruned_before_this_run_is_kept(self) -> None:
        verdict = self._classify(
            _branch("feat", upstream="refs/remotes/origin/feat", remotename="origin"),
            pruned_oids={},
            upstream_exists=False,
        )
        assert isinstance(verdict, BranchKept)
        self.assertIn("pruned before this run", verdict.reason)

    def test_narrow_refspec_disables_gone_based_deletion(self) -> None:
        verdict = self._classify(
            _branch("feat", upstream="refs/remotes/origin/feat", remotename="origin"),
            pushed=True,
            pruned_oids={"refs/remotes/origin/feat": "last-known"},
            gone_allowed=False,
        )
        assert isinstance(verdict, BranchKept)
        self.assertEqual(verdict.reason, "narrow fetch refspec")

    def test_checked_out_branch_is_never_deleted(self) -> None:
        verdict = self._classify(
            _branch("feat", upstream="refs/remotes/origin/feat", remotename="origin"),
            merged=True,
            checked_out={"refs/heads/feat": Path("/tmp/wt")},
        )
        assert isinstance(verdict, BranchKept)
        self.assertIn("checked out at", verdict.reason)

    def test_ahead_branch_is_never_deleted(self) -> None:
        verdict = self._classify(
            _branch("feat", upstream="refs/remotes/origin/feat",
                    remotename="origin", trackshort=">"),
            merged=True,
        )
        assert isinstance(verdict, BranchKept)
        self.assertEqual(verdict.reason, "unpushed commits")

    def test_branch_without_upstream_is_kept_even_when_merged(self) -> None:
        verdict = self._classify(_branch("scratch"), merged=True)
        assert isinstance(verdict, BranchKept)
        self.assertEqual(verdict.reason, "no upstream")

    def test_local_tracking_branch_is_kept(self) -> None:
        verdict = self._classify(
            _branch("mirror", upstream="refs/heads/main", remotename="."), merged=False
        )
        assert isinstance(verdict, BranchKept)
        self.assertEqual(verdict.reason, "tracks a local branch")

    def test_shallow_clone_keeps_everything(self) -> None:
        verdict = self._classify(
            _branch("feat", upstream="refs/remotes/origin/feat", remotename="origin"),
            merged=True,
            shallow=True,
        )
        assert isinstance(verdict, BranchKept)
        self.assertEqual(verdict.reason, "shallow clone")

    def test_default_branch_is_skipped_entirely(self) -> None:
        with (
            patch.object(refs, "is_ancestor", return_value=True),
            patch.object(refs, "ref_exists", return_value=True),
            patch.object(
                refs,
                "merged_branches",
                return_value={"refs/heads/main", "refs/heads/feat"},
            ),
        ):
            plan = planning.classify_branches(
                REPO,
                [_branch("main"), _branch("feat", upstream="refs/remotes/origin/feat",
                                          remotename="origin")],
                default="main",
                default_tips=["tip"],
                checked_out={},
                pruned_oids={},
                gone_allowed=True,
                shallow=False,
            )
        names = [b.name for b in plan.delete] + [b.name for b in plan.keep]
        self.assertNotIn("main", names)


class ClassifyWorktreeTests(unittest.TestCase):
    def test_main_worktree_is_never_a_candidate(self) -> None:
        main = Worktree(path=Path("/tmp/repo"), branch="refs/heads/main")
        plan = planning.classify_worktrees(REPO, [main], deleting=set(), known_branches=set())
        self.assertEqual(plan.remove, [])
        self.assertEqual(plan.keep, [])

    def test_locked_worktree_is_kept_with_its_reason(self) -> None:
        wt = Worktree(
            path=Path("/tmp/gone"), branch="refs/heads/x", locked=True,
            locked_reason="usb stick", prunable=True,
        )
        verdict = planning.classify_worktree(REPO, wt, deleting=set(), known_branches=set())
        assert isinstance(verdict, WorktreeKept)
        self.assertEqual(verdict.reason, "locked: usb stick")

    def test_bare_record_is_ignored(self) -> None:
        wt = Worktree(path=Path("/tmp/bare"), bare=True)
        self.assertIsNone(
            planning.classify_worktree(REPO, wt, deleting=set(), known_branches=set())
        )

    def test_prunable_worktree_is_prune_only(self) -> None:
        wt = Worktree(
            path=Path("/tmp/gone"), branch="refs/heads/x",
            prunable=True, prunable_reason="gitdir file points to non-existent location",
        )
        verdict = planning.classify_worktree(REPO, wt, deleting=set(), known_branches=set())
        assert isinstance(verdict, WorktreeInfo)
        self.assertTrue(verdict.prune_only)
        self.assertIn("non-existent", verdict.reason)

    def test_worktree_with_a_live_branch_is_kept(self) -> None:
        wt = Worktree(path=Path("/tmp/live"), branch="refs/heads/x")
        with patch.object(Path, "is_dir", return_value=True):
            verdict = planning.classify_worktree(
                REPO, wt, deleting=set(), known_branches={"refs/heads/x"}
            )
        assert isinstance(verdict, WorktreeKept)
        self.assertEqual(verdict.reason, "branch still in use")

    def test_dirty_worktree_is_kept_with_counts(self) -> None:
        wt = Worktree(path=Path("/tmp/dirty"), branch="refs/heads/x")
        with (
            patch.object(Path, "is_dir", return_value=True),
            patch.object(Path, "is_file", return_value=False),
            patch.object(discover, "in_progress", return_value=None),
            patch.object(discover, "is_clean", return_value=(False, 3, 12)),
        ):
            verdict = planning.classify_worktree(
                REPO, wt, deleting={"refs/heads/x"}, known_branches={"refs/heads/x"}
            )
        assert isinstance(verdict, WorktreeKept)
        self.assertEqual(verdict.reason, "3 modified, 12 untracked")

    def test_worktree_with_submodules_is_kept(self) -> None:
        wt = Worktree(path=Path("/tmp/subs"), branch="refs/heads/x")
        with (
            patch.object(Path, "is_dir", return_value=True),
            patch.object(Path, "is_file", return_value=True),
        ):
            verdict = planning.classify_worktree(
                REPO, wt, deleting={"refs/heads/x"}, known_branches={"refs/heads/x"}
            )
        assert isinstance(verdict, WorktreeKept)
        self.assertEqual(verdict.reason, "contains submodules")

    def test_worktree_mid_rebase_is_kept(self) -> None:
        wt = Worktree(path=Path("/tmp/reb"), branch="refs/heads/x")
        with (
            patch.object(Path, "is_dir", return_value=True),
            patch.object(Path, "is_file", return_value=False),
            patch.object(discover, "in_progress", return_value="rebase"),
        ):
            verdict = planning.classify_worktree(
                REPO, wt, deleting={"refs/heads/x"}, known_branches={"refs/heads/x"}
            )
        assert isinstance(verdict, WorktreeKept)
        self.assertEqual(verdict.reason, "rebase in progress")

    def test_clean_worktree_of_a_deleted_branch_is_removed(self) -> None:
        wt = Worktree(path=Path("/tmp/dead"), branch="refs/heads/x")
        with (
            patch.object(Path, "is_dir", return_value=True),
            patch.object(Path, "is_file", return_value=False),
            patch.object(discover, "in_progress", return_value=None),
            patch.object(discover, "is_clean", return_value=(True, 0, 0)),
        ):
            verdict = planning.classify_worktree(
                REPO, wt, deleting={"refs/heads/x"}, known_branches={"refs/heads/x"}
            )
        assert isinstance(verdict, WorktreeInfo)
        self.assertEqual(verdict.reason, "branch is being deleted")
        self.assertFalse(verdict.prune_only)

    def test_detached_worktree_with_unreachable_head_is_kept(self) -> None:
        wt = Worktree(path=Path("/tmp/det"), head="abc", detached=True)
        with (
            patch.object(Path, "is_dir", return_value=True),
            patch.object(refs, "any_ref_contains", return_value=False),
        ):
            verdict = planning.classify_worktree(REPO, wt, deleting=set(), known_branches=set())
        assert isinstance(verdict, WorktreeKept)
        self.assertIn("not reachable from any ref", verdict.reason)



ROOT = Path("/tmp/repo")


def _del_branch(name: str = "feat", sha: str = "abc1234") -> BranchInfo:
    return BranchInfo(name=name, sha=sha, reason="merged")


def _del_worktree(path: str = "/tmp/wt") -> WorktreeInfo:
    return WorktreeInfo(
        path=Path(path), branch="refs/heads/feat", reason="branch is being deleted"
    )


class ReconcileTests(unittest.TestCase):
    def test_a_branch_whose_worktree_is_going_stays_deletable(self) -> None:
        branch = _del_branch("feat")
        worktree = _del_worktree("/tmp/wt")
        deletions, kept = planning.reconcile(
            planning.BranchPlan(delete=[branch]),
            planning.WorktreePlan(remove=[worktree]),
            {"refs/heads/feat": Path("/tmp/wt")},
        )
        self.assertEqual(deletions, [branch])
        self.assertEqual(kept, [])

    def test_a_branch_whose_worktree_survives_is_kept_with_that_reason(self) -> None:
        branch = _del_branch("feat")
        survivor = WorktreeKept(
            path=Path("/tmp/wt"), branch="refs/heads/feat", reason="2 modified"
        )
        deletions, kept = planning.reconcile(
            planning.BranchPlan(delete=[branch]),
            planning.WorktreePlan(keep=[survivor]),
            {"refs/heads/feat": Path("/tmp/wt")},
        )
        self.assertEqual(deletions, [])
        self.assertIn("2 modified", kept[0].reason)

    def test_a_branch_held_by_no_worktree_is_unaffected(self) -> None:
        branch = _del_branch("feat")
        deletions, kept = planning.reconcile(planning.BranchPlan(delete=[branch]), planning.WorktreePlan(), {})
        self.assertEqual(deletions, [branch])
        self.assertEqual(kept, [])


class PrunedOidTests(unittest.TestCase):
    def test_applied_run_diffs_the_snapshots(self) -> None:
        before = {"refs/remotes/origin/a": "aaa", "refs/remotes/origin/b": "bbb"}
        after = {"refs/remotes/origin/a": "aaa"}
        result = planning.stale_upstreams(ROOT, "origin", before, after, set(), dry_run=False)
        self.assertEqual(result, {"refs/remotes/origin/b": "bbb"})

    def test_applied_run_ignores_symrefs(self) -> None:
        before = {"refs/remotes/origin/HEAD": "aaa"}
        result = planning.stale_upstreams(
            ROOT, "origin", before, {}, {"refs/remotes/origin/HEAD"}, dry_run=False
        )
        self.assertEqual(result, {})

    def test_dry_run_asks_the_remote_instead_of_pruning(self) -> None:
        after = {"refs/remotes/origin/a": "aaa", "refs/remotes/origin/gone": "ggg"}
        with patch.object(refs, "remote_branch_refs", return_value={"refs/remotes/origin/a"}):
            result = planning.stale_upstreams(ROOT, "origin", {}, after, set(), dry_run=True)
        self.assertEqual(result, {"refs/remotes/origin/gone": "ggg"})

    def test_dry_run_reports_none_when_the_remote_is_unreachable(self) -> None:
        with patch.object(refs, "remote_branch_refs", return_value=None):
            self.assertIsNone(
                planning.stale_upstreams(ROOT, "origin", {}, {}, set(), dry_run=True)
            )

    def test_dry_run_ignores_another_remote(self) -> None:
        # ls-remote only ever describes one remote, but the ref snapshot covers
        # all of refs/remotes. Without the prefix filter every upstream/* ref
        # reads as stale and a branch tracking a live upstream/x is offered up
        # for deletion.
        after = {
            "refs/remotes/origin/a": "aaa",
            "refs/remotes/origin/gone": "ggg",
            "refs/remotes/upstream/feat": "fff",
        }
        with patch.object(refs, "remote_branch_refs", return_value={"refs/remotes/origin/a"}):
            result = planning.stale_upstreams(ROOT, "origin", {}, after, set(), dry_run=True)
        self.assertEqual(result, {"refs/remotes/origin/gone": "ggg"})

    def test_applied_run_ignores_another_remote(self) -> None:
        before = {"refs/remotes/origin/b": "bbb", "refs/remotes/upstream/feat": "fff"}
        after = {"refs/remotes/origin/b": "bbb"}
        result = planning.stale_upstreams(ROOT, "origin", before, after, set(), dry_run=False)
        self.assertEqual(result, {})

if __name__ == "__main__":
    unittest.main()
