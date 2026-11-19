from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shad.errors import ShadError
from shad.sessions import store
from shad.sessions.model import Entry, Snapshot

_SNAPSHOT = Snapshot(
    saved_at=1700000000,
    entries=(Entry(group=None, key="kb", harness="claude", session_id="uuid-a", attached=True),),
)


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_write_then_read_round_trips(self) -> None:
        path = self.root / "shad" / "sessions.json"
        store.write(path, _SNAPSHOT)
        self.assertEqual(store.read(path), _SNAPSHOT)

    def test_write_creates_the_directory_and_leaves_no_temp_file(self) -> None:
        path = self.root / "nested" / "sessions.json"
        store.write(path, _SNAPSHOT)
        self.assertEqual(os.listdir(path.parent), ["sessions.json"])

    def test_write_replaces_an_existing_file(self) -> None:
        path = self.root / "sessions.json"
        store.write(path, _SNAPSHOT)
        later = Snapshot(saved_at=1700000001, entries=())
        store.write(path, later)
        self.assertEqual(store.read(path), later)

    def test_read_of_a_missing_file_says_how_to_create_it(self) -> None:
        with self.assertRaises(ShadError) as ctx:
            store.read(self.root / "sessions.json")
        self.assertIn("shad sessions save", str(ctx.exception))

    def test_snapshot_path_is_in_the_data_dir(self) -> None:
        with patch("shad.sessions.store.default_data_dir", return_value=Path("/data/shad")):
            self.assertEqual(store.snapshot_path(), Path("/data/shad/sessions.json"))
