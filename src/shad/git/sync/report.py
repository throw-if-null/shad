"""
Rendering for `shad git sync`.

Nothing here runs git or decides anything — it prints the plans and outcomes
that shad.git.sync.command produces, on the Output the root injected. Sections
with nothing to show are omitted entirely, and projects with nothing to
report collapse to a single line, so a seven-project run stays readable.
"""

from __future__ import annotations

from rich.text import Text

from shad.git.model import ProjectOutcome, ProjectPlan, SyncRun
from shad.output import Output
from shad.style import make_table


def _plural(count: int, noun: str, plural: str | None = None) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {plural or noun + 's'}"


def render_header(out: Output, count: int) -> None:
    """Announce a multi-project run, so the network gap is not silent."""
    if count > 1:
        out.print()
        out.print(Text(f"syncing {_plural(count, 'project')}…", style="dim"))


def _project_title(plan: ProjectPlan) -> Text:
    return Text(plan.project.display_name, style="bold bright_white") + Text(
        f"  {plan.project.path}", style="dim"
    )


def _render_fetch(out: Output, plan: ProjectPlan) -> None:
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
    out.print(table)


def _render_pruned(out: Output, plan: ProjectPlan, *, dry_run: bool) -> None:
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
    out.print(table)


def _render_kept(out: Output, plan: ProjectPlan) -> None:
    """Branches and worktrees get separate tables — their columns differ."""
    if plan.branches_kept:
        table = make_table("branches kept")
        for branch in plan.branches_kept:
            table.add_row(
                Text(branch.name, style="cyan"),
                Text(branch.sha, style="yellow"),
                Text(branch.reason, style="dim"),
            )
        out.print(table)

    if plan.worktrees_kept:
        table = make_table("worktrees kept")
        for worktree in plan.worktrees_kept:
            table.add_row(
                Text(str(worktree.path), style="cyan", overflow="fold"),
                Text(worktree.branch_name, style="cyan"),
                Text(worktree.reason, style="dim"),
            )
        out.print(table)


def render_applied(out: Output, plans: list[ProjectPlan], *, dry_run: bool = False) -> None:
    """
    Report what already happened: fetch, prune, and fast-forward.

    Printed before the confirmation prompt, in the past tense, because
    declining the prompt does not undo any of it.
    """
    out.print()
    for plan in plans:
        if plan.status == "skipped":
            out.print(
                Text("  ● ", style="cyan")
                + Text(f"{plan.project.display_name}  ", style="dim")
                + Text(plan.detail or "skipped", style="dim")
            )
            continue
        if plan.status == "failed":
            out.print(
                Text("  ✗ ", style="bold red")
                + Text(f"{plan.project.display_name}  ", style="bright_white")
                + Text(plan.detail or "failed", style="dim")
            )
            continue
        if not plan.changed:
            out.print(
                Text("  ● ", style="cyan")
                + Text(f"{plan.project.display_name}  ", style="bright_white")
                + Text("up to date", style="dim")
            )
            continue

        out.print()
        out.print(_project_title(plan))
        out.print()
        _render_fetch(out, plan)
        _render_pruned(out, plan, dry_run=dry_run)
        _render_kept(out, plan)


def render_pending(out: Output, plans: list[ProjectPlan]) -> None:
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

    out.print()
    out.print(table)


def render_dry_run_footer(out: Output) -> None:
    out.print()
    out.print(Text("  dry run — nothing was deleted", style="dim"))
    out.print()


def render_results(out: Output, outcomes: list[ProjectOutcome]) -> None:
    """Per-deletion results, including the OID needed to undo a branch delete."""
    printed = False
    for outcome in outcomes:
        for path in outcome.removed_worktrees:
            if not printed:
                out.print()
                printed = True
            out.print(
                Text("  ✓ ", style="bold green")
                + Text("removed worktree  ", style="dim")
                + Text(str(path), style="cyan")
            )
        for branch in outcome.deleted_branches:
            if not printed:
                out.print()
                printed = True
            # Deleting a branch drops its reflog, so this is the user's only
            # recovery path until the next gc. The command carries the full
            # OID: a 7-character prefix can be ambiguous in a large repository,
            # and an undo that fails to resolve is no undo at all.
            out.print(
                Text("  ✓ ", style="bold green")
                + Text("deleted branch    ", style="dim")
                + Text(branch.name, style="cyan")
                + Text(f"  (was {branch.sha})", style="dim")
                + Text(
                    f"  restore: git branch {branch.name} {branch.oid or branch.sha}",
                    style="dim",
                )
            )
        for failure in outcome.failures:
            if not printed:
                out.print()
                printed = True
            out.print(Text("  ✗ ", style="bold red") + Text(failure, style="dim"))


def render_summary(out: Output, run: SyncRun) -> None:
    """Counts on one line, then any per-project failures beneath it."""
    synced = [o for o in run.outcomes if o.plan.status == "ok"]
    skipped = [o for o in run.outcomes if o.plan.status == "skipped"]
    failed = [o for o in run.outcomes if o.plan.status == "failed"]
    branches = sum(len(o.deleted_branches) for o in run.outcomes)
    worktrees = sum(len(o.removed_worktrees) for o in run.outcomes)

    out.print()
    glyph = (
        Text("  ✓ ", style="bold green")
        if synced
        else Text("  · ", style="dim")
    )
    parts = [_plural(len(synced), "project") + " synced"]
    if branches:
        parts.append(_plural(branches, "branch", "branches") + " deleted")
    if worktrees:
        parts.append(_plural(worktrees, "worktree") + " removed")
    if skipped:
        parts.append(_plural(len(skipped), "project") + " skipped")
    out.print(glyph + Text("   ".join(parts), style="dim"))

    if failed:
        out.print(
            Text("  ✗ ", style="bold red")
            + Text(_plural(len(failed), "project") + " failed", style="dim")
        )
        for outcome in failed:
            out.print(
                Text(f"      {outcome.plan.project.display_name}   ", style="bright_white")
                + Text(outcome.plan.detail or "unknown error", style="dim")
            )
    out.print()


def render_aborted(out: Output) -> None:
    out.print(Text("  Aborted.", style="dim"))
