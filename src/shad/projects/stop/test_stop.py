from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from shad.shared.config import Project
from shad.projects.stop.command import stop_project


def _completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class StopProjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = Project(
            key="shad", group="tin", path=Path("/tmp/shad"), session="tin-shad"
        )

    def test_stop_project_kills_all_project_sessions(self) -> None:
        with patch("shad.projects.stop.command.list_project_sessions",
                   return_value=["tin-shad", "tin-shad--oc-sess-123"]), \
             patch("shad.projects.stop.command._run") as run, \
             patch("shad.projects.stop.command.console") as mock_console:
            stop_project(self.project)

        run.assert_any_call(["tmux", "kill-session", "-t", "tin-shad"])
        run.assert_any_call(["tmux", "kill-session", "-t", "tin-shad--oc-sess-123"])
        self.assertEqual(run.call_count, 2)
        mock_console.print.assert_called_once()

    def test_stop_project_no_sessions_prints_not_running(self) -> None:
        with patch("shad.projects.stop.command.list_project_sessions", return_value=[]), \
             patch("shad.projects.stop.command._run") as run, \
             patch("shad.projects.stop.command.console") as mock_console:
            stop_project(self.project)

        run.assert_not_called()
        mock_console.print.assert_called_once()
        printed_text = str(mock_console.print.call_args)
        self.assertIn("not running", printed_text)

    def test_stop_project_single_session_message(self) -> None:
        with patch("shad.projects.stop.command.list_project_sessions", return_value=["tin-shad"]), \
             patch("shad.projects.stop.command._run"), \
             patch("shad.projects.stop.command.console") as mock_console:
            stop_project(self.project)

        mock_console.print.assert_called_once()

    def test_stop_project_multiple_sessions_message(self) -> None:
        sessions = ["tin-shad", "tin-shad--oc-a", "tin-shad--oc-b"]
        with patch("shad.projects.stop.command.list_project_sessions", return_value=sessions), \
             patch("shad.projects.stop.command._run"), \
             patch("shad.projects.stop.command.console") as mock_console:
            stop_project(self.project)

        mock_console.print.assert_called_once()
        printed_text = str(mock_console.print.call_args)
        self.assertIn("3", printed_text)


if __name__ == "__main__":
    unittest.main()
