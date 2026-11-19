from __future__ import annotations

import io
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from rich.console import Console

from shad.harness import Harnesses, Recorded, Target, Unreadable
from shad.projects.open.sessions import (
    _render_picker,
    _truncate,
    display_title,
    pick_target,
    updated_str,
)

_HARNESSES = Harnesses(Path("/home"))
_OPENCODE = _HARNESSES.known["opencode"]
_CLAUDE = _HARNESSES.known["claude"]

# ---------------------------------------------------------------------------
# pick_opencode_target
# ---------------------------------------------------------------------------


class PickOpencodeTargetTests(unittest.TestCase):
    def test_returns_fresh_target_when_no_sessions_exist(self) -> None:
        with patch("shad.harness.Opencode.recorded", return_value=[]):
            target = pick_target(_OPENCODE, Path("/tmp/project"), "opencode")

        assert target is not None
        self.assertEqual(target.command, "opencode")
        self.assertTrue(target.fresh)
        assert target.session_key is not None
        self.assertTrue(target.session_key.startswith("fresh-"))

    def test_returns_session_scoped_target_for_existing_session(self) -> None:
        sessions = [Recorded(id="sess-123", title="Fix bug", updated=0)]

        with (
            patch("shad.harness.Opencode.recorded", return_value=sessions),
            patch("shad.projects.open.sessions._run_picker", return_value=1),
        ):
            target = pick_target(_OPENCODE, Path("/tmp/project"), "opencode")

        self.assertEqual(
            target,
            Target(command="opencode -s sess-123", session_key="sess-123"),
        )

    def test_returns_fresh_target_when_new_session_selected(self) -> None:
        sessions = [Recorded(id="sess-123", title="Fix bug", updated=0)]

        with (
            patch("shad.harness.Opencode.recorded", return_value=sessions),
            patch("shad.projects.open.sessions._run_picker", return_value=0),
        ):
            target = pick_target(_OPENCODE, Path("/tmp/project"), "opencode")

        assert target is not None
        self.assertEqual(target.command, "opencode")
        self.assertTrue(target.fresh)
        assert target.session_key is not None
        self.assertTrue(target.session_key.startswith("fresh-"))

    def test_returns_none_when_picker_cancelled(self) -> None:
        sessions = [Recorded(id="sess-123", title="Fix bug", updated=0)]

        with (
            patch("shad.harness.Opencode.recorded", return_value=sessions),
            patch("shad.projects.open.sessions._run_picker", return_value=None),
        ):
            target = pick_target(_OPENCODE, Path("/tmp/project"), "opencode")

        self.assertIsNone(target)

    def test_an_unreadable_store_is_shown_in_the_picker(self) -> None:
        with (
            patch(
                "shad.harness.Opencode.recorded",
                side_effect=Unreadable("could not read the opencode session database: boom"),
            ),
            patch("shad.projects.open.sessions._run_picker", return_value=0) as picker,
        ):
            target = pick_target(_OPENCODE, Path("/tmp/project"), "opencode")

        assert target is not None
        self.assertTrue(target.fresh)
        self.assertEqual(picker.call_args.args[0], [])
        self.assertIn("boom", picker.call_args.kwargs["note"])

    def test_returns_second_session_when_index_2_selected(self) -> None:
        s1 = Recorded(id="aaa", title="First", updated=1000)
        s2 = Recorded(id="bbb", title="Second", updated=2000)

        with (
            patch("shad.harness.Opencode.recorded", return_value=[s1, s2]),
            patch("shad.projects.open.sessions._run_picker", return_value=2),
        ):
            target = pick_target(_OPENCODE, Path("/tmp/project"), "opencode")

        self.assertEqual(
            target, Target(command="opencode -s bbb", session_key="bbb")
        )


# ---------------------------------------------------------------------------
# how a recorded session is shown
# ---------------------------------------------------------------------------


class PresentationTests(unittest.TestCase):
    def test_updated_str_formats_epoch_correctly(self) -> None:
        session = Recorded(id="x", title="t", updated=1705314600000)
        self.assertRegex(updated_str(session), r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}")

    def test_display_title_returns_untitled_for_matching_pattern(self) -> None:
        session = Recorded(id="x", title="New session - 2024-01-15T10:30:00.000Z", updated=0)
        self.assertEqual(display_title(session), "(untitled)")

    def test_display_title_returns_title_unchanged_for_normal_title(self) -> None:
        session = Recorded(id="x", title="Fix the login bug", updated=0)
        self.assertEqual(display_title(session), "Fix the login bug")

    def test_display_title_does_not_match_partial_pattern(self) -> None:
        title = "New session - 2024-01-15T10:30:00.000Z trailing text"
        session = Recorded(id="x", title=title, updated=0)
        self.assertEqual(display_title(session), title)


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


class RenderPickerTests(unittest.TestCase):
    @staticmethod
    def _text(sessions: list[Recorded], width: int = 120) -> str:
        console = Console(record=True, width=width, file=io.StringIO())
        console.print(_render_picker(sessions, 0, "portal", "claude"))
        return console.export_text()

    def test_a_named_session_shows_its_name_and_its_first_prompt(self) -> None:
        text = self._text([
            Recorded(id="a", title="I want to finish the docs hub", updated=0,
                      name="docs-hub"),
        ])
        row = next(line for line in text.splitlines() if "docs-hub" in line)
        self.assertIn("I want to finish the docs hub", row)
        self.assertLess(row.index("docs-hub"), row.index("I want"))

    def test_names_line_up_in_one_column(self) -> None:
        text = self._text([
            Recorded(id="a", title="first prompt", updated=0, name="docs-hub"),
            Recorded(id="b", title="second prompt", updated=0,
                      name="A much longer generated session name than fits"),
        ])
        rows = [line for line in text.splitlines() if "prompt" in line]
        self.assertEqual(rows[0].index("first"), rows[1].index("second"))

    def test_an_unnamed_session_shows_only_its_first_prompt(self) -> None:
        text = self._text([Recorded(id="a", title="Fix the login bug", updated=0)])
        self.assertIn("Fix the login bug", text)

    def test_a_row_wider_than_the_terminal_is_cropped_not_wrapped(self) -> None:
        text = self._text([
            Recorded(id="a", title="p" * 60, updated=0, name="n" * 40),
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
            "shad.harness.Claude.recorded", return_value=[]
        ):
            target = pick_target(_CLAUDE, Path("/tmp/project"), "claude")

        assert target is not None
        self.assertTrue(target.fresh)
        self.assertEqual(target.session_prefix, "cc")
        assert target.session_key is not None
        uuid.UUID(target.session_key)  # the key is the conversation id shad chose
        self.assertEqual(target.command, f"claude --session-id {target.session_key}")

    def test_resumed_sessions_get_distinct_session_keys(self) -> None:
        sessions = [
            Recorded(id="uuid-a", title="First", updated=2000),
            Recorded(id="uuid-b", title="Second", updated=1000),
        ]

        targets = []
        for chosen in (1, 2):
            with (
                patch(
                    "shad.harness.Claude.recorded",
                    return_value=sessions,
                ),
                patch(
                    "shad.projects.open.sessions._run_picker", return_value=chosen
                ),
            ):
                targets.append(pick_target(_CLAUDE, Path("/tmp/project"), "claude"))

        self.assertEqual(
            targets,
            [
                Target(
                    command="claude --resume uuid-a",
                    session_key="uuid-a",
                    session_prefix="cc",
                ),
                Target(
                    command="claude --resume uuid-b",
                    session_key="uuid-b",
                    session_prefix="cc",
                ),
            ],
        )

    def test_returns_fresh_target_when_new_session_selected(self) -> None:
        sessions = [Recorded(id="uuid-a", title="First", updated=0)]

        with (
            patch(
                "shad.harness.Claude.recorded",
                return_value=sessions,
            ),
            patch("shad.projects.open.sessions._run_picker", return_value=0),
        ):
            target = pick_target(_CLAUDE, Path("/tmp/project"), "claude")

        assert target is not None
        self.assertTrue(target.fresh)
        self.assertEqual(target.session_prefix, "cc")
        assert target.session_key is not None
        uuid.UUID(target.session_key)
        self.assertEqual(target.command, f"claude --session-id {target.session_key}")

    def test_fresh_targets_get_distinct_session_keys(self) -> None:
        with patch(
            "shad.harness.Claude.recorded", return_value=[]
        ):
            first = pick_target(_CLAUDE, Path("/tmp/project"), "claude")
            second = pick_target(_CLAUDE, Path("/tmp/project"), "claude")

        assert first is not None and second is not None
        self.assertNotEqual(first.session_key, second.session_key)

    def test_returns_none_when_picker_cancelled(self) -> None:
        sessions = [Recorded(id="uuid-a", title="First", updated=0)]

        with (
            patch(
                "shad.harness.Claude.recorded",
                return_value=sessions,
            ),
            patch("shad.projects.open.sessions._run_picker", return_value=None),
        ):
            target = pick_target(_CLAUDE, Path("/tmp/project"), "claude")

        self.assertIsNone(target)




if __name__ == "__main__":
    unittest.main()
