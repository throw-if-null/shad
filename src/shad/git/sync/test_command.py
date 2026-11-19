from __future__ import annotations

import io
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

from shad.config.load import Project
from shad.errors import ShadError
from shad.git import apply, refs
from shad.git.model import BranchInfo, ProjectOutcome, ProjectPlan, Repo, WorktreeInfo
from shad.git.sync import command as C
from shad.git.testing import GitCase, git, words
from shad.output import Output

ROOT = Path("/tmp/repo")


def _out() -> Output:
    """An Output nothing reads: these tests assert on the run, not the report."""
    return Output(stdout=io.StringIO(), stderr=io.StringIO())


def _project(key: str, group: str | None = None) -> Project:
    return Project(
        key=key,
        group=group,
        path=Path("/tmp") / key,
        session=f"{group}-{key}" if group else key,
    )


def _plan(
    project: Project | None = None,
    *,
    status: str = "ok",
    branches: list[BranchInfo] | None = None,
    worktrees: list[WorktreeInfo] | None = None,
) -> ProjectPlan:
    return ProjectPlan(
        project=project or _project("kb"),
        status=status,
        repo_root=ROOT,
        branch_deletions=branches or [],
        worktree_removals=worktrees or [],
    )


def _branch(
    name: str = "feat",
    sha: str = "abc1234",
    force: bool = False,
    oid: str = "abc1234def",
) -> BranchInfo:
    return BranchInfo(name=name, sha=sha, reason="merged", force=force, oid=oid)


def _resolve_all(
    projects: list[Project], plans: list[ProjectPlan | None], trace: object = None
):
    """
    Stand-in for C._resolve: every project resolves to its own repository.

    The orchestration tests use paths that are not repositories, so the real
    discovery pass would skip them all before any planning happened.
    """
    return [
        (index, project, Repo(root=project.path, common_dir=project.path / ".git"))
        for index, project in enumerate(projects)
    ]


def _worktree(path: str = "/tmp/wt", prune_only: bool = False) -> WorktreeInfo:
    return WorktreeInfo(
        path=Path(path), branch="refs/heads/feat", reason="branch is being deleted",
        prune_only=prune_only,
    )


class SyncGateTests(unittest.TestCase):
    """The confirmation gate is the only thing standing in front of deletions."""

    def setUp(self) -> None:
        self.plan = _plan(branches=[_branch()], worktrees=[_worktree()])

    def _run(self, **kwargs: Any) -> tuple[Mock, Mock]:
        with (
            patch.object(C, "require_git"),
            patch.object(C, "_resolve", side_effect=_resolve_all),
            patch.object(C, "fetch_and_plan", return_value=self.plan),
            patch.object(C, "report"),
            patch.object(C, "apply_plan") as apply_plan,
            patch.object(C, "Confirm") as confirm,
        ):
            confirm.ask.return_value = kwargs.pop("answer", False)
            C.sync_projects([_project("kb")], _out(), **kwargs)
        return apply_plan, confirm

    def test_dry_run_never_prompts_and_never_applies(self) -> None:
        apply_plan, confirm = self._run(dry_run=True)
        apply_plan.assert_not_called()
        confirm.ask.assert_not_called()

    def test_yes_skips_the_prompt_but_still_applies(self) -> None:
        apply_plan, confirm = self._run(yes=True)
        confirm.ask.assert_not_called()
        apply_plan.assert_called_once_with(self.plan)

    def test_declining_applies_nothing_and_raises_nothing(self) -> None:
        apply_plan, confirm = self._run(answer=False)
        confirm.ask.assert_called_once()
        apply_plan.assert_not_called()

    def test_accepting_applies(self) -> None:
        apply_plan, confirm = self._run(answer=True)
        confirm.ask.assert_called_once()
        apply_plan.assert_called_once_with(self.plan)

    def test_prompt_defaults_to_no(self) -> None:
        _apply, confirm = self._run(answer=False)
        self.assertIs(confirm.ask.call_args.kwargs["default"], False)

    def test_nothing_pending_never_prompts(self) -> None:
        self.plan = _plan()
        apply_plan, confirm = self._run()
        confirm.ask.assert_not_called()
        apply_plan.assert_not_called()

    def test_declining_marks_the_run_unconfirmed(self) -> None:
        with (
            patch.object(C, "require_git"),
            patch.object(C, "_resolve", side_effect=_resolve_all),
            patch.object(C, "fetch_and_plan", return_value=self.plan),
            patch.object(C, "report"),
            patch.object(C, "apply_plan"),
            patch.object(C, "Confirm") as confirm,
        ):
            confirm.ask.return_value = False
            run = C.sync_projects([_project("kb")], _out())
        self.assertFalse(run.confirmed)


class SyncOrchestrationTests(unittest.TestCase):
    def test_one_failing_project_does_not_abort_the_others(self) -> None:
        projects = [_project("a"), _project("b"), _project("c")]

        def fake(project: Project, **_kw: object) -> ProjectPlan:
            if project.key == "b":
                raise RuntimeError("boom")
            return _plan(project)

        with (
            patch.object(C, "require_git"),
            patch.object(C, "_resolve", side_effect=_resolve_all),
            patch.object(C, "fetch_and_plan", side_effect=fake),
            patch.object(C, "report"),
        ):
            run = C.sync_projects(projects, _out())

        by_key = {o.plan.project.key: o.plan for o in run.outcomes}
        self.assertEqual(len(run.outcomes), 3)
        self.assertEqual(by_key["b"].status, "failed")
        self.assertIn("boom", by_key["b"].detail or "")
        self.assertEqual(by_key["a"].status, "ok")
        self.assertEqual(by_key["c"].status, "ok")

    def test_results_keep_the_caller_order(self) -> None:
        projects = [_project("a"), _project("b"), _project("c")]
        with (
            patch.object(C, "require_git"),
            patch.object(C, "_resolve", side_effect=_resolve_all),
            patch.object(C, "fetch_and_plan", side_effect=lambda p, **_k: _plan(p)),
            patch.object(C, "report"),
        ):
            run = C.sync_projects(projects, _out())
        self.assertEqual([o.plan.project.key for o in run.outcomes], ["a", "b", "c"])

    def test_a_partial_failure_is_not_a_shad_error(self) -> None:
        def fake(project: Project, **_kw: object) -> ProjectPlan:
            if project.key == "a":
                raise RuntimeError("nope")
            return _plan(project)

        with (
            patch.object(C, "require_git"),
            patch.object(C, "_resolve", side_effect=_resolve_all),
            patch.object(C, "fetch_and_plan", side_effect=fake),
            patch.object(C, "report"),
        ):
            run = C.sync_projects([_project("a"), _project("b")], _out())
        self.assertEqual(len(run.outcomes), 2)


class ApplyPlanTests(unittest.TestCase):
    def test_worktrees_are_removed_before_branches_are_deleted(self) -> None:
        # git branch -d refuses a branch a worktree still has checked out, so
        # this ordering is what lets a dead pair go in one run.
        plan = _plan(branches=[_branch()], worktrees=[_worktree()])
        recorder = Mock()

        with (
            patch.object(apply, "remove_worktree", return_value=None) as remove,
            patch.object(apply, "delete_branch", return_value=None) as delete,
            patch.object(apply, "prune_worktrees", return_value=None),
            patch.object(refs, "ref_oid", return_value="abc1234def"),
        ):
            recorder.attach_mock(remove, "remove_worktree")
            recorder.attach_mock(delete, "delete_branch")
            C.apply_plan(plan)

        order = [name for name, _args, _kw in recorder.mock_calls]
        self.assertEqual(order, ["remove_worktree", "delete_branch"])

    def test_prune_only_worktrees_use_prune_not_remove(self) -> None:
        plan = _plan(worktrees=[_worktree(prune_only=True)])
        with (
            patch.object(apply, "prune_worktrees", return_value=None) as prune,
            patch.object(apply, "remove_worktree") as remove,
        ):
            outcome = C.apply_plan(plan)
        prune.assert_called()
        remove.assert_not_called()
        self.assertEqual(outcome.removed_worktrees, [Path("/tmp/wt")])

    def test_a_branch_that_moved_since_planning_is_skipped(self) -> None:
        plan = _plan(branches=[_branch(sha="abc1234")])
        with (
            patch.object(refs, "ref_oid", return_value="9999999fff"),
            patch.object(apply, "delete_branch") as delete,
        ):
            outcome = C.apply_plan(plan)
        delete.assert_not_called()
        self.assertEqual(outcome.deleted_branches, [])
        self.assertIn("moved since the plan was made", outcome.failures[0])

    def test_a_branch_sharing_a_short_prefix_is_not_mistaken_for_the_plan(self) -> None:
        # The re-verification compares full OIDs. Two objects can share a
        # 7-character prefix, and -D has no net.
        plan = _plan(branches=[_branch(sha="abc1234", oid="abc1234def")])
        with (
            patch.object(refs, "ref_oid", return_value="abc1234999"),
            patch.object(apply, "delete_branch") as delete,
        ):
            outcome = C.apply_plan(plan)
        delete.assert_not_called()
        self.assertIn("moved since the plan was made", outcome.failures[0])

    def test_a_branch_that_vanished_is_reported(self) -> None:
        plan = _plan(branches=[_branch()])
        with (
            patch.object(refs, "ref_oid", return_value=None),
            patch.object(apply, "delete_branch") as delete,
        ):
            outcome = C.apply_plan(plan)
        delete.assert_not_called()
        self.assertIn("already gone", outcome.failures[0])

    def test_force_flag_is_carried_through_to_the_delete(self) -> None:
        plan = _plan(branches=[_branch(force=True)])
        with (
            patch.object(refs, "ref_oid", return_value="abc1234def"),
            patch.object(apply, "delete_branch", return_value=None) as delete,
        ):
            C.apply_plan(plan)
        self.assertIs(delete.call_args.kwargs["force"], True)

    def test_one_failed_deletion_does_not_stop_the_rest(self) -> None:
        plan = _plan(branches=[_branch("a"), _branch("b")])
        with (
            patch.object(refs, "ref_oid", return_value="abc1234def"),
            patch.object(apply, "delete_branch", side_effect=["not fully merged", None]),
        ):
            outcome = C.apply_plan(plan)
        self.assertEqual([b.name for b in outcome.deleted_branches], ["b"])
        self.assertIn("branch a: not fully merged", outcome.failures)
class FailureIsolationTests(unittest.TestCase):
    """
    A timeout in one project must never abandon the others.

    run.git raises ShadError on timeout, and two phases now run on the main
    thread outside the pool's per-future guard: the serial discovery pass and
    the apply loop.
    """

    def test_a_discovery_timeout_fails_only_its_own_project(self) -> None:
        projects = [_project("a"), _project("b"), _project("c")]

        def fake(path: Path) -> Repo:
            if path == projects[1].path:
                raise ShadError.infrastructure("git_timeout", "git rev-parse timed out after 15s")
            return Repo(root=path, common_dir=path / ".git")

        plans: list[ProjectPlan | None] = [None] * 3
        with patch.object(C.discover, "discover", side_effect=fake):
            jobs = C._resolve(projects, plans)

        self.assertEqual([p.key for _i, p, _r in jobs], ["a", "c"])
        assert plans[1] is not None
        self.assertEqual(plans[1].status, "failed")
        self.assertIn("timed out", plans[1].detail or "")

    def test_an_apply_timeout_fails_only_its_own_project(self) -> None:
        good, bad = _plan(_project("a"), branches=[_branch()]), _plan(
            _project("b"), branches=[_branch()]
        )

        def fake(plan: ProjectPlan) -> ProjectOutcome:
            if plan.project.key == "b":
                raise ShadError.infrastructure(
                    "git_timeout", "git for-each-ref timed out after 15s"
                )
            return ProjectOutcome(plan=plan, deleted_branches=list(plan.branch_deletions))

        with (
            patch.object(C, "require_git"),
            patch.object(C, "_resolve", side_effect=_resolve_all),
            patch.object(C, "fetch_and_plan", side_effect=lambda p, **_k: {"a": good, "b": bad}[p.key]),
            patch.object(C, "apply_plan", side_effect=fake),
            patch.object(C, "report"),
        ):
            run = C.sync_projects([_project("a"), _project("b")], _out(), yes=True)

        by_key = {o.plan.project.key: o for o in run.outcomes}
        self.assertEqual([b.name for b in by_key["a"].deleted_branches], ["feat"])
        self.assertEqual(by_key["b"].deleted_branches, [])
        self.assertIn("timed out", by_key["b"].failures[0])

    def test_an_oid_timeout_keeps_the_deletions_already_applied(self) -> None:
        # apply_plan must not discard its own accumulated outcome either.
        plan = _plan(branches=[_branch("first"), _branch("second")])
        calls = {"n": 0}

        def fake_oid(_root: Path, refname: str) -> str:
            calls["n"] += 1
            if calls["n"] > 1:
                raise ShadError.infrastructure(
                    "git_timeout", "git for-each-ref timed out after 15s"
                )
            return "abc1234def"

        with (
            patch.object(refs, "ref_oid", side_effect=fake_oid),
            patch.object(apply, "delete_branch", return_value=None),
            patch.object(apply, "prune_worktrees", return_value=None),
        ):
            outcome = C.apply_plan(plan)

        self.assertEqual([b.name for b in outcome.deleted_branches], ["first"])
        self.assertIn("timed out", outcome.failures[0])

    def test_an_unreadable_worktree_list_fails_the_project(self) -> None:
        # Returning [] would mean "no branch is checked out anywhere", which
        # would offer branches held by a linked worktree for deletion.
        project = _project("kb")
        with (
            patch.object(C.discover, "discover", return_value=Repo(root=ROOT, common_dir=ROOT / ".git")),
            patch.object(C.discover, "in_progress", return_value=None),
            patch.object(refs, "list_remotes", return_value=[]),
            patch.object(refs, "list_worktrees", return_value=[]),
        ):
            plan = C.fetch_and_plan(project)

        self.assertEqual(plan.status, "failed")
        self.assertEqual(plan.detail, "could not list worktrees")
        self.assertEqual(plan.branch_deletions, [])


class SyncTests(GitCase):
    """
    Feature:    git/sync
    Boundary:   command. `shad git sync [<group>] [<name>] [--dry-run]
                [--yes] [--switch]` as a process with no terminal, against
                real clones of bare remotes under the test root. Contract:
                exit code + stdout + stderr + the repositories.
    """

    def test_sync_dry_run_reports_deletions_and_deletes_nothing(self) -> None:
        """
        Criterion:  sync-dry-run-reports-deletions-and-deletes-nothing
          Given:    kb tracks feat/merged, which the remote's main has merged.
          When:     `shad git sync kb --dry-run`.
          Then:     exit 0, stderr empty, stdout lists feat/merged under the
                    pending deletions and says nothing was deleted, and the
                    branch still exists.
        """
        self.clone("kb", merged=True)
        result = self.run_detached("git", "sync", "kb", "--dry-run")
        self.assertEqual((result.code, result.err), (0, ""), result.out)
        self.assertIn("pending deletions", result.out)
        self.assertIn("feat/merged", result.out)
        self.assertIn("nothing was deleted", result.out)
        self.assertIn("feat/merged", self.branches("kb"))

    def test_sync_yes_deletes_a_merged_branch(self) -> None:
        """
        Criterion:  sync-yes-deletes-a-merged-branch
          Given:    kb tracks feat/merged, which the remote's main has merged.
          When:     `shad git sync kb --yes`.
          Then:     exit 0, stderr empty, stdout reports the branch deleted
                    with a restore command and counts 1 branch deleted, and
                    the branch is gone.
        """
        self.clone("kb", merged=True)
        result = self.run_detached("git", "sync", "kb", "--yes")
        self.assertEqual((result.code, result.err), (0, ""), result.out)
        self.assertIn("deleted branch", result.out)
        self.assertIn("restore: git branch feat/merged", words(result.out))
        self.assertIn("1 branch deleted", result.out)
        self.assertNotIn("feat/merged", self.branches("kb"))

    def test_sync_keeps_a_branch_with_unpushed_commits(self) -> None:
        """
        Criterion:  sync-keeps-a-branch-with-unpushed-commits
          Given:    kb's feat/unpushed is one commit ahead of its upstream.
          When:     `shad git sync kb --yes`.
          Then:     exit 0, stdout lists feat/unpushed among the branches
                    kept, and the branch still exists.
        """
        self.clone("kb", unpushed=True)
        result = self.run_detached("git", "sync", "kb", "--yes")
        self.assertEqual(result.code, 0, result.err)
        self.assertIn("branches kept", result.out)
        self.assertIn("feat/unpushed", result.out)
        self.assertIn("feat/unpushed", self.branches("kb"))

    def test_sync_fast_forwards_the_default_branch(self) -> None:
        """
        Criterion:  sync-fast-forwards-the-default-branch
          Given:    the remote's main is one commit ahead of kb's.
          When:     `shad git sync kb --yes`.
          Then:     exit 0, stdout reports the fast-forward, and kb's HEAD is
                    the remote's commit.
        """
        self.clone("kb")
        oid = self.advance_remote("kb")
        result = self.run_detached("git", "sync", "kb", "--yes")
        self.assertEqual(result.code, 0, result.err)
        self.assertIn("fast-forward", result.out)
        self.assertEqual(self.head("kb"), oid)

    def test_sync_switch_checks_out_the_default_branch(self) -> None:
        """
        Criterion:  sync-switch-checks-out-the-default-branch
          Given:    kb has feat/work checked out, and `shad git sync kb
                    --yes` without --switch left it there.
          When:     `shad git sync kb --switch --yes`.
          Then:     exit 0, stdout reports the switch, and main is checked
                    out.
        """
        path = self.clone("kb")
        git(path, "switch", "-q", "-c", "feat/work")
        self.run_detached("git", "sync", "kb", "--yes")
        self.assertEqual(git(path, "branch", "--show-current"), "feat/work")
        result = self.run_detached("git", "sync", "kb", "--switch", "--yes")
        self.assertEqual(result.code, 0, result.err)
        self.assertIn("switch", result.out)
        self.assertEqual(git(path, "branch", "--show-current"), "main")

    def test_sync_reports_every_project_and_skips_a_plain_directory(self) -> None:
        """
        Criterion:  sync-reports-every-project-and-skips-a-plain-directory
          Given:    kb is an up-to-date clone, and tin shad and tin coral
                    are plain directories.
          When:     `shad git sync --yes`.
          Then:     exit 0, stdout reports kb up to date and the other two
                    skipped with a reason, and counts 1 project synced and 2
                    skipped.
        """
        self.clone("kb")
        for name in ("tin/shad", "tin/coral"):
            (self.root / name).mkdir(parents=True)
        result = self.run_detached("git", "sync", "--yes")
        self.assertEqual(result.code, 0, result.err)
        self.assertIn("syncing 3 projects", result.out)
        self.assertIn("up to date", result.out)
        self.assertIn("1 project synced", result.out)
        self.assertIn("2 projects skipped", result.out)

    def test_sync_targets_a_group(self) -> None:
        """
        Criterion:  sync-targets-a-group
          Given:    kb, tin shad and tin coral are clones.
          When:     `shad git sync tin --dry-run`.
          Then:     exit 0, and stdout names tin shad and tin coral and not
                    kb.
        """
        for name in ("kb", "tin/shad", "tin/coral"):
            self.clone(name)
        result = self.run_detached("git", "sync", "tin", "--dry-run")
        self.assertEqual(result.code, 0, result.err)
        self.assertIn("tin shad", result.out)
        self.assertIn("tin coral", result.out)
        self.assertNotIn("kb", result.out)

    def test_sync_with_every_project_failed_exits_1(self) -> None:
        """
        Criterion:  sync-with-every-project-failed-exits-1
          Given:    kb's remote cannot be reached.
          When:     `shad git sync kb --yes`.
          Then:     exit 1, stdout reports kb failed, and stderr says every
                    project failed.
        """
        self.clone("kb")
        self.break_remote("kb")
        result = self.run_detached("git", "sync", "kb", "--yes")
        self.assertEqual(result.code, 1, result.out)
        self.assertIn("1 project failed", result.out)
        self.assertIn("all 1 project(s) failed", result.err)

    def test_sync_with_no_projects_does_no_work(self) -> None:
        """
        Criterion:  sync-with-no-projects-does-no-work
          Given:    the config names no project.
          When:     `shad git sync`.
          Then:     exit 0, stderr empty, stdout says none is configured.
        """
        self.write_config("[defaults]\n")
        result = self.run_detached("git", "sync")
        self.assertEqual((result.code, result.err), (0, ""), result.out)
        self.assertIn("no projects configured", result.out)

    def test_sync_of_an_unknown_target_fails(self) -> None:
        """
        Criterion:  sync-of-an-unknown-target-fails
          When:     `shad git sync nope`, and `shad git sync kb shad`.
          Then:     each exits 1 with stdout empty; the first is one line
                    `no_such_project: <non-empty>` naming nope, the second one
                    line `no_such_group: <non-empty>` naming the `shad git
                    sync kb` form.
        """
        result = self.run_detached("git", "sync", "nope")
        self.assertEqual((result.code, result.out), (1, ""), result.err)
        self.assertRegex(result.err, r"^no_such_project: .+\n$")
        self.assertIn("nope", result.err)
        result = self.run_detached("git", "sync", "kb", "shad")
        self.assertEqual((result.code, result.out), (1, ""), result.err)
        self.assertRegex(result.err, r"^no_such_group: .+\n$")
        self.assertIn("shad git sync kb", words(result.err))

    def test_git_without_an_action_fails(self) -> None:
        """
        Criterion:  git-without-an-action-fails
          When:     `shad git`, and `shad git frob`.
          Then:     the first exits 2, stdout empty, stderr one line
                    `no_action: <non-empty>`; the second exits 2.
        """
        result = self.run_shad("git")
        self.assertEqual((result.code, result.out), (2, ""), result.err)
        self.assertRegex(result.err, r"^no_action: .+\n$")
        self.assertIn("no git action given", result.err)
        self.assertEqual(self.run_shad("git", "frob").code, 2)


if __name__ == "__main__":
    unittest.main()
