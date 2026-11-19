"""
Deciding which branches and worktrees are safe to remove.

This module is the safety boundary. It runs no mutations; it only classifies,
and everything it declines to delete is reported with a reason.

The branch rule, in one sentence: delete only when losing work is impossible —
either the commits are already reachable from the default branch, or the
upstream ref was pruned in this run after every commit had been pushed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from shad.git import discover, refs
from shad.git.model import (
    BranchInfo,
    BranchKept,
    BranchRef,
    Worktree,
    WorktreeInfo,
    WorktreeKept,
)


@dataclass(frozen=True)
class BranchPlan:
    delete: list[BranchInfo] = field(default_factory=list)
    keep: list[BranchKept] = field(default_factory=list)


@dataclass(frozen=True)
class WorktreePlan:
    remove: list[WorktreeInfo] = field(default_factory=list)
    keep: list[WorktreeKept] = field(default_factory=list)


def classify_branch(
    repo: Path,
    branch: BranchRef,
    *,
    merged: set[str],
    checked_out: dict[str, Path],
    pruned_oids: dict[str, str],
    gone_allowed: bool,
    shallow: bool,
) -> BranchInfo | BranchKept:
    """
    Decide the fate of one local branch.

    The rule: delete iff the branch is not protected AND either (a) its tip is
    reachable from a default tip, or (b) its upstream was pruned in *this* run
    and its tip was reachable from that ref's last-known OID.

    *merged* is clause (a), precomputed by classify_branches: the refnames
    git reports as merged into any default tip.

    Clause (b) is what makes squash-merged PR branches deletable. `git branch
    -d` falls back to "merged into HEAD" once the upstream ref is gone, so it
    refuses them — by commit ancestry a squash-merged branch really is
    unmerged. Rather than guessing, (b) asks the only question that matters:
    were all of this branch's commits on the server before the server deleted
    the ref? If so, deleting cannot lose work.

    *pruned_oids* maps a pruned refs/remotes ref to its last-known OID, so (b)
    only ever applies to refs pruned in this run. A branch whose upstream was
    pruned by an earlier fetch has no recoverable OID and is kept.
    """
    name, sha = branch.name, branch.short_oid

    def kept(reason: str) -> BranchKept:
        return BranchKept(name=name, sha=sha, reason=reason)

    if shallow:
        return kept("shallow clone")

    worktree = checked_out.get(branch.refname)
    if worktree is not None:
        # Only the main worktree pins a branch outright — it is never removed.
        # A branch held by a *linked* worktree stays a candidate here; the
        # worktree pass decides whether that worktree can go, and reconcile()
        # moves the branch back to "kept" when it cannot.
        return kept(f"checked out at {worktree}")

    if branch.trackshort in (">", "<>"):
        return kept("unpushed commits")

    # The never-delete checks come first, including "no upstream": a purely
    # local branch is a deliberate bookmark, and is kept even when its tip is
    # already reachable from the default branch.
    if not branch.upstream:
        return kept("no upstream")

    if branch.remotename == ".":
        # Tracks another local branch; says nothing about the server.
        return kept("tracks a local branch")

    if branch.refname in merged:
        return BranchInfo(name=name, sha=sha, reason="merged", force=False, oid=branch.oid)

    if branch.upstream in pruned_oids:
        if not gone_allowed:
            return kept("narrow fetch refspec")
        pushed = refs.is_ancestor(repo, branch.oid, pruned_oids[branch.upstream])
        if pushed is True:
            return BranchInfo(
                name=name, sha=sha, reason="pushed-then-gone", force=True, oid=branch.oid
            )
        if pushed is False:
            return kept("upstream gone, has unpushed commits")
        return kept("upstream gone, last-known state unavailable")

    if not refs.ref_exists(repo, branch.upstream):
        # Pruned by an earlier fetch: no last-known OID exists, so whether the
        # work reached the server cannot be proven. Keep it.
        return kept("upstream gone, merge state unknown (pruned before this run)")

    return kept("not merged")


def classify_branches(
    repo: Path,
    branches: list[BranchRef],
    *,
    default: str,
    default_tips: list[str],
    checked_out: dict[str, Path],
    pruned_oids: dict[str, str],
    gone_allowed: bool,
    shallow: bool,
) -> BranchPlan:
    """Apply classify_branch to every branch except the default one."""
    plan = BranchPlan()
    default_ref = f"refs/heads/{default}"

    # Ask git once per tip rather than once per branch per tip.
    merged: set[str] = set()
    for tip in default_tips:
        merged |= refs.merged_branches(repo, tip)

    for branch in branches:
        if branch.refname == default_ref:
            continue  # never a candidate, never listed
        verdict = classify_branch(
            repo,
            branch,
            merged=merged,
            checked_out=checked_out,
            pruned_oids=pruned_oids,
            gone_allowed=gone_allowed,
            shallow=shallow,
        )
        if isinstance(verdict, BranchInfo):
            plan.delete.append(verdict)
        else:
            plan.keep.append(verdict)

    return plan


def classify_worktree(
    repo: Path,
    wt: Worktree,
    *,
    deleting: set[str],
    known_branches: set[str],
) -> WorktreeInfo | WorktreeKept | None:
    """
    Decide the fate of one linked worktree. None means "not a candidate".

    Locked and bare records are filtered here rather than relying on git's
    refusal, because a plan that lists something git will reject is a bad
    plan. Locked especially: a locked worktree's directory being absent is
    expected (an unmounted disk), and pruning its record destroys bookkeeping
    for a worktree that still exists.
    """
    branch = wt.branch

    def kept(reason: str) -> WorktreeKept:
        return WorktreeKept(path=wt.path, branch=branch, reason=reason)

    if wt.bare:
        return None
    if wt.locked:
        suffix = f": {wt.locked_reason}" if wt.locked_reason else ""
        return kept(f"locked{suffix}")

    if wt.prunable:
        return WorktreeInfo(
            path=wt.path,
            branch=branch,
            reason=wt.prunable_reason or "directory gone",
            prune_only=True,
        )

    if not wt.path.is_dir():
        # git did not call it prunable, so `git worktree prune` will not drop
        # it — gc.worktreePruneExpire can hold a record open. Planning the
        # removal anyway would promise something git refuses to do. Report it
        # and leave it: a directory that is merely unreachable right now (an
        # unmounted disk) must survive.
        return kept("directory is missing, but git does not consider it prunable")

    if wt.detached or branch is None:
        if wt.head and not refs.any_ref_contains(repo, wt.head):
            return kept("detached HEAD not reachable from any ref")
        return kept("detached HEAD")

    if branch in deleting:
        reason = "branch is being deleted"
    elif branch not in known_branches:
        reason = "branch gone"
    else:
        return kept("branch still in use")

    if (wt.path / ".gitmodules").is_file():
        return kept("contains submodules")

    operation = discover.in_progress(wt.path)
    if operation is not None:
        return kept(f"{operation} in progress")

    clean, changed, untracked = discover.is_clean(wt.path, untracked=True)
    if not clean:
        parts = []
        if changed:
            parts.append(f"{changed} modified")
        if untracked:
            parts.append(f"{untracked} untracked")
        return kept(", ".join(parts) or "not clean")

    return WorktreeInfo(path=wt.path, branch=branch, reason=reason, prune_only=False)


def classify_worktrees(
    repo: Path,
    worktrees: list[Worktree],
    *,
    deleting: set[str],
    known_branches: set[str],
) -> WorktreePlan:
    """Apply classify_worktree to every worktree except the main one (index 0)."""
    plan = WorktreePlan()

    for wt in worktrees[1:]:
        verdict = classify_worktree(
            repo, wt, deleting=deleting, known_branches=known_branches
        )
        if isinstance(verdict, WorktreeInfo):
            plan.remove.append(verdict)
        elif isinstance(verdict, WorktreeKept):
            plan.keep.append(verdict)

    return plan


def reconcile(
    branch_plan: BranchPlan,
    worktree_plan: WorktreePlan,
    checked_out: dict[str, Path],
) -> tuple[list[BranchInfo], list[BranchKept]]:
    """
    Settle branches whose fate depends on a worktree.

    A branch checked out in a linked worktree is only deletable if that
    worktree is also being removed — git refuses otherwise. When the worktree
    survives (dirty, locked, has submodules, mid-rebase), the branch goes back
    to "kept" carrying the worktree's reason, so the report explains itself.
    """
    removing = {w.path for w in worktree_plan.remove}
    kept_reason = {w.path: w.reason for w in worktree_plan.keep}

    deletions: list[BranchInfo] = []
    kept: list[BranchKept] = list(branch_plan.keep)

    for branch in branch_plan.delete:
        holder = checked_out.get(f"refs/heads/{branch.name}")
        if holder is None or holder in removing:
            deletions.append(branch)
            continue
        reason = kept_reason.get(holder, "checked out")
        kept.append(
            BranchKept(
                name=branch.name,
                sha=branch.sha,
                reason=f"checked out at {holder} ({reason})",
            )
        )

    return deletions, kept


def stale_upstreams(
    root: Path,
    remote: str,
    before: dict[str, str],
    after: dict[str, str],
    symrefs: set[str],
    *,
    dry_run: bool,
) -> dict[str, str] | None:
    """
    Map each stale remote-tracking ref to the OID it last pointed at.

    That OID is what proves a branch whose upstream is gone was fully pushed
    before the server deleted it, so it must be captured, never inferred from
    fetch stderr — which is translated and reshaped by `fetch.output = compact`.

    Applied run: the fetch pruned them, so diff the before/after snapshots.
    Dry run: nothing was pruned, so ask the remote which branches it still has
    and treat everything else as stale. Both yield refs the server no longer
    carries, but the dry-run path leaves them in place for the real run.

    Both paths are scoped to *remote*. The snapshots cover all of refs/remotes,
    while `live` only ever describes one remote — without the prefix filter a
    second remote's refs would every one of them read as stale, and a branch
    tracking a live `upstream/x` would be offered for deletion.
    """
    prefix = f"refs/remotes/{remote}/"

    if not dry_run:
        return {
            ref: before[ref]
            for ref in before.keys() - after.keys()
            if ref.startswith(prefix) and ref not in symrefs
        }

    live = refs.remote_branch_refs(root, remote)
    if live is None:
        return None
    return {
        ref: oid
        for ref, oid in after.items()
        if ref.startswith(prefix) and ref not in live and ref not in symrefs
    }
