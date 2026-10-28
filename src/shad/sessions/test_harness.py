from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shad.sessions import harness
from shad.sessions.harness import (
    Claude,
    Conversation,
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
    """live_conversation reads ~/.claude/sessions/<pid>.json."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.sessions_dir = root / "sessions"
        self.sessions_dir.mkdir()
        self.projects_dir = root / "projects"
        self.projects_dir.mkdir()
        self.alive: set[int] = set()
        for patcher in (
            patch("shad.sessions.harness.CLAUDE_SESSIONS_DIR", self.sessions_dir),
            patch("shad.sessions.harness._alive", side_effect=self.alive.__contains__),
            patch("shad.projects.open.sessions.CLAUDE_PROJECTS_DIR", self.projects_dir),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _write(self, record: dict) -> None:
        (self.sessions_dir / f"{record['pid']}.json").write_text(json.dumps(record))

    def _running(self, tmux_session: str, key: str | None = "fresh-1") -> RunningSession:
        return RunningSession(tmux_session=tmux_session, key=key, project_path=Path("/p/kb"))

    def _live(self, tmux_session: str, key: str | None = "fresh-1") -> Conversation | None:
        return Claude().live_conversation(self._running(tmux_session, key))

    def test_reads_the_conversation_of_the_process_in_the_tmux_session(self) -> None:
        self._write(
            _record(
                10,
                _UUID_A,
                "kb--cc-fresh-1:@0.%0",
                name="  RELEASER   WORKFLOW ",
                status="idle",
                statusUpdatedAt=1_700_000_000_500,
            )
        )
        self.alive.add(10)
        self.assertEqual(
            self._live("kb--cc-fresh-1"),
            Conversation(
                id=_UUID_A, name="RELEASER WORKFLOW", status="idle", status_since=1_700_000_000
            ),
        )

    def test_status_since_falls_back_to_updated_at(self) -> None:
        self._write(_record(10, _UUID_A, "kb--cc-x:@0.%0", status="busy", updatedAt=5_000))
        self.alive.add(10)
        live = self._live("kb--cc-x")
        assert live is not None
        self.assertEqual((live.status, live.status_since), ("busy", 5))

    def test_reads_the_first_prompt_as_the_title(self) -> None:
        self._write(_record(10, _UUID_A, "kb--cc-x:@0.%0"))
        self.alive.add(10)
        transcript_dir = self.projects_dir / "-p-kb"
        transcript_dir.mkdir()
        entry = {"type": "user", "message": {"role": "user", "content": "Fix the  panel"}}
        (transcript_dir / f"{_UUID_A}.jsonl").write_text(json.dumps(entry) + "\n")
        live = self._live("kb--cc-x")
        assert live is not None
        self.assertEqual(live.title, "Fix the panel")

    def test_the_record_wins_over_the_id_in_the_tmux_name(self) -> None:
        """/clear and /resume move the process to another conversation."""
        self._write(_record(10, _UUID_B, f"kb--cc-{_UUID_A}:@0.%0"))
        self.alive.add(10)
        live = self._live(f"kb--cc-{_UUID_A}", key=_UUID_A)
        assert live is not None
        self.assertEqual(live.id, _UUID_B)

    def test_ignores_a_record_whose_process_has_exited(self) -> None:
        self._write(_record(10, _UUID_A, "kb--cc-fresh-1:@0.%0"))
        self.assertIsNone(self._live("kb--cc-fresh-1"))

    def test_ignores_records_of_other_tmux_sessions(self) -> None:
        self._write(_record(10, _UUID_A, "kb--cc-fresh-2:@0.%0"))
        self.alive.add(10)
        self.assertIsNone(self._live("kb--cc-fresh-1"))

    def test_the_later_start_wins_when_two_live_records_share_a_session(self) -> None:
        self._write(_record(10, _UUID_A, "kb--cc-x:@0.%0", started=100))
        self._write(_record(11, _UUID_B, "kb--cc-x:@0.%0", started=200))
        self.alive.update({10, 11})
        live = self._live("kb--cc-x")
        assert live is not None
        self.assertEqual(live.id, _UUID_B)

    def test_skips_records_that_are_not_well_formed(self) -> None:
        (self.sessions_dir / "1.json").write_text("{")
        (self.sessions_dir / "2.json").write_text("[]")
        self._write(_record(3, "", "kb--cc-x:@0.%0"))
        self._write(_record(4, _UUID_A, None))
        self._write({"pid": "5", "sessionId": _UUID_A, "tmux": "kb--cc-x:@0.%0"})
        self.alive.update({3, 4, 5})
        self.assertIsNone(self._live("kb--cc-x"))

    def test_odd_optional_fields_are_dropped_not_fatal(self) -> None:
        self._write(
            _record(10, _UUID_A, "kb--cc-x:@0.%0", name="  ", status=3, statusUpdatedAt=True)
        )
        self.alive.add(10)
        self.assertEqual(self._live("kb--cc-x"), Conversation(id=_UUID_A))

    def test_falls_back_to_a_uuid_in_the_tmux_name(self) -> None:
        self.assertEqual(self._live(f"kb--cc-{_UUID_A}", key=_UUID_A), Conversation(id=_UUID_A))

    def test_a_fresh_key_is_not_an_id(self) -> None:
        self.assertIsNone(self._live("kb--cc-fresh-1"))

    def test_a_bare_base_session_has_no_fallback(self) -> None:
        self.assertIsNone(self._live("kb", key=None))

    def test_a_missing_sessions_dir_is_empty(self) -> None:
        with patch("shad.sessions.harness.CLAUDE_SESSIONS_DIR", self.sessions_dir / "absent"):
            self.assertIsNone(self._live("kb--cc-fresh-1"))


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
