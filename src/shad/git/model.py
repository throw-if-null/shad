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


# What we split git output on. A real NUL cannot be passed in argv, so git is
# asked to emit one — and git has two --format languages that spell it
# differently. Neither accepts the other's spelling: the wrong one is emitted
# as literal text, git still exits 0, and the parse yields plausible garbage.
# run._check_format_dialect refuses the swap at the call site.
NUL = "\x00"


# ref-filter: `for-each-ref`, `branch --format`, `tag --format`.
FMT_SEP = "%00"


# pretty-format: `log`, `show`, `stash list`, `reflog`. Note that `-z` on these
# terminates each record with the same byte the fields are separated by, so a
# reader splits on NUL and groups by field count, not by record.
LOG_SEP = "%x00"


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
class Stash:
    """One entry of `stash list`."""

    ref: str  # stash@{0}
    subject: str  # the reflog subject, e.g. "WIP on main: 1a2b3c4 ..."
    timestamp: int  # committer date, seconds since the epoch; 0 when unreadable
    branch: str  # branch the stash was made on, "" when it cannot be read

    @property
    def message(self) -> str:
        """The subject without git's "WIP on <branch>: <oid>" preamble."""
        head, sep, tail = self.subject.partition(": ")
        if sep and head.startswith(("WIP on ", "On ")):
            return tail
        return self.subject


@dataclass(frozen=True)
class FetchResult:
    ok: bool
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
class Switch:
    """The main worktree being moved onto the default branch, or why it was not."""

    branch: str
    status: str  # "switched" | "current" | "skipped"
    from_branch: str | None = None  # only set when a switch happened or would have
    detail: str | None = None


@dataclass(frozen=True)
class BranchInfo:
    """A branch the plan intends to delete."""

    name: str
    sha: str  # abbreviated, for display only
    reason: str  # "merged" | "pushed-then-gone"
    force: bool = False  # -D rather than -d
    oid: str = ""  # full OID: the restore command and the TOCTOU re-verify


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
    # Printed verbatim in the confirmation table. One of git's own prunable
    # reason, "branch is being deleted", or "branch gone".
    reason: str
    prune_only: bool = False  # git calls it prunable; `worktree prune` handles it

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
    switch: Switch | None = None
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
        if self.switch is not None and self.switch.status != "current":
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
