from __future__ import annotations

import argparse
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from shad.git import apply, refs
from shad.git import command as C
from shad.git.model import BranchInfo, ProjectPlan, Repo, WorktreeInfo
from shad.shared.config import Config, Defaults, Project
from shad.shared.errors import ShadError

ROOT = Path("/tmp/repo")


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


def _resolve_all(projects: list[Project], plans: list[ProjectPlan | None]):
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

    def _run(self, **kwargs: bool) -> tuple[Mock, Mock]:
        with (
            patch.object(C, "require_git"),
            patch.object(C, "_resolve", side_effect=_resolve_all),
            patch.object(C, "fetch_and_plan", return_value=self.plan),
            patch.object(C, "report"),
            patch.object(C, "console"),
            patch.object(C, "apply_plan") as apply_plan,
            patch.object(C, "Confirm") as confirm,
        ):
            confirm.ask.return_value = kwargs.pop("answer", False)
            C.sync_projects([_project("kb")], **kwargs)
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
            patch.object(C, "console"),
            patch.object(C, "apply_plan"),
            patch.object(C, "Confirm") as confirm,
        ):
            confirm.ask.return_value = False
            run = C.sync_projects([_project("kb")])
        self.assertFalse(run.confirmed)


class SyncOrchestrationTests(unittest.TestCase):
    def test_no_projects_does_no_work(self) -> None:
        with patch.object(C, "console") as console, patch.object(C, "require_git") as require:
            run = C.sync_projects([])
        require.assert_not_called()
        self.assertEqual(run.outcomes, [])
        self.assertIn("no projects configured", str(console.print.call_args))

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
            patch.object(C, "console"),
        ):
            run = C.sync_projects(projects)

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
            patch.object(C, "console"),
        ):
            run = C.sync_projects(projects)
        self.assertEqual([o.plan.project.key for o in run.outcomes], ["a", "b", "c"])

    def test_every_project_failing_is_a_shad_error(self) -> None:
        with (
            patch.object(C, "require_git"),
            patch.object(C, "_resolve", side_effect=_resolve_all),
            patch.object(C, "fetch_and_plan", side_effect=RuntimeError("nope")),
            patch.object(C, "report"),
            patch.object(C, "console"),
            self.assertRaises(ShadError) as ctx,
        ):
            C.sync_projects([_project("a"), _project("b")])
        self.assertIn("all 2 project(s) failed", str(ctx.exception))

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
            patch.object(C, "console"),
        ):
            run = C.sync_projects([_project("a"), _project("b")])
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
class CmdGitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = Config(
            defaults=Defaults(),
            projects={"kb": _project("kb")},
            groups={"tin": {"shad": _project("shad", "tin"), "coral": _project("coral", "tin")}},
        )

    def _args(self, **kwargs: object) -> argparse.Namespace:
        base: dict[str, object] = {
            "git_action": "sync", "name": [], "yes": False, "dry_run": False,
            "switch": False,
        }
        base.update(kwargs)
        return argparse.Namespace(**base)

    def _keys(self, **kwargs: object) -> list[str]:
        with patch.object(C, "sync_projects") as sync:
            C.cmd_git(self.cfg, self._args(**kwargs))
        return [p.key for p in sync.call_args.args[0]]

    def test_no_tokens_targets_every_project(self) -> None:
        self.assertEqual(sorted(self._keys()), ["coral", "kb", "shad"])

    def test_one_token_targets_one_project(self) -> None:
        self.assertEqual(self._keys(name=["kb"]), ["kb"])

    def test_one_token_expands_a_group(self) -> None:
        self.assertEqual(self._keys(name=["tin"]), ["coral", "shad"])

    def test_two_tokens_target_one_grouped_project(self) -> None:
        self.assertEqual(self._keys(name=["tin", "shad"]), ["shad"])

    def test_flags_are_forwarded(self) -> None:
        with patch.object(C, "sync_projects") as sync:
            C.cmd_git(self.cfg, self._args(yes=True, dry_run=True, switch=True))
        self.assertEqual(
            sync.call_args.kwargs, {"yes": True, "dry_run": True, "switch": True}
        )

    def test_switch_defaults_to_off(self) -> None:
        # The only working-tree mutation in the command; a bare `shad git sync`
        # must never check anything out.
        with patch.object(C, "sync_projects") as sync:
            C.cmd_git(self.cfg, self._args())
        self.assertIs(sync.call_args.kwargs["switch"], False)

    def test_missing_action_is_rejected(self) -> None:
        with self.assertRaises(ShadError) as ctx:
            C.cmd_git(self.cfg, self._args(git_action=None))
        self.assertIn("no git action given", str(ctx.exception))

    def test_unknown_action_is_rejected(self) -> None:
        with self.assertRaises(ShadError) as ctx:
            C.cmd_git(self.cfg, self._args(git_action="nope"))
        self.assertIn("unknown git action 'nope'", str(ctx.exception))

    def test_resolution_errors_name_the_git_command(self) -> None:
        with self.assertRaises(ShadError) as ctx:
            C.cmd_git(self.cfg, self._args(name=["kb", "shad"]))
        self.assertIn("shad git sync kb", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
