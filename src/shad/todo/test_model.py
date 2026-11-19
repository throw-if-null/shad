from __future__ import annotations

import unittest

from shad.errors import ShadError
from shad.todo.model import (
    STATUSES,
    Item,
    Status,
    check_labels,
    parse,
    problems,
    serialize,
    slugify,
    sort_key,
    template,
)

FILE = """\
title: Fix panel resize
status: in-progress
labels: chore, investigation
created: 2026-10-07T10:12:00+02:00

Free text.

A second paragraph, kept as is.
"""


class SlugTests(unittest.TestCase):
    def test_lowercases_and_collapses_runs_of_other_characters(self) -> None:
        self.assertEqual(slugify("Fix the Panel -- resize!!"), "fix-the-panel-resize")

    def test_strips_leading_and_trailing_hyphens(self) -> None:
        self.assertEqual(slugify("  (draft) "), "draft")

    def test_truncates_to_the_key_limit_without_a_dangling_hyphen(self) -> None:
        key = slugify("a" * 39 + " bb")
        self.assertEqual(key, "a" * 39)
        self.assertLessEqual(len(key), 40)

    def test_title_without_letters_or_digits_is_an_error(self) -> None:
        with self.assertRaises(ShadError):
            slugify("!!! ???")


class ParseTests(unittest.TestCase):
    def test_reads_every_known_header_and_the_body(self) -> None:
        item = parse(FILE, key="fix-panel-resize", updated=5)
        self.assertEqual(item.title, "Fix panel resize")
        self.assertEqual(item.status, Status.IN_PROGRESS)
        self.assertEqual(item.labels, ("chore", "investigation"))
        self.assertEqual(item.created, "2026-10-07T10:12:00+02:00")
        self.assertEqual(item.body, "Free text.\n\nA second paragraph, kept as is.\n")
        self.assertEqual(item.updated, 5)

    def test_round_trips_byte_for_byte(self) -> None:
        self.assertEqual(serialize(parse(FILE, key="k")), FILE)

    def test_status_change_keeps_the_body_and_unknown_headers(self) -> None:
        text = "title: t\nstatus: todo\nlabels: \ncreated: c\npriority: high\n\nbody\n"
        item = parse(text, key="t").with_status("done")
        self.assertEqual(
            serialize(item),
            "title: t\nstatus: done\nlabels: \ncreated: c\npriority: high\n\nbody\n",
        )

    def test_header_names_are_case_insensitive_and_first_wins(self) -> None:
        item = parse("Title: one\ntitle: two\nstatus: todo\n\n", key="k")
        self.assertEqual(item.title, "one")

    def test_a_file_with_no_blank_line_has_no_body(self) -> None:
        item = parse("title: t\nstatus: todo\n", key="k")
        self.assertEqual(item.title, "t")
        self.assertEqual(item.body, "")

    def test_a_file_with_no_headers_is_an_item_with_problems(self) -> None:
        item = parse("just some text\n", key="k")
        self.assertEqual(item.title, "")
        self.assertIn("no title", problems(item, []))
        self.assertIn("no status", problems(item, []))

    def test_a_body_that_starts_with_blank_lines_is_kept(self) -> None:
        text = "title: t\nstatus: todo\nlabels: \ncreated: \n\n\n\nbody\n"
        self.assertEqual(parse(text, key="k").body, "\n\nbody\n")
        self.assertEqual(serialize(parse(text, key="k")), text)


class TemplateTests(unittest.TestCase):
    def test_parses_to_an_empty_draft_with_the_given_labels(self) -> None:
        item = parse(template(["poc"], ["chore", "poc"]), key="")
        self.assertEqual(item.title, "")
        self.assertEqual(item.status, Status.TODO)
        self.assertEqual(item.labels, ("poc",))
        self.assertEqual(item.body, "")

    def test_help_lines_name_the_vocabulary_and_never_become_headers(self) -> None:
        text = template([], ["chore", "poc"])
        self.assertIn("# labels: chore, poc", text)
        self.assertIn("# statuses: todo, in-progress, done, wont-do", text)
        self.assertEqual(parse(text, key="").extra, ())

    def test_starts_on_the_title_and_ends_on_an_empty_body_line(self) -> None:
        text = template([], [])
        self.assertTrue(text.startswith("title: \n"))
        self.assertTrue(text.endswith("\n\n"))
        self.assertIn("# labels: none configured", text)


class ProblemTests(unittest.TestCase):
    def test_a_good_item_has_none(self) -> None:
        item = Item(key="k", title="t", status="todo", labels=("chore",))
        self.assertEqual(problems(item, ["chore"]), [])

    def test_unknown_status_and_label_are_reported_not_raised(self) -> None:
        item = Item(key="k", title="t", status="doing", labels=("chore", "nope"))
        found = problems(item, ["chore"])
        self.assertEqual(found, ["unknown status 'doing'", "unknown label 'nope'"])

    def test_check_labels_rejects_an_unconfigured_label_and_names_the_known_ones(self) -> None:
        with self.assertRaises(ShadError) as ctx:
            check_labels(["poc"], ["chore", "docs"])
        self.assertIn("chore, docs", str(ctx.exception))
        self.assertIn("shad todo label add poc", str(ctx.exception))

    def test_check_labels_rejects_a_malformed_label(self) -> None:
        with self.assertRaises(ShadError):
            check_labels(["Bad Label"], ["bad-label"])


class OrderTests(unittest.TestCase):
    def test_statuses_are_declared_in_display_order(self) -> None:
        self.assertEqual(STATUSES, ("todo", "in-progress", "done", "wont-do"))

    def test_in_progress_sorts_first_and_unknown_status_before_everything(self) -> None:
        items = [
            Item(key="d", title="D", status="done"),
            Item(key="t", title="T", status="todo"),
            Item(key="w", title="W", status="wont-do"),
            Item(key="p", title="P", status="in-progress"),
            Item(key="x", title="X", status="bogus"),
        ]
        self.assertEqual([i.key for i in sorted(items, key=sort_key)], ["x", "p", "t", "d", "w"])

    def test_same_status_sorts_by_title_case_insensitively(self) -> None:
        items = [Item(key="b", title="beta", status="todo"), Item(key="a", title="Alpha", status="todo")]
        self.assertEqual([i.key for i in sorted(items, key=sort_key)], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
