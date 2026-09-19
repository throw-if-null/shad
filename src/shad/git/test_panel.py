"""
Smoke tests for the git panel.

Driven through textual's own `App.run_test()` under stdlib
`unittest.IsolatedAsyncioTestCase`, so the suite gains no test dependency and
still runs under pytest. The logic worth covering in depth lives in
snapshot.py, which is synchronous and tested directly; these assert that the
widgets are wired to it.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from textual.coordinate import Coordinate
from textual.widgets import ContentSwitcher, DataTable, ListItem, ListView, Static

from shad.git.model import BranchRef, Repo, Stash, Worktree
from shad.git.panel import BRANCHES, STASHES, WORKTREES, GitPanel, _age, _upstream
from shad.git.snapshot import Snapshot

ROOT = Path("/tmp/repo")
REPO = Repo(root=ROOT, common_dir=ROOT / ".git")


def _branch(name: str, *, upstream: str = "", trackshort: str = "") -> BranchRef:
    return BranchRef(
        refname=f"refs/heads/{name}",
        oid="a" * 40,
        upstream=upstream,
        remotename="origin" if upstream else "",
        trackshort=trackshort,
    )


SNAPSHOT = Snapshot(
    repo=REPO,
    git_version="2.55.0",
    head="main",
    head_upstream="refs/remotes/origin/main",
    remote="origin",
    ahead=1,
    behind=2,
    branches=[
        _branch("main", upstream="refs/remotes/origin/main", trackshort="<>"),
        _branch("side"),
    ],
    worktrees=[
        Worktree(path=ROOT, branch="refs/heads/main"),
        Worktree(path=Path("/tmp/wt"), branch=None, detached=True),
    ],
    stashes=[Stash(ref="stash@{0}", subject="On main: hello", timestamp=1, branch="main")],
)


class PanelTests(unittest.IsolatedAsyncioTestCase):
    def _app(self, snapshot: Snapshot = SNAPSHOT) -> GitPanel:
        app = GitPanel(REPO, fetch=False)
        # collect() is exercised by test_snapshot; the panel is fed directly so
        # these tests never touch a repository or the network.
        self._patch = patch("shad.git.panel.collect", return_value=snapshot)
        self._patch.start()
        self.addCleanup(self._patch.stop)
        return app

    @staticmethod
    def _header(app: GitPanel) -> str:
        return str(app.query_one("#header", Static).content)

    async def test_sections_are_populated_from_the_snapshot(self) -> None:
        app = self._app()
        async with app.run_test(size=(70, 17)) as pilot:
            await pilot.pause()
            self.assertEqual(app.query_one(f"#{BRANCHES}", DataTable).row_count, 2)
            self.assertEqual(app.query_one(f"#{WORKTREES}", DataTable).row_count, 2)
            self.assertEqual(app.query_one(f"#{STASHES}", DataTable).row_count, 1)

    async def test_header_reports_version_branch_and_both_counts(self) -> None:
        app = self._app()
        async with app.run_test(size=(70, 17)) as pilot:
            await pilot.pause()
            header = self._header(app)
        self.assertIn("2.55.0", header)
        self.assertIn("main", header)
        self.assertIn("↓2", header)
        self.assertIn("↑1", header)

    async def test_header_puts_the_branch_before_the_git_version(self) -> None:
        # A narrow pane truncates the tail, so the branch must not sit behind
        # the one fact that never changes between runs.
        app = self._app()
        async with app.run_test(size=(70, 17)) as pilot:
            await pilot.pause()
            header = self._header(app)
        self.assertLess(header.index("main"), header.index("2.55.0"))
        self.assertTrue(header.startswith("main"))

    async def test_header_says_no_upstream_rather_than_up_to_date(self) -> None:
        snapshot = Snapshot(repo=REPO, git_version="2.55.0", head="side", remote="origin")
        app = self._app(snapshot)
        async with app.run_test(size=(70, 17)) as pilot:
            await pilot.pause()
            header = self._header(app)
        self.assertIn("no upstream", header)
        self.assertNotIn("up to date", header)

    async def test_header_reports_a_failed_fetch(self) -> None:
        snapshot = Snapshot(repo=REPO, head="main", remote="origin", fetch_error="boom")
        app = self._app(snapshot)
        async with app.run_test(size=(70, 17)) as pilot:
            await pilot.pause()
            self.assertIn("fetch failed", self._header(app))

    async def test_nav_labels_carry_the_counts(self) -> None:
        app = self._app()
        async with app.run_test(size=(70, 17)) as pilot:
            await pilot.pause()
            labels = [
                str(item.query_one(Static).content) for item in app.query(ListItem)
            ]
        self.assertTrue(any(label.startswith("branches") and "2" in label for label in labels))
        self.assertTrue(any(label.startswith("stashes") and "1" in label for label in labels))

    async def test_moving_the_nav_switches_the_detail_panel(self) -> None:
        app = self._app()
        async with app.run_test(size=(70, 17)) as pilot:
            await pilot.pause()
            self.assertEqual(app.query_one(ContentSwitcher).current, BRANCHES)
            app.query_one(ListView).focus()
            await pilot.press("down")
            await pilot.pause()
            self.assertEqual(app.query_one(ContentSwitcher).current, WORKTREES)
            await pilot.press("down")
            await pilot.pause()
            self.assertEqual(app.query_one(ContentSwitcher).current, STASHES)

    async def test_q_exits(self) -> None:
        app = self._app()
        async with app.run_test(size=(70, 17)) as pilot:
            await pilot.pause()
            await pilot.press("q")
            await pilot.pause()
        self.assertFalse(app.is_running)

    async def test_refresh_recollects(self) -> None:
        app = self._app()
        async with app.run_test(size=(70, 17)) as pilot:
            await pilot.pause()
            calls_before = app.query_one(f"#{BRANCHES}", DataTable).row_count
            await pilot.press("r")
            await pilot.pause()
            await pilot.pause()
            # Rows are cleared and refilled, never appended to.
            self.assertEqual(
                app.query_one(f"#{BRANCHES}", DataTable).row_count, calls_before
            )

    async def test_a_checked_out_branch_is_marked(self) -> None:
        app = self._app()
        async with app.run_test(size=(70, 17)) as pilot:
            await pilot.pause()
            table = app.query_one(f"#{BRANCHES}", DataTable)
            names = [str(table.get_cell_at(Coordinate(row, 0))) for row in range(table.row_count)]
        self.assertTrue(any(n.startswith("●") and "main" in n for n in names))
        self.assertTrue(any(n.strip() == "side" for n in names))


class UpstreamLabelTests(unittest.TestCase):
    def test_a_same_named_upstream_shows_only_the_remote(self) -> None:
        branch = _branch("main", upstream="refs/remotes/origin/main")
        self.assertEqual(_upstream(branch), "origin")

    def test_a_differently_named_upstream_is_shown_in_full(self) -> None:
        branch = _branch("local", upstream="refs/remotes/origin/remote-name")
        self.assertEqual(_upstream(branch), "origin/remote-name")

    def test_no_upstream_renders_a_dash(self) -> None:
        self.assertEqual(_upstream(_branch("orphan")), "—")

    def test_a_slashed_branch_name_still_matches_its_upstream(self) -> None:
        branch = _branch("feat/a", upstream="refs/remotes/origin/feat/a")
        self.assertEqual(_upstream(branch), "origin")


class AgeTests(unittest.TestCase):
    NOW = 1_700_000_000.0

    def _age(self, seconds: int) -> str:
        return _age(int(self.NOW) - seconds, now=self.NOW)

    def test_units_step_up_with_the_interval(self) -> None:
        self.assertEqual(self._age(5), "5s")
        self.assertEqual(self._age(90), "1m")
        self.assertEqual(self._age(7200), "2h")
        self.assertEqual(self._age(3 * 86400), "3d")
        self.assertEqual(self._age(14 * 86400), "2w")
        self.assertEqual(self._age(60 * 86400), "2mo")
        self.assertEqual(self._age(800 * 86400), "2y")

    def test_a_missing_timestamp_renders_a_dash(self) -> None:
        self.assertEqual(_age(0, now=self.NOW), "—")

    def test_a_future_timestamp_does_not_render_a_negative_age(self) -> None:
        self.assertEqual(_age(int(self.NOW) + 60, now=self.NOW), "now")


if __name__ == "__main__":
    unittest.main()
