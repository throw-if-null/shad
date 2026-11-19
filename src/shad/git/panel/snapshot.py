"""
One read-only reading of a repository, for the git panel.

A query layer over refs and discover: it collects what the panel displays and
decides nothing. It is deliberately synchronous and free of rendering, so the
panel can call it from a worker thread and the tests can drive it without a
terminal.

The optional fetch is the one network call. It never prunes — pruning takes a
remote-tracking ref's reflog with it, and those last-known OIDs are the
evidence `shad git sync` needs to prove a gone-upstream branch was fully
pushed. A viewer must not consume that.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from shad.git import refs
from shad.git.apply import fetch as fetch_remote
from shad.git.discover import head_branch
from shad.git.model import BranchRef, Repo, Stash, Worktree, short_branch
from shad.git.run import git_version_string


@dataclass(frozen=True)
class Snapshot:
    """What the panel shows. Every field is already resolved for display."""

    repo: Repo
    git_version: str = ""
    head: str | None = None  # short branch name; None when HEAD is detached
    head_upstream: str | None = None  # HEAD's upstream refname; None when it has none
    remote: str | None = None  # None when there is no remote, or it is ambiguous
    ahead: int = 0  # unpushed commits on HEAD's branch
    behind: int = 0  # commits to pull on HEAD's branch
    branches: list[BranchRef] = field(default_factory=list)
    worktrees: list[Worktree] = field(default_factory=list)
    stashes: list[Stash] = field(default_factory=list)
    fetch_error: str | None = None  # set when the fetch was attempted and failed
    fetched_at: float | None = None  # monotonic-independent wall clock of a good fetch

    @property
    def name(self) -> str:
        return self.repo.root.name

    @property
    def checked_out(self) -> set[str]:
        """Full refnames held by a worktree, which the branch list marks."""
        return {w.branch for w in self.worktrees if w.branch}


def collect(repo: Repo, *, fetch: bool) -> Snapshot:
    """
    Read *repo* once and return everything the panel renders.

    Never raises for an ordinary git problem: a failed query yields an empty
    section and a failed fetch is recorded on the snapshot. The panel must
    still render local state with no network.
    """
    root = repo.root

    fetch_error: str | None = None
    fetched_at: float | None = None

    remote = refs.primary_remote(refs.list_remotes(root))
    if fetch and remote is not None:
        result = fetch_remote(root, remote, prune=False)
        if result.ok:
            fetched_at = time.time()
        else:
            fetch_error = result.error

    branches = refs.list_branches(root)
    head_ref = head_branch(root)
    head = short_branch(head_ref) if head_ref else None

    head_upstream = _head_upstream(head_ref, branches)
    ahead, behind = (
        refs.ahead_behind(root, head_ref, head_upstream)
        if head_ref and head_upstream
        else (0, 0)
    )

    return Snapshot(
        repo=repo,
        git_version=git_version_string(),
        head=head,
        head_upstream=head_upstream,
        remote=remote,
        ahead=ahead,
        behind=behind,
        branches=branches,
        worktrees=refs.list_worktrees(root),
        stashes=refs.list_stashes(root),
        fetch_error=fetch_error,
        fetched_at=fetched_at,
    )


def _head_upstream(head_ref: str | None, branches: list[BranchRef]) -> str | None:
    """
    The upstream of HEAD's branch, or None when it is detached or untracked.

    Exact ahead/behind counts are read for this branch alone, because they
    cost one subprocess each and the header is the only place they appear.
    Every other branch shows the %(upstream:trackshort) symbol that
    list_branches already collected for free.
    """
    if head_ref is None:
        return None
    for branch in branches:
        if branch.refname == head_ref:
            return branch.upstream or None
    return None
