from __future__ import annotations

import unittest
from unittest.mock import patch

from shad.shared.editor import resolve_editor
from shad.shared.errors import ShadError


class ResolveEditorTests(unittest.TestCase):
    def test_visual_wins_over_editor(self) -> None:
        with patch.dict("os.environ", {"VISUAL": "code --wait", "EDITOR": "vim"}):
            self.assertEqual(resolve_editor(), "code --wait")

    def test_editor_when_visual_is_unset(self) -> None:
        with patch.dict("os.environ", {"EDITOR": "vim"}, clear=True):
            self.assertEqual(resolve_editor(), "vim")

    def test_first_installed_fallback(self) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("shad.shared.editor.shutil.which", side_effect=lambda name: name == "vi" or None),
        ):
            self.assertEqual(resolve_editor(), "vi")

    def test_no_editor_is_an_error(self) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("shad.shared.editor.shutil.which", return_value=None),
            self.assertRaises(ShadError),
        ):
            resolve_editor()
