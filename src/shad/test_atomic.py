from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from shad import atomic


class CreateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_creates_the_file_and_its_directory(self) -> None:
        path = self.root / "a" / "b.md"
        atomic.create(path, "one\n")
        self.assertEqual(path.read_text(), "one\n")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)

    def test_a_second_create_of_one_path_fails_and_keeps_the_first(self) -> None:
        path = self.root / "b.md"
        atomic.create(path, "first\n")
        with self.assertRaises(FileExistsError):
            atomic.create(path, "second\n")
        self.assertEqual(path.read_text(), "first\n")


class ReplaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_a_new_file_gets_the_text_and_mode_0644(self) -> None:
        path = self.root / "new.json"
        atomic.replace(path, "{}\n")
        self.assertEqual(path.read_text(), "{}\n")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)
        self.assertEqual(os.listdir(self.root), ["new.json"])

    def test_an_existing_file_keeps_its_mode(self) -> None:
        path = self.root / "kept.toml"
        path.write_text("old\n")
        path.chmod(0o600)
        atomic.replace(path, "new\n")
        self.assertEqual(path.read_text(), "new\n")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_a_failing_check_leaves_the_file_and_no_temporary(self) -> None:
        path = self.root / "checked.toml"
        path.write_text("old\n")

        def reject(tmp: Path) -> None:
            self.assertEqual(tmp.read_text(), "bad\n")
            raise ValueError("no")

        with self.assertRaises(ValueError):
            atomic.replace(path, "bad\n", check=reject)
        self.assertEqual(path.read_text(), "old\n")
        self.assertEqual(os.listdir(self.root), ["checked.toml"])


if __name__ == "__main__":
    unittest.main()
