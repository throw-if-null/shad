from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from shad.harness import Claude, Harnesses, _Record
from shad.sessions.live import collect, duplicates
from shad.sessions.model import Entry
from shad.sessions.testing import CFG, KB, SHAD, UUID_A, UUID_B, running
from shad.tmux import Tmux


def _record(session_id: str, **extra: object) -> _Record:
    fields: dict = {"name": None, "status": None, "status_since": None, "started": 0, **extra}
    return _Record(session_id=session_id, **fields)


class CollectTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.harnesses = Harnesses(Path("/home"))
        self.harnesses.claude.projects_dir = Path(self._tmp.name)

    def _collect(
        self,
        sessions: dict[str, list[str]],
        *,
        attached: set[str] | None = None,
        commands: dict[str, set[str]] | None = None,
        records: dict[str, _Record] | None = None,
    ):
        tmux = Mock(spec=Tmux)
        tmux.list_project_sessions.side_effect = lambda base: sessions.get(base, [])
        tmux.attached_sessions.return_value = attached or set()
        tmux.pane_commands.return_value = commands or {}
        with patch.object(
            Claude, "_process_record", autospec=True,
            side_effect=lambda self, name: (records or {}).get(name),
        ):
            return collect(CFG, tmux, self.harnesses)

    def test_lists_every_running_session_in_config_order(self) -> None:
        sessions = {"tin-shad": [f"tin-shad--cc-{UUID_A}"], "kb": ["kb--cc-fresh-9"]}
        found = self._collect(
            sessions,
            attached={f"tin-shad--cc-{UUID_A}"},
            commands={"kb--cc-fresh-9": {"claude", "bash"}, f"tin-shad--cc-{UUID_A}": {"bash"}},
            records={"kb--cc-fresh-9": _record(UUID_B, name="Netbird", status="idle", status_since=7)},
        )

        self.assertEqual(
            found,
            [
                running(
                    "kb--cc-fresh-9", KB, session_id=UUID_B, name="Netbird", status="idle",
                    status_since=7,
                ),
                running(f"tin-shad--cc-{UUID_A}", SHAD, attached=True, harness_running=False),
            ],
        )

    def test_entry_carries_what_the_snapshot_stores(self) -> None:
        live = running("kb--cc-x", KB, session_id=UUID_A, name="N", title="T", attached=True)
        self.assertEqual(
            live.entry,
            Entry(
                group=None, key="kb", harness="claude", session_id=UUID_A, attached=True,
                name="N", title="T",
            ),
        )

    def test_a_session_without_a_findable_conversation_has_none(self) -> None:
        (found,) = self._collect({"kb": ["kb--cc-fresh-9"]})
        self.assertIsNone(found.conversation)
        self.assertIsNone(found.entry.session_id)
        self.assertIsNone(found.unsupported)

    def test_a_bare_base_session_still_asks_the_harness(self) -> None:
        (found,) = self._collect({"kb": ["kb"]}, records={"kb": _record(UUID_A)})
        self.assertEqual(found.harness, "claude")
        assert found.conversation is not None
        self.assertEqual(found.conversation.id, UUID_A)

    def test_an_opencode_session_is_listed_but_unsupported(self) -> None:
        (found,) = self._collect({"kb": ["kb--oc-ses_1"]}, commands={"kb--oc-ses_1": {"opencode"}})
        self.assertEqual(found.harness, "opencode")
        self.assertIsNone(found.conversation)
        self.assertTrue(found.harness_running)
        self.assertEqual(found.unsupported, "the opencode harness is not supported")

    def test_nothing_running_is_empty(self) -> None:
        self.assertEqual(self._collect({}), [])


class DuplicatesTests(unittest.TestCase):
    def test_names_every_session_whose_conversation_is_held_twice(self) -> None:
        rows = [
            running("kb--cc-a", session_id=UUID_A),
            running("kb--cc-fresh-1", session_id=UUID_A),
            running("kb--cc-b", session_id=UUID_B),
            running("kb--cc-fresh-2", session_id=None),
            running("kb--cc-fresh-3", session_id=None),
        ]
        self.assertEqual(duplicates(rows), {"kb--cc-a", "kb--cc-fresh-1"})
