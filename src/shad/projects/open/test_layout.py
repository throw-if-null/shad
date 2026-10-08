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


class GridTests(unittest.TestCase):
    """With todo_percent set the window is a 2x2 grid addressed by pane id."""

    PROJECT = Project(key="shad", group="tin", path=Path("/tmp/shad"), session="tin-shad")

    def _calls(self, position: str, project: Project = PROJECT) -> list[list[str]]:
        defaults = Defaults(oc_position=position, panel_percent=35, todo_percent=30)
        ids = iter(["%0", "%1", "%2", "%3"])

        def fake_run(args: list[str], check: bool = True) -> unittest.mock.Mock:
            result = unittest.mock.Mock()
            prints_id = args[1] in ("display-message", "split-window")
            result.stdout = f"{next(ids)}\n" if prints_id else ""
            return result

        with patch("shad.projects.open.layout._run", side_effect=fake_run) as run:
            _create_session(project, defaults, "opencode", "tin-shad")
        return [c.args[0] for c in run.call_args_list]

    @staticmethod
    def _sent(calls: list[list[str]]) -> dict[str, str]:
        return {c[-1]: c[3] for c in calls if c[:2] == ["tmux", "send-keys"]}

    @staticmethod
    def _splits(calls: list[list[str]]) -> list[list[str]]:
        return [c for c in calls if c[:2] == ["tmux", "split-window"]]

    def test_top_puts_the_harness_and_todo_above_shell_and_git(self) -> None:
        calls = self._calls("top")
        sent = self._sent(calls)
        self.assertEqual(sent["opencode\n"], "%0")
        self.assertEqual(sent["shad todo panel --project tin/shad\n"], "%1")
        self.assertEqual(sent["shad projects tin shad status\n"], "%2")
        self.assertEqual(sent["shad git panel tin shad\n"], "%3")

        splits = self._splits(calls)
        # The right column first, then each column at panel_percent.
        self.assertEqual(splits[0][2:7], ["-t", "%0", "-h", "-p", "30"])
        self.assertEqual(splits[1][2:7], ["-t", "%0", "-v", "-p", "35"])
        self.assertEqual(splits[2][2:7], ["-t", "%1", "-v", "-p", "35"])

    def test_bottom_puts_the_harness_and_todo_in_the_lower_panes(self) -> None:
        calls = self._calls("bottom")
        sent = self._sent(calls)
        self.assertEqual(sent["shad projects tin shad status\n"], "%0")
        self.assertEqual(sent["shad git panel tin shad\n"], "%1")
        self.assertEqual(sent["opencode\n"], "%2")
        self.assertEqual(sent["shad todo panel --project tin/shad\n"], "%3")

        splits = self._splits(calls)
        self.assertEqual(splits[1][2:7], ["-t", "%0", "-v", "-p", "65"])
        self.assertEqual(splits[2][2:7], ["-t", "%1", "-v", "-p", "65"])

    def test_every_split_asks_tmux_for_the_new_pane_id(self) -> None:
        for position in ("top", "bottom"):
            with self.subTest(position=position):
                for split in self._splits(self._calls(position)):
                    self.assertEqual(split[-3:], ["-P", "-F", "#{pane_id}"])

    def test_four_distinct_panes_and_focus_on_the_harness(self) -> None:
        for position in ("top", "bottom"):
            with self.subTest(position=position):
                calls = self._calls(position)
                sent = self._sent(calls)
                self.assertEqual(len(set(sent.values())), 4)
                focus = next(c[3] for c in calls if c[:2] == ["tmux", "select-pane"])
                self.assertEqual(focus, sent["opencode\n"])

    def test_ungrouped_project_passes_a_bare_key_to_the_todo_panel(self) -> None:
        project = Project(key="myapp", group=None, path=Path("/tmp/myapp"), session="myapp")
        sent = self._sent(self._calls("top", project))
        self.assertIn("shad todo panel --project myapp\n", sent)
        self.assertIn("shad git panel myapp\n", sent)

    def test_zero_todo_percent_keeps_the_three_pane_layout(self) -> None:
        project = Project(key="myapp", group=None, path=Path("/tmp/myapp"), session="myapp")
        with patch("shad.projects.open.layout._run") as run:
            _create_session(project, Defaults(todo_percent=0), "opencode", "myapp")
        calls = [c.args[0] for c in run.call_args_list]
        self.assertFalse(any("shad todo panel" in c[-1] for c in calls if c[1] == "send-keys"))
        self.assertFalse(any("-P" in c for c in self._splits(calls)))


if __name__ == "__main__":
    unittest.main()
