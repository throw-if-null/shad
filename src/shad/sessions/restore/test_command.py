from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shad.sessions import store
from shad.sessions.model import Entry, Snapshot
from shad.sessions.restore.command import restore_sessions
from shad.sessions.testing import CFG, SHAD, UUID_A, UUID_B, running
from shad.shared.errors import ShadError


def _args(*, no_attach: bool = False) -> argparse.Namespace:
    return argparse.Namespace(sessions_action="restore", no_attach=no_attach)


def _entry(key: str, session_id: str | None, *, group: str | None = None, attached: bool = False) -> Entry:
    return Entry(group=group, key=key, harness="claude", session_id=session_id, attached=attached)


class RestoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "sessions.json"
        patcher = patch("shad.sessions.store.snapshot_path", return_value=self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _write_snapshot(self, *entries: Entry) -> None:
        store.write(self.path, Snapshot(saved_at=1, entries=entries))

    def test_creates_the_missing_sessions_and_attaches(self) -> None:
        self._write_snapshot(_entry("kb", UUID_A), _entry("shad", UUID_B, group="tin", attached=True))
        with (
            patch("shad.sessions.live.collect", return_value=[]),
            patch("shad.sessions.restore.plan.session_exists", side_effect=lambda n: n.startswith("kb")),
            patch("shad.sessions.harness.Claude.can_resume", return_value=True),
            patch("shad.sessions.restore.command._create_session") as create,
            patch("shad.sessions.restore.command._attach", return_value=0) as attach,
        ):
            code = restore_sessions(CFG, _args())

        self.assertEqual(code, 0)
        create.assert_called_once_with(
            SHAD, CFG.defaults, f"claude --resume {UUID_B}", f"tin-shad--cc-{UUID_B}"
        )
        attach.assert_called_once_with(f"tin-shad--cc-{UUID_B}")

    def test_does_not_recreate_a_conversation_that_is_live(self) -> None:
        self._write_snapshot(_entry("kb", UUID_A, attached=True))
        with (
            patch("shad.sessions.live.collect", return_value=[running("kb--cc-fresh-9")]),
            patch("shad.sessions.restore.plan.session_exists", return_value=False),
            patch("shad.sessions.restore.command._create_session") as create,
            patch("shad.sessions.restore.command._attach", return_value=0) as attach,
        ):
            restore_sessions(CFG, _args())

        create.assert_not_called()
        attach.assert_called_once_with("kb--cc-fresh-9")

    def test_no_attach_returns_none(self) -> None:
        self._write_snapshot(_entry("kb", UUID_A, attached=True))
        with (
            patch("shad.sessions.live.collect", return_value=[]),
            patch("shad.sessions.restore.plan.session_exists", return_value=False),
            patch("shad.sessions.harness.Claude.can_resume", return_value=True),
            patch("shad.sessions.restore.command._create_session") as create,
            patch("shad.sessions.restore.command._attach") as attach,
        ):
            code = restore_sessions(CFG, _args(no_attach=True))

        self.assertIsNone(code)
        create.assert_called_once()
        attach.assert_not_called()

    def test_nothing_to_attach_returns_none(self) -> None:
        self._write_snapshot(_entry("gone", UUID_A, attached=True))
        with (
            patch("shad.sessions.live.collect", return_value=[]),
            patch("shad.sessions.restore.command._create_session") as create,
            patch("shad.sessions.restore.command._attach") as attach,
        ):
            code = restore_sessions(CFG, _args())

        self.assertIsNone(code)
        create.assert_not_called()
        attach.assert_not_called()

    def test_without_a_snapshot_fails(self) -> None:
        with self.assertRaises(ShadError):
            restore_sessions(CFG, _args(no_attach=True))
