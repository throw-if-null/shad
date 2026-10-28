from __future__ import annotations

import json
import unittest

from shad.sessions.model import FORMAT, Entry, Snapshot, parse, serialize
from shad.shared.errors import ShadError

_ENTRIES = (
    Entry(
        group="tin", key="shad", harness="claude", session_id="uuid-a", attached=True,
        name="Releaser", title="first prompt",
    ),
    Entry(group=None, key="kb", harness="claude", session_id=None, attached=False),
)


class RoundTripTests(unittest.TestCase):
    def test_parse_inverts_serialize(self) -> None:
        snapshot = Snapshot(saved_at=1700000000, entries=_ENTRIES)
        self.assertEqual(parse(serialize(snapshot)), snapshot)

    def test_serialize_writes_the_format_and_one_object_per_entry(self) -> None:
        data = json.loads(serialize(Snapshot(saved_at=5, entries=_ENTRIES)))
        self.assertEqual(data["format"], FORMAT)
        self.assertEqual(data["saved_at"], 5)
        self.assertEqual(
            data["sessions"][0],
            {
                "group": "tin",
                "key": "shad",
                "harness": "claude",
                "session_id": "uuid-a",
                "attached": True,
                "name": "Releaser",
                "title": "first prompt",
            },
        )

    def test_display_name_joins_group_and_key(self) -> None:
        self.assertEqual(_ENTRIES[0].display_name, "tin shad")
        self.assertEqual(_ENTRIES[1].display_name, "kb")


class ParseRejectionTests(unittest.TestCase):
    def _rejects(self, text: str, fragment: str) -> None:
        with self.assertRaises(ShadError) as ctx:
            parse(text)
        self.assertIn(fragment, str(ctx.exception))

    def test_rejects_text_that_is_not_json(self) -> None:
        self._rejects("{", "not valid JSON")

    def test_rejects_a_non_object(self) -> None:
        self._rejects("[]", "not a JSON object")

    def test_rejects_an_unknown_format(self) -> None:
        self._rejects(json.dumps({"format": 99, "saved_at": 1, "sessions": []}), "format 99")

    def test_rejects_a_missing_timestamp(self) -> None:
        self._rejects(json.dumps({"format": FORMAT, "sessions": []}), "saved_at")

    def test_rejects_a_missing_sessions_list(self) -> None:
        self._rejects(json.dumps({"format": FORMAT, "saved_at": 1}), "sessions list")

    def test_rejects_an_entry_without_a_key(self) -> None:
        raw = {"format": FORMAT, "saved_at": 1, "sessions": [{"harness": "claude"}]}
        self._rejects(json.dumps(raw), "session 0 has no project key")

    def test_rejects_an_entry_without_a_harness(self) -> None:
        raw = {"format": FORMAT, "saved_at": 1, "sessions": [{"key": "kb"}]}
        self._rejects(json.dumps(raw), "no harness")

    def test_rejects_a_non_string_session_id(self) -> None:
        raw = {
            "format": FORMAT,
            "saved_at": 1,
            "sessions": [{"key": "kb", "harness": "claude", "session_id": 7}],
        }
        self._rejects(json.dumps(raw), "invalid session_id")

    def test_rejects_a_non_string_name_or_title(self) -> None:
        base = {"key": "kb", "harness": "claude"}
        for field in ("name", "title"):
            raw = {"format": FORMAT, "saved_at": 1, "sessions": [{**base, field: 1}]}
            self._rejects(json.dumps(raw), f"invalid {field}")

    def test_name_and_title_are_optional(self) -> None:
        raw = {"format": FORMAT, "saved_at": 1, "sessions": [{"key": "kb", "harness": "claude"}]}
        entry = parse(json.dumps(raw)).entries[0]
        self.assertEqual((entry.name, entry.title), (None, None))

    def test_attached_defaults_to_false(self) -> None:
        raw = {"format": FORMAT, "saved_at": 1, "sessions": [{"key": "kb", "harness": "claude"}]}
        self.assertFalse(parse(json.dumps(raw)).entries[0].attached)
