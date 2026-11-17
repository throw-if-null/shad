from __future__ import annotations

import itertools
import unittest
import unittest.mock
from pathlib import Path
from unittest.mock import call, patch

from shad.projects.open.layout import _create_session
from shad.shared.config import OC_POSITIONS, Defaults, Project


def _record(
    project: Project, defaults: Defaults, session: str = "myapp"
) -> list[list[str]]:
    """Run _create_session against a fake tmux that hands out pane ids %0, %1, ..."""
    ids = (f"%{n}" for n in itertools.count())

    def fake_run(args: list[str], check: bool = True) -> unittest.mock.Mock:
        result = unittest.mock.Mock()
        prints_id = args[1] == "display-message" or "-P" in args
        result.stdout = f"{next(ids)}\n" if prints_id else ""
        return result

    with patch("shad.projects.open.layout._run", side_effect=fake_run) as run:
        _create_session(project, defaults, "opencode", session)
    return [c.args[0] for c in run.call_args_list]


def _sent(calls: list[list[str]]) -> dict[str, str]:
    """Map each command typed into a pane to that pane's target."""
    return {c[-1]: c[3] for c in calls if c[:2] == ["tmux", "send-keys"]}


def _splits(calls: list[list[str]]) -> list[list[str]]:
    return [c for c in calls if c[:2] == ["tmux", "split-window"]]


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

    def test_every_layout_launches_the_panel_exactly_once(self) -> None:
        project = Project(
            key="myapp", group=None, path=Path("/tmp/myapp"), session="myapp"
        )

        for position in OC_POSITIONS:
            for todo_panel in (True, False):
                with self.subTest(position=position, todo_panel=todo_panel):
                    defaults = Defaults(oc_position=position, todo_panel=todo_panel)
                    calls = _record(project, defaults)
                    sent = [c[-1] for c in calls if c[:2] == ["tmux", "send-keys"]]
                    self.assertEqual(sent.count("shad git panel myapp\n"), 1)
                    # The panel must not land in the pane the harness owns.
                    targets = _sent(calls)
                    self.assertNotEqual(
                        targets["shad git panel myapp\n"], targets["opencode\n"]
                    )


class GridTests(unittest.TestCase):
    """With the todo pane on, every pane is addressed by its id."""

    PROJECT = Project(key="shad", group="tin", path=Path("/tmp/shad"), session="tin-shad")

    def _calls(self, position: str, project: Project = PROJECT) -> list[list[str]]:
        defaults = Defaults(
            oc_position=position, panel_percent=35, split_percent=40, todo_percent=30
        )
        return _record(project, defaults, "tin-shad")


    def test_top_puts_the_harness_and_todo_above_shell_and_git(self) -> None:
        calls = self._calls("top")
        sent = _sent(calls)
        self.assertEqual(sent["opencode\n"], "%0")
        self.assertEqual(sent["shad todo panel\n"], "%1")
        self.assertEqual(sent["shad projects tin shad status\n"], "%2")
        self.assertEqual(sent["shad git panel tin shad\n"], "%3")

        splits = _splits(calls)
        # The right column first, then each column at panel_percent.
        self.assertEqual(splits[0][2:7], ["-t", "%0", "-h", "-l", "30%"])
        self.assertEqual(splits[1][2:7], ["-t", "%0", "-v", "-l", "35%"])
        self.assertEqual(splits[2][2:7], ["-t", "%1", "-v", "-l", "35%"])

    def test_bottom_puts_the_harness_and_todo_in_the_lower_panes(self) -> None:
        calls = self._calls("bottom")
        sent = _sent(calls)
        self.assertEqual(sent["shad projects tin shad status\n"], "%0")
        self.assertEqual(sent["shad git panel tin shad\n"], "%1")
        self.assertEqual(sent["opencode\n"], "%2")
        self.assertEqual(sent["shad todo panel\n"], "%3")

        splits = _splits(calls)
        self.assertEqual(splits[1][2:7], ["-t", "%0", "-v", "-l", "65%"])
        self.assertEqual(splits[2][2:7], ["-t", "%1", "-v", "-l", "65%"])

    def test_left_puts_the_todo_column_right_of_the_bundle(self) -> None:
        calls = self._calls("left")
        sent = _sent(calls)
        self.assertEqual(sent["opencode\n"], "%0")
        self.assertEqual(sent["shad todo panel\n"], "%1")
        self.assertEqual(sent["shad projects tin shad status\n"], "%2")
        self.assertEqual(sent["shad git panel tin shad\n"], "%3")

        splits = _splits(calls)
        # The todo column, then the bundle beside the harness, then git
        # inside the bundle at split_percent.
        self.assertEqual(splits[0][2:7], ["-t", "%0", "-h", "-l", "30%"])
        self.assertEqual(splits[1][2:7], ["-t", "%0", "-h", "-l", "35%"])
        self.assertEqual(splits[2][2:7], ["-t", "%2", "-v", "-l", "40%"])

    def test_every_split_asks_tmux_for_the_new_pane_id(self) -> None:
        for position in OC_POSITIONS:
            with self.subTest(position=position):
                for split in _splits(self._calls(position)):
                    self.assertEqual(split[-3:], ["-P", "-F", "#{pane_id}"])

    def test_four_distinct_panes_and_focus_on_the_harness(self) -> None:
        for position in OC_POSITIONS:
            with self.subTest(position=position):
                calls = self._calls(position)
                sent = _sent(calls)
                self.assertEqual(len(set(sent.values())), 4)
                focus = next(c[3] for c in calls if c[:2] == ["tmux", "select-pane"])
                self.assertEqual(focus, sent["opencode\n"])

    def test_ungrouped_project_passes_a_bare_key_to_the_git_panel(self) -> None:
        project = Project(key="myapp", group=None, path=Path("/tmp/myapp"), session="myapp")
        sent = _sent(self._calls("top", project))
        self.assertIn("shad todo panel\n", sent)
        self.assertIn("shad git panel myapp\n", sent)

    def test_the_todo_pane_is_on_by_default(self) -> None:
        sent = _sent(_record(self.PROJECT, Defaults(), "tin-shad"))
        self.assertIn("shad todo panel\n", sent)

    def test_todo_panel_off_keeps_the_three_pane_layout(self) -> None:
        project = Project(key="myapp", group=None, path=Path("/tmp/myapp"), session="myapp")
        calls = _record(project, Defaults(todo_panel=False))
        self.assertNotIn("shad todo panel\n", _sent(calls))
        self.assertFalse(any("-P" in c for c in _splits(calls)))


class GitPanelOffTests(unittest.TestCase):
    """With git_panel off, no pane runs the git panel and no pane is left empty."""

    PROJECT = Project(key="shad", group="tin", path=Path("/tmp/shad"), session="tin-shad")

    def _calls(self, position: str, todo_panel: bool) -> list[list[str]]:
        defaults = Defaults(
            oc_position=position,
            panel_percent=35,
            todo_percent=30,
            git_panel=False,
            todo_panel=todo_panel,
        )
        return _record(self.PROJECT, defaults, "tin-shad")

    def test_no_layout_launches_the_git_panel(self) -> None:
        for position in OC_POSITIONS:
            for todo_panel in (True, False):
                with self.subTest(position=position, todo_panel=todo_panel):
                    sent = _sent(self._calls(position, todo_panel))
                    self.assertNotIn("shad git panel tin shad\n", sent)
                    self.assertIn("shad projects tin shad status\n", sent)
                    self.assertEqual(
                        "shad todo panel\n" in sent, todo_panel
                    )

    def test_every_pane_runs_something_and_the_harness_has_focus(self) -> None:
        for position in OC_POSITIONS:
            for todo_panel in (True, False):
                with self.subTest(position=position, todo_panel=todo_panel):
                    calls = self._calls(position, todo_panel)
                    sent = _sent(calls)
                    panes = 3 if todo_panel else 2
                    self.assertEqual(len(_splits(calls)), panes - 1)
                    self.assertEqual(len(set(sent.values())), panes)
                    focus = next(c[3] for c in calls if c[:2] == ["tmux", "select-pane"])
                    self.assertEqual(focus, sent["opencode\n"])

    def test_the_todo_pane_takes_the_full_height_of_its_column(self) -> None:
        # Only the first split touches the todo column; nothing splits it.
        for position in OC_POSITIONS:
            with self.subTest(position=position):
                calls = self._calls(position, todo_panel=True)
                splits = _splits(calls)
                self.assertEqual(splits[0][2:7], ["-t", "%0", "-h", "-l", "30%"])
                todo = _sent(calls)["shad todo panel\n"]
                self.assertEqual(todo, "%1")
                self.assertFalse(any(split[3] == todo for split in splits))

    def test_without_either_panel_the_harness_and_bash_split_once(self) -> None:
        expected = {
            "top": (["-v", "-l", "35%"], "tin-shad:0.0", "tin-shad:0.1"),
            "bottom": (["-v", "-l", "65%"], "tin-shad:0.1", "tin-shad:0.0"),
            "left": (["-h", "-l", "35%"], "tin-shad:0.0", "tin-shad:0.1"),
        }
        for position, (split, harness, shell) in expected.items():
            with self.subTest(position=position):
                calls = self._calls(position, todo_panel=False)
                self.assertEqual(_splits(calls)[0][4:7], split)
                sent = _sent(calls)
                self.assertEqual(sent["opencode\n"], harness)
                self.assertEqual(sent["shad projects tin shad status\n"], shell)


if __name__ == "__main__":
    unittest.main()
