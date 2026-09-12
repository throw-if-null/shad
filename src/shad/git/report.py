"""
Rendering for `shad git sync`.

Nothing here runs git or decides anything — it prints the plans and outcomes
that shad.git.command produces. Sections with nothing to show are omitted
entirely, and projects with nothing to report collapse to a single line, so a
seven-project run stays readable.
"""

from __future__ import annotations

from rich.console import Console
from rich.text import Text

from shad.git.model import ProjectOutcome, ProjectPlan, SyncRun
from shad.shared.render import make_table

console = Console()


def _plural(count: int, noun: str, plural: str | None = None) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {plural or noun + 's'}"


def render_header(count: int) -> None:
    """Announce a multi-project run, so the network gap is not silent."""
    if count > 1:
        console.print()
        console.print(Text(f"syncing {_plural(count, 'project')}…", style="dim"))


def _project_title(plan: ProjectPlan) -> Text:
    return Text(plan.project.display_name, style="bold bright_white") + Text(
        f"  {plan.project.path}", style="dim"
    )


def _render_fetch(plan: ProjectPlan) -> None:
    rows: list[tuple[str, Text]] = []

    if plan.relinked_from is not None:
        rows.append(
            ("worktree", Text(f"{plan.relinked_from} — syncing the whole repository", style="dim"))
        )
    if plan.default_branch:
        rows.append(("default branch", Text(plan.default_branch, style="bright_white")))

    sw = plan.switch
    if sw is not None and sw.status != "current":
        if sw.from_branch:
            # from_branch is set only when a switch happened or would have;
            # every earlier gate returns a bare reason instead.
            value = Text()
            if sw.status != "switched":
                value.append("would switch  ", style="dim")
            value.append(sw.from_branch, style="cyan")
            value.append(" → ")
            value.append(sw.branch, style="bright_white")
        else:
            value = Text(sw.detail or "skipped", style="dim")
        rows.append(("switch", value))

    ff = plan.fast_forward
    if ff is not None:
        if ff.status == "current":
            value = Text("up to date", style="dim")
        elif ff.before and ff.after:
            # Both the applied and the dry-run case know the range; only the
            # leading verb differs.
            value = Text()
            if ff.status != "advanced":
                value.append("would advance  ", style="dim")
            value.append(ff.before, style="yellow")
            value.append(" → ")
            value.append(ff.after, style="yellow")
            value.append(f"  +{ff.ahead}", style="bold green")
        else:
            value = Text(ff.detail or "skipped", style="dim")
        rows.append(("fast-forward", value))

    if not rows:
        return

    table = make_table("fetch")
    for label, value in rows:
        table.add_row(Text(label, style="dim"), value)
    console.print(table)


def _render_pruned(plan: ProjectPlan, *, dry_run: bool) -> None:
    if not plan.pruned_refs:
        return
    # --dry-run fetches but never prunes, so these refs are still present.
    table = make_table("stale remote refs (would prune)" if dry_run else "pruned remote refs")
    tracked = plan.pruned_tracked_by
    for ref in plan.pruned_refs:
        note = tracked.get(ref)
        table.add_row(
            Text(ref, style="cyan"),
            Text(f"was tracked by {note}", style="dim") if note else Text(""),
        )
    console.print(table)


def _render_kept(plan: ProjectPlan) -> None:
    """Branches and worktrees get separate tables — their columns differ."""
    if plan.branches_kept:
        table = make_table("branches kept")
        for branch in plan.branches_kept:
            table.add_row(
                Text(branch.name, style="cyan"),
                Text(branch.sha, style="yellow"),
                Text(branch.reason, style="dim"),
            )
        console.print(table)

    if plan.worktrees_kept:
        table = make_table("worktrees kept")
        for worktree in plan.worktrees_kept:
            table.add_row(
                Text(str(worktree.path), style="cyan", overflow="fold"),
                Text(worktree.branch_name, style="cyan"),
                Text(worktree.reason, style="dim"),
            )
        console.print(table)


def render_applied(plans: list[ProjectPlan], *, dry_run: bool = False) -> None:
    """
    Report what already happened: fetch, prune, and fast-forward.

    Printed before the confirmation prompt, in the past tense, because
    declining the prompt does not undo any of it.
    """
    console.print()
    for plan in plans:
        if plan.status == "skipped":
            console.print(
                Text("  ● ", style="cyan")
                + Text(f"{plan.project.display_name}  ", style="dim")
                + Text(plan.detail or "skipped", style="dim")
            )
            continue
        if plan.status == "failed":
            console.print(
                Text("  ✗ ", style="bold red")
                + Text(f"{plan.project.display_name}  ", style="bright_white")
                + Text(plan.detail or "failed", style="dim")
            )
            continue
        if not plan.changed:
            console.print(
                Text("  ● ", style="cyan")
                + Text(f"{plan.project.display_name}  ", style="bright_white")
                + Text("up to date", style="dim")
            )
            continue

        console.print()
        console.print(_project_title(plan))
        console.print()
        _render_fetch(plan)
        _render_pruned(plan, dry_run=dry_run)
        _render_kept(plan)


def render_pending(plans: list[ProjectPlan]) -> None:
    """
    One consolidated table of every deletion across every project.

    This is the exact set the user is consenting to, so it must be readable in
    one glance rather than split across per-project tables.
    """
    table = make_table("pending deletions")
    for plan in plans:
        name = plan.project.display_name
        for worktree in plan.worktree_removals:
            table.add_row(
                Text(name, style="bright_white"),
                Text("worktree", style="dim"),
                Text(str(worktree.path), style="cyan", overflow="fold"),
                Text(worktree.branch_name or "", style="cyan"),
                Text(worktree.reason, style="dim"),
            )
        for branch in plan.branch_deletions:
            table.add_row(
                Text(name, style="bright_white"),
                Text("branch", style="dim"),
                Text(branch.name, style="cyan"),
                Text(branch.sha, style="yellow"),
                Text(branch.reason, style="dim"),
            )

    console.print()
    console.print(table)


def render_dry_run_footer() -> None:
    console.print()
    console.print(Text("  dry run — nothing was deleted", style="dim"))
    console.print()


def render_results(outcomes: list[ProjectOutcome]) -> None:
    """Per-deletion results, including the OID needed to undo a branch delete."""
    printed = False
    for outcome in outcomes:
        for path in outcome.removed_worktrees:
            if not printed:
                console.print()
                printed = True
            console.print(
                Text("  ✓ ", style="bold green")
                + Text("removed worktree  ", style="dim")
                + Text(str(path), style="cyan")
            )
        for branch in outcome.deleted_branches:
            if not printed:
                console.print()
                printed = True
            # Deleting a branch drops its reflog, so this OID is the user's
            # only recovery path until the next gc. Always show it.
            console.print(
                Text("  ✓ ", style="bold green")
                + Text("deleted branch    ", style="dim")
                + Text(branch.name, style="cyan")
                + Text(f"  (was {branch.sha})", style="dim")
                + Text(f"  restore: git branch {branch.name} {branch.sha}", style="dim")
            )
        for failure in outcome.failures:
            if not printed:
                console.print()
                printed = True
            console.print(Text("  ✗ ", style="bold red") + Text(failure, style="dim"))


def render_summary(run: SyncRun) -> None:
    """Counts on one line, then any per-project failures beneath it."""
    synced = [o for o in run.outcomes if o.plan.status == "ok"]
    skipped = [o for o in run.outcomes if o.plan.status == "skipped"]
    failed = [o for o in run.outcomes if o.plan.status == "failed"]
    branches = sum(len(o.deleted_branches) for o in run.outcomes)
    worktrees = sum(len(o.removed_worktrees) for o in run.outcomes)

    console.print()
    parts = [_plural(len(synced), "project") + " synced"]
    if branches:
        parts.append(_plural(branches, "branch", "branches") + " deleted")
    if worktrees:
        parts.append(_plural(worktrees, "worktree") + " removed")
    if skipped:
        parts.append(_plural(len(skipped), "project") + " skipped")
    console.print(Text("  ✓ ", style="bold green") + Text("   ".join(parts), style="dim"))

    if failed:
        console.print(
            Text("  ✗ ", style="bold red")
            + Text(_plural(len(failed), "project") + " failed", style="dim")
        )
        for outcome in failed:
            console.print(
                Text(f"      {outcome.plan.project.display_name}   ", style="bright_white")
                + Text(outcome.plan.detail or "unknown error", style="dim")
            )
    console.print()


def render_aborted() -> None:
    console.print(Text("  Aborted.", style="dim"))
