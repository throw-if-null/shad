"""`shad todo panel` — the pane; a thin textual view over the todo files."""

from __future__ import annotations

import argparse

from shad.shared.config import Config
from shad.todo import store


def open_todo_panel(cfg: Config, args: argparse.Namespace) -> None:
    # Imported here, not at module scope: textual costs roughly 100ms to
    # import, and `shad todo add` from a script must not pay it.
    from shad.todo.panel.app import run_panel

    run_panel(store.todo_dir(cfg), cfg.todo_labels)
