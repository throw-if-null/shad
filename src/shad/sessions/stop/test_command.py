from __future__ import annotations

import argparse
import unittest
from unittest.mock import patch

from shad.sessions.stop.command import stop_sessions
from shad.sessions.testing import CFG, SHAD, running
from shad.shared.errors import ShadError
from shad.shared.picker import NoTerminal
from shad.testing import TmuxCase

_ARGS = argparse.Namespace(sessions_action="stop")


class StopTests(unittest.TestCase):
    def test_kills_the_picked_sessions_and_not_the_current_one(self) -> None:
        live = [running("kb--cc-here"), running("kb--cc-x"), running("tin-shad--cc-y", SHAD)]
        with (
            patch("shad.sessions.live.collect", return_value=live),
            patch("shad.sessions.stop.command.current_session", return_value="kb--cc-here"),
            patch("shad.sessions.pick.pick_many", return_value=frozenset({1})) as pick,
            patch("shad.sessions.stop.command.kill_session") as kill,
        ):
            stop_sessions(CFG, _ARGS)

        self.assertEqual(pick.call_args.args[1], 2)
        self.assertEqual(list(pick.call_args.args[2]), [])
        kill.assert_called_once_with("tin-shad--cc-y")

    def test_nothing_picked_kills_nothing(self) -> None:
        with (
            patch("shad.sessions.live.collect", return_value=[running("kb--cc-x")]),
            patch("shad.sessions.stop.command.current_session", return_value=None),
            patch("shad.sessions.pick.pick_many", return_value=frozenset()),
            patch("shad.sessions.stop.command.kill_session") as kill,
        ):
            stop_sessions(CFG, _ARGS)
        kill.assert_not_called()

    def test_cancel_kills_nothing(self) -> None:
        with (
            patch("shad.sessions.live.collect", return_value=[running("kb--cc-x")]),
            patch("shad.sessions.stop.command.current_session", return_value=None),
            patch("shad.sessions.pick.pick_many", return_value=None),
            patch("shad.sessions.stop.command.kill_session") as kill,
        ):
            stop_sessions(CFG, _ARGS)
        kill.assert_not_called()

    def test_only_the_current_session_opens_no_picker(self) -> None:
        with (
            patch("shad.sessions.live.collect", return_value=[running("kb--cc-here")]),
            patch("shad.sessions.stop.command.current_session", return_value="kb--cc-here"),
            patch("shad.sessions.pick.pick_many") as pick,
            patch("shad.sessions.stop.command.kill_session") as kill,
        ):
            stop_sessions(CFG, _ARGS)
        pick.assert_not_called()
        kill.assert_not_called()

    def test_lists_unsupported_sessions_too(self) -> None:
        live = [running("kb--oc-x", session_id=None, harness="opencode", unsupported="no")]
        with (
            patch("shad.sessions.live.collect", return_value=live),
            patch("shad.sessions.stop.command.current_session", return_value=None),
            patch("shad.sessions.pick.pick_many", return_value=frozenset({0})),
            patch("shad.sessions.stop.command.kill_session") as kill,
        ):
            stop_sessions(CFG, _ARGS)
        kill.assert_called_once_with("kb--oc-x")

    def test_without_a_terminal_fails(self) -> None:
        with (
            patch("shad.sessions.live.collect", return_value=[running("kb--cc-x")]),
            patch("shad.sessions.stop.command.current_session", return_value=None),
            patch("shad.sessions.pick.pick_many", side_effect=NoTerminal("no tty")),
            patch("shad.sessions.stop.command.kill_session") as kill,
            self.assertRaises(ShadError),
        ):
            stop_sessions(CFG, _ARGS)
        kill.assert_not_called()


class StopPickerTests(TmuxCase):
    def test_cancelling_the_picker_stops_nothing(self) -> None:
        """
        Feature:    sessions/stop
        Boundary:   command. `shad sessions stop` in a terminal pane of an
                    isolated tmux server. Contract: exit code + screen.
        Criterion:  stop-cancel-leaves-every-session-running
          Given:    project kb's session `kb` runs, and no other.
          When:     `shad sessions stop`, then `q` at the picker.
          Then:     exit 0, the screen says nothing stopped, and `kb` still
                    runs.
        """
        (self.root / "kb").mkdir()
        self.write_config(f'[projects.kb]\npath = "{self.root / "kb"}"\n')
        self.server.new_session("kb", command="sleep 100000")

        pane = self.pane("sessions", "stop")
        pane.wait_for("stop sessions")
        pane.send("q")

        self.assertEqual(pane.wait_exit(), 0)
        self.assertIn("nothing stopped", pane.screen())
        self.assertIn("kb", self.server.sessions())
