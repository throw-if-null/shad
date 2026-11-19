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

import io
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shad.config import Project
from shad.git import apply, discover, refs
from shad.git.model import BranchInfo, Worktree, WorktreeKept
from shad.git.panel import snapshot
from shad.git.sync import command as C
from shad.git.sync import plan as planning
from shad.output import Output

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
            merged=refs.merged_branches(self.clone, main_tip),
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


@unittest.skipUnless(shutil.which("git"), "git not installed")
class SecondRemoteTests(unittest.TestCase):
    """
    A clone with `origin` and `upstream`, the ordinary fork layout.

    The ref snapshot covers all of refs/remotes while `ls-remote` only ever
    describes one remote, so the dry-run path has to filter by remote. Without
    that, every `upstream/*` ref reads as stale and a branch tracking a live
    `upstream/feat` is offered for deletion — a preview the real run would not
    honour. Only a fixture with two real remotes catches it.
    """

    tmp: tempfile.TemporaryDirectory[str]
    clone: Path

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)

        seed = root / "seed"
        seed.mkdir()
        _git(root, "init", "--quiet", "--initial-branch=main", str(seed))
        _commit(seed, "README.md", "one\n", "Add readme")
        _git(seed, "switch", "--quiet", "-c", "feat")
        _commit(seed, "feat.txt", "f\n", "Add feat")
        _git(seed, "switch", "--quiet", "main")

        origin = root / "origin.git"
        upstream = root / "upstream.git"
        _git(root, "clone", "--quiet", "--bare", str(seed), str(origin))
        _git(root, "clone", "--quiet", "--bare", str(seed), str(upstream))

        cls.clone = root / "clone"
        _git(root, "clone", "--quiet", str(origin), str(cls.clone))
        _git(cls.clone, "remote", "add", "upstream", str(upstream))
        _git(cls.clone, "fetch", "--quiet", "upstream")
        # Tracks upstream, which still very much has the branch.
        _git(cls.clone, "branch", "--quiet", "--track", "feat", "upstream/feat")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def _plan(self, *, dry_run: bool) -> C.ProjectPlan:
        project = Project(key="fork", group=None, path=self.clone, session="fork")
        return C.fetch_and_plan(project, dry_run=dry_run)

    def test_dry_run_does_not_call_a_live_second_remote_stale(self) -> None:
        plan = self._plan(dry_run=True)
        self.assertEqual(plan.status, "ok", plan.detail)
        self.assertEqual(plan.pruned_refs, [])
        self.assertEqual([b.name for b in plan.branch_deletions], [])

    def test_the_applied_run_agrees_with_the_preview(self) -> None:
        plan = self._plan(dry_run=False)
        self.assertEqual(plan.status, "ok", plan.detail)
        self.assertEqual(plan.pruned_refs, [])
        self.assertEqual([b.name for b in plan.branch_deletions], [])
        self.assertIn("feat", [k.name for k in plan.branches_kept])


@unittest.skipUnless(shutil.which("git"), "git not installed")
class NoRemoteTests(unittest.TestCase):
    """A repository with no remote is skipped with a reason, not called synced."""

    def test_a_repository_with_no_remote_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            repo = root / "local"
            repo.mkdir()
            _git(root, "init", "--quiet", "--initial-branch=main", str(repo))
            _commit(repo, "README.md", "one\n", "Add readme")

            project = Project(key="local", group=None, path=repo, session="local")
            plan = C.fetch_and_plan(project)

        # Not "ok": the report prints `detail` only for skipped and failed
        # projects, so an "ok" plan with nothing else to show renders as
        # "up to date" and the reason is lost.
        self.assertEqual(plan.status, "skipped")
        self.assertEqual(plan.detail, "no remote configured")


@unittest.skipUnless(shutil.which("git"), "git not installed")
class SwitchDefaultTests(unittest.TestCase):
    """
    --switch against a real clone, sitting on a merged branch.

    The interaction that matters: switching un-pins the branch it leaves
    behind, so a branch that was only kept because the main worktree had it
    checked out becomes deletable in the *same* run. A mocked test cannot show
    that, because it depends on git actually moving HEAD between the two reads
    of `worktree list`.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)

        seed = root / "seed"
        seed.mkdir()
        _git(root, "init", "--quiet", "--initial-branch=main", str(seed))
        _commit(seed, "README.md", "one\n", "Add readme")
        _git(seed, "switch", "--quiet", "-c", "feat/merged")
        _commit(seed, "merged.txt", "m\n", "Add merged")
        _git(seed, "switch", "--quiet", "main")
        _git(seed, "merge", "--no-ff", "--quiet", "-m", "Merge merged", "feat/merged")

        remote = root / "remote.git"
        _git(root, "clone", "--quiet", "--bare", str(seed), str(remote))

        self.clone = root / "clone"
        _git(root, "clone", "--quiet", str(remote), str(self.clone))
        _git(self.clone, "branch", "--quiet", "--track", "feat/merged", "origin/feat/merged")
        # The user is sitting on the merged branch.
        _git(self.clone, "switch", "--quiet", "feat/merged")

        self.project = Project(
            key="proj", group=None, path=self.clone, session="proj"
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _head(self) -> str:
        return _git(self.clone, "rev-parse", "--abbrev-ref", "HEAD")

    def test_without_switch_the_checked_out_branch_is_pinned(self) -> None:
        plan = C.fetch_and_plan(self.project)
        self.assertIsNone(plan.switch)
        self.assertEqual(self._head(), "feat/merged")
        self.assertEqual([b.name for b in plan.branch_deletions], [])
        kept = {k.name: k.reason for k in plan.branches_kept}
        self.assertIn("feat/merged", kept)
        self.assertIn("checked out at", kept["feat/merged"])

    def test_switching_un_pins_the_branch_it_leaves_behind(self) -> None:
        plan = C.fetch_and_plan(self.project, switch=True)
        assert plan.switch is not None
        self.assertEqual(plan.switch.status, "switched")
        self.assertEqual(plan.switch.from_branch, "feat/merged")
        self.assertEqual(self._head(), "main")
        # The whole point: it is deletable now, not on the next run.
        self.assertEqual([b.name for b in plan.branch_deletions], ["feat/merged"])

    def test_dry_run_reports_the_switch_without_moving_head(self) -> None:
        plan = C.fetch_and_plan(self.project, dry_run=True, switch=True)
        assert plan.switch is not None
        self.assertEqual(plan.switch.detail, "would switch")
        self.assertEqual(self._head(), "feat/merged")

    def test_dry_run_previews_the_deletion_the_switch_unlocks(self) -> None:
        # The switch does not happen under --dry-run, so the un-pinning has to
        # be modelled — otherwise the preview keeps a branch the real run
        # would offer for deletion.
        plan = C.fetch_and_plan(self.project, dry_run=True, switch=True)
        self.assertEqual(self._head(), "feat/merged")
        self.assertEqual([b.name for b in plan.branch_deletions], ["feat/merged"])
        self.assertNotIn("feat/merged", [k.name for k in plan.branches_kept])

    def test_dry_run_without_switch_still_keeps_the_pinned_branch(self) -> None:
        plan = C.fetch_and_plan(self.project, dry_run=True)
        self.assertEqual([b.name for b in plan.branch_deletions], [])
        self.assertIn("feat/merged", [k.name for k in plan.branches_kept])

    def test_a_dirty_tree_is_skipped_and_keeps_its_branch(self) -> None:
        (self.clone / "README.md").write_text("dirty\n")
        plan = C.fetch_and_plan(self.project, switch=True)
        assert plan.switch is not None
        self.assertEqual(plan.switch.status, "skipped")
        self.assertEqual(plan.switch.detail, "1 uncommitted change(s)")
        self.assertEqual(self._head(), "feat/merged")
        self.assertEqual([b.name for b in plan.branch_deletions], [])


@unittest.skipUnless(shutil.which("git"), "git not installed")
class RepoDedupeTests(unittest.TestCase):
    """
    Two configured directories, one repository.

    A linked worktree shares its ref store with the main worktree, so planning
    both would list the same branch twice in the confirmation table and report
    the second apply as failures. Two *clones* of one remote are genuinely
    separate repositories and must both be synced — the identity has to be
    --git-common-dir, which tells those cases apart.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

        seed = self.root / "seed"
        seed.mkdir()
        _git(self.root, "init", "--quiet", "--initial-branch=main", str(seed))
        _commit(seed, "README.md", "one\n", "Add readme")
        _git(seed, "switch", "--quiet", "-c", "feat/login")
        _commit(seed, "login.txt", "l\n", "Add login")
        _git(seed, "switch", "--quiet", "main")
        _git(seed, "merge", "--no-ff", "--quiet", "-m", "Merge login", "feat/login")

        self.remote = self.root / "remote.git"
        _git(self.root, "clone", "--quiet", "--bare", str(seed), str(self.remote))

    def _clone(self, name: str) -> Path:
        target = self.root / name
        _git(self.root, "clone", "--quiet", str(self.remote), str(target))
        return target

    def _project(self, name: str, path: Path) -> Project:
        return Project(key=name, group=None, path=path, session=name)

    def _plans(self, projects: list[Project]) -> list:
        plans: list = [None] * len(projects)
        jobs = C._resolve(projects, plans)
        return [plans, jobs]

    def test_a_linked_worktree_is_skipped_as_the_same_repository(self) -> None:
        main = self._clone("myproj")
        _git(main, "branch", "--quiet", "--track", "feat/login", "origin/feat/login")
        linked = self.root / "myproj-login"
        _git(main, "worktree", "add", "--quiet", str(linked), "feat/login")

        projects = [self._project("myproj", main), self._project("login", linked)]
        plans, jobs = self._plans(projects)

        # Only the first is planned; the second is reported, not silently dropped.
        self.assertEqual([p.key for _i, p, _r in jobs], ["myproj"])
        assert plans[1] is not None
        self.assertEqual(plans[1].status, "skipped")
        self.assertEqual(plans[1].detail, "same repository as myproj")

    def test_the_repository_root_wins_over_a_linked_worktree(self) -> None:
        # Even when the worktree is configured first: it is the directory the
        # work happens in, and it needs no re-rooting.
        main = self._clone("myproj")
        linked = self.root / "myproj-login"
        _git(main, "worktree", "add", "--quiet", str(linked), "-b", "wip")

        projects = [self._project("login", linked), self._project("myproj", main)]
        plans, jobs = self._plans(projects)

        self.assertEqual([p.key for _i, p, _r in jobs], ["myproj"])
        assert plans[0] is not None
        self.assertEqual(plans[0].detail, "same repository as myproj")

    def test_two_clones_of_one_remote_are_both_synced(self) -> None:
        a = self._clone("cloneA")
        b = self._clone("cloneB")
        # Each clone carries its own local work, so each needs its own pass.
        _git(a, "switch", "--quiet", "-c", "work-a")
        _git(b, "switch", "--quiet", "-c", "work-b")

        projects = [self._project("a", a), self._project("b", b)]
        plans, jobs = self._plans(projects)

        self.assertEqual([p.key for _i, p, _r in jobs], ["a", "b"])
        self.assertEqual([p for p in plans if p is not None], [])

    def test_a_full_run_over_the_duplicate_reports_no_failures(self) -> None:
        main = self._clone("myproj")
        _git(main, "branch", "--quiet", "--track", "feat/login", "origin/feat/login")
        linked = self.root / "myproj-login"
        _git(main, "worktree", "add", "--quiet", str(linked), "feat/login")

        projects = [self._project("myproj", main), self._project("login", linked)]
        with patch.object(C, "report"):
            run = C.sync_projects(projects, Output(stdout=io.StringIO()), yes=True)

        # The merged branch and its worktree go exactly once, with no
        # "already gone" noise from a second pass over the same repository.
        deleted = [b.name for o in run.outcomes for b in o.deleted_branches]
        removed = [str(p) for o in run.outcomes for p in o.removed_worktrees]
        failures = [f for o in run.outcomes for f in o.failures]
        self.assertEqual(deleted, ["feat/login"])
        self.assertEqual(removed, [str(linked)])
        self.assertEqual(failures, [])


@unittest.skipUnless(shutil.which("git"), "git not installed")
class BareWorktreeTests(unittest.TestCase):
    """
    A bare repository must stay unreachable, including through its worktrees.

    discover() refuses a bare path directly, but a linked worktree re-roots
    onto its main worktree — which for a bare-hub layout *is* the bare
    directory. That would put a bare record at index 0 of every later worktree
    scan and the user's own working directory at index 1, where
    classify_worktrees treats it as a removal candidate.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

        seed = self.root / "seed"
        seed.mkdir()
        _git(self.root, "init", "--quiet", "--initial-branch=main", str(seed))
        _commit(seed, "README.md", "one\n", "Add readme")

        self.bare = self.root / "repo.git"
        _git(self.root, "clone", "--quiet", "--bare", str(seed), str(self.bare))
        self.worktree = self.root / "wt-main"
        _git(self.bare, "worktree", "add", "--quiet", str(self.worktree), "main")

    def test_the_bare_directory_itself_is_refused(self) -> None:
        with self.assertRaises(discover.NotUsable):
            discover.discover(self.bare)

    def test_a_worktree_of_a_bare_repository_is_refused(self) -> None:
        with self.assertRaises(discover.NotUsable) as ctx:
            discover.discover(self.worktree)
        self.assertIn("bare repository", str(ctx.exception))

    def test_the_project_is_skipped_rather_than_planned(self) -> None:
        project = Project(
            key="hub", group=None, path=self.worktree, session="hub"
        )
        plan = C.fetch_and_plan(project)
        self.assertEqual(plan.status, "skipped")
        # Above all: the user's own working directory is not a candidate.
        self.assertEqual(plan.worktree_removals, [])


@unittest.skipUnless(shutil.which("git"), "git not installed")
class WorktreePruneAgreementTests(unittest.TestCase):
    """shad must never plan a removal `git worktree prune` will not perform."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

        self.repo = self.root / "repo"
        self.repo.mkdir()
        _git(self.root, "init", "--quiet", "--initial-branch=main", str(self.repo))
        _commit(self.repo, "README.md", "one\n", "Add readme")
        self.wt = self.root / "wt"
        _git(self.repo, "worktree", "add", "--quiet", str(self.wt), "-b", "x")

    def _classify(self):
        worktrees = refs.list_worktrees(self.repo)
        return planning.classify_worktrees(
            self.repo, worktrees, deleting=set(), known_branches={"refs/heads/x"}
        )

    def test_a_deleted_directory_is_prunable_and_planned(self) -> None:
        shutil.rmtree(self.wt)
        # git marks this prunable immediately: the gitdir file points nowhere.
        plan = self._classify()
        self.assertEqual([str(w.path) for w in plan.remove], [str(self.wt)])
        self.assertTrue(plan.remove[0].prune_only)

    def test_a_missing_directory_git_will_not_prune_is_kept(self) -> None:
        # Stand in for an unmounted disk: the directory is unreachable, but the
        # admin record is intact, so git does not call it prunable.
        records = refs.list_worktrees(self.repo)
        intact = [w for w in records if w.path == self.wt]
        self.assertTrue(intact and not intact[0].prunable)

        gone = Worktree(path=self.root / "never-mounted", branch="refs/heads/x")
        verdict = planning.classify_worktree(
            self.repo, gone, deleting=set(), known_branches={"refs/heads/x"}
        )
        self.assertIsInstance(verdict, WorktreeKept)
        assert isinstance(verdict, WorktreeKept)
        self.assertIn("does not consider it prunable", verdict.reason)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(shutil.which("git"), "git not installed")
class SnapshotTests(unittest.TestCase):
    """
    snapshot.collect against a real repository.

    The stash reflog is the reason this class exists. `stash list` belongs to
    the log pretty-format family, which does not interpret the `%00` escape
    the rest of the slice uses, and `-z` frames records with the same NUL that
    separates fields. Both are external contracts a faked stdout cannot check.
    """

    tmp: tempfile.TemporaryDirectory[str]
    remote: Path
    clone: Path

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)

        work = root / "work"
        work.mkdir()
        _git(root, "init", "--quiet", "--initial-branch=main", str(work))
        _commit(work, "README.md", "one\n", "Add readme")

        cls.remote = root / "remote.git"
        _git(root, "clone", "--quiet", "--bare", str(work), str(cls.remote))

        cls.clone = root / "clone"
        _git(root, "clone", "--quiet", str(cls.remote), str(cls.clone))

        # A branch with no upstream, and one linked worktree holding it.
        _git(cls.clone, "branch", "--quiet", "side", "main")
        _git(cls.clone, "worktree", "add", "--quiet", str(root / "wt-side"), "side")
        _git(cls.clone, "worktree", "add", "--quiet", "--detach", str(root / "wt-det"))

        # Three stashes: a custom message, a WIP, and one made on `side`.
        (cls.clone / "README.md").write_text("dirty one\n")
        _git(cls.clone, "stash", "push", "--quiet", "-m", "custom: with a colon")
        (cls.clone / "README.md").write_text("dirty two\n")
        _git(cls.clone, "stash", "push", "--quiet")

        # The remote advances, so `behind` is non-zero after a fetch.
        _commit(work, "second.txt", "two\n", "Add second")
        _git(work, "push", "--quiet", str(cls.remote), "main")

    @classmethod
    def tearDownClass(cls) -> None:
        # Worktrees hold open handles under the temp dir on some platforms.
        _git(cls.clone, "worktree", "prune")
        cls.tmp.cleanup()

    def _collect(self, *, fetch: bool) -> snapshot.Snapshot:
        return snapshot.collect(discover.discover(self.clone), fetch=fetch)

    def test_local_collect_reports_head_branches_worktrees_and_stashes(self) -> None:
        snap = self._collect(fetch=False)
        self.assertEqual(snap.head, "main")
        self.assertEqual(snap.git_version.split(".")[0], "2")
        self.assertEqual(
            sorted(b.name for b in snap.branches), ["main", "side"]
        )
        self.assertEqual(len(snap.worktrees), 3)
        self.assertEqual(len(snap.stashes), 2)
        self.assertIsNone(snap.fetch_error)

    def test_stash_records_survive_a_message_containing_the_separator(self) -> None:
        stashes = self._collect(fetch=False).stashes
        # Newest first, as `stash list` orders them.
        self.assertEqual([s.ref for s in stashes], ["stash@{0}", "stash@{1}"])
        self.assertTrue(all(s.branch == "main" for s in stashes))
        self.assertEqual(stashes[1].message, "custom: with a colon")
        self.assertTrue(all(s.timestamp > 0 for s in stashes))

    def test_worktrees_report_their_branch_and_detached_state(self) -> None:
        worktrees = self._collect(fetch=False).worktrees
        by_name = {w.path.name: w for w in worktrees}
        self.assertEqual(by_name["clone"].branch, "refs/heads/main")
        self.assertEqual(by_name["wt-side"].branch, "refs/heads/side")
        self.assertTrue(by_name["wt-det"].detached)
        self.assertIsNone(by_name["wt-det"].branch)

    def test_checked_out_covers_every_worktree_not_just_the_main_one(self) -> None:
        snap = self._collect(fetch=False)
        self.assertEqual(
            snap.checked_out, {"refs/heads/main", "refs/heads/side"}
        )

    def test_a_branch_without_an_upstream_reports_none(self) -> None:
        snap = self._collect(fetch=False)
        side = next(b for b in snap.branches if b.name == "side")
        self.assertEqual(side.upstream, "")

    def test_fetch_reports_the_commits_available_to_pull(self) -> None:
        snap = self._collect(fetch=True)
        self.assertIsNone(snap.fetch_error)
        self.assertIsNotNone(snap.fetched_at)
        self.assertEqual(snap.remote, "origin")
        self.assertEqual(snap.head_upstream, "refs/remotes/origin/main")
        self.assertEqual(snap.behind, 1)
        self.assertEqual(snap.ahead, 0)

    def test_the_panel_fetch_does_not_prune(self) -> None:
        # A viewer must leave the remote-tracking refs that `shad git sync`
        # reads as proof a gone branch was fully pushed.
        _git(self.clone, "update-ref", "refs/remotes/origin/ghost", "HEAD")
        snap = self._collect(fetch=True)
        self.assertIsNone(snap.fetch_error)
        self.assertTrue(refs.ref_exists(self.clone, "refs/remotes/origin/ghost"))
        _git(self.clone, "update-ref", "-d", "refs/remotes/origin/ghost")

    def test_an_unreachable_remote_still_yields_local_state(self) -> None:
        _git(self.clone, "remote", "set-url", "origin", str(self.clone / "nope.git"))
        try:
            snap = self._collect(fetch=True)
        finally:
            _git(self.clone, "remote", "set-url", "origin", str(self.remote))
        self.assertIsNotNone(snap.fetch_error)
        self.assertIsNone(snap.fetched_at)
        self.assertEqual(len(snap.branches), 2)
        self.assertEqual(len(snap.stashes), 2)


@unittest.skipUnless(shutil.which("git"), "git not installed")
class FormatDialectTests(unittest.TestCase):
    """
    The external fact behind run._check_format_dialect.

    git's ref-filter and pretty-format languages spell a NUL differently and
    each emits the other's spelling as literal text, exiting 0 either way.
    The guard encodes that; this proves it against the installed git, so a
    future release that changed it would fail here rather than leave the
    guard rejecting formats that had become valid.
    """

    tmp: tempfile.TemporaryDirectory[str]
    repo: Path

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.repo = Path(cls.tmp.name) / "repo"
        cls.repo.mkdir()
        _git(Path(cls.tmp.name), "init", "--quiet", "--initial-branch=main", str(cls.repo))
        _commit(cls.repo, "f.txt", "one\n", "Add f")
        (cls.repo / "f.txt").write_text("two\n")
        _git(cls.repo, "stash", "push", "--quiet", "-m", "a message")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_for_each_ref_expands_percent_00_and_not_percent_x00(self) -> None:
        good = _git(self.repo, "for-each-ref", "--format=%(refname)%00%(objectname)")
        self.assertIn("\x00", good)

        bad = _git(self.repo, "for-each-ref", "--format=%(refname)%x00%(objectname)")
        self.assertNotIn("\x00", bad)
        self.assertIn("%x00", bad)

    def test_stash_list_expands_percent_x00_and_not_percent_00(self) -> None:
        good = _git(self.repo, "stash", "list", "--format=%gd%x00%gs")
        self.assertIn("\x00", good)

        bad = _git(self.repo, "stash", "list", "--format=%gd%00%gs")
        self.assertNotIn("\x00", bad)
        self.assertIn("%00", bad)

    def test_the_wrong_escape_is_not_an_error_which_is_why_a_guard_exists(self) -> None:
        # Exit 0, empty stderr: nothing downstream can detect the mistake.
        env = {**os.environ, **_ISOLATE}
        result = subprocess.run(
            ["git", "-C", str(self.repo), "stash", "list", "--format=%gd%00%gs"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")


@unittest.skipUnless(shutil.which("git"), "git not installed")
class StatusQueryTests(unittest.TestCase):
    """
    latest_tag and recent_commits against a real repository.

    `shad projects ... status` renders these, and both are log/describe
    commands whose formats and exit codes are external contracts.
    """

    tmp: tempfile.TemporaryDirectory[str]
    repo: Path
    empty: Path

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)

        cls.repo = root / "repo"
        cls.repo.mkdir()
        _git(root, "init", "--quiet", "--initial-branch=main", str(cls.repo))
        _commit(cls.repo, "a.txt", "one\n", "Add a")
        _git(cls.repo, "tag", "v0.1.0")
        _commit(cls.repo, "b.txt", "two\n", "fix: add b")

        cls.empty = root / "empty"
        cls.empty.mkdir()
        _git(root, "init", "--quiet", "--initial-branch=main", str(cls.empty))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_latest_tag_finds_a_reachable_tag(self) -> None:
        self.assertEqual(refs.latest_tag(self.repo), "v0.1.0")

    def test_latest_tag_is_empty_when_there_are_no_tags(self) -> None:
        self.assertEqual(refs.latest_tag(self.empty), "")

    def test_recent_commits_are_newest_first_with_real_timestamps(self) -> None:
        commits = refs.recent_commits(self.repo, 3)
        self.assertEqual([c.subject for c in commits], ["fix: add b", "Add a"])
        self.assertTrue(all(c.timestamp > 0 for c in commits))
        self.assertTrue(all(c.short_oid for c in commits))

    def test_recent_commits_honours_the_count(self) -> None:
        self.assertEqual(len(refs.recent_commits(self.repo, 1)), 1)

    def test_recent_commits_on_an_unborn_head_is_empty(self) -> None:
        self.assertEqual(refs.recent_commits(self.empty, 3), [])

    def test_an_inherited_git_dir_cannot_retarget_the_query(self) -> None:
        # The bug this migration fixed: a bare subprocess with cwd= reported
        # whichever repository GIT_DIR named, not the project.
        with patch.dict(
            os.environ,
            {"GIT_DIR": str(self.empty / ".git"), "GIT_WORK_TREE": str(self.empty)},
        ):
            self.assertEqual(refs.latest_tag(self.repo), "v0.1.0")
            self.assertEqual(len(refs.recent_commits(self.repo, 3)), 2)
            self.assertEqual(discover.head_branch(self.repo), "refs/heads/main")
