from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from shad.shared.config import Defaults, Project
from shad.projects.open.sessions import OpencodeTarget
from shad.shared.tmux import (
    _attach,
    list_project_sessions,
    project_session_name,
    session_exists,
    tmux_server_running,
)


def _completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


# ---------------------------------------------------------------------------
# project_session_name + list_project_sessions
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

        with patch("shad.shared.tmux._run", return_value=result):
            sessions = list_project_sessions("tin-shad")

        self.assertEqual(sessions, ["tin-shad", "tin-shad--oc-sess-123"])

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
        with patch("shad.shared.tmux._run", return_value=_completed(returncode=1)):
            sessions = list_project_sessions("tin-shad")
        self.assertEqual(sessions, [])

    def test_list_project_sessions_strips_whitespace_from_lines(self) -> None:
        result = _completed(stdout="  tin-shad  \n  tin-shad--oc-abc  \n")
        with patch("shad.shared.tmux._run", return_value=result):
            sessions = list_project_sessions("tin-shad")
        self.assertEqual(sessions, ["tin-shad", "tin-shad--oc-abc"])


# ---------------------------------------------------------------------------
# session_exists
# ---------------------------------------------------------------------------

class SessionExistsTests(unittest.TestCase):
    def test_returns_true_when_tmux_exits_0(self) -> None:
        with patch("shad.shared.tmux._run", return_value=_completed(returncode=0)):
            self.assertTrue(session_exists("tin-shad"))

    def test_returns_false_when_tmux_exits_nonzero(self) -> None:
        with patch("shad.shared.tmux._run", return_value=_completed(returncode=1)):
            self.assertFalse(session_exists("tin-shad"))


# ---------------------------------------------------------------------------
# tmux_server_running
# ---------------------------------------------------------------------------

class TmuxServerRunningTests(unittest.TestCase):
    def test_returns_true_when_exit_0(self) -> None:
        with patch("shad.shared.tmux._run", return_value=_completed(returncode=0)):
            self.assertTrue(tmux_server_running())

    def test_returns_false_when_no_server_running_in_stderr(self) -> None:
        with patch("shad.shared.tmux._run", return_value=_completed(
            returncode=1, stderr="error: no server running on /tmp/tmux-1000/default"
        )):
            self.assertFalse(tmux_server_running())

    def test_returns_true_when_nonzero_but_different_error(self) -> None:
        with patch("shad.shared.tmux._run", return_value=_completed(
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


if __name__ == "__main__":
    unittest.main()
