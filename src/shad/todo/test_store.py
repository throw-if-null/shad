from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from shad.config.load import Config, Defaults
from shad.errors import ShadError
from shad.todo import store

VOCAB = ["chore", "poc"]


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name) / "todo"

    # -- paths ------------------------------------------------------------

    def test_todo_dir_defaults_to_todo_under_the_data_dir(self) -> None:
        with patch("shad.todo.store.default_data_dir", return_value=Path("/data")):
            self.assertEqual(store.todo_dir(Config(defaults=Defaults())), Path("/data/todo"))

    def test_the_configured_todo_path_replaces_the_data_dir(self) -> None:
        cfg = Config(defaults=Defaults(), todo_path=Path("/notes/todo"))
        with patch("shad.todo.store.default_data_dir", return_value=Path("/data")):
            self.assertEqual(store.todo_dir(cfg), Path("/notes/todo"))

    # -- add --------------------------------------------------------------

    def test_add_creates_the_file_with_canonical_headers(self) -> None:
        item = store.add(self.dir, "  Fix   panel resize ", ["poc", "chore", "poc"], VOCAB)
        self.assertEqual(item.key, "fix-panel-resize")
        text = store.item_path(self.dir, item.key).read_text()
        lines = text.splitlines()
        self.assertEqual(lines[0], "title: Fix panel resize")
        self.assertEqual(lines[1], "status: todo")
        self.assertEqual(lines[2], "labels: poc, chore")
        self.assertTrue(lines[3].startswith("created: 20"))
        self.assertTrue(text.endswith("\n\n"))

    def test_add_refuses_a_duplicate_key(self) -> None:
        store.add(self.dir, "Same", [], VOCAB)
        with self.assertRaises(ShadError) as ctx:
            store.add(self.dir, "same!", [], VOCAB)
        self.assertIn("already exists", str(ctx.exception))

    def test_add_refuses_an_unknown_label_before_touching_the_disk(self) -> None:
        with self.assertRaises(ShadError):
            store.add(self.dir, "x", ["nope"], VOCAB)
        self.assertFalse(self.dir.exists())

    def test_add_writes_status_body_and_unknown_headers(self) -> None:
        item = store.add(
            self.dir,
            "t",
            [],
            VOCAB,
            status="in-progress",
            body="\n\nFirst line.\n\n  indented\n\n\n",
            extra=(("priority", "high"),),
        )
        self.assertEqual(item.status, "in-progress")
        text = store.item_path(self.dir, "t").read_text()
        self.assertIn("status: in-progress\n", text)
        self.assertIn("priority: high\n", text)
        self.assertTrue(text.endswith("\n\nFirst line.\n\n  indented\n"))

    def test_add_stores_a_whitespace_only_body_as_empty(self) -> None:
        store.add(self.dir, "t", [], VOCAB, body="\n  \n\n")
        self.assertTrue(store.item_path(self.dir, "t").read_text().endswith("\n\n"))
        self.assertEqual(store.read_item(self.dir, "t").body, "")

    def test_add_refuses_an_unknown_status_before_touching_the_disk(self) -> None:
        with self.assertRaises(ShadError):
            store.add(self.dir, "x", [], VOCAB, status="doing")
        self.assertFalse(self.dir.exists())

    def test_add_refuses_an_empty_title(self) -> None:
        with self.assertRaises(ShadError):
            store.add(self.dir, "   ", [], VOCAB)

    # -- list / keys / resolve -------------------------------------------

    def test_missing_directory_lists_nothing(self) -> None:
        self.assertEqual(store.list_items(self.dir), [])
        self.assertEqual(store.keys(self.dir), [])
        self.assertEqual(store.signature(self.dir), frozenset())

    def test_list_is_in_display_order_and_skips_non_items(self) -> None:
        store.add(self.dir, "Done thing", [], VOCAB)
        store.add(self.dir, "Active", [], VOCAB)
        store.set_status(self.dir, "done-thing", "done")
        store.set_status(self.dir, "active", "in-progress")
        (self.dir / "notes.txt").write_text("not an item")
        (self.dir / ".active.123.tmp").write_text("title: ghost\n")
        self.assertEqual([i.key for i in store.list_items(self.dir)], ["active", "done-thing"])

    def test_resolve_key_accepts_a_unique_prefix(self) -> None:
        store.add(self.dir, "alpha one", [], VOCAB)
        store.add(self.dir, "beta", [], VOCAB)
        self.assertEqual(store.resolve_key(self.dir, "al"), "alpha-one")
        self.assertEqual(store.resolve_key(self.dir, "beta"), "beta")

    def test_resolve_key_rejects_unknown_and_ambiguous(self) -> None:
        store.add(self.dir, "alpha", [], VOCAB)
        store.add(self.dir, "alps", [], VOCAB)
        with self.assertRaises(ShadError):
            store.resolve_key(self.dir, "al")
        with self.assertRaises(ShadError):
            store.resolve_key(self.dir, "zzz")

    # -- set_status / remove ---------------------------------------------

    def test_set_status_rewrites_headers_and_keeps_the_body_byte_for_byte(self) -> None:
        store.add(self.dir, "t", [], VOCAB)
        path = store.item_path(self.dir, "t")
        body = "\n  indented\n\ttabbed\nno trailing newline"
        path.write_text(path.read_text() + body)
        before = path.read_text()

        item = store.set_status(self.dir, "t", "wont-do")

        self.assertEqual(item.status, "wont-do")
        after = path.read_text()
        self.assertEqual(after.replace("status: wont-do", "status: todo"), before)
        self.assertEqual([p.name for p in self.dir.iterdir()], ["t.md"])

    def test_set_status_rejects_an_unknown_status(self) -> None:
        store.add(self.dir, "t", [], VOCAB)
        with self.assertRaises(ShadError):
            store.set_status(self.dir, "t", "doing")

    def test_remove_deletes_the_file_and_reports_a_missing_one(self) -> None:
        store.add(self.dir, "t", [], VOCAB)
        store.remove(self.dir, "t")
        self.assertEqual(store.keys(self.dir), [])
        with self.assertRaises(ShadError):
            store.remove(self.dir, "t")

    # -- signature --------------------------------------------------------

    def test_signature_changes_on_add_edit_and_delete(self) -> None:
        first = store.signature(self.dir)
        store.add(self.dir, "t", [], VOCAB)
        second = store.signature(self.dir)
        self.assertNotEqual(first, second)

        path = store.item_path(self.dir, "t")
        os.utime(path, ns=(1, 1))
        third = store.signature(self.dir)
        self.assertNotEqual(second, third)

        store.remove(self.dir, "t")
        self.assertEqual(store.signature(self.dir), frozenset())

    # -- label usage ------------------------------------------------------

    def test_label_usage_counts_the_items_that_carry_the_label(self) -> None:
        store.add(self.dir, "one", ["chore"], VOCAB)
        store.add(self.dir, "two", ["chore", "poc"], VOCAB)
        store.add(self.dir, "three", [], VOCAB)
        self.assertEqual(store.label_usage(self.dir, "chore"), 2)
        self.assertEqual(store.label_usage(self.dir, "poc"), 1)
        self.assertEqual(store.label_usage(self.dir / "nope", "poc"), 0)


if __name__ == "__main__":
    unittest.main()
