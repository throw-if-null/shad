from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from shad.editor import Editor
from shad.errors import ShadError


class EditorTests(unittest.TestCase):
    def test_visual_wins_over_editor(self) -> None:
        editor = Editor.from_env({"VISUAL": "code --wait", "EDITOR": "vim"})
        self.assertEqual(editor.resolve(), "code --wait")

    def test_editor_when_visual_is_unset(self) -> None:
        self.assertEqual(Editor.from_env({"EDITOR": "vim"}).resolve(), "vim")

    def test_an_empty_variable_counts_as_unset(self) -> None:
        with patch("shad.editor.shutil.which", side_effect=lambda name: name == "vi" or None):
            self.assertEqual(Editor.from_env({"VISUAL": "", "EDITOR": ""}).resolve(), "vi")

    def test_the_first_installed_fallback(self) -> None:
        with patch("shad.editor.shutil.which", side_effect=lambda name: name == "vi" or None):
            self.assertEqual(Editor(None).resolve(), "vi")

    def test_no_editor_is_an_infrastructure_error(self) -> None:
        with patch("shad.editor.shutil.which", return_value=None), self.assertRaises(ShadError) as ctx:
            Editor(None).resolve()
        self.assertEqual(ctx.exception.code, "no_editor")

    def test_open_runs_the_command_line_on_the_file(self) -> None:
        done: subprocess.CompletedProcess[bytes] = subprocess.CompletedProcess(["x"], 0)
        with patch("shad.editor.subprocess.run", return_value=done) as run:
            Editor("code --wait").open(Path("/tmp/f.md"))
        self.assertEqual(run.call_args.args[0], ["code", "--wait", "/tmp/f.md"])

    def test_a_failing_editor_is_an_infrastructure_error(self) -> None:
        failed: subprocess.CompletedProcess[bytes] = subprocess.CompletedProcess(["x"], 3)
        with patch("shad.editor.subprocess.run", return_value=failed), self.assertRaises(ShadError) as ctx:
            Editor("vim").open(Path("/tmp/f.md"))
        self.assertEqual(ctx.exception.code, "editor_failed")
        self.assertIn("3", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
