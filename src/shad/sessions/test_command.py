from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shad.sessions import store
from shad.sessions.command import cmd_sessions
from shad.sessions.live import Collected, Running, Skipped
from shad.sessions.model import Entry, Snapshot
from shad.shared.config import Config, Defaults, Project
from shad.shared.errors import ShadError

_UUID_A = "11111111-1111-4111-8111-111111111111"
_UUID_B = "22222222-2222-4222-8222-222222222222"

_KB = Project(key="kb", group=None, path=Path("/p/kb"), session="kb", harness="claude")
_SHAD = Project(key="shad", group="tin", path=Path("/p/shad"), session="tin-shad", harness="claude")
_CFG = Config(defaults=Defaults(), projects={"kb": _KB}, groups={"tin": {"shad": _SHAD}})


def _args(action: str | None, **flags: object) -> argparse.Namespace:
    return argparse.Namespace(sessions_action=action, **flags)


class CommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.path = self.root / "sessions.json"
        patcher = patch("shad.sessions.store.snapshot_path", return_value=self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_rejects_a_missing_or_unknown_action(self) -> None:
        with self.assertRaises(ShadError):
            cmd_sessions(_CFG, _args(None))
        with self.assertRaises(ShadError):
            cmd_sessions(_CFG, _args("bogus"))

    # -- save -------------------------------------------------------------

    def test_save_writes_what_is_running(self) -> None:
        entries = [Entry(group=None, key="kb", harness="claude", session_id=_UUID_A, attached=True)]
        live = Collected(running=[Running(f"kb--cc-{_UUID_A}", entries[0])])
        with patch("shad.sessions.live.collect", return_value=live):
            cmd_sessions(_CFG, _args("save"))

        snapshot = store.read(self.path)
        self.assertEqual(list(snapshot.entries), entries)
        self.assertGreater(snapshot.saved_at, 0)

    def test_save_with_nothing_running_leaves_the_file_alone(self) -> None:
        store.write(self.path, Snapshot(saved_at=1, entries=()))
        before = self.path.read_text()
        with (
            patch("shad.sessions.live.collect", return_value=Collected()),
            self.assertRaises(ShadError) as ctx,
        ):
            cmd_sessions(_CFG, _args("save"))
        self.assertIn("no shad sessions are running", str(ctx.exception))
        self.assertEqual(self.path.read_text(), before)

    def test_save_with_only_skipped_sessions_leaves_the_file_alone(self) -> None:
        skipped = [Skipped("kb--oc-x", _KB, "the opencode harness is not supported")]
        with (
            patch("shad.sessions.live.collect", return_value=Collected(skipped=skipped)),
            self.assertRaises(ShadError) as ctx,
        ):
            cmd_sessions(_CFG, _args("save"))
        self.assertIn("no session could be saved", str(ctx.exception))
        self.assertFalse(self.path.exists())

    # -- restore ----------------------------------------------------------

    def _write_snapshot(self, *entries: Entry) -> None:
        store.write(self.path, Snapshot(saved_at=1, entries=entries))

    def test_restore_creates_the_missing_sessions_and_attaches(self) -> None:
        self._write_snapshot(
            Entry(group=None, key="kb", harness="claude", session_id=_UUID_A, attached=False),
            Entry(group="tin", key="shad", harness="claude", session_id=_UUID_B, attached=True),
        )
        with (
            patch("shad.sessions.live.collect", return_value=Collected()),
            patch("shad.sessions.restore.session_exists", side_effect=lambda n: n.startswith("kb")),
            patch("shad.sessions.harness.Claude.can_resume", return_value=True),
            patch("shad.sessions.command._create_session") as create,
            patch("shad.sessions.command._attach", return_value=0) as attach,
        ):
            code = cmd_sessions(_CFG, _args("restore", no_attach=False))

        self.assertEqual(code, 0)
        create.assert_called_once_with(
            _SHAD, _CFG.defaults, f"claude --resume {_UUID_B}", f"tin-shad--cc-{_UUID_B}"
        )
        attach.assert_called_once_with(f"tin-shad--cc-{_UUID_B}")

    def test_restore_does_not_recreate_a_conversation_that_is_live(self) -> None:
        saved = Entry(group=None, key="kb", harness="claude", session_id=_UUID_A, attached=True)
        self._write_snapshot(saved)
        live = Collected(running=[Running("kb--cc-fresh-9", saved)])
        with (
            patch("shad.sessions.live.collect", return_value=live),
            patch("shad.sessions.restore.session_exists", return_value=False),
            patch("shad.sessions.command._create_session") as create,
            patch("shad.sessions.command._attach", return_value=0) as attach,
        ):
            cmd_sessions(_CFG, _args("restore", no_attach=False))

        create.assert_not_called()
        attach.assert_called_once_with("kb--cc-fresh-9")

    def test_restore_without_attach_returns_none(self) -> None:
        self._write_snapshot(
            Entry(group=None, key="kb", harness="claude", session_id=_UUID_A, attached=True)
        )
        with (
            patch("shad.sessions.live.collect", return_value=Collected()),
            patch("shad.sessions.restore.session_exists", return_value=False),
            patch("shad.sessions.harness.Claude.can_resume", return_value=True),
            patch("shad.sessions.command._create_session") as create,
            patch("shad.sessions.command._attach") as attach,
        ):
            code = cmd_sessions(_CFG, _args("restore", no_attach=True))

        self.assertIsNone(code)
        create.assert_called_once()
        attach.assert_not_called()

    def test_restore_with_nothing_to_attach_returns_none(self) -> None:
        self._write_snapshot(
            Entry(group=None, key="gone", harness="claude", session_id=_UUID_A, attached=True)
        )
        with (
            patch("shad.sessions.live.collect", return_value=Collected()),
            patch("shad.sessions.command._create_session") as create,
            patch("shad.sessions.command._attach") as attach,
        ):
            code = cmd_sessions(_CFG, _args("restore", no_attach=False))

        self.assertIsNone(code)
        create.assert_not_called()
        attach.assert_not_called()

    def test_restore_without_a_snapshot_fails(self) -> None:
        with self.assertRaises(ShadError):
            cmd_sessions(_CFG, _args("restore", no_attach=True))

    # -- show -------------------------------------------------------------

    def test_show_reads_the_snapshot(self) -> None:
        self._write_snapshot(
            Entry(group=None, key="kb", harness="claude", session_id=_UUID_A, attached=True)
        )
        self.assertIsNone(cmd_sessions(_CFG, _args("show")))

    def test_show_without_a_snapshot_fails(self) -> None:
        with self.assertRaises(ShadError):
            cmd_sessions(_CFG, _args("show"))
