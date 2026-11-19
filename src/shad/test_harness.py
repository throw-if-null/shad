from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shad.harness import (
    Claude,
    Conversation,
    Harnesses,
    Opencode,
    Recorded,
    RunningSession,
    Target,
    Unreadable,
    fresh_target,
    harness_for_prefix,
    is_uuid,
    resume_target,
)

_UUID_A = "11111111-1111-4111-8111-111111111111"
_UUID_B = "22222222-2222-4222-8222-222222222222"


def _harnesses() -> Harnesses:
    return Harnesses(Path("/home"))


def _claude_at(projects_dir: Path) -> Claude:
    """A Claude whose transcript directory is *projects_dir* itself."""
    claude = Claude(Path("/home"))
    claude.projects_dir = projects_dir
    return claude


def _opencode_at(db_path: Path) -> Opencode:
    """An Opencode whose database is *db_path*."""
    opencode = Opencode(Path("/home"))
    opencode.db_path = db_path
    return opencode


def _record(
    pid: int, session_id: str, tmux: str | None, started: int = 0, **extra: object
) -> dict:
    record: dict = {"pid": pid, "sessionId": session_id, "startedAt": started, **extra}
    if tmux is not None:
        record["tmux"] = tmux
    return record


class ClaudeProcessRecordTests(unittest.TestCase):
    """live_conversation reads <home>/.claude/sessions/<pid>.json."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)
        self.claude = Claude(self.home)
        self.sessions_dir = self.claude.sessions_dir
        self.projects_dir = self.claude.projects_dir
        self.sessions_dir.mkdir(parents=True)
        self.projects_dir.mkdir(parents=True)
        self.alive: set[int] = set()
        patcher = patch("shad.harness._alive", side_effect=self.alive.__contains__)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _write(self, record: dict) -> None:
        (self.sessions_dir / f"{record['pid']}.json").write_text(json.dumps(record))

    def _running(self, tmux_session: str, key: str | None = "fresh-1") -> RunningSession:
        return RunningSession(tmux_session=tmux_session, key=key, project_path=Path("/p/kb"))

    def _live(self, tmux_session: str, key: str | None = "fresh-1") -> Conversation | None:
        return self.claude.live_conversation(self._running(tmux_session, key))

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
        claude = Claude(self.home / "absent")
        self.assertIsNone(claude.live_conversation(self._running("kb--cc-fresh-1")))


class ClaudeCommandTests(unittest.TestCase):
    def test_can_resume_requires_the_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            claude = Claude(Path(tmp))
            directory = claude.project_dir(Path("/p/kb"))
            directory.mkdir(parents=True)
            (directory / f"{_UUID_A}.jsonl").write_text("")
            self.assertTrue(claude.can_resume(Path("/p/kb"), _UUID_A))
            self.assertFalse(claude.can_resume(Path("/p/kb"), _UUID_B))
            self.assertFalse(claude.can_resume(Path("/p/other"), _UUID_A))

    def test_resume_command(self) -> None:
        claude = Claude(Path("/home"))
        self.assertEqual(claude.resume_command("claude", _UUID_A), f"claude --resume {_UUID_A}")

    def test_fresh_command_passes_a_chosen_id(self) -> None:
        claude = Claude(Path("/home"))
        self.assertEqual(claude.fresh_command("claude", _UUID_A), f"claude --session-id {_UUID_A}")
        self.assertEqual(claude.fresh_command("claude", None), "claude")

    def test_new_session_ids_are_distinct_uuids(self) -> None:
        claude = Claude(Path("/home"))
        first, second = claude.new_session_id(), claude.new_session_id()
        assert first is not None and second is not None
        self.assertTrue(is_uuid(first))
        self.assertNotEqual(first, second)


class TargetTests(unittest.TestCase):
    """The one place a harness's command lines are written."""

    def setUp(self) -> None:
        self.harnesses = _harnesses()

    def test_a_resumed_claude_conversation(self) -> None:
        self.assertEqual(
            resume_target(self.harnesses.known["claude"], "claude", _UUID_A),
            Target(command=f"claude --resume {_UUID_A}", session_key=_UUID_A, session_prefix="cc"),
        )

    def test_a_fresh_claude_conversation_runs_under_an_id_shad_chose(self) -> None:
        claude = self.harnesses.known["claude"]
        target = fresh_target(claude, "claude")
        assert target.session_key is not None
        self.assertTrue(is_uuid(target.session_key))
        self.assertEqual(target.command, f"claude --session-id {target.session_key}")
        self.assertTrue(target.fresh)
        self.assertEqual(target.session_prefix, "cc")
        self.assertNotEqual(target.session_key, fresh_target(claude, "claude").session_key)

    def test_a_resumed_opencode_session(self) -> None:
        self.assertEqual(
            resume_target(self.harnesses.known["opencode"], "opencode", "sess-1"),
            Target(command="opencode -s sess-1", session_key="sess-1", session_prefix="oc"),
        )

    def test_a_fresh_opencode_session_is_keyed_by_the_moment(self) -> None:
        target = fresh_target(self.harnesses.known["opencode"], "opencode")
        self.assertEqual(target.command, "opencode")
        assert target.session_key is not None
        self.assertTrue(target.session_key.startswith("fresh-"))
        self.assertTrue(target.fresh)
        self.assertEqual(target.session_prefix, "oc")


class RegistryTests(unittest.TestCase):
    def test_claude_is_supported_and_opencode_is_not(self) -> None:
        harnesses = _harnesses()
        self.assertIsInstance(harnesses.for_harness("claude"), Claude)
        self.assertIsNone(harnesses.for_harness("opencode"))
        self.assertIsInstance(harnesses.known["opencode"], Opencode)

    def test_prefixes_map_back_to_harness_names(self) -> None:
        self.assertEqual(harness_for_prefix("cc"), "claude")
        self.assertEqual(harness_for_prefix("oc"), "opencode")
        self.assertIsNone(harness_for_prefix("xx"))


# ---------------------------------------------------------------------------
# Opencode.recorded
# ---------------------------------------------------------------------------


def _opencode_schema(path: Path) -> None:
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE project (id TEXT PRIMARY KEY, worktree TEXT)")
    con.execute(
        "CREATE TABLE session "
        "(id TEXT PRIMARY KEY, project_id TEXT, title TEXT, "
        "time_updated INTEGER, time_archived INTEGER)"
    )
    con.commit()
    con.close()


class OpencodeRecordedTests(unittest.TestCase):
    def test_returns_empty_list_when_db_does_not_exist(self) -> None:
        result = _opencode_at(Path("/nonexistent/path/opencode.db")).recorded(Path("/tmp/project"))
        self.assertEqual(result, [])

    def test_raises_unreadable_on_db_error(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            f.write(b"not a valid sqlite database")
            bad_db = Path(f.name)
        try:
            with self.assertRaises(Unreadable) as ctx:
                _opencode_at(bad_db).recorded(Path("/tmp/project"))
            self.assertIn("could not read the opencode session database", str(ctx.exception))
        finally:
            bad_db.unlink(missing_ok=True)

    def test_returns_sessions_from_sqlite_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "opencode.db"
            _opencode_schema(db_path)
            con = sqlite3.connect(str(db_path))
            con.execute("INSERT INTO project VALUES ('proj-1', '/tmp/myproject')")
            con.execute(
                "INSERT INTO session VALUES ('sess-1', 'proj-1', 'My session', 1000000, NULL)"
            )
            con.commit()
            con.close()
            result = _opencode_at(db_path).recorded(Path("/tmp/myproject"))

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].id, "sess-1")
        self.assertEqual(result[0].title, "My session")
        self.assertEqual(result[0].updated, 1000000)

    def test_archived_sessions_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "opencode.db"
            _opencode_schema(db_path)
            con = sqlite3.connect(str(db_path))
            con.execute("INSERT INTO project VALUES ('proj-1', '/tmp/myproject')")
            con.execute("INSERT INTO session VALUES ('sess-active', 'proj-1', 'Active', 2000, NULL)")
            con.execute(
                "INSERT INTO session VALUES ('sess-archived', 'proj-1', 'Archived', 1000, 9999)"
            )
            con.commit()
            con.close()
            result = _opencode_at(db_path).recorded(Path("/tmp/myproject"))

        ids = [s.id for s in result]
        self.assertIn("sess-active", ids)
        self.assertNotIn("sess-archived", ids)


# ---------------------------------------------------------------------------
# Claude.project_dir / Claude.recorded
# ---------------------------------------------------------------------------


def _write_transcript(
    directory: Path, session_id: str, entries: list[dict], mtime: float
) -> Path:
    path = directory / f"{session_id}.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in entries))
    os.utime(path, (mtime, mtime))
    return path


def _user_entry(text: str, *, meta: bool = False) -> dict:
    entry: dict = {"type": "user", "message": {"role": "user", "content": text}}
    if meta:
        entry["isMeta"] = True
    return entry


class ClaudeProjectDirTests(unittest.TestCase):
    def test_path_separators_become_hyphens(self) -> None:
        result = Claude(Path("/home")).project_dir(Path("/var/home/me/src/tin/shad"))
        self.assertEqual(result.name, "-var-home-me-src-tin-shad")

    def test_dots_become_hyphens(self) -> None:
        result = Claude(Path("/home")).project_dir(Path("/home/me/.local/share/chezmoi"))
        self.assertEqual(result.name, "-home-me--local-share-chezmoi")


class ClaudeRecordedTests(unittest.TestCase):
    def test_returns_empty_list_when_directory_does_not_exist(self) -> None:
        result = _claude_at(Path("/nonexistent/claude/projects")).recorded(Path("/tmp/project"))
        self.assertEqual(result, [])

    def test_titles_sessions_with_the_first_real_user_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "-tmp-project"
            directory.mkdir()
            _write_transcript(
                directory,
                "sess-a",
                [
                    {"type": "mode", "mode": "normal"},
                    _user_entry("<local-command-caveat>Caveat: ...", meta=True),
                    _user_entry("<command-name>/clear</command-name>"),
                    _user_entry("Fix the login bug"),
                    _user_entry("and then the logout bug"),
                ],
                mtime=1000,
            )
            result = _claude_at(Path(tmp)).recorded(Path("/tmp/project"))

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].id, "sess-a")
        self.assertEqual(result[0].title, "Fix the login bug")
        self.assertEqual(result[0].updated, 1000 * 1000)

    def test_orders_sessions_newest_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "-tmp-project"
            directory.mkdir()
            _write_transcript(directory, "old", [_user_entry("older")], mtime=1000)
            _write_transcript(directory, "new", [_user_entry("newer")], mtime=2000)
            result = _claude_at(Path(tmp)).recorded(Path("/tmp/project"))

        self.assertEqual([s.id for s in result], ["new", "old"])

    def test_skips_transcripts_without_a_user_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "-tmp-project"
            directory.mkdir()
            _write_transcript(directory, "empty", [{"type": "mode", "mode": "normal"}], mtime=2000)
            _write_transcript(directory, "real", [_user_entry("a prompt")], mtime=1000)
            result = _claude_at(Path(tmp)).recorded(Path("/tmp/project"))

        self.assertEqual([s.id for s in result], ["real"])

    def test_honours_the_session_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "-tmp-project"
            directory.mkdir()
            for i in range(4):
                _write_transcript(directory, f"sess-{i}", [_user_entry(f"p{i}")], mtime=1000 + i)
            result = _claude_at(Path(tmp)).recorded(Path("/tmp/project"), limit=2)

        self.assertEqual([s.id for s in result], ["sess-3", "sess-2"])

    def test_reads_text_blocks_from_structured_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "-tmp-project"
            directory.mkdir()
            _write_transcript(
                directory,
                "sess-a",
                [
                    {
                        "type": "user",
                        "message": {
                            "role": "user",
                            "content": [
                                {"type": "image"},
                                {"type": "text", "text": "describe  this\nimage"},
                            ],
                        },
                    }
                ],
                mtime=1000,
            )
            result = _claude_at(Path(tmp)).recorded(Path("/tmp/project"))

        self.assertEqual(result[0].title, "describe this image")

    def _query_one(self, entries: list[dict]) -> Recorded:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "-tmp-project"
            directory.mkdir()
            _write_transcript(directory, "sess-a", entries, mtime=1000)
            [session] = _claude_at(Path(tmp)).recorded(Path("/tmp/project"))
        return session

    def test_names_a_session_with_its_last_custom_title(self) -> None:
        session = self._query_one([
            _user_entry("Fix the login bug"),
            {"type": "ai-title", "aiTitle": "Login bug fix"},
            {"type": "custom-title", "customTitle": "login"},
            {"type": "ai-title", "aiTitle": "Login bug fix"},
            {"type": "custom-title", "customTitle": "auth"},
        ])
        self.assertEqual(session.name, "auth")
        self.assertEqual(session.title, "Fix the login bug")

    def test_falls_back_to_the_last_ai_title(self) -> None:
        session = self._query_one([
            _user_entry("Fix the login bug"),
            {"type": "ai-title", "aiTitle": "Login bug"},
            {"type": "ai-title", "aiTitle": "Login bug fix"},
        ])
        self.assertEqual(session.name, "Login bug fix")

    def test_a_session_without_title_entries_has_no_name(self) -> None:
        session = self._query_one([_user_entry("Fix the login bug")])
        self.assertIsNone(session.name)
        self.assertEqual(session.title, "Fix the login bug")

    def test_reads_a_name_written_past_the_prompt_scan(self) -> None:
        # /rename appends its entry wherever the conversation is, so the name
        # scan cannot stop where the first-prompt scan does.
        filler = [{"type": "assistant", "message": {"content": "ok"}}] * 300
        session = self._query_one(
            [_user_entry("Fix the login bug"), *filler,
             {"type": "custom-title", "customTitle": "login"}]
        )
        self.assertEqual(session.name, "login")

    def test_a_line_that_is_not_an_object_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "-tmp-project"
            directory.mkdir()
            path = _write_transcript(directory, "sess-a", [_user_entry("hi")], mtime=1000)
            with path.open("a") as handle:
                handle.write('["ai-title"]\n')
            os.utime(path, (1000, 1000))
            [session] = _claude_at(Path(tmp)).recorded(Path("/tmp/project"))
        self.assertIsNone(session.name)

    def test_a_prompt_that_quotes_a_title_entry_is_not_a_name(self) -> None:
        session = self._query_one([
            _user_entry('why is there a "custom-title" entry in my transcript?'),
        ])
        self.assertIsNone(session.name)


if __name__ == "__main__":
    unittest.main()
