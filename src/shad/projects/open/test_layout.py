from __future__ import annotations

import unittest
import unittest.mock
from pathlib import Path
from unittest.mock import call, patch

from shad.projects.open.layout import _create_session
from shad.shared.config import Defaults, Project


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


class GitPaneTests(unittest.TestCase):
    """The third pane runs shad's own panel, not a third-party git client."""

    @staticmethod
    def _sent(run: unittest.mock.MagicMock) -> list[str]:
        return [
            c.args[0][-1]
            for c in run.call_args_list
            if c.args and c.args[0][:2] == ["tmux", "send-keys"]
        ]

    def test_grouped_project_targets_group_and_key(self) -> None:
        project = Project(
            key="shad", group="tin", path=Path("/tmp/shad"), session="tin-shad"
        )

        with patch("shad.projects.open.layout._run") as run:
            _create_session(project, Defaults(), "opencode", "tin-shad")

        sent = self._sent(run)
        self.assertIn("shad git panel tin shad\n", sent)
        self.assertIn("shad projects tin shad status\n", sent)

    def test_ungrouped_project_targets_key_only(self) -> None:
        project = Project(
            key="myapp", group=None, path=Path("/tmp/myapp"), session="myapp"
        )

        with patch("shad.projects.open.layout._run") as run:
            _create_session(project, Defaults(), "opencode", "myapp")

        sent = self._sent(run)
        self.assertIn("shad git panel myapp\n", sent)
        self.assertIn("shad projects myapp status\n", sent)

    def test_every_position_launches_the_panel_exactly_once(self) -> None:
        project = Project(
            key="myapp", group=None, path=Path("/tmp/myapp"), session="myapp"
        )

        for position in ("top", "bottom", "left"):
            with self.subTest(position=position):
                defaults = Defaults(oc_position=position)
                with patch("shad.projects.open.layout._run") as run:
                    _create_session(project, defaults, "opencode", "myapp")

                sent = self._sent(run)
                self.assertEqual(sent.count("shad git panel myapp\n"), 1)
                # The panel must not land in the pane the harness owns.
                panel_target = next(
                    c.args[0][3]
                    for c in run.call_args_list
                    if c.args and c.args[0][:2] == ["tmux", "send-keys"]
                    and c.args[0][-1] == "shad git panel myapp\n"
                )
                harness_target = next(
                    c.args[0][3]
                    for c in run.call_args_list
                    if c.args and c.args[0][:2] == ["tmux", "send-keys"]
                    and c.args[0][-1] == "opencode\n"
                )
                self.assertNotEqual(panel_target, harness_target)


if __name__ == "__main__":
    unittest.main()
