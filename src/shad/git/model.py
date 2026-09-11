"""
Run-level dataclasses for `shad git sync`.

These live apart from both shad.git.command and shad.git.report because the
renderer must read them without importing the orchestrator, which imports the
renderer.

shad.git.repo owns the per-repository facts (BranchInfo, Worktree, ...);
this module owns what one sync *run* did with them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from shad.git.repo import (
    BranchInfo,
    BranchKept,
    FastForward,
    WorktreeInfo,
    WorktreeKept,
)
from shad.shared.config import Project


@dataclass
class ProjectPlan:
    """
    What one project looked like after the ungated phase, and what is pending.

    `status` is a single field rather than parallel flags: a configured project
    that is not a git repository is *skipped*, not *failed*, and must not
    render as an error during a sync-everything run.
    """

    project: Project
    status: str = "ok"  # "ok" | "skipped" | "failed"
    detail: str | None = None
    relinked_from: Path | None = None
    repo_root: Path | None = None  # main worktree; what apply_plan operates on
    default_branch: str | None = None
    fast_forward: FastForward | None = None
    pruned_refs: list[str] = field(default_factory=list)
    pruned_tracked_by: dict[str, str] = field(default_factory=dict)
    branch_deletions: list[BranchInfo] = field(default_factory=list)
    branches_kept: list[BranchKept] = field(default_factory=list)
    worktree_removals: list[WorktreeInfo] = field(default_factory=list)
    worktrees_kept: list[WorktreeKept] = field(default_factory=list)

    @property
    def pending(self) -> int:
        """How many deletions this project is asking the user to confirm."""
        return len(self.branch_deletions) + len(self.worktree_removals)

    @property
    def changed(self) -> bool:
        """True when this project has anything worth printing a block for."""
        if self.pending or self.pruned_refs or self.branches_kept or self.worktrees_kept:
            return True
        ff = self.fast_forward
        return ff is not None and ff.status != "current"


@dataclass
class ProjectOutcome:
    """What was actually applied for one project, after the confirmation."""

    plan: ProjectPlan
    deleted_branches: list[BranchInfo] = field(default_factory=list)
    removed_worktrees: list[Path] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


@dataclass
class SyncRun:
    outcomes: list[ProjectOutcome] = field(default_factory=list)
    dry_run: bool = False
    confirmed: bool = True
