"""
`shad git sync` — fetch, fast-forward, and prune dead branches and worktrees.

Two orderings in this module are load-bearing:

  1. Fast-forward BEFORE classifying branches. A branch merged upstream is
     only reachable from the default tip once that tip is current. Getting
     this backwards silently under-reports deletable branches, and the bug is
     invisible to any test that fakes git output.

  2. Remove worktrees BEFORE deleting branches. `git branch -d` refuses a
     branch a worktree has checked out, so this ordering is what makes a
     dead-worktree-plus-merged-branch pair disappear in one run, not two.

Fetch, prune and fast-forward are applied immediately and are NOT undone when
the user declines the prompt; only deletions are gated.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from rich.console import Console
from rich.prompt import Confirm
from rich.text import Text

from shad.git import repo as R
from shad.git import report
from shad.git.model import ProjectOutcome, ProjectPlan, SyncRun
from shad.shared.config import Config, Project, resolve_target
from shad.shared.errors import ShadError

console = Console()

ACTIONS = ("sync",)

# Each unit of work is a `git fetch` subprocess; an uncapped pool would open
# one per configured project, contending for the ssh-agent and the link.
MAX_WORKERS = 8


# ── inspect (phase 0-2) ───────────────────────────────────────────────────


def fetch_and_plan(project: Project, *, dry_run: bool = False) -> ProjectPlan:
    """
    Apply the ungated steps for one project and compute what is still pending.

    Runs in a worker thread: it must not print, and it must not raise for an
    ordinary per-project problem — those become a status on the returned plan.
    """
    plan = ProjectPlan(project=project)

    try:
        found = R.discover(project.path)
    except R.NotUsable as exc:
        plan.status = "skipped"
        plan.detail = str(exc)
        return plan
    except R.GitMissing as exc:
        plan.status = "failed"
        plan.detail = str(exc)
        return plan

    root = found.root
    plan.relinked_from = found.relinked_from

    operation = R.in_progress(root)
    if operation is not None:
        plan.status = "skipped"
        plan.detail = f"{operation} in progress"
        return plan

    remotes = R.list_remotes(root)
    remote = R.primary_remote(remotes)
    if remote is None and remotes:
        plan.status = "skipped"
        plan.detail = (
            f"multiple remotes ({', '.join(sorted(remotes))}) and no 'origin'"
        )
        return plan

    before: dict[str, str] = {}
    symrefs: set[str] = set()
    gone_allowed = False

    if remote is not None:
        before, symrefs = R.snapshot_remotes(root)
        result = R.fetch(root, remote, prune=not dry_run)
        if not result.ok:
            plan.status = "failed"
            plan.detail = result.error
            return plan

        after, symrefs = R.snapshot_remotes(root)
        pruned_oids = _pruned_oids(
            root, remote, before, after, symrefs, dry_run=dry_run
        )
        if pruned_oids is None:
            plan.status = "failed"
            plan.detail = f"could not list branches on {remote}"
            return plan

        plan.pruned_refs = sorted(ref.removeprefix("refs/remotes/") for ref in pruned_oids)
        gone_allowed = R.has_full_refspec(root, remote)
    else:
        pruned_oids = {}

    worktrees = R.list_worktrees(root)
    checked_out = {w.branch: w.path for w in worktrees if w.branch}

    default = (
        R.default_branch(root, remote, allow_network=True) if remote is not None else None
    )
    plan.default_branch = default

    if default is None:
        plan.detail = "cannot determine the default branch"
        return plan

    remote_ref = f"refs/remotes/{remote}/{default}"
    local_ref = f"refs/heads/{default}"

    plan.fast_forward = _fast_forward(
        root, default, local_ref, remote_ref, checked_out, dry_run=dry_run
    )

    default_tips = [
        oid
        for oid in (R.ref_oid(root, remote_ref), R.ref_oid(root, local_ref))
        if oid is not None
    ]
    if not default_tips:
        return plan

    branches = R.list_branches(root)
    plan.pruned_tracked_by = {
        ref.removeprefix("refs/remotes/"): b.name
        for ref in pruned_oids
        for b in branches
        if b.upstream == ref
    }

    # Only the main worktree pins a branch outright. A branch held by a linked
    # worktree is still a delete candidate here, because that worktree may
    # itself be removable — reconcile() settles the pair below.
    main_worktree = worktrees[0].path if worktrees else root
    pinned = {ref: path for ref, path in checked_out.items() if path == main_worktree}

    branch_plan = R.classify_branches(
        root,
        branches,
        default=default,
        default_tips=default_tips,
        checked_out=pinned,
        pruned_oids=pruned_oids,
        gone_allowed=gone_allowed,
        shallow=found.shallow,
    )

    worktree_plan = R.classify_worktrees(
        root,
        worktrees,
        deleting={f"refs/heads/{b.name}" for b in branch_plan.delete},
        known_branches={b.refname for b in branches},
    )

    deletions, kept = _reconcile(branch_plan, worktree_plan, checked_out)
    plan.branch_deletions = deletions
    plan.branches_kept = kept
    plan.worktree_removals = worktree_plan.remove
    plan.worktrees_kept = worktree_plan.keep

    plan.repo_root = root
    return plan


def _reconcile(
    branch_plan: R.BranchPlan,
    worktree_plan: R.WorktreePlan,
    checked_out: dict[str, Path],
) -> tuple[list[R.BranchInfo], list[R.BranchKept]]:
    """
    Settle branches whose fate depends on a worktree.

    A branch checked out in a linked worktree is only deletable if that
    worktree is also being removed — git refuses otherwise. When the worktree
    survives (dirty, locked, has submodules, mid-rebase), the branch goes back
    to "kept" carrying the worktree's reason, so the report explains itself.
    """
    removing = {w.path for w in worktree_plan.remove}
    kept_reason = {w.path: w.reason for w in worktree_plan.keep}

    deletions: list[R.BranchInfo] = []
    kept: list[R.BranchKept] = list(branch_plan.keep)

    for branch in branch_plan.delete:
        holder = checked_out.get(f"refs/heads/{branch.name}")
        if holder is None or holder in removing:
            deletions.append(branch)
            continue
        reason = kept_reason.get(holder, "checked out")
        kept.append(
            R.BranchKept(
                name=branch.name,
                sha=branch.sha,
                reason=f"checked out at {holder} ({reason})",
            )
        )

    return deletions, kept


def _pruned_oids(
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
    """
    if not dry_run:
        return {
            ref: before[ref] for ref in before.keys() - after.keys() if ref not in symrefs
        }

    live = R.remote_branch_refs(root, remote)
    if live is None:
        return None
    return {
        ref: oid
        for ref, oid in after.items()
        if ref not in live and ref not in symrefs
    }


def _fast_forward(
    root: Path,
    default: str,
    local_ref: str,
    remote_ref: str,
    checked_out: dict[str, Path],
    *,
    dry_run: bool,
) -> R.FastForward:
    """Bring the local default branch up to the fetched remote tip, or explain why not."""
    remote_oid = R.ref_oid(root, remote_ref)
    if remote_oid is None:
        return R.FastForward(branch=default, status="skipped", detail=f"no {remote_ref}")

    local_oid = R.ref_oid(root, local_ref)
    if local_oid is None:
        # Do not create a branch the user never had; classification uses the
        # remote tip anyway.
        return R.FastForward(
            branch=default, status="skipped", detail=f"no local {default}"
        )

    if local_oid == remote_oid:
        return R.FastForward(branch=default, status="current")

    if R.is_ancestor(root, local_oid, remote_oid) is not True:
        ahead, behind = R.ahead_behind(root, local_ref, remote_ref)
        return R.FastForward(
            branch=default,
            status="skipped",
            detail=f"diverged ({ahead} ahead, {behind} behind)",
        )

    if dry_run:
        return R.FastForward(
            branch=default,
            status="skipped",
            before=local_oid[:7],
            after=remote_oid[:7],
            ahead=R.count_commits(root, local_oid, remote_oid),
            detail="would fast-forward",
        )

    worktree = checked_out.get(local_ref)
    error: str | None
    if worktree is None:
        error = R.fast_forward_unchecked(root, default, remote_ref)
    elif worktree.resolve() != root.resolve():
        return R.FastForward(
            branch=default,
            status="skipped",
            detail=f"checked out at {worktree}",
        )
    elif R.head_branch(root) != local_ref:
        return R.FastForward(branch=default, status="skipped", detail="HEAD is detached")
    else:
        clean, changed, _untracked = R.is_clean(root, untracked=False)
        if not clean:
            return R.FastForward(
                branch=default,
                status="skipped",
                detail=f"{changed} uncommitted change(s)",
            )
        error = R.fast_forward_checked_out(root, remote_ref)

    if error is not None:
        return R.FastForward(branch=default, status="skipped", detail=error)

    return R.FastForward(
        branch=default,
        status="advanced",
        before=local_oid[:7],
        after=remote_oid[:7],
        ahead=R.count_commits(root, local_oid, remote_oid),
    )


# ── apply (phase 4) ───────────────────────────────────────────────────────


def apply_plan(plan: ProjectPlan) -> ProjectOutcome:
    """
    Execute one project's pending deletions.

    Worktrees first: `git branch -d` refuses a branch a worktree still has
    checked out. Each failure is recorded and the rest continue.
    """
    outcome = ProjectOutcome(plan=plan)
    root = plan.repo_root
    if root is None:
        return outcome

    if any(w.prune_only for w in plan.worktree_removals):
        error = R.prune_worktrees(root)
        if error is not None:
            outcome.failures.append(f"worktree prune: {error}")
        else:
            outcome.removed_worktrees.extend(
                w.path for w in plan.worktree_removals if w.prune_only
            )

    for worktree in plan.worktree_removals:
        if worktree.prune_only:
            continue
        error = R.remove_worktree(root, worktree.path)
        if error is not None:
            outcome.failures.append(f"worktree {worktree.path}: {error}")
        else:
            outcome.removed_worktrees.append(worktree.path)

    for branch in plan.branch_deletions:
        # Re-verify the tip: the user may have been at the prompt while another
        # pane committed. This is the only TOCTOU window, and -D has no net.
        current = R.ref_oid(root, f"refs/heads/{branch.name}")
        if current is None:
            outcome.failures.append(f"branch {branch.name}: already gone")
            continue
        if current[:7] != branch.sha:
            outcome.failures.append(
                f"branch {branch.name}: moved since the plan was made; skipped"
            )
            continue
        error = R.delete_branch(root, branch.name, force=branch.force)
        if error is not None:
            outcome.failures.append(f"branch {branch.name}: {error}")
        else:
            outcome.deleted_branches.append(branch)

    if plan.worktree_removals:
        R.prune_worktrees(root)  # cheap no-op safety net

    return outcome


# ── orchestration ─────────────────────────────────────────────────────────


def sync_projects(
    projects: list[Project], *, yes: bool = False, dry_run: bool = False
) -> SyncRun:
    """Run the full sync over *projects* and return what happened."""
    if not projects:
        console.print(Text("no projects configured", style="dim"))
        return SyncRun(dry_run=dry_run)

    R.require_git()

    report.render_header(len(projects))
    plans = _inspect(projects, dry_run=dry_run)

    report.render_applied(plans, dry_run=dry_run)

    pending = [p for p in plans if p.pending]

    if dry_run:
        if pending:
            report.render_pending(plans)
        report.render_dry_run_footer()
        run = SyncRun(
            outcomes=[ProjectOutcome(plan=p) for p in plans], dry_run=True
        )
        _raise_if_all_failed(run)
        return run

    if not pending:
        run = SyncRun(outcomes=[ProjectOutcome(plan=p) for p in plans])
        report.render_summary(run)
        _raise_if_all_failed(run)
        return run

    report.render_pending(plans)
    console.print()
    if not yes and not Confirm.ask(
        "  Delete these branches and worktrees?", default=False
    ):
        report.render_aborted()
        return SyncRun(
            outcomes=[ProjectOutcome(plan=p) for p in plans], confirmed=False
        )

    outcomes = [apply_plan(p) if p.pending else ProjectOutcome(plan=p) for p in plans]
    run = SyncRun(outcomes=outcomes)
    report.render_results(outcomes)
    report.render_summary(run)
    _raise_if_all_failed(run)
    return run


def _inspect(projects: list[Project], *, dry_run: bool) -> list[ProjectPlan]:
    """
    Fetch and plan every project concurrently.

    Results are collected by index because as_completed scrambles order, and a
    worker failure lands on the plan rather than aborting the batch.
    """
    plans: list[ProjectPlan | None] = [None] * len(projects)

    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(projects))) as pool:
        futures = {
            pool.submit(fetch_and_plan, project, dry_run=dry_run): index
            for index, project in enumerate(projects)
        }
        for future in as_completed(futures):
            index = futures[future]
            try:
                plans[index] = future.result()
            except Exception as exc:  # noqa: BLE001 — one bad project must not abort the rest
                plans[index] = ProjectPlan(
                    project=projects[index], status="failed", detail=str(exc)
                )

    return [p for p in plans if p is not None]


def _raise_if_all_failed(run: SyncRun) -> None:
    """A run where every project failed is a real failure; a partial one is not."""
    if run.outcomes and all(o.plan.status == "failed" for o in run.outcomes):
        raise ShadError(f"all {len(run.outcomes)} project(s) failed")


def cmd_git(cfg: Config, args: argparse.Namespace) -> None:
    action = getattr(args, "git_action", None)
    if action is None:
        raise ShadError(f"no git action given; available: {', '.join(ACTIONS)}")
    if action not in ACTIONS:
        raise ShadError(
            f"unknown git action '{action}'; available: {', '.join(ACTIONS)}"
        )

    target = resolve_target(cfg, list(args.name), usage="shad git sync")
    sync_projects(
        target.projects,
        yes=getattr(args, "yes", False),
        dry_run=getattr(args, "dry_run", False),
    )
