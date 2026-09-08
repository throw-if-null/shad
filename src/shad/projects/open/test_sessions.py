from __future__ import annotations

import sqlite3
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

from shad.projects.open.sessions import (
    OcSession,
    OpencodeTarget,
    _query_sessions,
    _truncate,
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

    def test_returns_empty_list_and_warns_on_db_error(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            f.write(b"not a valid sqlite database")
            bad_db = Path(f.name)

        try:
            with (
                patch("shad.projects.open.sessions.DB_PATH", bad_db),
                warnings.catch_warnings(record=True) as caught,
            ):
                warnings.simplefilter("always")
                result = _query_sessions(Path("/tmp/project"))

            self.assertEqual(result, [])
            self.assertTrue(
                any(
                    "could not read opencode session DB" in str(w.message)
                    for w in caught
                ),
                "Expected a warning about the DB",
            )
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


if __name__ == "__main__":
    unittest.main()
