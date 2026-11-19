from __future__ import annotations

import io
import unittest
from pathlib import Path

from shad.config.load import Project
from shad.git.model import (
    BranchInfo,
    BranchKept,
    FastForward,
    ProjectOutcome,
    ProjectPlan,
    SyncRun,
    WorktreeInfo,
    WorktreeKept,
)
from shad.git.sync import report
from shad.output import Output


def _project(key: str = "shad", group: str | None = "tin") -> Project:
    return Project(
        key=key, group=group, path=Path("/tmp") / key,
        session=f"{group}-{key}" if group else key,
    )


def _capture(width: int = 200) -> tuple[Output, io.StringIO]:
    """
    An Output over a buffer, and the buffer.

    Tables elsewhere in the suite are asserted on via str(call_args), but a
    rich Table has no useful __str__ — it only becomes text when rendered.
    """
    buffer = io.StringIO()
    return Output(stdout=buffer, width=width, color=False), buffer


def _text(buffer: io.StringIO) -> str:
    """Collapse wrapping and table borders so assertions can match content."""
    raw = buffer.getvalue()
    for char in "│╭╮╰╯├┤┬┴┼─":
        raw = raw.replace(char, " ")
    return " ".join(raw.split())


class RenderAppliedTests(unittest.TestCase):
    def _render(self, plan: ProjectPlan) -> str:
        out, buffer = _capture()
        report.render_applied(out, [plan])
        return _text(buffer)

    def test_unchanged_project_collapses_to_one_line(self) -> None:
        output = self._render(ProjectPlan(project=_project()))
        self.assertIn("tin shad", output)
        self.assertIn("up to date", output)
        self.assertNotIn("fetch", output)

    def test_skipped_project_is_not_rendered_as_an_error(self) -> None:
        plan = ProjectPlan(
            project=_project(), status="skipped", detail="not a git repository"
        )
        output = self._render(plan)
        self.assertIn("not a git repository", output)
        self.assertNotIn("✗", output)

    def test_failed_project_is_rendered_as_an_error(self) -> None:
        plan = ProjectPlan(
            project=_project(), status="failed", detail="could not read from remote"
        )
        output = self._render(plan)
        self.assertIn("✗", output)
        self.assertIn("could not read from remote", output)

    def test_fast_forward_shows_the_range_and_count(self) -> None:
        plan = ProjectPlan(
            project=_project(),
            default_branch="main",
            fast_forward=FastForward(
                branch="main", status="advanced", before="a1b2c3d", after="e4f5a6b", ahead=4
            ),
        )
        output = self._render(plan)
        self.assertIn("a1b2c3d", output)
        self.assertIn("e4f5a6b", output)
        self.assertIn("+4", output)

    def test_dry_run_fast_forward_is_marked_as_hypothetical(self) -> None:
        plan = ProjectPlan(
            project=_project(),
            default_branch="main",
            fast_forward=FastForward(
                branch="main", status="skipped", before="a1b2c3d",
                after="e4f5a6b", ahead=2, detail="would fast-forward",
            ),
        )
        self.assertIn("would advance", self._render(plan))

    def test_diverged_default_branch_explains_itself(self) -> None:
        plan = ProjectPlan(
            project=_project(),
            default_branch="main",
            fast_forward=FastForward(
                branch="main", status="skipped", detail="diverged (2 ahead, 3 behind)"
            ),
        )
        self.assertIn("diverged (2 ahead, 3 behind)", self._render(plan))

    def test_dry_run_calls_stale_refs_stale_because_nothing_was_pruned(self) -> None:
        plan = ProjectPlan(project=_project(), pruned_refs=["origin/feat/login"])
        out, buffer = _capture()
        report.render_applied(out, [plan], dry_run=True)
        output = _text(buffer)
        self.assertIn("would prune", output)
        self.assertNotIn("pruned remote refs", output)

    def test_pruned_refs_name_the_branch_that_tracked_them(self) -> None:
        plan = ProjectPlan(
            project=_project(),
            pruned_refs=["origin/feat/login"],
            pruned_tracked_by={"origin/feat/login": "feat/login"},
        )
        output = self._render(plan)
        self.assertIn("origin/feat/login", output)
        self.assertIn("was tracked by feat/login", output)

    def test_kept_branches_and_worktrees_get_separate_sections(self) -> None:
        plan = ProjectPlan(
            project=_project(),
            branches_kept=[BranchKept(name="wip", sha="c3d4e5f", reason="unpushed commits")],
            worktrees_kept=[
                WorktreeKept(path=Path("/tmp/wt"), branch="refs/heads/x", reason="2 modified")
            ],
        )
        output = self._render(plan)
        self.assertIn("branches kept", output)
        self.assertIn("worktrees kept", output)
        self.assertIn("unpushed commits", output)
        self.assertIn("2 modified", output)

    def test_a_relinked_worktree_says_so(self) -> None:
        plan = ProjectPlan(
            project=_project(),
            relinked_from=Path("/tmp/wt-feat"),
            branches_kept=[BranchKept(name="x", sha="a", reason="no upstream")],
        )
        self.assertIn("syncing the whole repository", self._render(plan))


class RenderPendingTests(unittest.TestCase):
    def test_one_table_covers_every_project(self) -> None:
        plans = [
            ProjectPlan(
                project=_project("shad"),
                branch_deletions=[BranchInfo(name="feat/login", sha="a1b2c3d", reason="merged")],
            ),
            ProjectPlan(
                project=_project("sol", group="cv"),
                worktree_removals=[
                    WorktreeInfo(
                        path=Path("/tmp/wt"), branch="refs/heads/feat/x", reason="branch gone"
                    )
                ],
            ),
        ]
        out, buffer = _capture()
        report.render_pending(out, plans)
        output = _text(buffer)

        self.assertIn("pending deletions", output)
        self.assertIn("tin shad", output)
        self.assertIn("cv sol", output)
        self.assertIn("feat/login", output)
        self.assertIn("a1b2c3d", output)
        # The worktree row shows the short branch name, not the full refname.
        self.assertIn("feat/x", output)
        self.assertNotIn("refs/heads/feat/x", output)


class RenderResultsTests(unittest.TestCase):
    def test_a_deleted_branch_always_carries_its_recovery_command(self) -> None:
        outcome = ProjectOutcome(
            plan=ProjectPlan(project=_project()),
            deleted_branches=[BranchInfo(name="feat/login", sha="9c3fe4b", reason="merged")],
        )
        out, buffer = _capture()
        report.render_results(out, [outcome])
        output = _text(buffer)
        self.assertIn("deleted branch", output)
        self.assertIn("was 9c3fe4b", output)
        self.assertIn("restore: git branch feat/login 9c3fe4b", output)

    def test_failures_are_shown_with_a_cross(self) -> None:
        outcome = ProjectOutcome(
            plan=ProjectPlan(project=_project()),
            failures=["branch feat: not fully merged"],
        )
        out, buffer = _capture()
        report.render_results(out, [outcome])
        output = _text(buffer)
        self.assertIn("✗", output)
        self.assertIn("not fully merged", output)


class RenderSummaryTests(unittest.TestCase):
    def _summary(self, run: SyncRun) -> str:
        out, buffer = _capture()
        report.render_summary(out, run)
        return _text(buffer)

    def test_counts_are_pluralised_correctly(self) -> None:
        run = SyncRun(
            outcomes=[
                ProjectOutcome(
                    plan=ProjectPlan(project=_project()),
                    deleted_branches=[BranchInfo(name="a", sha="1", reason="merged")],
                    removed_worktrees=[Path("/tmp/a"), Path("/tmp/b")],
                )
            ]
        )
        output = self._summary(run)
        self.assertIn("1 project synced", output)
        self.assertIn("1 branch deleted", output)
        self.assertIn("2 worktrees removed", output)

    def test_several_branches_read_as_branches(self) -> None:
        run = SyncRun(
            outcomes=[
                ProjectOutcome(
                    plan=ProjectPlan(project=_project()),
                    deleted_branches=[
                        BranchInfo(name="a", sha="1", reason="merged"),
                        BranchInfo(name="b", sha="2", reason="merged"),
                    ],
                )
            ]
        )
        output = self._summary(run)
        self.assertIn("2 branches deleted", output)
        self.assertNotIn("branchs", output)

    def test_failures_are_listed_beneath_the_counts(self) -> None:
        run = SyncRun(
            outcomes=[
                ProjectOutcome(plan=ProjectPlan(project=_project("shad"))),
                ProjectOutcome(
                    plan=ProjectPlan(
                        project=_project("sol", group="cv"),
                        status="failed",
                        detail="could not read from remote repository",
                    )
                ),
            ]
        )
        output = self._summary(run)
        self.assertIn("1 project synced", output)
        self.assertIn("1 project failed", output)
        self.assertIn("cv sol", output)
        self.assertIn("could not read from remote repository", output)

    def test_skipped_projects_are_counted_separately(self) -> None:
        run = SyncRun(
            outcomes=[
                ProjectOutcome(
                    plan=ProjectPlan(project=_project(), status="skipped", detail="not a repo")
                )
            ]
        )
        output = self._summary(run)
        self.assertIn("0 projects synced", output)
        self.assertIn("1 project skipped", output)


class RenderHeaderTests(unittest.TestCase):
    def test_single_project_run_prints_no_header(self) -> None:
        out, buffer = _capture()
        report.render_header(out, 1)
        self.assertEqual(buffer.getvalue(), "")

    def test_multi_project_run_announces_the_count(self) -> None:
        out, buffer = _capture()
        report.render_header(out, 7)
        self.assertIn("syncing 7 projects", _text(buffer))


if __name__ == "__main__":
    unittest.main()
