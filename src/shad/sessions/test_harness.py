from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shad.sessions import harness
from shad.sessions.harness import (
    Claude,
    RunningSession,
    for_harness,
    harness_for_prefix,
)

_UUID_A = "11111111-1111-4111-8111-111111111111"
_UUID_B = "22222222-2222-4222-8222-222222222222"


def _record(
    pid: int, session_id: str, tmux: str | None, started: int = 0, **extra: object
) -> dict:
    record: dict = {"pid": pid, "sessionId": session_id, "startedAt": started, **extra}
    if tmux is not None:
        record["tmux"] = tmux
    return record


class ClaudeProcessRecordTests(unittest.TestCase):
    """live_session_id reads ~/.claude/sessions/<pid>.json."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.sessions_dir = Path(self._tmp.name)
        self.alive: set[int] = set()
        patcher_dir = patch("shad.sessions.harness.CLAUDE_SESSIONS_DIR", self.sessions_dir)
        patcher_alive = patch("shad.sessions.harness._alive", side_effect=self.alive.__contains__)
        patcher_dir.start()
        patcher_alive.start()
        self.addCleanup(patcher_dir.stop)
        self.addCleanup(patcher_alive.stop)

    def _write(self, record: dict) -> None:
        (self.sessions_dir / f"{record['pid']}.json").write_text(json.dumps(record))

    def _running(self, tmux_session: str, key: str | None = "fresh-1") -> RunningSession:
        return RunningSession(tmux_session=tmux_session, key=key, project_path=Path("/p"))

    def test_reads_the_id_of_the_process_in_the_tmux_session(self) -> None:
        self._write(_record(10, _UUID_A, "kb--cc-fresh-1:@0.%0"))
        self.alive.add(10)
        self.assertEqual(Claude().live_session_id(self._running("kb--cc-fresh-1")), _UUID_A)

    def test_the_record_wins_over_the_id_in_the_tmux_name(self) -> None:
        """/clear and /resume move the process to another conversation."""
        self._write(_record(10, _UUID_B, f"kb--cc-{_UUID_A}:@0.%0"))
        self.alive.add(10)
        running = self._running(f"kb--cc-{_UUID_A}", key=_UUID_A)
        self.assertEqual(Claude().live_session_id(running), _UUID_B)

    def test_ignores_a_record_whose_process_has_exited(self) -> None:
        self._write(_record(10, _UUID_A, "kb--cc-fresh-1:@0.%0"))
        self.assertIsNone(Claude().live_session_id(self._running("kb--cc-fresh-1")))

    def test_ignores_records_of_other_tmux_sessions(self) -> None:
        self._write(_record(10, _UUID_A, "kb--cc-fresh-2:@0.%0"))
        self.alive.add(10)
        self.assertIsNone(Claude().live_session_id(self._running("kb--cc-fresh-1")))

    def test_the_later_start_wins_when_two_live_records_share_a_session(self) -> None:
        self._write(_record(10, _UUID_A, "kb--cc-x:@0.%0", started=100))
        self._write(_record(11, _UUID_B, "kb--cc-x:@0.%0", started=200))
        self.alive.update({10, 11})
        self.assertEqual(Claude().live_session_id(self._running("kb--cc-x")), _UUID_B)

    def test_skips_records_that_are_not_well_formed(self) -> None:
        (self.sessions_dir / "1.json").write_text("{")
        (self.sessions_dir / "2.json").write_text("[]")
        self._write(_record(3, "", "kb--cc-x:@0.%0"))
        self._write(_record(4, _UUID_A, None))
        self._write({"pid": "5", "sessionId": _UUID_A, "tmux": "kb--cc-x:@0.%0"})
        self.alive.update({3, 4, 5})
        self.assertIsNone(Claude().live_session_id(self._running("kb--cc-x")))

    def test_falls_back_to_a_uuid_in_the_tmux_name(self) -> None:
        running = self._running(f"kb--cc-{_UUID_A}", key=_UUID_A)
        self.assertEqual(Claude().live_session_id(running), _UUID_A)

    def test_a_fresh_key_is_not_an_id(self) -> None:
        self.assertIsNone(Claude().live_session_id(self._running("kb--cc-fresh-1")))

    def test_a_bare_base_session_has_no_id(self) -> None:
        self.assertIsNone(Claude().live_session_id(self._running("kb", key=None)))

    def test_a_missing_sessions_dir_is_empty(self) -> None:
        with patch("shad.sessions.harness.CLAUDE_SESSIONS_DIR", self.sessions_dir / "absent"):
            self.assertIsNone(Claude().live_session_id(self._running("kb--cc-fresh-1")))


class ClaudeCommandTests(unittest.TestCase):
    def test_can_resume_requires_the_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            projects = Path(tmp)
            (projects / "-p-kb").mkdir()
            (projects / "-p-kb" / f"{_UUID_A}.jsonl").write_text("")
            with patch("shad.projects.open.sessions.CLAUDE_PROJECTS_DIR", projects):
                self.assertTrue(Claude().can_resume(Path("/p/kb"), _UUID_A))
                self.assertFalse(Claude().can_resume(Path("/p/kb"), _UUID_B))
                self.assertFalse(Claude().can_resume(Path("/p/other"), _UUID_A))

    def test_resume_command(self) -> None:
        self.assertEqual(Claude().resume_command("claude", _UUID_A), f"claude --resume {_UUID_A}")

    def test_fresh_command_passes_a_chosen_id(self) -> None:
        self.assertEqual(
            Claude().fresh_command("claude", _UUID_A), f"claude --session-id {_UUID_A}"
        )
        self.assertEqual(Claude().fresh_command("claude", None), "claude")

    def test_new_session_ids_are_distinct_uuids(self) -> None:
        first, second = Claude().new_session_id(), Claude().new_session_id()
        assert first is not None and second is not None
        self.assertRegex(first, harness._UUID_RE)
        self.assertNotEqual(first, second)


class RegistryTests(unittest.TestCase):
    def test_claude_is_supported_and_opencode_is_not(self) -> None:
        self.assertIsInstance(for_harness("claude"), Claude)
        self.assertIsNone(for_harness("opencode"))

    def test_prefixes_map_back_to_harness_names(self) -> None:
        self.assertEqual(harness_for_prefix("cc"), "claude")
        self.assertEqual(harness_for_prefix("oc"), "opencode")
        self.assertIsNone(harness_for_prefix("xx"))
