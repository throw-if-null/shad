"""
Types for the git slice.

Two layers. The first describes one repository as git reports it; the
second describes what one sync run decided and did with that.

They live apart from both the orchestrator and the renderer because the
renderer must read them without importing the orchestrator, which imports
the renderer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from shad.shared.config import Project

# ── one repository ────────────────────────────────────────────────


# What we split git output on, and what we ask git to emit as a separator.
# `%00` is git's own escape; a real NUL cannot be passed in argv.
NUL = "\x00"


FMT_SEP = "%00"


@dataclass(frozen=True)
class Repo:
    """A resolved git repository, rooted at its main worktree."""

    root: Path  # main worktree (or the configured path when it is the main one)
    common_dir: Path  # resolved --git-common-dir; the repo identity for dedupe
    shallow: bool = False
    relinked_from: Path | None = None  # set when the configured path was a linked worktree


@dataclass(frozen=True)
class BranchRef:
    """One entry of `for-each-ref refs/heads`."""

    refname: str  # refs/heads/<name>
    oid: str
    upstream: str  # refs/remotes/<remote>/<name>, or "" when unset
    remotename: str  # "origin", "." for a local-tracking branch, or ""
    trackshort: str  # ">" ahead, "<" behind, "<>" diverged, "=" in sync, "" unknown

    @property
    def name(self) -> str:
        return self.refname[len("refs/heads/") :]

    @property
    def short_oid(self) -> str:
        return self.oid[:7]


@dataclass(frozen=True)
class Worktree:
    """One record of `worktree list --porcelain -z`."""

    path: Path
    head: str | None = None
    branch: str | None = None  # full refname, None when detached or bare
    bare: bool = False
    detached: bool = False
    locked: bool = False
    locked_reason: str = ""
    prunable: bool = False
    prunable_reason: str = ""


@dataclass(frozen=True)
class FetchResult:
    ok: bool
    pruned: list[str] = field(default_factory=list)  # short names, e.g. "origin/feat/x"
    error: str | None = None


@dataclass(frozen=True)
class FastForward:
    branch: str
    status: str  # "advanced" | "current" | "skipped"
    before: str | None = None
    after: str | None = None
    ahead: int = 0
    detail: str | None = None


@dataclass(frozen=True)
class BranchInfo:
    """A branch the plan intends to delete."""

    name: str
    sha: str
    reason: str  # "merged" | "pushed-then-gone"
    force: bool = False  # -D rather than -d


@dataclass(frozen=True)
class BranchKept:
    """A branch deliberately not deleted, and why."""

    name: str
    sha: str
    reason: str


def short_branch(refname: str | None) -> str:
    """Strip the refs/heads/ prefix for display."""
    if not refname:
        return ""
    return refname.removeprefix("refs/heads/")


@dataclass(frozen=True)
class WorktreeInfo:
    """A worktree the plan intends to remove or prune."""

    path: Path
    branch: str | None
    reason: str  # "prunable" | "branch gone" | "branch merged"
    prune_only: bool = False  # directory is gone; `worktree prune` handles it

    @property
    def branch_name(self) -> str:
        return short_branch(self.branch)


@dataclass(frozen=True)
class WorktreeKept:
    path: Path
    branch: str | None
    reason: str

    @property
    def branch_name(self) -> str:
        return short_branch(self.branch)


# ── one sync run ─────────────────────────────────────────────────


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
