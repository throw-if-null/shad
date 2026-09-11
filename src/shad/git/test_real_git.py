"""
Parser tests against a real git repository.

Everything these cover is an *external contract* — the record grammar of
`worktree list --porcelain -z`, the symbols `%(upstream:trackshort)` emits,
and what `fetch --prune` actually does to the ref store. A mock-only suite
encodes an assumption about those formats and passes forever while being
wrong, which is the failure mode that matters for a command whose job is
deleting branches.

The fixture is hermetic: a bare "remote" and a clone inside a
TemporaryDirectory, so fetch exercises the real code path with no network.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from shad.git import apply, discover, refs
from shad.git import plan as planning
from shad.git.model import BranchInfo

_ISOLATE = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "shad test",
    "GIT_AUTHOR_EMAIL": "shad@example.invalid",
    "GIT_COMMITTER_NAME": "shad test",
    "GIT_COMMITTER_EMAIL": "shad@example.invalid",
    "LC_ALL": "C",
}


def _git(cwd: Path, *args: str) -> str:
    """Run git for fixture building, isolated from the developer's config."""
    env = {**os.environ, **_ISOLATE}
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return result.stdout.strip()


def _commit(cwd: Path, filename: str, body: str, message: str) -> str:
    (cwd / filename).write_text(body)
    _git(cwd, "add", filename)
    _git(cwd, "commit", "-m", message)
    return _git(cwd, "rev-parse", "HEAD")


@unittest.skipUnless(shutil.which("git"), "git not installed")
class RealRepoTests(unittest.TestCase):
    tmp: tempfile.TemporaryDirectory[str]
    remote: Path
    clone: Path

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)

        origin_work = root / "origin-work"
        origin_work.mkdir()
        _git(root, "init", "--quiet", "--initial-branch=main", str(origin_work))
        _commit(origin_work, "README.md", "one\n", "Add readme")

        # merged/         -> plain merge into main
        # squashed/       -> squash-merged, then the remote branch is deleted
        # unpushed/       -> pushed, then one extra local-only commit
        # stale/          -> exists only locally, never had an upstream
        _git(origin_work, "switch", "--quiet", "-c", "feat/merged")
        _commit(origin_work, "merged.txt", "m\n", "Add merged")
        _git(origin_work, "switch", "--quiet", "main")
        _git(origin_work, "merge", "--no-ff", "--quiet", "-m", "Merge merged", "feat/merged")

        _git(origin_work, "switch", "--quiet", "-c", "feat/squashed", "main")
        _commit(origin_work, "sq1.txt", "a\n", "Squash part one")
        _commit(origin_work, "sq2.txt", "b\n", "Squash part two")

        _git(origin_work, "switch", "--quiet", "-c", "feat/unpushed", "main")
        _commit(origin_work, "up.txt", "u\n", "Add unpushed base")

        _git(origin_work, "switch", "--quiet", "main")

        cls.remote = root / "remote.git"
        _git(root, "clone", "--quiet", "--bare", str(origin_work), str(cls.remote))

        cls.clone = root / "clone"
        _git(root, "clone", "--quiet", str(cls.remote), str(cls.clone))

        for name in ("feat/merged", "feat/squashed", "feat/unpushed"):
            _git(cls.clone, "branch", "--quiet", "--track", name, f"origin/{name}")

        # One local-only commit on feat/unpushed, so it is ahead of its upstream.
        _git(cls.clone, "switch", "--quiet", "feat/unpushed")
        _commit(cls.clone, "local.txt", "l\n", "Local only")
        _git(cls.clone, "switch", "--quiet", "main")

        # A branch that never had an upstream.
        _git(cls.clone, "branch", "--quiet", "scratch", "main")

        # Squash-merge feat/squashed into the remote's main, then delete the
        # remote branch — the exact shape a merged GitHub PR leaves behind.
        _git(origin_work, "merge", "--quiet", "--squash", "feat/squashed")
        _git(origin_work, "commit", "-m", "Squash feat/squashed")
        _git(origin_work, "push", "--quiet", str(cls.remote), "main")
        _git(cls.remote, "branch", "--quiet", "-D", "feat/squashed")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    # ── detection ─────────────────────────────────────────────────────────

    def test_discover_returns_the_clone_root(self) -> None:
        found = discover.discover(self.clone)
        self.assertEqual(found.root, self.clone.resolve())
        self.assertFalse(found.shallow)
        self.assertIsNone(found.relinked_from)

    def test_discover_refuses_a_subdirectory_of_a_repository(self) -> None:
        sub = self.clone / "sub"
        sub.mkdir(exist_ok=True)
        with self.assertRaises(discover.NotUsable) as ctx:
            discover.discover(sub)
        self.assertIn("is not its root", str(ctx.exception))

    def test_discover_refuses_a_non_repository(self) -> None:
        outside = Path(self.tmp.name) / "plain"
        outside.mkdir(exist_ok=True)
        with self.assertRaises(discover.NotUsable) as ctx:
            discover.discover(outside)
        self.assertIn("not a git repository", str(ctx.exception))

    def test_in_progress_is_none_on_a_quiet_repository(self) -> None:
        self.assertIsNone(discover.in_progress(self.clone))

    # ── refs ──────────────────────────────────────────────────────────────

    def test_list_branches_reports_upstream_and_tracking(self) -> None:
        branches = {b.name: b for b in refs.list_branches(self.clone)}

        self.assertIn("main", branches)
        self.assertEqual(branches["feat/merged"].upstream, "refs/remotes/origin/feat/merged")
        self.assertEqual(branches["feat/merged"].remotename, "origin")

        # One local commit on top of the upstream is reported as ahead.
        self.assertEqual(branches["feat/unpushed"].trackshort, ">")

        # A branch that never had an upstream reports neither.
        self.assertEqual(branches["scratch"].upstream, "")
        self.assertEqual(branches["scratch"].remotename, "")

    def test_snapshot_remotes_reads_refs_and_flags_the_symref(self) -> None:
        remote_refs, symrefs = refs.snapshot_remotes(self.clone)
        self.assertIn("refs/remotes/origin/main", remote_refs)
        self.assertEqual(len(remote_refs["refs/remotes/origin/main"]), 40)
        self.assertIn("refs/remotes/origin/HEAD", symrefs)

    def test_default_branch_resolves_without_network(self) -> None:
        self.assertEqual(
            refs.default_branch(self.clone, "origin", allow_network=False), "main"
        )

    def test_has_full_refspec_is_true_for_a_normal_clone(self) -> None:
        self.assertTrue(refs.has_full_refspec(self.clone, "origin"))

    def test_is_ancestor_answers_true_false_and_unknown(self) -> None:
        main = refs.ref_oid(self.clone, "refs/heads/main")
        merged = refs.ref_oid(self.clone, "refs/heads/feat/merged")
        assert main and merged
        self.assertIs(refs.is_ancestor(self.clone, merged, main), True)
        self.assertIs(refs.is_ancestor(self.clone, main, merged), False)
        self.assertIsNone(refs.is_ancestor(self.clone, "0" * 40, main))

    # ── worktrees ─────────────────────────────────────────────────────────

    def test_list_worktrees_parses_records_and_lists_main_first(self) -> None:
        added = Path(self.tmp.name) / "wt-merged"
        _git(self.clone, "worktree", "add", "--quiet", str(added), "feat/merged")
        try:
            worktrees = refs.list_worktrees(self.clone)
            self.assertEqual(worktrees[0].path, self.clone.resolve())
            self.assertFalse(worktrees[0].locked)

            by_path = {w.path: w for w in worktrees}
            entry = by_path[added.resolve()]
            self.assertEqual(entry.branch, "refs/heads/feat/merged")
            self.assertFalse(entry.detached)
            self.assertFalse(entry.prunable)
            self.assertEqual(len(entry.head or ""), 40)
        finally:
            _git(self.clone, "worktree", "remove", "--force", str(added))

    def test_list_worktrees_marks_a_deleted_directory_prunable(self) -> None:
        added = Path(self.tmp.name) / "wt-gone"
        _git(self.clone, "worktree", "add", "--quiet", "--detach", str(added))
        shutil.rmtree(added)
        try:
            entry = {w.path: w for w in refs.list_worktrees(self.clone)}[added.resolve()]
            self.assertTrue(entry.prunable)
            self.assertTrue(entry.prunable_reason)
        finally:
            _git(self.clone, "worktree", "prune")

    def test_list_worktrees_reports_a_locked_record(self) -> None:
        added = Path(self.tmp.name) / "wt-locked"
        _git(self.clone, "worktree", "add", "--quiet", "--detach", str(added))
        _git(self.clone, "worktree", "lock", "--reason", "on a usb stick", str(added))
        try:
            entry = {w.path: w for w in refs.list_worktrees(self.clone)}[added.resolve()]
            self.assertTrue(entry.locked)
            self.assertEqual(entry.locked_reason, "on a usb stick")
        finally:
            _git(self.clone, "worktree", "unlock", str(added))
            _git(self.clone, "worktree", "remove", "--force", str(added))

    # ── fetch and the squash-merge rule ───────────────────────────────────

    def test_fetch_prune_and_the_squash_merged_branch_rule(self) -> None:
        before, symrefs = refs.snapshot_remotes(self.clone)

        result = apply.fetch(self.clone, "origin", prune=True)
        self.assertTrue(result.ok, result.error)

        after, _ = refs.snapshot_remotes(self.clone)
        pruned = {
            ref: before[ref]
            for ref in before.keys() - after.keys()
            if ref not in symrefs
        }
        self.assertIn("refs/remotes/origin/feat/squashed", pruned)

        branches = {b.name: b for b in refs.list_branches(self.clone)}
        main_tip = refs.ref_oid(self.clone, "refs/remotes/origin/main")
        assert main_tip

        # The squash-merged branch is NOT an ancestor of main — this is exactly
        # why `git branch -d` refuses it and why clause (b) exists.
        squashed = branches["feat/squashed"]
        self.assertIs(refs.is_ancestor(self.clone, squashed.oid, main_tip), False)

        verdict = planning.classify_branch(
            self.clone,
            squashed,
            default_tips=[main_tip],
            checked_out={},
            pruned_oids=pruned,
            gone_allowed=True,
            shallow=False,
        )
        self.assertIsInstance(verdict, BranchInfo)
        assert isinstance(verdict, BranchInfo)
        self.assertEqual(verdict.reason, "pushed-then-gone")
        self.assertTrue(verdict.force)

    def test_classify_branches_keeps_unpushed_and_upstreamless_branches(self) -> None:
        main_tip = refs.ref_oid(self.clone, "refs/remotes/origin/main")
        assert main_tip
        result = planning.classify_branches(
            self.clone,
            refs.list_branches(self.clone),
            default="main",
            default_tips=[main_tip],
            checked_out={"refs/heads/main": self.clone},
            pruned_oids={},
            gone_allowed=True,
            shallow=False,
        )
        kept = {k.name: k.reason for k in result.keep}
        deleted = {d.name: d.reason for d in result.delete}

        self.assertNotIn("main", kept)
        self.assertNotIn("main", deleted)
        self.assertEqual(kept["feat/unpushed"], "unpushed commits")
        self.assertEqual(kept["scratch"], "no upstream")
        self.assertEqual(deleted["feat/merged"], "merged")

    def test_classify_branches_deletes_nothing_in_a_shallow_clone(self) -> None:
        main_tip = refs.ref_oid(self.clone, "refs/remotes/origin/main")
        assert main_tip
        result = planning.classify_branches(
            self.clone,
            refs.list_branches(self.clone),
            default="main",
            default_tips=[main_tip],
            checked_out={},
            pruned_oids={},
            gone_allowed=True,
            shallow=True,
        )
        self.assertEqual(result.delete, [])
        self.assertTrue(all(k.reason == "shallow clone" for k in result.keep))


if __name__ == "__main__":
    unittest.main()
