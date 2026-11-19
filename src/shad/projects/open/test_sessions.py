from __future__ import annotations

import io
import json
import os
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from rich.console import Console

from shad.projects.open.sessions import (
    OcSession,
    OpencodeTarget,
    Unreadable,
    _query_claude_sessions,
    _query_sessions,
    _render_picker,
    _truncate,
    claude_project_dir,
    pick_claude_target,
    pick_opencode_target,
)

# ---------------------------------------------------------------------------
# pick_opencode_target
# ---------------------------------------------------------------------------


class PickOpencodeTargetTests(unittest.TestCase):
    def test_returns_fresh_target_when_no_sessions_exist(self) -> None:
        with patch("shad.projects.open.sessions._query_sessions", return_value=[]):
            target = pick_opencode_target(Path("/tmp/project"), "opencode")

        assert target is not None
        self.assertEqual(target.command, "opencode")
        self.assertTrue(target.fresh)
        assert target.session_key is not None
        self.assertTrue(target.session_key.startswith("fresh-"))

    def test_returns_session_scoped_target_for_existing_session(self) -> None:
        sessions = [OcSession(id="sess-123", title="Fix bug", time_updated=0)]

        with (
            patch("shad.projects.open.sessions._query_sessions", return_value=sessions),
            patch("shad.projects.open.sessions._run_picker", return_value=1),
        ):
            target = pick_opencode_target(Path("/tmp/project"), "opencode")

        self.assertEqual(
            target,
            OpencodeTarget(command="opencode -s sess-123", session_key="sess-123"),
        )

    def test_returns_fresh_target_when_new_session_selected(self) -> None:
        sessions = [OcSession(id="sess-123", title="Fix bug", time_updated=0)]

        with (
            patch("shad.projects.open.sessions._query_sessions", return_value=sessions),
            patch("shad.projects.open.sessions._run_picker", return_value=0),
        ):
            target = pick_opencode_target(Path("/tmp/project"), "opencode")

        assert target is not None
        self.assertEqual(target.command, "opencode")
        self.assertTrue(target.fresh)
        assert target.session_key is not None
        self.assertTrue(target.session_key.startswith("fresh-"))

    def test_returns_none_when_picker_cancelled(self) -> None:
        sessions = [OcSession(id="sess-123", title="Fix bug", time_updated=0)]

        with (
            patch("shad.projects.open.sessions._query_sessions", return_value=sessions),
            patch("shad.projects.open.sessions._run_picker", return_value=None),
        ):
            target = pick_opencode_target(Path("/tmp/project"), "opencode")

        self.assertIsNone(target)

    def test_an_unreadable_store_is_shown_in_the_picker(self) -> None:
        with (
            patch(
                "shad.projects.open.sessions._query_sessions",
                side_effect=Unreadable("could not read the opencode session database: boom"),
            ),
            patch("shad.projects.open.sessions._run_picker", return_value=0) as picker,
        ):
            target = pick_opencode_target(Path("/tmp/project"), "opencode")

        assert target is not None
        self.assertTrue(target.fresh)
        self.assertEqual(picker.call_args.args[0], [])
        self.assertIn("boom", picker.call_args.kwargs["note"])

    def test_returns_second_session_when_index_2_selected(self) -> None:
        s1 = OcSession(id="aaa", title="First", time_updated=1000)
        s2 = OcSession(id="bbb", title="Second", time_updated=2000)

        with (
            patch("shad.projects.open.sessions._query_sessions", return_value=[s1, s2]),
            patch("shad.projects.open.sessions._run_picker", return_value=2),
        ):
            target = pick_opencode_target(Path("/tmp/project"), "opencode")

        self.assertEqual(
            target, OpencodeTarget(command="opencode -s bbb", session_key="bbb")
        )


# ---------------------------------------------------------------------------
# OcSession properties
# ---------------------------------------------------------------------------


class OcSessionPropertiesTests(unittest.TestCase):
    def test_updated_str_formats_epoch_correctly(self) -> None:
        session = OcSession(id="x", title="t", time_updated=1705314600000)
        result = session.updated_str
        self.assertRegex(result, r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}")

    def test_display_title_returns_untitled_for_matching_pattern(self) -> None:
        session = OcSession(
            id="x",
            title="New session - 2024-01-15T10:30:00.000Z",
            time_updated=0,
        )
        self.assertEqual(session.display_title, "(untitled)")

    def test_display_title_returns_title_unchanged_for_normal_title(self) -> None:
        session = OcSession(id="x", title="Fix the login bug", time_updated=0)
        self.assertEqual(session.display_title, "Fix the login bug")

    def test_display_title_does_not_match_partial_pattern(self) -> None:
        title = "New session - 2024-01-15T10:30:00.000Z trailing text"
        session = OcSession(id="x", title=title, time_updated=0)
        self.assertEqual(session.display_title, title)


# ---------------------------------------------------------------------------
# _truncate
# ---------------------------------------------------------------------------


class TruncateTests(unittest.TestCase):
    def test_short_string_unchanged(self) -> None:
        self.assertEqual(_truncate("hello", 10), "hello")

    def test_string_at_max_len_unchanged(self) -> None:
        self.assertEqual(_truncate("hello", 5), "hello")

    def test_long_string_truncated_with_ellipsis(self) -> None:
        result = _truncate("hello world", 8)
        self.assertEqual(len(result), 8)
        self.assertTrue(result.endswith("…"))
        self.assertEqual(result, "hello w…")


# ---------------------------------------------------------------------------
# _query_sessions
# ---------------------------------------------------------------------------


class QuerySessionsTests(unittest.TestCase):
    def test_returns_empty_list_when_db_does_not_exist(self) -> None:
        with patch(
            "shad.projects.open.sessions.DB_PATH", Path("/nonexistent/path/opencode.db")
        ):
            result = _query_sessions(Path("/tmp/project"))
        self.assertEqual(result, [])

    def test_raises_unreadable_on_db_error(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            f.write(b"not a valid sqlite database")
            bad_db = Path(f.name)

        try:
            with (
                patch("shad.projects.open.sessions.DB_PATH", bad_db),
                self.assertRaises(Unreadable) as ctx,
            ):
                _query_sessions(Path("/tmp/project"))
            self.assertIn("could not read the opencode session database", str(ctx.exception))
        finally:
            bad_db.unlink(missing_ok=True)

    def test_returns_sessions_from_sqlite_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "opencode.db"
            con = sqlite3.connect(str(db_path))
            con.execute("CREATE TABLE project (id TEXT PRIMARY KEY, worktree TEXT)")
            con.execute(
                "CREATE TABLE session "
                "(id TEXT PRIMARY KEY, project_id TEXT, title TEXT, "
                "time_updated INTEGER, time_archived INTEGER)"
            )
            con.execute("INSERT INTO project VALUES ('proj-1', '/tmp/myproject')")
            con.execute(
                "INSERT INTO session VALUES "
                "('sess-1', 'proj-1', 'My session', 1000000, NULL)"
            )
            con.commit()
            con.close()

            with patch("shad.projects.open.sessions.DB_PATH", db_path):
                result = _query_sessions(Path("/tmp/myproject"))

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].id, "sess-1")
        self.assertEqual(result[0].title, "My session")
        self.assertEqual(result[0].time_updated, 1000000)

    def test_archived_sessions_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "opencode.db"
            con = sqlite3.connect(str(db_path))
            con.execute("CREATE TABLE project (id TEXT PRIMARY KEY, worktree TEXT)")
            con.execute(
                "CREATE TABLE session "
                "(id TEXT PRIMARY KEY, project_id TEXT, title TEXT, "
                "time_updated INTEGER, time_archived INTEGER)"
            )
            con.execute("INSERT INTO project VALUES ('proj-1', '/tmp/myproject')")
            con.execute(
                "INSERT INTO session VALUES "
                "('sess-active', 'proj-1', 'Active', 2000, NULL)"
            )
            con.execute(
                "INSERT INTO session VALUES "
                "('sess-archived', 'proj-1', 'Archived', 1000, 9999)"
            )
            con.commit()
            con.close()

            with patch("shad.projects.open.sessions.DB_PATH", db_path):
                result = _query_sessions(Path("/tmp/myproject"))

        ids = [s.id for s in result]
        self.assertIn("sess-active", ids)
        self.assertNotIn("sess-archived", ids)


# ---------------------------------------------------------------------------
# claude_project_dir / _query_claude_sessions
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
        with patch(
            "shad.projects.open.sessions.CLAUDE_PROJECTS_DIR", Path("/projects")
        ):
            result = claude_project_dir(Path("/var/home/me/src/tin/shad"))
        self.assertEqual(result.name, "-var-home-me-src-tin-shad")

    def test_dots_become_hyphens(self) -> None:
        with patch(
            "shad.projects.open.sessions.CLAUDE_PROJECTS_DIR", Path("/projects")
        ):
            result = claude_project_dir(Path("/home/me/.local/share/chezmoi"))
        self.assertEqual(result.name, "-home-me--local-share-chezmoi")


class QueryClaudeSessionsTests(unittest.TestCase):
    def test_returns_empty_list_when_directory_does_not_exist(self) -> None:
        with patch(
            "shad.projects.open.sessions.CLAUDE_PROJECTS_DIR",
            Path("/nonexistent/claude/projects"),
        ):
            result = _query_claude_sessions(Path("/tmp/project"))
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
            with patch(
                "shad.projects.open.sessions.CLAUDE_PROJECTS_DIR", Path(tmp)
            ):
                result = _query_claude_sessions(Path("/tmp/project"))

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].id, "sess-a")
        self.assertEqual(result[0].title, "Fix the login bug")
        self.assertEqual(result[0].time_updated, 1000 * 1000)

    def test_orders_sessions_newest_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "-tmp-project"
            directory.mkdir()
            _write_transcript(directory, "old", [_user_entry("older")], mtime=1000)
            _write_transcript(directory, "new", [_user_entry("newer")], mtime=2000)
            with patch(
                "shad.projects.open.sessions.CLAUDE_PROJECTS_DIR", Path(tmp)
            ):
                result = _query_claude_sessions(Path("/tmp/project"))

        self.assertEqual([s.id for s in result], ["new", "old"])

    def test_skips_transcripts_without_a_user_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "-tmp-project"
            directory.mkdir()
            _write_transcript(
                directory,
                "empty",
                [{"type": "mode", "mode": "normal"}],
                mtime=2000,
            )
            _write_transcript(directory, "real", [_user_entry("a prompt")], mtime=1000)
            with patch(
                "shad.projects.open.sessions.CLAUDE_PROJECTS_DIR", Path(tmp)
            ):
                result = _query_claude_sessions(Path("/tmp/project"))

        self.assertEqual([s.id for s in result], ["real"])

    def test_honours_the_session_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "-tmp-project"
            directory.mkdir()
            for i in range(4):
                _write_transcript(
                    directory, f"sess-{i}", [_user_entry(f"p{i}")], mtime=1000 + i
                )
            with patch(
                "shad.projects.open.sessions.CLAUDE_PROJECTS_DIR", Path(tmp)
            ):
                result = _query_claude_sessions(Path("/tmp/project"), limit=2)

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
            with patch(
                "shad.projects.open.sessions.CLAUDE_PROJECTS_DIR", Path(tmp)
            ):
                result = _query_claude_sessions(Path("/tmp/project"))

        self.assertEqual(result[0].title, "describe this image")

    def _query_one(self, entries: list[dict]) -> OcSession:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "-tmp-project"
            directory.mkdir()
            _write_transcript(directory, "sess-a", entries, mtime=1000)
            with patch(
                "shad.projects.open.sessions.CLAUDE_PROJECTS_DIR", Path(tmp)
            ):
                [session] = _query_claude_sessions(Path("/tmp/project"))
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
            with patch("shad.projects.open.sessions.CLAUDE_PROJECTS_DIR", Path(tmp)):
                [session] = _query_claude_sessions(Path("/tmp/project"))
        self.assertIsNone(session.name)

    def test_a_prompt_that_quotes_a_title_entry_is_not_a_name(self) -> None:
        session = self._query_one([
            _user_entry('why is there a "custom-title" entry in my transcript?'),
        ])
        self.assertIsNone(session.name)


class RenderPickerTests(unittest.TestCase):
    @staticmethod
    def _text(sessions: list[OcSession], width: int = 120) -> str:
        console = Console(record=True, width=width, file=io.StringIO())
        console.print(_render_picker(sessions, 0, "portal", "claude"))
        return console.export_text()

    def test_a_named_session_shows_its_name_and_its_first_prompt(self) -> None:
        text = self._text([
            OcSession(id="a", title="I want to finish the docs hub", time_updated=0,
                      name="docs-hub"),
        ])
        row = next(line for line in text.splitlines() if "docs-hub" in line)
        self.assertIn("I want to finish the docs hub", row)
        self.assertLess(row.index("docs-hub"), row.index("I want"))

    def test_names_line_up_in_one_column(self) -> None:
        text = self._text([
            OcSession(id="a", title="first prompt", time_updated=0, name="docs-hub"),
            OcSession(id="b", title="second prompt", time_updated=0,
                      name="A much longer generated session name than fits"),
        ])
        rows = [line for line in text.splitlines() if "prompt" in line]
        self.assertEqual(rows[0].index("first"), rows[1].index("second"))

    def test_an_unnamed_session_shows_only_its_first_prompt(self) -> None:
        text = self._text([OcSession(id="a", title="Fix the login bug", time_updated=0)])
        self.assertIn("Fix the login bug", text)

    def test_a_row_wider_than_the_terminal_is_cropped_not_wrapped(self) -> None:
        text = self._text([
            OcSession(id="a", title="p" * 60, time_updated=0, name="n" * 40),
        ], width=80)
        # A wrapped row would continue on a line of its own, without the name.
        rows = [line for line in text.splitlines() if "ppp" in line]
        self.assertEqual(len(rows), 1)
        self.assertIn("nnn", rows[0])
        self.assertIn("…", rows[0])


# ---------------------------------------------------------------------------
# pick_claude_target
# ---------------------------------------------------------------------------


class PickClaudeTargetTests(unittest.TestCase):
    def test_returns_fresh_target_when_no_sessions_exist(self) -> None:
        with patch(
            "shad.projects.open.sessions._query_claude_sessions", return_value=[]
        ):
            target = pick_claude_target(Path("/tmp/project"), "claude")

        assert target is not None
        self.assertTrue(target.fresh)
        self.assertEqual(target.session_prefix, "cc")
        assert target.session_key is not None
        uuid.UUID(target.session_key)  # the key is the conversation id shad chose
        self.assertEqual(target.command, f"claude --session-id {target.session_key}")

    def test_resumed_sessions_get_distinct_session_keys(self) -> None:
        sessions = [
            OcSession(id="uuid-a", title="First", time_updated=2000),
            OcSession(id="uuid-b", title="Second", time_updated=1000),
        ]

        targets = []
        for chosen in (1, 2):
            with (
                patch(
                    "shad.projects.open.sessions._query_claude_sessions",
                    return_value=sessions,
                ),
                patch(
                    "shad.projects.open.sessions._run_picker", return_value=chosen
                ),
            ):
                targets.append(pick_claude_target(Path("/tmp/project"), "claude"))

        self.assertEqual(
            targets,
            [
                OpencodeTarget(
                    command="claude --resume uuid-a",
                    session_key="uuid-a",
                    session_prefix="cc",
                ),
                OpencodeTarget(
                    command="claude --resume uuid-b",
                    session_key="uuid-b",
                    session_prefix="cc",
                ),
            ],
        )

    def test_returns_fresh_target_when_new_session_selected(self) -> None:
        sessions = [OcSession(id="uuid-a", title="First", time_updated=0)]

        with (
            patch(
                "shad.projects.open.sessions._query_claude_sessions",
                return_value=sessions,
            ),
            patch("shad.projects.open.sessions._run_picker", return_value=0),
        ):
            target = pick_claude_target(Path("/tmp/project"), "claude")

        assert target is not None
        self.assertTrue(target.fresh)
        self.assertEqual(target.session_prefix, "cc")
        assert target.session_key is not None
        uuid.UUID(target.session_key)
        self.assertEqual(target.command, f"claude --session-id {target.session_key}")

    def test_fresh_targets_get_distinct_session_keys(self) -> None:
        with patch(
            "shad.projects.open.sessions._query_claude_sessions", return_value=[]
        ):
            first = pick_claude_target(Path("/tmp/project"), "claude")
            second = pick_claude_target(Path("/tmp/project"), "claude")

        assert first is not None and second is not None
        self.assertNotEqual(first.session_key, second.session_key)

    def test_returns_none_when_picker_cancelled(self) -> None:
        sessions = [OcSession(id="uuid-a", title="First", time_updated=0)]

        with (
            patch(
                "shad.projects.open.sessions._query_claude_sessions",
                return_value=sessions,
            ),
            patch("shad.projects.open.sessions._run_picker", return_value=None),
        ):
            target = pick_claude_target(Path("/tmp/project"), "claude")

        self.assertIsNone(target)




if __name__ == "__main__":
    unittest.main()
