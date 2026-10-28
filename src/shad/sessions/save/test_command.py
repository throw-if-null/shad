from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shad.sessions import store
from shad.sessions.model import Entry, Snapshot
from shad.sessions.save.command import save_sessions
from shad.sessions.testing import CFG, KB, SHAD, UUID_A, UUID_B, running
from shad.shared.errors import ShadError
from shad.shared.picker import NoTerminal


def _args(*, all: bool = False) -> argparse.Namespace:
    return argparse.Namespace(sessions_action="save", all=all)


def _entry(key: str, session_id: str | None) -> Entry:
    return Entry(group=None, key=key, harness="claude", session_id=session_id, attached=False)


class SaveTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "sessions.json"
        patcher = patch("shad.sessions.store.snapshot_path", return_value=self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _write_snapshot(self, *entries: Entry) -> None:
        store.write(self.path, Snapshot(saved_at=1, entries=entries))

    def test_all_writes_every_savable_session(self) -> None:
        live = [
            running("kb--cc-x", KB, session_id=UUID_A, attached=True, name="N", title="T"),
            running("kb--oc-y", KB, session_id=None, harness="opencode", unsupported="no"),
            running("tin-shad--cc-z", SHAD, session_id=UUID_B),
        ]
        with (
            patch("shad.sessions.live.collect", return_value=live),
            patch("shad.sessions.pick.pick_many") as pick,
        ):
            save_sessions(CFG, _args(all=True))

        pick.assert_not_called()
        self.assertEqual(
            list(store.read(self.path).entries),
            [
                Entry(group=None, key="kb", harness="claude", session_id=UUID_A, attached=True, name="N", title="T"),
                Entry(group="tin", key="shad", harness="claude", session_id=UUID_B, attached=False),
            ],
        )

    def test_writes_the_picked_rows_only(self) -> None:
        live = [running("kb--cc-x", KB, session_id=UUID_A), running("tin-shad--cc-z", SHAD, session_id=UUID_B)]
        with (
            patch("shad.sessions.live.collect", return_value=live),
            patch("shad.sessions.pick.pick_many", return_value=frozenset({1})),
        ):
            save_sessions(CFG, _args())

        self.assertEqual([e.session_id for e in store.read(self.path).entries], [UUID_B])

    def test_checks_every_row_when_there_is_no_snapshot(self) -> None:
        live = [running("kb--cc-x", session_id=UUID_A), running("kb--cc-y", session_id=UUID_B)]
        with (
            patch("shad.sessions.live.collect", return_value=live),
            patch("shad.sessions.pick.pick_many", return_value=frozenset()) as pick,
        ):
            save_sessions(CFG, _args())

        self.assertEqual(set(pick.call_args.args[2]), {0, 1})

    def test_checks_the_rows_the_snapshot_already_holds(self) -> None:
        self._write_snapshot(_entry("kb", UUID_B))
        live = [
            running("kb--cc-x", session_id=UUID_A),
            running("kb--cc-y", session_id=UUID_B),
            running("kb--cc-fresh", session_id=None),
        ]
        with (
            patch("shad.sessions.live.collect", return_value=live),
            patch("shad.sessions.pick.pick_many", return_value=frozenset()) as pick,
        ):
            save_sessions(CFG, _args())

        self.assertEqual(set(pick.call_args.args[2]), {1})

    def test_an_empty_pick_writes_an_empty_snapshot(self) -> None:
        self._write_snapshot(_entry("kb", UUID_A))
        with (
            patch("shad.sessions.live.collect", return_value=[running("kb--cc-x")]),
            patch("shad.sessions.pick.pick_many", return_value=frozenset()),
        ):
            save_sessions(CFG, _args())

        self.assertEqual(store.read(self.path).entries, ())

    def test_cancel_leaves_the_file_alone(self) -> None:
        self._write_snapshot(_entry("kb", UUID_A))
        before = self.path.read_text()
        with (
            patch("shad.sessions.live.collect", return_value=[running("kb--cc-x")]),
            patch("shad.sessions.pick.pick_many", return_value=None),
        ):
            save_sessions(CFG, _args())

        self.assertEqual(self.path.read_text(), before)

    def test_without_a_terminal_points_at_all(self) -> None:
        with (
            patch("shad.sessions.live.collect", return_value=[running("kb--cc-x")]),
            patch("shad.sessions.pick.pick_many", side_effect=NoTerminal("no tty")),
            self.assertRaises(ShadError) as ctx,
        ):
            save_sessions(CFG, _args())

        self.assertIn("--all", str(ctx.exception))
        self.assertFalse(self.path.exists())

    def test_nothing_running_leaves_the_file_alone(self) -> None:
        self._write_snapshot(_entry("kb", UUID_A))
        before = self.path.read_text()
        with (
            patch("shad.sessions.live.collect", return_value=[]),
            self.assertRaises(ShadError) as ctx,
        ):
            save_sessions(CFG, _args(all=True))

        self.assertIn("no shad sessions are running", str(ctx.exception))
        self.assertEqual(self.path.read_text(), before)

    def test_only_unsupported_sessions_leaves_the_file_alone(self) -> None:
        live = [running("kb--oc-x", session_id=None, harness="opencode", unsupported="no")]
        with (
            patch("shad.sessions.live.collect", return_value=live),
            self.assertRaises(ShadError) as ctx,
        ):
            save_sessions(CFG, _args(all=True))

        self.assertIn("no session could be saved", str(ctx.exception))
        self.assertFalse(self.path.exists())
