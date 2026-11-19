from __future__ import annotations

import tomllib
import unittest

from shad.config.toml_edit import (
    format_key,
    format_value,
    remove_path,
    set_value,
    split_dotted,
)
from shad.errors import ShadError


class SplitDottedTests(unittest.TestCase):
    def test_plain_segments(self) -> None:
        self.assertEqual(split_dotted("projects.alvr.db.path"), ["projects", "alvr", "db", "path"])

    def test_quoted_segment_keeps_dots(self) -> None:
        self.assertEqual(split_dotted('projects."my.app".path'), ["projects", "my.app", "path"])

    def test_empty_segment_rejected(self) -> None:
        with self.assertRaises(ShadError):
            split_dotted("projects..path")

    def test_unterminated_quote_rejected(self) -> None:
        with self.assertRaises(ShadError):
            split_dotted('projects."broken')


class FormattingTests(unittest.TestCase):
    def test_format_key_quotes_non_bare_segments(self) -> None:
        self.assertEqual(format_key(["projects", "my.app"]), 'projects."my.app"')

    def test_format_value_by_type(self) -> None:
        self.assertEqual(format_value(35), "35")
        self.assertEqual(format_value(True), "true")
        self.assertEqual(format_value("/tmp/kb"), '"/tmp/kb"')
        self.assertEqual(format_value('say "hi"'), '"say \\"hi\\""')


class SetValueTests(unittest.TestCase):
    def test_existing_key_keeps_alignment_and_comment(self) -> None:
        text = '[defaults]\npanel_percent = 35  # bundle width\n'
        result = set_value(text, ["defaults", "panel_percent"], "42")
        self.assertEqual(result, '[defaults]\npanel_percent = 42  # bundle width\n')

    def test_new_key_lands_after_last_key_not_after_comments(self) -> None:
        text = (
            "[defaults]\n"
            'oc_position = "top"\n'
            "\n"
            "# ── projects ──\n"
            "\n"
            "[projects.kb]\n"
            'path = "/tmp/kb"\n'
        )
        result = set_value(text, ["defaults", "harness"], '"claude"')
        self.assertEqual(
            result,
            "[defaults]\n"
            'oc_position = "top"\n'
            'harness = "claude"\n'
            "\n"
            "# ── projects ──\n"
            "\n"
            "[projects.kb]\n"
            'path = "/tmp/kb"\n',
        )

    def test_key_in_empty_table_lands_after_header(self) -> None:
        text = "[defaults]\n# only comments here\n"
        result = set_value(text, ["defaults", "harness"], '"claude"')
        self.assertEqual(result, '[defaults]\nharness = "claude"\n# only comments here\n')

    def test_missing_table_is_appended(self) -> None:
        text = '[defaults]\nharness = "claude"\n'
        result = set_value(text, ["projects", "kb", "path"], '"/tmp/kb"')
        self.assertEqual(
            result,
            '[defaults]\nharness = "claude"\n\n[projects.kb]\npath = "/tmp/kb"\n',
        )
        self.assertEqual(tomllib.loads(result)["projects"]["kb"]["path"], "/tmp/kb")

    def test_dotted_key_in_parent_table_is_updated_in_place(self) -> None:
        text = '[projects]\nkb.path = "/tmp/old"\n'
        result = set_value(text, ["projects", "kb", "path"], '"/tmp/new"')
        self.assertEqual(result, '[projects]\nkb.path = "/tmp/new"\n')

    def test_commented_out_key_is_not_treated_as_existing(self) -> None:
        text = '[projects.kb]\npath = "/tmp/kb"\n# session = "kb"\n'
        result = set_value(text, ["projects", "kb", "session"], '"knowledge"')
        self.assertEqual(
            result,
            '[projects.kb]\npath = "/tmp/kb"\nsession = "knowledge"\n# session = "kb"\n',
        )

    def test_multiline_value_is_rejected(self) -> None:
        text = "[defaults]\nnames = [\n  1,\n  2,\n]\n"
        with self.assertRaises(ShadError) as ctx:
            set_value(text, ["defaults", "names"], "3")
        self.assertIn("multi-line value", str(ctx.exception))

    def test_key_without_table_is_rejected(self) -> None:
        with self.assertRaises(ShadError):
            set_value("", ["harness"], '"claude"')

    def test_empty_file_gets_a_table(self) -> None:
        result = set_value("", ["defaults", "harness"], '"claude"')
        self.assertEqual(result, '[defaults]\nharness = "claude"\n')


class RemovePathTests(unittest.TestCase):
    def test_removes_single_key(self) -> None:
        text = '[projects.kb]\npath = "/tmp/kb"\nsession = "kb"\n'
        result = remove_path(text, ["projects", "kb", "session"])
        self.assertEqual(result, '[projects.kb]\npath = "/tmp/kb"\n')

    def test_removes_table_and_subtables(self) -> None:
        text = (
            "[defaults]\n"
            'harness = "claude"\n'
            "\n"
            "[projects.alvr.db]\n"
            'path = "/tmp/db"\n'
            "\n"
            "[projects.alvr.kb]\n"
            'path = "/tmp/kb"\n'
            "\n"
            "[projects.orfe]\n"
            'path = "/tmp/orfe"\n'
        )
        result = remove_path(text, ["projects", "alvr"])
        self.assertNotIn("alvr", result)
        parsed = tomllib.loads(result)
        self.assertEqual(list(parsed["projects"]), ["orfe"])

    def test_unknown_key_raises(self) -> None:
        with self.assertRaises(ShadError) as ctx:
            remove_path('[defaults]\nharness = "claude"\n', ["defaults", "nope"])
        self.assertIn("key not found", str(ctx.exception))


class ArrayValueTests(unittest.TestCase):
    def test_format_value_renders_a_list_on_one_line(self) -> None:
        self.assertEqual(format_value(["a", "b c", 'q"x']), '["a", "b c", "q\\"x"]')
        self.assertEqual(format_value([]), "[]")
        self.assertEqual(format_value([1, True]), "[1, true]")

    def test_set_value_replaces_an_existing_single_line_array(self) -> None:
        text = '[todo]\nlabels = ["a"]   # keep\n'
        result = set_value(text, ["todo", "labels"], format_value(["a", "b"]))
        self.assertEqual(result, '[todo]\nlabels = ["a", "b"]   # keep\n')

    def test_set_value_still_rejects_a_multi_line_array(self) -> None:
        text = '[todo]\nlabels = [\n  "a",\n]\n'
        with self.assertRaises(ShadError):
            set_value(text, ["todo", "labels"], "[]")
