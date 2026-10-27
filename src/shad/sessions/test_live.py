from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from shad.sessions.live import collect
from shad.sessions.model import Entry
from shad.shared.config import Config, Defaults, Project

_UUID_A = "11111111-1111-4111-8111-111111111111"
_UUID_B = "22222222-2222-4222-8222-222222222222"

_KB = Project(key="kb", group=None, path=Path("/p/kb"), session="kb", harness="claude")
_SHAD = Project(key="shad", group="tin", path=Path("/p/shad"), session="tin-shad", harness="claude")
_CFG = Config(defaults=Defaults(), projects={"kb": _KB}, groups={"tin": {"shad": _SHAD}})


class CollectTests(unittest.TestCase):
    def _collect(
        self,
        running: dict[str, list[str]],
        attached: set[str] = frozenset(),  # type: ignore[assignment]
        records: dict[str, str] | None = None,
    ):
        with (
            patch("shad.sessions.live.list_project_sessions", side_effect=lambda b: running.get(b, [])),
            patch("shad.sessions.live.attached_sessions", return_value=set(attached)),
            patch(
                "shad.sessions.harness._claude_process_session",
                side_effect=lambda name: (records or {}).get(name),
            ),
        ):
            return collect(_CFG)

    def test_records_every_running_session_in_config_order(self) -> None:
        running = {"tin-shad": [f"tin-shad--cc-{_UUID_A}"], "kb": ["kb--cc-fresh-9"]}
        collected = self._collect(
            running, attached={f"tin-shad--cc-{_UUID_A}"}, records={"kb--cc-fresh-9": _UUID_B}
        )

        self.assertEqual(
            collected.entries,
            [
                Entry(group=None, key="kb", harness="claude", session_id=_UUID_B, attached=False),
                Entry(group="tin", key="shad", harness="claude", session_id=_UUID_A, attached=True),
            ],
        )
        self.assertEqual(collected.skipped, [])
        self.assertEqual(
            [running.session for running in collected.running],
            ["kb--cc-fresh-9", f"tin-shad--cc-{_UUID_A}"],
        )

    def test_a_session_without_a_findable_id_is_kept_without_one(self) -> None:
        collected = self._collect({"kb": ["kb--cc-fresh-9"]})
        self.assertEqual(
            collected.entries,
            [Entry(group=None, key="kb", harness="claude", session_id=None, attached=False)],
        )

    def test_a_bare_base_session_uses_the_configured_harness(self) -> None:
        collected = self._collect({"kb": ["kb"]}, attached={"kb"})
        self.assertEqual(
            collected.entries,
            [Entry(group=None, key="kb", harness="claude", session_id=None, attached=True)],
        )

    def test_an_opencode_session_is_skipped_with_the_reason(self) -> None:
        collected = self._collect({"kb": ["kb--oc-ses_1"]})
        self.assertEqual(collected.entries, [])
        self.assertEqual(len(collected.skipped), 1)
        self.assertEqual(collected.skipped[0].session, "kb--oc-ses_1")
        self.assertEqual(collected.skipped[0].project, _KB)
        self.assertIn("opencode harness is not supported", collected.skipped[0].reason)

    def test_nothing_running_is_empty(self) -> None:
        collected = self._collect({})
        self.assertEqual((collected.entries, collected.skipped), ([], []))
