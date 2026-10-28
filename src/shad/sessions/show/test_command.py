from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shad.sessions import store
from shad.sessions.model import Entry, Snapshot
from shad.sessions.show.command import show_sessions
from shad.sessions.testing import CFG, UUID_A
from shad.shared.errors import ShadError

_ARGS = argparse.Namespace(sessions_action="show")


class ShowTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "sessions.json"
        patcher = patch("shad.sessions.store.snapshot_path", return_value=self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_reads_the_snapshot(self) -> None:
        entry = Entry(group=None, key="kb", harness="claude", session_id=UUID_A, attached=True)
        store.write(self.path, Snapshot(saved_at=1, entries=(entry,)))
        show_sessions(CFG, _ARGS)

    def test_an_empty_snapshot(self) -> None:
        store.write(self.path, Snapshot(saved_at=1, entries=()))
        show_sessions(CFG, _ARGS)

    def test_without_a_snapshot_fails(self) -> None:
        with self.assertRaises(ShadError):
            show_sessions(CFG, _ARGS)
