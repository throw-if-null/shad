from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from shad.config import Config, Defaults
from shad.sessions import store
from shad.sessions.model import Entry, Snapshot, parse

_SNAPSHOT = Snapshot(
    saved_at=1700000000,
    entries=(Entry(group=None, key="kb", harness="claude", session_id="11111111-1111-4111-8111-111111111111", attached=True),),
)


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_write_round_trips_through_parse(self) -> None:
        path = self.root / "shad" / "sessions.json"
        store.write(path, _SNAPSHOT)
        self.assertEqual(parse(path.read_text()), _SNAPSHOT)

    def test_write_creates_the_directory_and_leaves_no_temp_file(self) -> None:
        path = self.root / "nested" / "sessions.json"
        store.write(path, _SNAPSHOT)
        self.assertEqual(os.listdir(path.parent), ["sessions.json"])

    def test_write_replaces_an_existing_file(self) -> None:
        path = self.root / "sessions.json"
        store.write(path, _SNAPSHOT)
        later = Snapshot(saved_at=1700000001, entries=())
        store.write(path, later)
        self.assertEqual(parse(path.read_text()), later)

    def test_snapshot_path_is_in_the_data_dir(self) -> None:
        cfg = Config(defaults=Defaults(), data_dir=Path("/data/shad"))
        self.assertEqual(store.snapshot_path(cfg), Path("/data/shad/sessions.json"))
