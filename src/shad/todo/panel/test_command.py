from __future__ import annotations

import unittest
from pathlib import Path


class LazyImportTests(unittest.TestCase):
    def test_the_panel_app_is_imported_inside_the_function(self) -> None:
        """textual must not load for `shad todo add`; only the panel's run may import it."""
        import shad.todo.panel.command as module

        source = Path(module.__file__).read_text()
        self.assertNotIn("\nfrom shad.todo.panel.app", source)
        self.assertNotIn("\nimport shad.todo.panel", source)
        self.assertIn("    from shad.todo.panel.app import run_panel", source)
