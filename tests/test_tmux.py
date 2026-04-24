from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shad.config import Defaults, Project
from shad.sessions import OpencodeTarget
from shad.tmux import (
    _attach,
    list_project_sessions,
    open_project,
    project_session_name,
    session_exists,
    stop_project,
    tmux_server_running,
)


def _completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


# ---------------------------------------------------------------------------
# Existing tests (preserved)
# ---------------------------------------------------------------------------

class TmuxHelpersTests(unittest.TestCase):
    def test_project_session_name_scopes_existing_opencode_session(self) -> None:
        session = project_session_name(
            "tin-shad",
            OpencodeTarget(command="opencode -s sess-123", session_key="sess-123"),
        )
        self.assertEqual(session, "tin-shad--oc-sess-123")

    def test_list_project_sessions_matches_base_and_scoped_sessions(self) -> None:
        result = _completed(stdout="tin-shad\ntin-shad--oc-sess-123\ntin-shad-extra\nother\n")

        with patch("shad.tmux._run", return_value=result):
            sessions = list_project_sessions("tin-shad")

        self.assertEqual(sessions, ["tin-shad", "tin-shad--oc-sess-123"])

    # --- new helpers tests ---

    def test_project_session_name_returns_base_when_no_session_key(self) -> None:
        session = project_session_name(
            "tin-shad",
            OpencodeTarget(command="opencode"),
        )
        self.assertEqual(session, "tin-shad")

    def test_project_session_name_sanitises_special_chars(self) -> None:
        session = project_session_name(
            "proj",
            OpencodeTarget(command="opencode -s abc/def:ghi", session_key="abc/def:ghi"),
        )
        self.assertEqual(session, "proj--oc-abc_def_ghi")

    def test_project_session_name_falls_back_when_key_all_special(self) -> None:
        session = project_session_name(
            "proj",
            OpencodeTarget(command="opencode -s !!!", session_key="!!!"),
        )
        self.assertEqual(session, "proj--oc-session")

    def test_list_project_sessions_returns_empty_on_nonzero_exit(self) -> None:
        with patch("shad.tmux._run", return_value=_completed(returncode=1)):
            sessions = list_project_sessions("tin-shad")
        self.assertEqual(sessions, [])

    def test_list_project_sessions_strips_whitespace_from_lines(self) -> None:
        result = _completed(stdout="  tin-shad  \n  tin-shad--oc-abc  \n")
        with patch("shad.tmux._run", return_value=result):
            sessions = list_project_sessions("tin-shad")
        self.assertEqual(sessions, ["tin-shad", "tin-shad--oc-abc"])


# ---------------------------------------------------------------------------
# session_exists
# ---------------------------------------------------------------------------

class SessionExistsTests(unittest.TestCase):
    def test_returns_true_when_tmux_exits_0(self) -> None:
        with patch("shad.tmux._run", return_value=_completed(returncode=0)):
            self.assertTrue(session_exists("tin-shad"))

    def test_returns_false_when_tmux_exits_nonzero(self) -> None:
        with patch("shad.tmux._run", return_value=_completed(returncode=1)):
            self.assertFalse(session_exists("tin-shad"))


# ---------------------------------------------------------------------------
# tmux_server_running
# ---------------------------------------------------------------------------

class TmuxServerRunningTests(unittest.TestCase):
    def test_returns_true_when_exit_0(self) -> None:
        with patch("shad.tmux._run", return_value=_completed(returncode=0)):
            self.assertTrue(tmux_server_running())

    def test_returns_false_when_no_server_running_in_stderr(self) -> None:
        with patch("shad.tmux._run", return_value=_completed(
            returncode=1, stderr="error: no server running on /tmp/tmux-1000/default"
        )):
            self.assertFalse(tmux_server_running())

    def test_returns_true_when_nonzero_but_different_error(self) -> None:
        with patch("shad.tmux._run", return_value=_completed(
            returncode=1, stderr="socket permission denied"
        )):
            self.assertTrue(tmux_server_running())


# ---------------------------------------------------------------------------
# _attach
# ---------------------------------------------------------------------------

class AttachTests(unittest.TestCase):
    def test_outside_tmux_uses_attach_session(self) -> None:
        env = {k: v for k, v in __import__("os").environ.items() if k != "TMUX"}
        with patch("os.environ", env), \
             patch("subprocess.run", return_value=_completed(returncode=0)) as mock_run:
            code = _attach("tin-shad")

        args = mock_run.call_args[0][0]
        self.assertIn("attach-session", args)
        self.assertIn("tin-shad", args)
        self.assertEqual(code, 0)

    def test_inside_tmux_uses_switch_client(self) -> None:
        env = dict(__import__("os").environ, TMUX="/tmp/tmux-1234/default,12,0")
        with patch("os.environ", env), \
             patch("subprocess.run", return_value=_completed(returncode=0)) as mock_run:
            _attach("tin-shad")

        args = mock_run.call_args[0][0]
        self.assertIn("switch-client", args)

    def test_returns_subprocess_exit_code(self) -> None:
        env = {k: v for k, v in __import__("os").environ.items() if k != "TMUX"}
        with patch("os.environ", env), \
             patch("subprocess.run", return_value=_completed(returncode=42)):
            code = _attach("tin-shad")
        self.assertEqual(code, 42)


# ---------------------------------------------------------------------------
# open_project (existing + new)
# ---------------------------------------------------------------------------

class OpenProjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = Project(
            key="shad", group="tin", path=Path("/tmp/shad"), session="tin-shad"
        )
        self.defaults = Defaults()

    def test_open_project_returns_none_when_picker_cancelled(self) -> None:
        with patch("shad.tmux.pick_opencode_target", return_value=None), \
             patch("shad.tmux._create_session") as create_session, \
             patch("shad.tmux._attach") as attach:
            result = open_project(self.project, self.defaults)

        self.assertIsNone(result)
        create_session.assert_not_called()
        attach.assert_not_called()

    def test_open_project_returns_attach_exit_code(self) -> None:
        target = OpencodeTarget(command="opencode -s sess-123", session_key="sess-123")

        with patch("shad.tmux.pick_opencode_target", return_value=target), \
             patch("shad.tmux.session_exists", return_value=True), \
             patch("shad.tmux._create_session"), \
             patch("shad.tmux._attach", return_value=0) as attach:
            result = open_project(self.project, self.defaults)

        attach.assert_called_once_with("tin-shad--oc-sess-123")
        self.assertEqual(result, 0)

    def test_open_project_creates_scoped_tmux_session_for_existing_oc_session(self) -> None:
        target = OpencodeTarget(command="opencode -s sess-123", session_key="sess-123")

        with patch("shad.tmux.pick_opencode_target", return_value=target), \
             patch("shad.tmux.session_exists", return_value=False), \
             patch("shad.tmux._create_session") as create_session, \
             patch("shad.tmux._attach"):
            open_project(self.project, self.defaults)

        create_session.assert_called_once_with(
            self.project, self.defaults, "opencode -s sess-123", "tin-shad--oc-sess-123"
        )

    def test_open_project_reuses_existing_scoped_tmux_session(self) -> None:
        target = OpencodeTarget(command="opencode -s sess-123", session_key="sess-123")

        with patch("shad.tmux.pick_opencode_target", return_value=target), \
             patch("shad.tmux.session_exists", return_value=True), \
             patch("shad.tmux._create_session") as create_session, \
             patch("shad.tmux._attach"):
            open_project(self.project, self.defaults)

        create_session.assert_not_called()

    def test_open_project_no_session_key_uses_base_session_name(self) -> None:
        target = OpencodeTarget(command="opencode")

        with patch("shad.tmux.pick_opencode_target", return_value=target), \
             patch("shad.tmux.session_exists", return_value=False), \
             patch("shad.tmux._create_session") as create_session, \
             patch("shad.tmux._attach"):
            open_project(self.project, self.defaults)

        create_session.assert_called_once_with(
            self.project, self.defaults, "opencode", "tin-shad"
        )


# ---------------------------------------------------------------------------
# stop_project (existing + new branches)
# ---------------------------------------------------------------------------

class StopProjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = Project(
            key="shad", group="tin", path=Path("/tmp/shad"), session="tin-shad"
        )

    def test_stop_project_kills_all_project_sessions(self) -> None:
        with patch("shad.tmux.list_project_sessions",
                   return_value=["tin-shad", "tin-shad--oc-sess-123"]), \
             patch("shad.tmux._run") as run, \
             patch("shad.tmux.console") as mock_console:
            stop_project(self.project)

        run.assert_any_call(["tmux", "kill-session", "-t", "tin-shad"])
        run.assert_any_call(["tmux", "kill-session", "-t", "tin-shad--oc-sess-123"])
        self.assertEqual(run.call_count, 2)
        mock_console.print.assert_called_once()

    def test_stop_project_no_sessions_prints_not_running(self) -> None:
        with patch("shad.tmux.list_project_sessions", return_value=[]), \
             patch("shad.tmux._run") as run, \
             patch("shad.tmux.console") as mock_console:
            stop_project(self.project)

        run.assert_not_called()
        mock_console.print.assert_called_once()
        printed_text = str(mock_console.print.call_args)
        self.assertIn("not running", printed_text)

    def test_stop_project_single_session_message(self) -> None:
        with patch("shad.tmux.list_project_sessions", return_value=["tin-shad"]), \
             patch("shad.tmux._run"), \
             patch("shad.tmux.console") as mock_console:
            stop_project(self.project)

        mock_console.print.assert_called_once()

    def test_stop_project_multiple_sessions_message(self) -> None:
        sessions = ["tin-shad", "tin-shad--oc-a", "tin-shad--oc-b"]
        with patch("shad.tmux.list_project_sessions", return_value=sessions), \
             patch("shad.tmux._run"), \
             patch("shad.tmux.console") as mock_console:
            stop_project(self.project)

        mock_console.print.assert_called_once()
        printed_text = str(mock_console.print.call_args)
        self.assertIn("3", printed_text)


if __name__ == "__main__":
    unittest.main()
