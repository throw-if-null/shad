from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import call, patch

from shad.shared.config import Defaults, Project
from shad.projects.open.layout import _create_session


class WindowTitleTests(unittest.TestCase):
    def test_grouped_project_uses_group_pipe_key(self) -> None:
        project = Project(
            key="shad", group="tin", path=Path("/tmp/shad"), session="tin-shad"
        )

        with patch("shad.projects.open.layout._run") as run:
            _create_session(project, Defaults(), "opencode", "tin-shad")

        new_session_call = run.call_args_list[0]
        self.assertEqual(
            new_session_call,
            call(
                [
                    "tmux",
                    "new-session",
                    "-d",
                    "-s",
                    "tin-shad",
                    "-n",
                    "tin|shad",
                    "-c",
                    str(project.path),
                ]
            ),
        )

    def test_ungrouped_project_uses_key_only(self) -> None:
        project = Project(
            key="myapp", group=None, path=Path("/tmp/myapp"), session="myapp"
        )

        with patch("shad.projects.open.layout._run") as run:
            _create_session(project, Defaults(), "opencode", "myapp")

        new_session_call = run.call_args_list[0]
        self.assertEqual(
            new_session_call,
            call(
                [
                    "tmux",
                    "new-session",
                    "-d",
                    "-s",
                    "myapp",
                    "-n",
                    "myapp",
                    "-c",
                    str(project.path),
                ]
            ),
        )


if __name__ == "__main__":
    unittest.main()
