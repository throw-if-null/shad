"""
The git panel — the read-only repository view that occupies shad's git pane.

Three sections (branches, worktrees, stashes) behind a left nav, over a
one-line header. Nothing here mutates the repository: the only git write the
panel performs is the fetch inside snapshot.collect, which touches
remote-tracking refs and nothing else.

The pane is about 17 rows by 40 to 50 columns at shad's default panel_percent
and todo_percent, so the header is one line rather than a table and the nav
column is fixed narrow.

textual is imported by this module only, and shad.git.command imports this
module lazily, so `shad projects` and `shad git sync` never pay for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import (
    ContentSwitcher,
    DataTable,
    Footer,
    ListItem,
    ListView,
    Static,
)

from shad.errors import ShadError
from shad.git.model import BranchRef, Repo, short_branch
from shad.git.snapshot import Snapshot, collect
from shad.shared.render import relative_age

# Nav entries, in display order. The id is also the DataTable/ContentSwitcher id.
BRANCHES = "branches"
WORKTREES = "worktrees"
STASHES = "stashes"


@dataclass(frozen=True)
class Section:
    id: str
    label: str
    columns: tuple[str, ...]


SECTIONS: tuple[Section, ...] = (
    Section(BRANCHES, "branches", ("branch", "", "upstream")),
    Section(WORKTREES, "worktrees", ("worktree", "branch", "")),
    Section(STASHES, "stashes", ("ref", "branch", "message", "age")),
)


# %(upstream:trackshort) is a symbol, not a translated string. Spell it out.
_TRACK = {
    "=": ("=", "in sync"),
    ">": ("↑", "ahead"),
    "<": ("↓", "behind"),
    "<>": ("↕", "diverged"),
}


def _upstream(branch: BranchRef) -> str:
    """
    The upstream, abbreviated to fit a narrow pane.

    An upstream whose branch name matches the local one renders as just the
    remote, because "origin/some-long-branch-name" beside "some-long-branch-
    name" spends the width on the one part the reader already knows. A branch
    tracking a *differently named* upstream is the case worth the space, so
    that one keeps "remote/name" in full.
    """
    if not branch.upstream:
        return "—"
    tracked = branch.upstream.removeprefix("refs/remotes/")
    remote, _, name = tracked.partition("/")
    return remote if name == branch.name else tracked


class GitPanel(App[None]):
    """Read-only repository view."""

    CSS = """
    Screen { layers: base; }
    #header { height: 1; padding: 0 1; background: $panel; color: $text; }
    #body { height: 1fr; }
    /* 16 = 12-char label + 2 padding + 1 border, with a column to spare.
       Narrower and the labels wrap onto a second line. */
    #nav { width: 16; border-right: solid $panel-lighten-2; }
    #nav > ListItem { padding: 0 1; }
    ContentSwitcher { width: 1fr; }
    DataTable { height: 1fr; }
    #message { padding: 0 1; color: $text-muted; }
    """

    ENABLE_COMMAND_PALETTE = False

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("q", "quit", "quit"),
        Binding("r", "refresh", "refresh"),
        Binding("tab", "focus_next", "focus", show=False),
        Binding("j", "cursor_down", "down", show=False),
        Binding("k", "cursor_up", "up", show=False),
    ]

    def __init__(self, repo: Repo, *, fetch: bool = True) -> None:
        super().__init__()
        self._repo = repo
        self._fetch_on_start = fetch
        self._snapshot: Snapshot | None = None
        self._busy = False

    # ── layout ────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Static("", id="header")
        with Horizontal(id="body"):
            yield ListView(
                *(ListItem(Static(s.label), id=f"nav-{s.id}") for s in SECTIONS),
                id="nav",
            )
            with ContentSwitcher(initial=BRANCHES):
                for section in SECTIONS:
                    table: DataTable[str] = DataTable(id=section.id)
                    table.cursor_type = "row"
                    table.zebra_stripes = True
                    yield table
        yield Footer()

    def on_mount(self) -> None:
        for section in SECTIONS:
            self.query_one(f"#{section.id}", DataTable).add_columns(*section.columns)
        self._set_header("reading repository…")
        self.load(fetch=self._fetch_on_start)

    # ── data ──────────────────────────────────────────────────────────────

    def load(self, *, fetch: bool) -> None:
        """Collect in a thread so the fetch cannot block the UI."""
        if self._busy:
            return
        self._busy = True
        self._collect(fetch)

    def _collect(self, fetch: bool) -> None:
        # Wrapped rather than decorated so the tests can call load() and await
        # the worker through the app's own worker group.
        self.run_worker(
            lambda: collect(self._repo, fetch=fetch),
            name="collect",
            thread=True,
            exit_on_error=False,
        )

    def on_worker_state_changed(self, event: object) -> None:
        state = getattr(event, "state", None)
        worker = getattr(event, "worker", None)
        if worker is None or getattr(worker, "name", "") != "collect":
            return
        name = getattr(state, "name", "")
        if name == "SUCCESS":
            self._busy = False
            self.apply_snapshot(worker.result)
        elif name in ("ERROR", "CANCELLED"):
            self._busy = False
            self._set_header(_failure(worker.error))

    def apply_snapshot(self, snapshot: Snapshot) -> None:
        self._snapshot = snapshot
        self._render_header(snapshot)
        self._fill_branches(snapshot)
        self._fill_worktrees(snapshot)
        self._fill_stashes(snapshot)
        self._label_nav(snapshot)

    # ── rendering ─────────────────────────────────────────────────────────

    def _set_header(self, text: str) -> None:
        self.query_one("#header", Static).update(text)

    def _render_header(self, snap: Snapshot) -> None:
        # Ordered most to least urgent, because a narrow pane truncates the
        # tail: at 28 columns the branch must still be visible, and the git
        # version is the one fact that never changes between runs.
        bits = [snap.head or "detached"]
        # Tracking state describes HEAD's branch, so an untracked HEAD says so
        # rather than borrowing "up to date" from the fact that a remote exists.
        if snap.head_upstream is None:
            bits.append("no upstream")
        elif snap.behind or snap.ahead:
            if snap.behind:
                bits.append(f"↓{snap.behind}")
            if snap.ahead:
                bits.append(f"↑{snap.ahead}")
        else:
            bits.append("up to date")
        if snap.fetch_error:
            bits.append("fetch failed")
        elif snap.remote is None:
            bits.append("no remote")
        bits.append(snap.name)
        if snap.git_version:
            bits.append(f"git {snap.git_version}")
        self._set_header("  ·  ".join(bits))

    def _label_nav(self, snap: Snapshot) -> None:
        counts = {
            BRANCHES: len(snap.branches),
            WORKTREES: len(snap.worktrees),
            STASHES: len(snap.stashes),
        }
        for section in SECTIONS:
            item = self.query_one(f"#nav-{section.id}", ListItem)
            item.query_one(Static).update(f"{section.label:<9}{counts[section.id]:>3}")

    def _fill_branches(self, snap: Snapshot) -> None:
        table = self._reset(BRANCHES)
        held = snap.checked_out
        for branch in sorted(snap.branches, key=lambda b: b.name):
            symbol, _ = _TRACK.get(branch.trackshort, ("", ""))
            marker = "● " if branch.refname in held else "  "
            table.add_row(f"{marker}{branch.name}", symbol, _upstream(branch))

    def _fill_worktrees(self, snap: Snapshot) -> None:
        table = self._reset(WORKTREES)
        for worktree in snap.worktrees:
            if worktree.detached:
                branch = "detached"
            elif worktree.branch:
                branch = short_branch(worktree.branch)
            else:
                branch = "—"
            flags = []
            if worktree.locked:
                flags.append("locked")
            if worktree.prunable:
                flags.append("prunable")
            if worktree.bare:
                flags.append("bare")
            table.add_row(worktree.path.name, branch, " ".join(flags))

    def _fill_stashes(self, snap: Snapshot) -> None:
        table = self._reset(STASHES)
        for stash in snap.stashes:
            table.add_row(
                stash.ref, stash.branch or "—", stash.message, relative_age(stash.timestamp)
            )

    def _reset(self, section_id: str) -> DataTable[str]:
        table: DataTable[str] = self.query_one(f"#{section_id}", DataTable)
        table.clear()
        return table

    # ── interaction ───────────────────────────────────────────────────────

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item is None or not event.item.id:
            return
        self.query_one(ContentSwitcher).current = event.item.id.removeprefix("nav-")

    def action_refresh(self) -> None:
        if self._busy:
            return
        self._set_header("fetching…")
        self.load(fetch=True)

    def action_cursor_down(self) -> None:
        self._active().action_cursor_down()

    def action_cursor_up(self) -> None:
        self._active().action_cursor_up()

    def _active(self) -> DataTable[str]:
        current = self.query_one(ContentSwitcher).current or BRANCHES
        return self.query_one(f"#{current}", DataTable)


def _failure(error: BaseException | None) -> str:
    """The header line for a failed reading: the model's code and category when it has them."""
    if isinstance(error, ShadError):
        return f"{error.code} ({error.category}): {error.message}"
    return f"failed: {error}" if error else "failed"


def run_panel(repo: Repo, *, fetch: bool = True) -> None:
    GitPanel(repo, fetch=fetch).run()
