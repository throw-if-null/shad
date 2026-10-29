from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from shad.shared.terminal import current, open_tab


class CurrentTests(unittest.TestCase):
    def test_kitty_when_its_variable_and_kitten_are_present(self) -> None:
        with (
            patch.dict("os.environ", {"KITTY_WINDOW_ID": "1"}),
            patch("shad.shared.terminal.shutil.which", return_value="/usr/bin/kitten"),
        ):
            self.assertEqual(current(), "kitty")

    def test_none_outside_kitty(self) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("shad.shared.terminal.shutil.which", return_value="/usr/bin/kitten"),
        ):
            self.assertIsNone(current())

    def test_none_without_kitten(self) -> None:
        with (
            patch.dict("os.environ", {"KITTY_WINDOW_ID": "1"}),
            patch("shad.shared.terminal.shutil.which", return_value=None),
        ):
            self.assertIsNone(current())


class OpenTabTests(unittest.TestCase):
    def test_launches_a_kitty_tab_behind_the_current_one(self) -> None:
        done = subprocess.CompletedProcess(args=[], returncode=0, stdout="7\n", stderr="")
        with patch("shad.shared.terminal.subprocess.run", return_value=done) as run:
            error = open_tab("kitty", ["tmux", "attach-session", "-t", "=kb"], Path("/p/kb"))

        self.assertIsNone(error)
        self.assertEqual(
            run.call_args.args[0],
            [
                "kitten", "@", "launch", "--type=tab", "--keep-focus", "--cwd=/p/kb",
                "tmux", "attach-session", "-t", "=kb",
            ],
        )

    def test_reports_kittens_error(self) -> None:
        failed = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="Remote control is disabled\n"
        )
        with patch("shad.shared.terminal.subprocess.run", return_value=failed):
            error = open_tab("kitty", ["true"], Path("/p"))

        self.assertEqual(error, "Remote control is disabled")

    def test_reports_no_answer(self) -> None:
        with patch(
            "shad.shared.terminal.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="kitten", timeout=10),
        ):
            error = open_tab("kitty", ["true"], Path("/p"))

        assert error is not None
        self.assertIn("did not answer", error)

    def test_rejects_an_unknown_terminal(self) -> None:
        with self.assertRaises(ValueError):
            open_tab("xterm", ["true"], Path("/p"))
