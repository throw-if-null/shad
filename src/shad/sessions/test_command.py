from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shad.sessions import store
from shad.sessions.command import cmd_sessions
from shad.sessions.model import Entry, Snapshot
from shad.sessions.testing import CFG, KB, SHAD, UUID_A, UUID_B, running
from shad.shared.errors import ShadError
from shad.shared.picker import NoTerminal


def _args(action: str | None, **flags: object) -> argparse.Namespace:
    return argparse.Namespace(sessions_action=action, **flags)


def _entry(key: str, session_id: str | None, *, group: str | None = None, attached: bool = False) -> Entry:
    return Entry(group=group, key=key, harness="claude", session_id=session_id, attached=attached)


class CommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "sessions.json"
        patcher = patch("shad.sessions.store.snapshot_path", return_value=self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _write_snapshot(self, *entries: Entry) -> None:
        store.write(self.path, Snapshot(saved_at=1, entries=entries))

    def test_rejects_a_missing_or_unknown_action(self) -> None:
        with self.assertRaises(ShadError):
            cmd_sessions(CFG, _args(None))
        with self.assertRaises(ShadError):
            cmd_sessions(CFG, _args("bogus"))

    # -- save -------------------------------------------------------------

    def test_save_all_writes_every_savable_session(self) -> None:
        live = [
            running("kb--cc-x", KB, session_id=UUID_A, attached=True, name="N", title="T"),
            running("kb--oc-y", KB, session_id=None, harness="opencode", unsupported="no"),
            running("tin-shad--cc-z", SHAD, session_id=UUID_B),
        ]
        with (
            patch("shad.sessions.live.collect", return_value=live),
            patch("shad.sessions.command.pick_many") as pick,
        ):
            cmd_sessions(CFG, _args("save", all=True))

        pick.assert_not_called()
        self.assertEqual(
            list(store.read(self.path).entries),
            [
                Entry(group=None, key="kb", harness="claude", session_id=UUID_A, attached=True, name="N", title="T"),
                Entry(group="tin", key="shad", harness="claude", session_id=UUID_B, attached=False),
            ],
        )

    def test_save_writes_the_picked_rows_only(self) -> None:
        live = [running("kb--cc-x", KB, session_id=UUID_A), running("tin-shad--cc-z", SHAD, session_id=UUID_B)]
        with (
            patch("shad.sessions.live.collect", return_value=live),
            patch("shad.sessions.command.pick_many", return_value=frozenset({1})),
        ):
            cmd_sessions(CFG, _args("save", all=False))

        self.assertEqual([e.session_id for e in store.read(self.path).entries], [UUID_B])

    def test_save_checks_every_row_when_there_is_no_snapshot(self) -> None:
        live = [running("kb--cc-x", session_id=UUID_A), running("kb--cc-y", session_id=UUID_B)]
        with (
            patch("shad.sessions.live.collect", return_value=live),
            patch("shad.sessions.command.pick_many", return_value=frozenset()) as pick,
        ):
            cmd_sessions(CFG, _args("save", all=False))

        self.assertEqual(set(pick.call_args.args[2]), {0, 1})

    def test_save_checks_the_rows_the_snapshot_already_holds(self) -> None:
        self._write_snapshot(_entry("kb", UUID_B))
        live = [
            running("kb--cc-x", session_id=UUID_A),
            running("kb--cc-y", session_id=UUID_B),
            running("kb--cc-fresh", session_id=None),
        ]
        with (
            patch("shad.sessions.live.collect", return_value=live),
            patch("shad.sessions.command.pick_many", return_value=frozenset()) as pick,
        ):
            cmd_sessions(CFG, _args("save", all=False))

        self.assertEqual(set(pick.call_args.args[2]), {1})

    def test_save_with_an_empty_pick_writes_an_empty_snapshot(self) -> None:
        self._write_snapshot(_entry("kb", UUID_A))
        with (
            patch("shad.sessions.live.collect", return_value=[running("kb--cc-x")]),
            patch("shad.sessions.command.pick_many", return_value=frozenset()),
        ):
            cmd_sessions(CFG, _args("save", all=False))

        self.assertEqual(store.read(self.path).entries, ())

    def test_save_cancelled_leaves_the_file_alone(self) -> None:
        self._write_snapshot(_entry("kb", UUID_A))
        before = self.path.read_text()
        with (
            patch("shad.sessions.live.collect", return_value=[running("kb--cc-x")]),
            patch("shad.sessions.command.pick_many", return_value=None),
        ):
            cmd_sessions(CFG, _args("save", all=False))

        self.assertEqual(self.path.read_text(), before)

    def test_save_without_a_terminal_points_at_all(self) -> None:
        with (
            patch("shad.sessions.live.collect", return_value=[running("kb--cc-x")]),
            patch("shad.sessions.command.pick_many", side_effect=NoTerminal("no tty")),
            self.assertRaises(ShadError) as ctx,
        ):
            cmd_sessions(CFG, _args("save", all=False))

        self.assertIn("--all", str(ctx.exception))
        self.assertFalse(self.path.exists())

    def test_save_with_nothing_running_leaves_the_file_alone(self) -> None:
        self._write_snapshot(_entry("kb", UUID_A))
        before = self.path.read_text()
        with (
            patch("shad.sessions.live.collect", return_value=[]),
            self.assertRaises(ShadError) as ctx,
        ):
            cmd_sessions(CFG, _args("save", all=True))

        self.assertIn("no shad sessions are running", str(ctx.exception))
        self.assertEqual(self.path.read_text(), before)

    def test_save_with_only_unsupported_sessions_leaves_the_file_alone(self) -> None:
        live = [running("kb--oc-x", session_id=None, harness="opencode", unsupported="no")]
        with (
            patch("shad.sessions.live.collect", return_value=live),
            self.assertRaises(ShadError) as ctx,
        ):
            cmd_sessions(CFG, _args("save", all=True))

        self.assertIn("no session could be saved", str(ctx.exception))
        self.assertFalse(self.path.exists())

    # -- restore ----------------------------------------------------------

    def test_restore_creates_the_missing_sessions_and_attaches(self) -> None:
        self._write_snapshot(_entry("kb", UUID_A), _entry("shad", UUID_B, group="tin", attached=True))
        with (
            patch("shad.sessions.live.collect", return_value=[]),
            patch("shad.sessions.restore.session_exists", side_effect=lambda n: n.startswith("kb")),
            patch("shad.sessions.harness.Claude.can_resume", return_value=True),
            patch("shad.sessions.command._create_session") as create,
            patch("shad.sessions.command._attach", return_value=0) as attach,
        ):
            code = cmd_sessions(CFG, _args("restore", no_attach=False))

        self.assertEqual(code, 0)
        create.assert_called_once_with(
            SHAD, CFG.defaults, f"claude --resume {UUID_B}", f"tin-shad--cc-{UUID_B}"
        )
        attach.assert_called_once_with(f"tin-shad--cc-{UUID_B}")

    def test_restore_does_not_recreate_a_conversation_that_is_live(self) -> None:
        self._write_snapshot(_entry("kb", UUID_A, attached=True))
        with (
            patch("shad.sessions.live.collect", return_value=[running("kb--cc-fresh-9")]),
            patch("shad.sessions.restore.session_exists", return_value=False),
            patch("shad.sessions.command._create_session") as create,
            patch("shad.sessions.command._attach", return_value=0) as attach,
        ):
            cmd_sessions(CFG, _args("restore", no_attach=False))

        create.assert_not_called()
        attach.assert_called_once_with("kb--cc-fresh-9")

    def test_restore_without_attach_returns_none(self) -> None:
        self._write_snapshot(_entry("kb", UUID_A, attached=True))
        with (
            patch("shad.sessions.live.collect", return_value=[]),
            patch("shad.sessions.restore.session_exists", return_value=False),
            patch("shad.sessions.harness.Claude.can_resume", return_value=True),
            patch("shad.sessions.command._create_session") as create,
            patch("shad.sessions.command._attach") as attach,
        ):
            code = cmd_sessions(CFG, _args("restore", no_attach=True))

        self.assertIsNone(code)
        create.assert_called_once()
        attach.assert_not_called()

    def test_restore_with_nothing_to_attach_returns_none(self) -> None:
        self._write_snapshot(_entry("gone", UUID_A, attached=True))
        with (
            patch("shad.sessions.live.collect", return_value=[]),
            patch("shad.sessions.command._create_session") as create,
            patch("shad.sessions.command._attach") as attach,
        ):
            code = cmd_sessions(CFG, _args("restore", no_attach=False))

        self.assertIsNone(code)
        create.assert_not_called()
        attach.assert_not_called()

    def test_restore_without_a_snapshot_fails(self) -> None:
        with self.assertRaises(ShadError):
            cmd_sessions(CFG, _args("restore", no_attach=True))

    # -- stop -------------------------------------------------------------

    def test_stop_kills_the_picked_sessions_and_not_the_current_one(self) -> None:
        live = [running("kb--cc-here"), running("kb--cc-x"), running("tin-shad--cc-y", SHAD)]
        with (
            patch("shad.sessions.live.collect", return_value=live),
            patch("shad.sessions.command.current_session", return_value="kb--cc-here"),
            patch("shad.sessions.command.pick_many", return_value=frozenset({1})) as pick,
            patch("shad.sessions.command.kill_session") as kill,
        ):
            cmd_sessions(CFG, _args("stop"))

        self.assertEqual(pick.call_args.args[1], 2)
        self.assertEqual(list(pick.call_args.args[2]), [])
        kill.assert_called_once_with("tin-shad--cc-y")

    def test_stop_with_nothing_picked_kills_nothing(self) -> None:
        with (
            patch("shad.sessions.live.collect", return_value=[running("kb--cc-x")]),
            patch("shad.sessions.command.current_session", return_value=None),
            patch("shad.sessions.command.pick_many", return_value=frozenset()),
            patch("shad.sessions.command.kill_session") as kill,
        ):
            cmd_sessions(CFG, _args("stop"))
        kill.assert_not_called()

    def test_stop_cancelled_kills_nothing(self) -> None:
        with (
            patch("shad.sessions.live.collect", return_value=[running("kb--cc-x")]),
            patch("shad.sessions.command.current_session", return_value=None),
            patch("shad.sessions.command.pick_many", return_value=None),
            patch("shad.sessions.command.kill_session") as kill,
        ):
            cmd_sessions(CFG, _args("stop"))
        kill.assert_not_called()

    def test_stop_with_only_the_current_session_opens_no_picker(self) -> None:
        with (
            patch("shad.sessions.live.collect", return_value=[running("kb--cc-here")]),
            patch("shad.sessions.command.current_session", return_value="kb--cc-here"),
            patch("shad.sessions.command.pick_many") as pick,
            patch("shad.sessions.command.kill_session") as kill,
        ):
            cmd_sessions(CFG, _args("stop"))
        pick.assert_not_called()
        kill.assert_not_called()

    def test_stop_lists_unsupported_sessions_too(self) -> None:
        live = [running("kb--oc-x", session_id=None, harness="opencode", unsupported="no")]
        with (
            patch("shad.sessions.live.collect", return_value=live),
            patch("shad.sessions.command.current_session", return_value=None),
            patch("shad.sessions.command.pick_many", return_value=frozenset({0})),
            patch("shad.sessions.command.kill_session") as kill,
        ):
            cmd_sessions(CFG, _args("stop"))
        kill.assert_called_once_with("kb--oc-x")

    def test_stop_without_a_terminal_fails(self) -> None:
        with (
            patch("shad.sessions.live.collect", return_value=[running("kb--cc-x")]),
            patch("shad.sessions.command.current_session", return_value=None),
            patch("shad.sessions.command.pick_many", side_effect=NoTerminal("no tty")),
            patch("shad.sessions.command.kill_session") as kill,
            self.assertRaises(ShadError),
        ):
            cmd_sessions(CFG, _args("stop"))
        kill.assert_not_called()

    # -- show -------------------------------------------------------------

    def test_show_reads_the_snapshot(self) -> None:
        self._write_snapshot(_entry("kb", UUID_A, attached=True))
        self.assertIsNone(cmd_sessions(CFG, _args("show")))

    def test_show_an_empty_snapshot(self) -> None:
        self._write_snapshot()
        self.assertIsNone(cmd_sessions(CFG, _args("show")))

    def test_show_without_a_snapshot_fails(self) -> None:
        with self.assertRaises(ShadError):
            cmd_sessions(CFG, _args("show"))
