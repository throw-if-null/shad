from __future__ import annotations

import unittest
from pathlib import Path
from typing import Self
from unittest.mock import patch

from shad.git.model import BranchRef, FetchResult, Repo, Stash, Worktree
from shad.git.panel import snapshot

ROOT = Path("/tmp/repo")
REPO = Repo(root=ROOT, common_dir=ROOT / ".git")


def _branch(
    name: str, *, upstream: str = "", trackshort: str = "", remotename: str = ""
) -> BranchRef:
    return BranchRef(
        refname=f"refs/heads/{name}",
        oid="a" * 40,
        upstream=upstream,
        remotename=remotename,
        trackshort=trackshort,
    )


class _Fixture:
    """Patches every collaborator collect() reaches, with sane defaults."""

    def __init__(self, **overrides: object) -> None:
        self.values: dict[str, object] = {
            "list_remotes": ["origin"],
            "list_branches": [_branch("main", upstream="refs/remotes/origin/main")],
            "list_worktrees": [Worktree(path=ROOT, branch="refs/heads/main")],
            "list_stashes": [],
            "ahead_behind": (0, 0),
            "head_branch": "refs/heads/main",
            "git_version_string": "2.55.0",
            "fetch": FetchResult(ok=True),
        }
        self.values.update(overrides)
        self.fetch_calls: list[dict[str, object]] = []
        self._patches: list[object] = []

    def __enter__(self) -> Self:
        def _fetch(repo: Path, remote: str, *, prune: bool) -> FetchResult:
            self.fetch_calls.append({"repo": repo, "remote": remote, "prune": prune})
            result = self.values["fetch"]
            assert isinstance(result, FetchResult)
            return result

        self._patches = [
            patch.object(snapshot.refs, "list_remotes", return_value=self.values["list_remotes"]),
            patch.object(snapshot.refs, "list_branches", return_value=self.values["list_branches"]),
            patch.object(snapshot.refs, "list_worktrees", return_value=self.values["list_worktrees"]),
            patch.object(snapshot.refs, "list_stashes", return_value=self.values["list_stashes"]),
            patch.object(snapshot.refs, "ahead_behind", return_value=self.values["ahead_behind"]),
            patch.object(snapshot, "head_branch", return_value=self.values["head_branch"]),
            patch.object(snapshot, "git_version_string", return_value=self.values["git_version_string"]),
            patch.object(snapshot, "fetch_remote", _fetch),
        ]
        for p in self._patches:
            p.start()  # type: ignore[attr-defined]
        return self

    def __exit__(self, *exc: object) -> None:
        for p in self._patches:
            p.stop()  # type: ignore[attr-defined]


class CollectTests(unittest.TestCase):
    def test_reports_head_and_its_exact_tracking_counts(self) -> None:
        with _Fixture(ahead_behind=(2, 3)):
            snap = snapshot.collect(REPO, fetch=False)
        self.assertEqual(snap.head, "main")
        self.assertEqual(snap.head_upstream, "refs/remotes/origin/main")
        self.assertEqual(snap.ahead, 2)
        self.assertEqual(snap.behind, 3)
        self.assertEqual(snap.name, "repo")

    def test_detached_head_has_no_branch_and_no_counts(self) -> None:
        with (
            _Fixture(head_branch=None) as fixture,
            patch.object(snapshot.refs, "ahead_behind") as ahead_behind,
        ):
            snap = snapshot.collect(REPO, fetch=False)
        self.assertIsNone(snap.head)
        self.assertIsNone(snap.head_upstream)
        self.assertEqual((snap.ahead, snap.behind), (0, 0))
        ahead_behind.assert_not_called()
        self.assertEqual(fixture.fetch_calls, [])

    def test_head_without_an_upstream_is_not_reported_as_in_sync(self) -> None:
        with (
            _Fixture(list_branches=[_branch("main")]),
            patch.object(snapshot.refs, "ahead_behind") as ahead_behind,
        ):
            snap = snapshot.collect(REPO, fetch=False)
        self.assertIsNone(snap.head_upstream)
        ahead_behind.assert_not_called()

    def test_ambiguous_remote_yields_no_remote_and_no_fetch(self) -> None:
        # Several remotes and none of them named origin: primary_remote cannot
        # choose, so there is nothing to fetch from and nothing to report.
        with _Fixture(list_remotes=["upstream", "fork"]) as fixture:
            snap = snapshot.collect(REPO, fetch=True)
        self.assertIsNone(snap.remote)
        self.assertEqual(fixture.fetch_calls, [])
        self.assertIsNone(snap.fetch_error)

    def test_origin_wins_when_several_remotes_exist(self) -> None:
        with _Fixture(list_remotes=["upstream", "origin"]) as fixture:
            snap = snapshot.collect(REPO, fetch=True)
        self.assertEqual(snap.remote, "origin")
        self.assertEqual(fixture.fetch_calls[0]["remote"], "origin")

    def test_no_remote_at_all_skips_the_fetch(self) -> None:
        with _Fixture(list_remotes=[]) as fixture:
            snap = snapshot.collect(REPO, fetch=True)
        self.assertIsNone(snap.remote)
        self.assertEqual(fixture.fetch_calls, [])

    def test_fetch_never_prunes(self) -> None:
        # Pruning destroys the last-known upstream OIDs that `shad git sync`
        # needs to prove a gone branch was fully pushed. A viewer must not.
        with _Fixture() as fixture:
            snapshot.collect(REPO, fetch=True)
        self.assertEqual(len(fixture.fetch_calls), 1)
        self.assertIs(fixture.fetch_calls[0]["prune"], False)
        self.assertEqual(fixture.fetch_calls[0]["remote"], "origin")

    def test_fetch_failure_is_recorded_and_local_state_still_collected(self) -> None:
        failure = FetchResult(ok=False, error="could not read from remote")
        with _Fixture(
            fetch=failure,
            list_stashes=[Stash(ref="stash@{0}", subject="On main: x", timestamp=1, branch="main")],
        ):
            snap = snapshot.collect(REPO, fetch=True)
        self.assertEqual(snap.fetch_error, "could not read from remote")
        self.assertIsNone(snap.fetched_at)
        self.assertEqual(len(snap.branches), 1)
        self.assertEqual(len(snap.stashes), 1)

    def test_a_good_fetch_stamps_the_time_and_leaves_no_error(self) -> None:
        with _Fixture():
            snap = snapshot.collect(REPO, fetch=True)
        self.assertIsNone(snap.fetch_error)
        self.assertIsNotNone(snap.fetched_at)

    def test_fetch_false_makes_no_network_call(self) -> None:
        with _Fixture() as fixture:
            snap = snapshot.collect(REPO, fetch=False)
        self.assertEqual(fixture.fetch_calls, [])
        self.assertIsNone(snap.fetched_at)
        self.assertIsNone(snap.fetch_error)

    def test_checked_out_lists_refnames_held_by_a_worktree(self) -> None:
        worktrees = [
            Worktree(path=ROOT, branch="refs/heads/main"),
            Worktree(path=Path("/tmp/wt"), branch="refs/heads/side"),
            Worktree(path=Path("/tmp/det"), branch=None, detached=True),
        ]
        with _Fixture(list_worktrees=worktrees):
            snap = snapshot.collect(REPO, fetch=False)
        self.assertEqual(snap.checked_out, {"refs/heads/main", "refs/heads/side"})

    def test_empty_repository_collects_without_error(self) -> None:
        with _Fixture(
            list_branches=[], list_worktrees=[], list_stashes=[], head_branch=None
        ):
            snap = snapshot.collect(REPO, fetch=False)
        self.assertEqual(snap.branches, [])
        self.assertEqual(snap.worktrees, [])
        self.assertEqual(snap.stashes, [])
        self.assertIsNone(snap.head)


if __name__ == "__main__":
    unittest.main()
