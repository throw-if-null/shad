from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shad.config import Defaults, Project
from shad.sessions import OpencodeTarget
from shad.tmux import list_project_sessions, open_project, project_session_name, stop_project


class TmuxHelpersTests(unittest.TestCase):
    def test_project_session_name_scopes_existing_opencode_session(self) -> None:
        session = project_session_name(
            "tin-shad",
            OpencodeTarget(command="opencode -s sess-123", session_key="sess-123"),
        )

        self.assertEqual(session, "tin-shad--oc-sess-123")

    def test_list_project_sessions_matches_base_and_scoped_sessions(self) -> None:
        result = subprocess.CompletedProcess(
            args=["tmux", "list-sessions"],
            returncode=0,
            stdout="tin-shad\ntin-shad--oc-sess-123\nother\n",
            stderr="",
        )

        with patch("shad.tmux._run", return_value=result):
            sessions = list_project_sessions("tin-shad")

        self.assertEqual(sessions, ["tin-shad", "tin-shad--oc-sess-123"])


class OpenProjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = Project(
            key="shad",
            group="tin",
            path=Path("/tmp/shad"),
            session="tin-shad",
        )
        self.defaults = Defaults()

    def test_open_project_creates_scoped_tmux_session_for_existing_oc_session(self) -> None:
        target = OpencodeTarget(command="opencode -s sess-123", session_key="sess-123")

        with patch("shad.tmux.pick_opencode_target", return_value=target), patch(
            "shad.tmux.session_exists", return_value=False
        ), patch("shad.tmux._create_session") as create_session, patch(
            "shad.tmux._attach"
        ) as attach:
            open_project(self.project, self.defaults)

        create_session.assert_called_once_with(
            self.project,
            self.defaults,
            "opencode -s sess-123",
            "tin-shad--oc-sess-123",
        )
        attach.assert_called_once_with("tin-shad--oc-sess-123")

    def test_open_project_reuses_existing_scoped_tmux_session(self) -> None:
        target = OpencodeTarget(command="opencode -s sess-123", session_key="sess-123")

        with patch("shad.tmux.pick_opencode_target", return_value=target), patch(
            "shad.tmux.session_exists", return_value=True
        ), patch("shad.tmux._create_session") as create_session, patch(
            "shad.tmux._attach"
        ) as attach:
            open_project(self.project, self.defaults)

        create_session.assert_not_called()
        attach.assert_called_once_with("tin-shad--oc-sess-123")


class StopProjectTests(unittest.TestCase):
    def test_stop_project_kills_all_project_sessions(self) -> None:
        project = Project(key="shad", group="tin", path=Path("/tmp/shad"), session="tin-shad")

        with patch(
            "shad.tmux.list_project_sessions",
            return_value=["tin-shad", "tin-shad--oc-sess-123"],
        ), patch("shad.tmux._run") as run, patch("builtins.print") as print_mock:
            stop_project(project)

        run.assert_any_call(["tmux", "kill-session", "-t", "tin-shad"])
        run.assert_any_call(["tmux", "kill-session", "-t", "tin-shad--oc-sess-123"])
        self.assertEqual(run.call_count, 2)
        print_mock.assert_called_once_with("stopped 2 sessions for 'tin-shad'")


if __name__ == "__main__":
    unittest.main()
