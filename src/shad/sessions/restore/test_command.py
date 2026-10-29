from __future__ import annotations

import argparse
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rich.console import Console

from shad.sessions import store
from shad.sessions.model import Entry, Snapshot
from shad.sessions.restore.command import restore_sessions
from shad.sessions.testing import CFG, KB, SHAD, UUID_A, UUID_B, running
from shad.shared.config import Config, Defaults, Project
from shad.shared.errors import ShadError

DOC = Project(key="doc", group=None, path=Path("/p/doc"), session="doc", harness="claude")
UUID_C = "33333333-3333-4333-8333-333333333333"


def _args(*, no_attach: bool = False) -> argparse.Namespace:
    return argparse.Namespace(sessions_action="restore", no_attach=no_attach)


def _entry(key: str, session_id: str | None, *, group: str | None = None, attached: bool = False) -> Entry:
    return Entry(group=group, key=key, harness="claude", session_id=session_id, attached=attached)


class RestoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "sessions.json"
        self.output = io.StringIO()
        for patcher in (
            patch("shad.sessions.store.snapshot_path", return_value=self.path),
            patch("shad.sessions.restore.command.attached_sessions", return_value=set()),
            patch("shad.shared.terminal.current", return_value="kitty"),
            patch(
                "shad.sessions.restore.command.console",
                Console(file=self.output, width=120, force_terminal=False),
            ),
        ):
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


class TabTests(RestoreTests):
    """The terminal tabs for the other sessions that were attached at save."""

    def setUp(self) -> None:
        super().setUp()
        for patcher in (
            patch("shad.sessions.live.collect", return_value=[]),
            patch("shad.sessions.restore.plan.session_exists", return_value=False),
            patch("shad.sessions.harness.Claude.can_resume", return_value=True),
            patch("shad.sessions.restore.command._create_session"),
            patch("shad.sessions.restore.command._attach", return_value=0),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_opens_a_tab_for_each_other_session_attached_at_save(self) -> None:
        self._write_snapshot(
            _entry("kb", UUID_A, attached=True), _entry("shad", UUID_B, group="tin", attached=True)
        )
        with patch("shad.shared.terminal.open_tab", return_value=None) as open_tab:
            restore_sessions(CFG, _args())

        open_tab.assert_called_once_with(
            "kitty",
            ["tmux", "attach-session", "-t", f"=tin-shad--cc-{UUID_B}"],
            Path("/p/shad"),
        )
        self.assertNotIn("no tab", self.output.getvalue())

    def test_no_tab_for_a_session_detached_at_save(self) -> None:
        self._write_snapshot(_entry("kb", UUID_A, attached=True), _entry("shad", UUID_B, group="tin"))
        with patch("shad.shared.terminal.open_tab") as open_tab:
            restore_sessions(CFG, _args())

        open_tab.assert_not_called()

    def test_no_tab_for_a_session_that_has_a_client_now(self) -> None:
        self._write_snapshot(
            _entry("kb", UUID_A, attached=True), _entry("shad", UUID_B, group="tin", attached=True)
        )
        live = running("tin-shad--cc-fresh-1", SHAD, session_id=UUID_B, attached=True)
        with (
            patch("shad.sessions.live.collect", return_value=[live]),
            patch(
                "shad.sessions.restore.command.attached_sessions",
                return_value={"tin-shad--cc-fresh-1"},
            ),
            patch("shad.shared.terminal.open_tab") as open_tab,
        ):
            restore_sessions(CFG, _args())

        open_tab.assert_not_called()

    def test_no_tabs_with_no_attach(self) -> None:
        self._write_snapshot(
            _entry("kb", UUID_A, attached=True), _entry("shad", UUID_B, group="tin", attached=True)
        )
        with patch("shad.shared.terminal.open_tab") as open_tab:
            restore_sessions(CFG, _args(no_attach=True))

        open_tab.assert_not_called()

    def test_prints_the_attach_commands_outside_kitty(self) -> None:
        self._write_snapshot(
            _entry("kb", UUID_A, attached=True), _entry("shad", UUID_B, group="tin", attached=True)
        )
        with (
            patch("shad.shared.terminal.current", return_value=None),
            patch("shad.shared.terminal.open_tab") as open_tab,
        ):
            restore_sessions(CFG, _args())

        open_tab.assert_not_called()
        output = self.output.getvalue()
        self.assertIn("no tab for 1 session(s): the terminal is not kitty", output)
        self.assertIn(f"tmux attach-session -t =tin-shad--cc-{UUID_B}", output)

    def test_stops_after_the_first_failure_and_prints_the_rest(self) -> None:
        cfg = Config(defaults=Defaults(), projects={"kb": KB, "doc": DOC}, groups=CFG.groups)
        self._write_snapshot(
            _entry("kb", UUID_A, attached=True),
            _entry("shad", UUID_B, group="tin", attached=True),
            _entry("doc", UUID_C, attached=True),
        )
        with patch("shad.shared.terminal.open_tab", return_value="kitty said no") as open_tab:
            restore_sessions(cfg, _args())

        open_tab.assert_called_once()
        output = self.output.getvalue()
        self.assertIn("no tab for 2 session(s): kitty said no", output)
        self.assertIn(f"tmux attach-session -t =tin-shad--cc-{UUID_B}", output)
        self.assertIn(f"tmux attach-session -t =doc--cc-{UUID_C}", output)
