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

  3. With --switch: switch AFTER the fast-forward and BEFORE classifying.
     After, so the checkout lands on the new tip in one working-tree update.
     Before, so the branch the switch leaves behind is no longer pinned by a
     worktree and can be cleaned up in the same run rather than the next one.

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

from shad.errors import ShadError
from shad.git import apply, discover, refs, report
from shad.git import plan as planning
from shad.git.model import ProjectOutcome, ProjectPlan, Repo, SyncRun
from shad.git.run import GitMissing, require_git
from shad.shared.config import Config, Project, resolve_target
from shad.trace import Trace

console = Console()

ACTIONS = ("sync", "panel")

# Each unit of work is a `git fetch` subprocess; an uncapped pool would open
# one per configured project, contending for the ssh-agent and the link.
MAX_WORKERS = 8


# ── inspect (phase 0-2) ───────────────────────────────────────────────────


def fetch_and_plan(
    project: Project,
    *,
    dry_run: bool = False,
    switch: bool = False,
    found: Repo | None = None,
) -> ProjectPlan:
    """
    Apply the ungated steps for one project and compute what is still pending.

    Runs in a worker thread: it must not print, and it must not raise for an
    ordinary per-project problem — those become a status on the returned plan.

    *found* is the already-resolved repository. _inspect resolves every project
    up front so it can drop duplicates before any fetch runs; passing the
    result through avoids discovering twice. Callers that plan a single project
    can omit it.
    """
    plan = ProjectPlan(project=project)

    if found is None:
        try:
            found = discover.discover(project.path)
        except discover.NotUsable as exc:
            plan.status = "skipped"
            plan.detail = str(exc)
            return plan
        except GitMissing as exc:
            plan.status = "failed"
            plan.detail = str(exc)
            return plan

    root = found.root
    plan.relinked_from = found.relinked_from

    operation = discover.in_progress(root)
    if operation is not None:
        plan.status = "skipped"
        plan.detail = f"{operation} in progress"
        return plan

    remotes = refs.list_remotes(root)
    remote = refs.primary_remote(remotes)
    if remote is None and remotes:
        plan.status = "skipped"
        plan.detail = (
            f"multiple remotes ({', '.join(sorted(remotes))}) and no 'origin'"
        )
        return plan

    gone_allowed = False

    if remote is not None:
        before, before_symrefs = refs.snapshot_remotes(root)
        result = apply.fetch(root, remote, prune=not dry_run)
        if not result.ok:
            plan.status = "failed"
            plan.detail = result.error
            return plan

        after, after_symrefs = refs.snapshot_remotes(root)
        # Union, not just the second snapshot: the applied path looks at refs
        # present before and absent after, which can never appear in `after`'s
        # symrefs, so filtering on that alone lets a pruned origin/HEAD through
        # as a deletion-justifying last-known OID.
        pruned_oids = planning.stale_upstreams(
            root,
            remote,
            before,
            after,
            before_symrefs | after_symrefs,
            dry_run=dry_run,
        )
        if pruned_oids is None:
            plan.status = "failed"
            plan.detail = f"could not list branches on {remote}"
            return plan

        plan.pruned_refs = sorted(ref.removeprefix("refs/remotes/") for ref in pruned_oids)
        gone_allowed = refs.has_full_refspec(root, remote)
    else:
        pruned_oids = {}

    worktrees = refs.list_worktrees(root)
    if not worktrees:
        # Every usable repository has at least a main worktree, so an empty
        # list means `git worktree list` failed. Carrying on would treat every
        # branch as unchecked out: branches held by a linked worktree would be
        # offered for deletion, and --switch would lose its holder gate.
        plan.status = "failed"
        plan.detail = "could not list worktrees"
        return plan
    checked_out = {w.branch: w.path for w in worktrees if w.branch}

    default = (
        refs.default_branch(root, remote, allow_network=True) if remote is not None else None
    )
    plan.default_branch = default

    if default is None:
        # Must be a status, not a bare detail: the report prints `detail` only
        # for skipped and failed projects, so an "ok" plan with nothing else to
        # show would render as "up to date". A repository with no remotes
        # reaches this too.
        plan.status = "skipped"
        plan.detail = (
            "no remote configured"
            if remote is None
            else "cannot determine the default branch"
        )
        return plan

    remote_ref = f"refs/remotes/{remote}/{default}"
    local_ref = f"refs/heads/{default}"

    plan.fast_forward = apply.fast_forward(
        root, default, local_ref, remote_ref, checked_out, dry_run=dry_run
    )

    if switch:
        plan.switch = apply.switch_default(
            root, default, local_ref, checked_out, dry_run=dry_run
        )
        if plan.switch.status == "switched":
            # HEAD moved, so the worktree list is stale. Re-read it: the branch
            # just left behind must stop counting as checked out, or it cannot
            # be deleted until the next run.
            worktrees = refs.list_worktrees(root)
            checked_out = {w.branch: w.path for w in worktrees if w.branch}
        elif plan.switch.from_branch:
            # Dry run: the switch did not happen, but it passed every gate, so
            # the real run will make it. Model the un-pinning anyway, or the
            # preview keeps the branch the real run would offer for deletion —
            # a preview that disagrees with the run it is previewing.
            checked_out.pop(f"refs/heads/{plan.switch.from_branch}", None)

    default_tips = [
        oid
        for oid in (refs.ref_oid(root, remote_ref), refs.ref_oid(root, local_ref))
        if oid is not None
    ]
    if not default_tips:
        return plan

    branches = refs.list_branches(root)
    plan.pruned_tracked_by = {
        ref.removeprefix("refs/remotes/"): b.name
        for ref in pruned_oids
        for b in branches
        if b.upstream == ref
    }

    # Only the main worktree pins a branch outright. A branch held by a linked
    # worktree is still a delete candidate here, because that worktree may
    # itself be removable — reconcile() settles the pair below.
    main_worktree = worktrees[0].path
    pinned = {ref: path for ref, path in checked_out.items() if path == main_worktree}

    branch_plan = planning.classify_branches(
        root,
        branches,
        default=default,
        default_tips=default_tips,
        checked_out=pinned,
        pruned_oids=pruned_oids,
        gone_allowed=gone_allowed,
        shallow=found.shallow,
    )

    worktree_plan = planning.classify_worktrees(
        root,
        worktrees,
        deleting={f"refs/heads/{b.name}" for b in branch_plan.delete},
        known_branches={b.refname for b in branches},
    )

    deletions, kept = planning.reconcile(branch_plan, worktree_plan, checked_out)
    plan.branch_deletions = deletions
    plan.branches_kept = kept
    plan.worktree_removals = worktree_plan.remove
    plan.worktrees_kept = worktree_plan.keep

    plan.repo_root = root
    return plan


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

    prune_only = [w for w in plan.worktree_removals if w.prune_only]
    if prune_only:
        error = apply.prune_worktrees(root)
        if error is not None:
            outcome.failures.append(f"worktree prune: {error}")
        else:
            # Report only what git actually dropped. `worktree prune` has its
            # own opinion — it keeps a record whose gitdir file is recent, and
            # honours gc.worktreePruneExpire — so a clean exit is not proof.
            # Claiming a removal that did not happen hides the leftover record.
            try:
                remaining = {w.path for w in refs.list_worktrees(root)}
            except ShadError as exc:
                outcome.failures.append(f"worktree prune: {exc}")
                remaining = {w.path for w in prune_only}  # claim nothing
            for worktree in prune_only:
                if worktree.path in remaining:
                    outcome.failures.append(
                        f"worktree {worktree.path}: still registered after prune"
                    )
                else:
                    outcome.removed_worktrees.append(worktree.path)

    for worktree in plan.worktree_removals:
        if worktree.prune_only:
            continue
        error = apply.remove_worktree(root, worktree.path)
        if error is not None:
            outcome.failures.append(f"worktree {worktree.path}: {error}")
        else:
            outcome.removed_worktrees.append(worktree.path)

    for branch in plan.branch_deletions:
        # Re-verify the tip: the user may have been at the prompt while another
        # pane committed. This is the only TOCTOU window, and -D has no net.
        try:
            current = refs.ref_oid(root, f"refs/heads/{branch.name}")
        except ShadError as exc:
            # Reported here rather than raised: the deletions already applied
            # for this project must survive, and so must the projects queued
            # behind it.
            outcome.failures.append(f"branch {branch.name}: {exc}")
            continue
        if current is None:
            outcome.failures.append(f"branch {branch.name}: already gone")
            continue
        if current != branch.oid:
            outcome.failures.append(
                f"branch {branch.name}: moved since the plan was made; skipped"
            )
            continue
        error = apply.delete_branch(root, branch.name, force=branch.force)
        if error is not None:
            outcome.failures.append(f"branch {branch.name}: {error}")
        else:
            outcome.deleted_branches.append(branch)

    if plan.worktree_removals:
        apply.prune_worktrees(root)  # cheap no-op safety net

    return outcome


# ── orchestration ─────────────────────────────────────────────────────────


def sync_projects(
    projects: list[Project],
    *,
    yes: bool = False,
    dry_run: bool = False,
    switch: bool = False,
    trace: Trace | None = None,
) -> SyncRun:
    """
    Run the full sync over *projects* and return what happened. *trace*
    receives the traceback of every per-project failure the run recorded.
    """
    trace = trace or Trace()
    if not projects:
        console.print(Text("no projects configured", style="dim"))
        return SyncRun(dry_run=dry_run)

    require_git()

    report.render_header(len(projects))
    plans = _inspect(projects, dry_run=dry_run, switch=switch, trace=trace)

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
        # Still summarise: the fetch and fast-forward already happened, and a
        # project that failed during them must not vanish because the user
        # declined the deletions.
        run = SyncRun(
            outcomes=[ProjectOutcome(plan=p) for p in plans], confirmed=False
        )
        report.render_summary(run)
        return run

    outcomes = [_apply_one(p, trace) for p in plans]
    run = SyncRun(outcomes=outcomes)
    report.render_results(outcomes)
    report.render_summary(run)
    _raise_if_all_failed(run)
    return run


def _apply_one(plan: ProjectPlan, trace: Trace) -> ProjectOutcome:
    """
    Apply one plan, converting an unexpected escape into a recorded failure.

    apply_plan already reports git's own errors, but its plumbing reads raise
    ShadError on timeout. Without this guard one slow repository would abandon
    every project queued behind it — after earlier ones had already deleted
    things.
    """
    if not plan.pending:
        return ProjectOutcome(plan=plan)
    try:
        return apply_plan(plan)
    except Exception as exc:  # noqa: BLE001 — one bad project must not abort the rest
        trace.exception(exc)
        return ProjectOutcome(plan=plan, failures=[str(exc)])


def _inspect(
    projects: list[Project], *, dry_run: bool, switch: bool = False, trace: Trace | None = None
) -> list[ProjectPlan]:
    """
    Resolve every project, drop repositories already covered, then fan out.

    Results are collected by index because as_completed scrambles order, and a
    worker failure lands on the plan rather than aborting the batch.
    """
    trace = trace or Trace()
    plans: list[ProjectPlan | None] = [None] * len(projects)
    jobs = _resolve(projects, plans, trace)

    if jobs:
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(jobs))) as pool:
            futures = {
                pool.submit(
                    fetch_and_plan, project, dry_run=dry_run, switch=switch, found=found
                ): index
                for index, project, found in jobs
            }
            for future in as_completed(futures):
                index = futures[future]
                try:
                    plans[index] = future.result()
                except Exception as exc:  # noqa: BLE001 — one bad project must not abort the rest
                    trace.exception(exc)
                    plans[index] = ProjectPlan(
                        project=projects[index], status="failed", detail=str(exc)
                    )

    return [p for p in plans if p is not None]


def _resolve(
    projects: list[Project], plans: list[ProjectPlan | None], trace: Trace | None = None
) -> list[tuple[int, Project, Repo]]:
    """
    Resolve each project to its repository and drop the ones already covered.

    Two configured directories can be one repository — linked worktrees share a
    ref store, an object store, and a branch list. `discover` re-roots a linked
    worktree onto its main worktree, so both land on the same repository, and
    without this pass both would be planned: the same branch listed twice in
    the confirmation table, and the second apply reporting "already gone" for
    work the first did. Concurrent fetches of one ref store also split the
    prune evidence non-deterministically between them.

    Identity is --git-common-dir, not the path: two *clones* of one remote have
    different common dirs and different local branches, so both must be synced.

    This runs serially on the main thread, before any fetch, because a worker
    cannot see its peers and the duplicate has to be dropped before it opens a
    second connection. It is local-only — a couple of rev-parse calls per
    project, no network.
    """
    trace = trace or Trace()
    resolved: list[tuple[int, Project, Repo]] = []

    for index, project in enumerate(projects):
        try:
            found = discover.discover(project.path)
        except discover.NotUsable as exc:
            plans[index] = ProjectPlan(
                project=project, status="skipped", detail=str(exc)
            )
        except GitMissing as exc:
            plans[index] = ProjectPlan(
                project=project, status="failed", detail=str(exc)
            )
        except Exception as exc:  # noqa: BLE001 — one bad project must not abort the rest
            # discover() runs git, so a timeout raises ShadError. This pass is
            # on the main thread, outside the pool's per-future guard, so an
            # escape here would abort the whole run before any other project
            # was even inspected.
            trace.exception(exc)
            plans[index] = ProjectPlan(
                project=project, status="failed", detail=str(exc)
            )
        else:
            resolved.append((index, project, found))

    # One project per repository. A project configured at the repository root
    # beats one configured at a linked worktree, whatever order they appear in:
    # it needs no re-rooting, and it makes "same repository as X" name the
    # directory the work actually happens in.
    chosen: dict[Path, tuple[int, Project, Repo]] = {}
    for entry in resolved:
        found = entry[2]
        current = chosen.get(found.common_dir)
        if current is None or (
            current[2].relinked_from is not None and found.relinked_from is None
        ):
            chosen[found.common_dir] = entry

    jobs: list[tuple[int, Project, Repo]] = []
    for entry in resolved:
        index, project, found = entry
        winner = chosen[found.common_dir]
        if winner[0] == index:
            jobs.append(entry)
        else:
            plans[index] = ProjectPlan(
                project=project,
                status="skipped",
                detail=f"same repository as {winner[1].display_name}",
            )

    return jobs


def _raise_if_all_failed(run: SyncRun) -> None:
    """A run where every project failed is a real failure; a partial one is not."""
    if run.outcomes and all(o.plan.status == "failed" for o in run.outcomes):
        raise ShadError.infrastructure("sync_failed", f"all {len(run.outcomes)} project(s) failed")


def cmd_git(cfg: Config, args: argparse.Namespace, trace: Trace | None = None) -> None:
    action = getattr(args, "git_action", None)
    if action is None:
        raise ShadError.usage("no_action", f"no git action given; available: {', '.join(ACTIONS)}")
    if action not in ACTIONS:
        raise ShadError.usage(
            "unknown_action",
            f"unknown git action '{action}'; available: {', '.join(ACTIONS)}"
        )

    if action == "panel":
        open_panel(cfg, list(args.name), fetch=not getattr(args, "no_fetch", False))
        return

    target = resolve_target(cfg, list(args.name), usage="shad git sync")
    sync_projects(
        target.projects,
        yes=getattr(args, "yes", False),
        dry_run=getattr(args, "dry_run", False),
        switch=getattr(args, "switch", False),
        trace=trace,
    )


def open_panel(cfg: Config, name: list[str], *, fetch: bool) -> None:
    """Run the read-only git panel against exactly one repository."""
    require_git()
    repo = _resolve_one(cfg, name)
    # Imported here, not at module scope: textual costs roughly 100ms to
    # import, and `shad git sync` must not pay it.
    from shad.git.panel import run_panel

    run_panel(repo, fetch=fetch)


def _resolve_one(cfg: Config, name: list[str]) -> Repo:
    """
    The single repository the panel shows.

    With no name this is the current directory, which is what makes the panel
    usable from any repository rather than only from a configured project.
    That differs from `sync`, where no name means every configured project —
    a single-repository view has no all-projects form.
    """
    if not name:
        path = Path.cwd()
    else:
        target = resolve_target(cfg, name, usage="shad git panel")
        if len(target.projects) != 1:
            names = ", ".join(p.display_name for p in target.projects)
            raise ShadError.usage(
                "ambiguous_target",
                f"'{' '.join(name)}' matches {len(target.projects)} projects "
                f"({names}); shad git panel shows one repository"
            )
        path = target.projects[0].path

    try:
        return discover.discover(path)
    except discover.NotUsable as exc:
        # The sync report prints a NotUsable hint on its own line; the error
        # line is one line.
        reason = "; ".join(line.strip() for line in str(exc).splitlines())
        raise ShadError.not_found("no_repository", reason) from None
    except GitMissing as exc:
        raise ShadError.infrastructure("git_missing", str(exc)) from None
