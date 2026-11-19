"""
The commands that change a repository.

Everything here mutates: fetching, fast-forwarding, deleting branches, and
removing worktrees. Each returns an error string rather than raising, so one
failure never aborts the rest of a run.

Nothing here decides *whether* an action is safe — shad.git.sync.plan does that.
"""

from __future__ import annotations

from pathlib import Path

from shad.errors import ShadError
from shad.git import discover, refs
from shad.git.model import FastForward, FetchResult, Switch, short_branch
from shad.git.run import T_FETCH, T_MUTATE, first_line, git


def _run(repo: Path, args: list[str], *, timeout: float, fallback: str) -> str | None:
    """
    Run one mutating git command. Returns an error string, or None on success.

    A timeout raises ShadError out of run.git; it is converted here rather than
    left to propagate, because apply_plan runs on the main thread with no
    per-project guard and one slow `worktree remove` must not abort the
    deletions still queued for every other project.
    """
    try:
        result = git(repo, args, timeout=timeout)
    except ShadError as exc:
        return str(exc)
    if result.returncode != 0:
        return first_line(result.stderr) or fallback
    return None


def fetch(repo: Path, remote: str, *, prune: bool) -> FetchResult:
    """
    Fetch from *remote*, optionally pruning stale remote-tracking refs.

    Always a real fetch, including under `shad git sync --dry-run`: it touches
    only remote-tracking refs, never a local branch, worktree, or working tree,
    and skipping it would leave the whole classification computed against
    stale refs.

    `prune` is False under --dry-run, because pruning is a one-shot event.
    A pruned ref takes its reflog with it, so its last-known OID — which the
    gone-branch rule needs — cannot be recovered afterwards. Pruning during a
    preview would consume that evidence and leave the real run unable to make
    the deletion the preview promised. remote_branch_refs() supplies the same
    answer without destroying anything.

    No --prune-tags (it deletes local-only tags), no explicit refspec (it would
    prune against a refspec the repo does not have), no --atomic (partial
    progress beats aborting everything).
    """
    args = ["fetch", "--no-recurse-submodules", "--no-auto-gc", "--quiet"]
    if prune:
        args.append("--prune")
    args += ["--", remote]

    error = _run(repo, args, timeout=T_FETCH, fallback="git fetch failed")
    if error is not None:
        return FetchResult(ok=False, error=error)
    return FetchResult(ok=True)


def fast_forward_checked_out(worktree: Path, upstream_ref: str) -> str | None:
    """Fast-forward the branch checked out in *worktree*. Returns an error, or None."""
    return _run(
        worktree,
        ["merge", "--ff-only", "--no-stat", "--quiet", upstream_ref],
        timeout=T_MUTATE,
        fallback="git merge --ff-only failed",
    )


def fast_forward_unchecked(repo: Path, branch: str, upstream_ref: str) -> str | None:
    """
    Fast-forward a branch that is not checked out anywhere.

    Uses a refspec fetch from `.` rather than update-ref: the refspec has no
    leading '+', so the ref backend enforces fast-forward-only, and git fetch
    refuses to move a branch checked out in a worktree. update-ref has neither
    guard and would desynchronise that worktree's HEAD and index. Source '.'
    means no network — the remote-tracking ref is already current.
    """
    return _run(
        repo,
        [
            "fetch",
            "--no-write-fetch-head",
            "--quiet",
            "--",
            ".",
            f"{upstream_ref}:refs/heads/{branch}",
        ],
        timeout=T_MUTATE,
        fallback="fast-forward failed",
    )


def delete_branch(repo: Path, name: str, *, force: bool) -> str | None:
    """Delete a local branch. Returns an error message, or None on success."""
    if name.startswith("-"):
        return "refusing to delete a branch whose name starts with '-'"
    args = ["branch", "--delete"]
    if force:
        args.append("--force")
    args.append(name)
    return _run(
        repo, args, timeout=T_MUTATE, fallback="git branch --delete failed"
    )


def remove_worktree(repo: Path, path: Path) -> str | None:
    """Remove a worktree. Never passes --force. Returns an error, or None."""
    return _run(
        repo,
        ["worktree", "remove", "--", str(path)],
        timeout=T_MUTATE,
        fallback="git worktree remove failed",
    )


def prune_worktrees(repo: Path) -> str | None:
    """Drop admin records whose directory is gone. Touches no working tree."""
    return _run(
        repo,
        ["worktree", "prune"],
        timeout=T_MUTATE,
        fallback="git worktree prune failed",
    )


def switch_default(
    root: Path,
    default: str,
    local_ref: str,
    checked_out: dict[str, Path],
    *,
    dry_run: bool,
) -> Switch:
    """
    Move the main worktree onto the default branch, or explain why not.

    This is the only step that touches a working tree the user can see, which
    is why it is opt-in (`--switch`). Every blocking condition skips with a
    reason rather than forcing: nothing here stashes, discards, or detaches.

    It runs *after* the fast-forward so the checkout lands directly on the new
    tip — one working-tree update, not two — and *before* branches are
    classified, so the branch it leaves behind is no longer pinned by a
    worktree and can be cleaned up in the same run.
    """

    def skipped(detail: str) -> Switch:
        return Switch(branch=default, status="skipped", detail=detail)

    current = discover.head_branch(root)
    if current == local_ref:
        return Switch(branch=default, status="current")
    if current is None:
        return skipped("HEAD is detached")

    if default.startswith("-"):
        return skipped("refusing a default branch name that starts with '-'")
    if not refs.ref_exists(root, local_ref):
        # Same rule as fast_forward: never create a branch the user never had.
        return skipped(f"no local {default}")

    holder = checked_out.get(local_ref)
    if holder is not None and holder.resolve() != root.resolve():
        return skipped(f"checked out at {holder}")

    clean, changed, _untracked = discover.is_clean(root, untracked=False)
    if not clean:
        return skipped(f"{changed} uncommitted change(s)")

    from_branch = short_branch(current)
    if dry_run:
        return Switch(
            branch=default,
            status="skipped",
            from_branch=from_branch,
            detail="would switch",
        )

    error = _run(
        root,
        ["switch", "--no-guess", default],
        timeout=T_MUTATE,
        fallback="git switch failed",
    )
    if error is not None:
        return skipped(error)
    return Switch(branch=default, status="switched", from_branch=from_branch)


def fast_forward(
    root: Path,
    default: str,
    local_ref: str,
    remote_ref: str,
    checked_out: dict[str, Path],
    *,
    dry_run: bool,
) -> FastForward:
    """Bring the local default branch up to the fetched remote tip, or explain why not."""
    remote_oid = refs.ref_oid(root, remote_ref)
    if remote_oid is None:
        return FastForward(branch=default, status="skipped", detail=f"no {remote_ref}")

    local_oid = refs.ref_oid(root, local_ref)
    if local_oid is None:
        # Do not create a branch the user never had; classification uses the
        # remote tip anyway.
        return FastForward(
            branch=default, status="skipped", detail=f"no local {default}"
        )

    if local_oid == remote_oid:
        return FastForward(branch=default, status="current")

    if refs.is_ancestor(root, local_oid, remote_oid) is not True:
        ahead, behind = refs.ahead_behind(root, local_ref, remote_ref)
        return FastForward(
            branch=default,
            status="skipped",
            detail=f"diverged ({ahead} ahead, {behind} behind)",
        )

    if dry_run:
        return FastForward(
            branch=default,
            status="skipped",
            before=local_oid[:7],
            after=remote_oid[:7],
            ahead=refs.count_commits(root, local_oid, remote_oid),
            detail="would fast-forward",
        )

    worktree = checked_out.get(local_ref)
    error: str | None
    if worktree is None:
        error = fast_forward_unchecked(root, default, remote_ref)
    elif worktree.resolve() != root.resolve():
        return FastForward(
            branch=default,
            status="skipped",
            detail=f"checked out at {worktree}",
        )
    elif discover.head_branch(root) != local_ref:
        return FastForward(branch=default, status="skipped", detail="HEAD is detached")
    else:
        clean, changed, _untracked = discover.is_clean(root, untracked=False)
        if not clean:
            return FastForward(
                branch=default,
                status="skipped",
                detail=f"{changed} uncommitted change(s)",
            )
        error = fast_forward_checked_out(root, remote_ref)

    if error is not None:
        return FastForward(branch=default, status="skipped", detail=error)

    return FastForward(
        branch=default,
        status="advanced",
        before=local_oid[:7],
        after=remote_oid[:7],
        ahead=refs.count_commits(root, local_oid, remote_oid),
    )
