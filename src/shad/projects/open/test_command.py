from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from shad.shared.config import Defaults, Project
from shad.projects.open.sessions import OpencodeTarget
from shad.projects.open.command import open_project


def _completed(
    returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


class OpenProjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = Project(
            key="shad", group="tin", path=Path("/tmp/shad"), session="tin-shad"
        )
        self.defaults = Defaults()

    def test_open_project_returns_none_when_picker_cancelled(self) -> None:
        with (
            patch("shad.projects.open.command.pick_opencode_target", return_value=None),
            patch("shad.projects.open.command._create_session") as create_session,
            patch("shad.projects.open.command._attach") as attach,
        ):
            result = open_project(self.project, self.defaults)

        self.assertIsNone(result)
        create_session.assert_not_called()
        attach.assert_not_called()

    def test_open_project_returns_attach_exit_code(self) -> None:
        target = OpencodeTarget(command="opencode -s sess-123", session_key="sess-123")

        with (
            patch(
                "shad.projects.open.command.pick_opencode_target", return_value=target
            ),
            patch("shad.projects.open.command.session_exists", return_value=True),
            patch("shad.projects.open.command._create_session"),
            patch("shad.projects.open.command._attach", return_value=0) as attach,
        ):
            result = open_project(self.project, self.defaults)

        attach.assert_called_once_with("tin-shad--oc-sess-123")
        self.assertEqual(result, 0)

    def test_open_project_creates_scoped_tmux_session_for_existing_oc_session(
        self,
    ) -> None:
        target = OpencodeTarget(command="opencode -s sess-123", session_key="sess-123")

        with (
            patch(
                "shad.projects.open.command.pick_opencode_target", return_value=target
            ),
            patch("shad.projects.open.command.session_exists", return_value=False),
            patch("shad.projects.open.command._create_session") as create_session,
            patch("shad.projects.open.command._attach"),
        ):
            open_project(self.project, self.defaults)

        create_session.assert_called_once_with(
            self.project, self.defaults, "opencode -s sess-123", "tin-shad--oc-sess-123"
        )

    def test_open_project_reuses_existing_scoped_tmux_session(self) -> None:
        target = OpencodeTarget(command="opencode -s sess-123", session_key="sess-123")

        with (
            patch(
                "shad.projects.open.command.pick_opencode_target", return_value=target
            ),
            patch("shad.projects.open.command.session_exists", return_value=True),
            patch("shad.projects.open.command._create_session") as create_session,
            patch("shad.projects.open.command._attach"),
        ):
            open_project(self.project, self.defaults)

        create_session.assert_not_called()

    def test_open_project_no_session_key_uses_base_session_name(self) -> None:
        target = OpencodeTarget(command="opencode")

        with (
            patch(
                "shad.projects.open.command.pick_opencode_target", return_value=target
            ),
            patch("shad.projects.open.command.session_exists", return_value=False),
            patch("shad.projects.open.command._create_session") as create_session,
            patch("shad.projects.open.command._attach"),
        ):
            open_project(self.project, self.defaults)

        create_session.assert_called_once_with(
            self.project, self.defaults, "opencode", "tin-shad"
        )

    def test_open_project_fresh_kills_existing_session_and_recreates(self) -> None:
        target = OpencodeTarget(command="opencode", session_key="fresh-123", fresh=True)

        with (
            patch(
                "shad.projects.open.command.pick_opencode_target", return_value=target
            ),
            patch("shad.projects.open.command.session_exists", return_value=True),
            patch("shad.projects.open.command._run") as run,
            patch("shad.projects.open.command._create_session") as create_session,
            patch("shad.projects.open.command._attach"),
        ):
            open_project(self.project, self.defaults)

        run.assert_called_once_with(
            ["tmux", "kill-session", "-t", "tin-shad--oc-fresh-123"], check=False
        )
        create_session.assert_called_once_with(
            self.project, self.defaults, "opencode", "tin-shad--oc-fresh-123"
        )


if __name__ == "__main__":
    unittest.main()
