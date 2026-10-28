from __future__ import annotations

import re
import unittest

from rich.console import Console

from shad.sessions.model import Entry
from shad.sessions.render import (
    NAME_WIDTH,
    TITLE_WIDTH,
    cells,
    columns,
    picker,
    state,
    table,
)
from shad.sessions.testing import KB, SHAD, UUID_A, UUID_B, running

_ANSI = re.compile(r"\x1b\[[0-9;]*m")

_WIDE = columns([], 500, taken=0)
_WIDE = type(_WIDE)(project=8, harness=6, id=8, name=NAME_WIDTH, title=TITLE_WIDTH)


def _entry(name: str | None = None, title: str | None = None, session_id: str | None = UUID_A) -> Entry:
    return Entry(group="tin", key="shad", harness="claude", session_id=session_id, attached=False, name=name, title=title)


class CellsTests(unittest.TestCase):
    def test_a_missing_id_shows_a_dash(self) -> None:
        texts = cells(_entry(session_id=None), _WIDE)
        self.assertEqual([c.plain for c in texts], ["tin shad", "claude", "—", "", ""])

    def test_the_id_is_shortened_and_long_names_are_truncated(self) -> None:
        texts = cells(_entry(name="n" * 40, title="first prompt"), _WIDE)
        plain = [c.plain for c in texts]
        self.assertEqual(plain[:3], ["tin shad", "claude", UUID_A[:8]])
        self.assertEqual(len(plain[3]), NAME_WIDTH)
        self.assertTrue(plain[3].endswith("…"))
        self.assertEqual(plain[4], "first prompt")

    def test_dropped_columns_have_no_cell(self) -> None:
        cols = columns([_entry(name="Alpha", title="prompt")], 30, taken=0)
        self.assertEqual(len(cells(_entry(name="Alpha", title="prompt"), cols)), len(cols.widths))


class ColumnsTests(unittest.TestCase):
    def test_name_and_title_fit_their_content_when_there_is_room(self) -> None:
        cols = columns([_entry(name="Alpha", title="a prompt")], 200, taken=0)
        self.assertEqual((cols.project, cols.harness, cols.id), (8, 6, 8))
        self.assertEqual((cols.name, cols.title), (5, 8))

    def test_long_content_is_capped(self) -> None:
        cols = columns([_entry(name="n" * 80, title="t" * 80)], 200, taken=0)
        self.assertEqual((cols.name, cols.title), (NAME_WIDTH, TITLE_WIDTH))

    def test_the_title_absorbs_the_shortage_first(self) -> None:
        entries = [_entry(name="n" * 80, title="t" * 80)]
        cols = columns(entries, 8 + 6 + 8 + NAME_WIDTH + 20, taken=0)
        self.assertEqual((cols.name, cols.title), (NAME_WIDTH, 20))

    def test_a_title_too_narrow_to_read_is_dropped_and_the_name_shrinks_next(self) -> None:
        entries = [_entry(name="n" * 80, title="t" * 80)]
        cols = columns(entries, 8 + 6 + 8 + NAME_WIDTH + 3, taken=0)
        self.assertEqual((cols.name, cols.title), (NAME_WIDTH, 0))
        cols = columns(entries, 8 + 6 + 8 + 10, taken=0)
        self.assertEqual((cols.name, cols.title), (10, 0))
        cols = columns(entries, 8 + 6 + 8 + 2, taken=0)
        self.assertEqual((cols.name, cols.title), (0, 0))

    def test_the_fixed_columns_never_shrink(self) -> None:
        cols = columns([_entry(name="n" * 80, title="t" * 80)], 5, taken=0)
        self.assertEqual((cols.project, cols.harness, cols.id), (8, 6, 8))

    def test_without_ids_the_id_column_is_one_dash_wide(self) -> None:
        self.assertEqual(columns([_entry(session_id=None)], 200, taken=0).id, 1)


class StateTests(unittest.TestCase):
    def test_attached_and_busy(self) -> None:
        live = running("kb--cc-x", attached=True, status="busy")
        self.assertEqual(state(live, duplicate=False).plain, "attached  busy")

    def test_detached_and_idle_with_its_age(self) -> None:
        live = running("kb--cc-x", status="idle", status_since=1_000)
        self.assertEqual(state(live, duplicate=False, now=1_000 + 7_200).plain, "detached  idle 2h")

    def test_idle_without_a_timestamp(self) -> None:
        live = running("kb--cc-x", status="idle")
        self.assertEqual(state(live, duplicate=False).plain, "detached  idle")

    def test_an_exited_harness_overrides_its_last_status(self) -> None:
        live = running("kb--cc-x", status="idle", status_since=1, harness_running=False)
        self.assertEqual(state(live, duplicate=False).plain, "detached  harness exited")

    def test_unknown_status_shows_only_the_attachment(self) -> None:
        self.assertEqual(state(running("kb--cc-x"), duplicate=False).plain, "detached")

    def test_unsupported_and_duplicate_are_appended(self) -> None:
        live = running(
            "kb--oc-x", session_id=None, harness="opencode",
            unsupported="the opencode harness is not supported",
        )
        self.assertEqual(
            state(live, duplicate=True).plain,
            "detached  the opencode harness is not supported  duplicate",
        )


def _rows() -> list:
    return [
        running("kb--cc-a", KB, name="Alpha release planning", title="I need a read only user for apps-analytics", attached=True, status="idle", status_since=1),
        running("tin-shad--cc-b", SHAD, session_id=UUID_B, name="Beta", title="Why is this still failing", status="busy"),
        running("kb--cc-fresh-1", KB, name="Alpha again", title="the same conversation"),
    ]


def _lines(raw: bytes) -> list[str]:
    return [line for line in _ANSI.sub("", raw.decode()).splitlines() if line]


class PickerTests(unittest.TestCase):
    def test_renders_a_pointer_a_box_per_row_and_the_footer(self) -> None:
        plain = "\n".join(_lines(picker(_rows(), 1, frozenset({0}), title="save sessions", accept="save", width=160)))
        self.assertIn("save sessions", plain)
        self.assertEqual(plain.count("[x]"), 1)
        self.assertEqual(plain.count("[ ]"), 2)
        self.assertEqual(plain.count("❯"), 1)
        self.assertIn("Alpha release planning", plain)
        self.assertIn("Enter  save", plain)
        self.assertEqual(plain.count("duplicate"), 2)

    def test_fits_the_width_and_keeps_the_fixed_columns_whole(self) -> None:
        for width in (72, 80, 100, 120, 160):
            with self.subTest(width=width):
                lines = _lines(picker(_rows(), 0, frozenset(), title="t", accept="a", width=width))
                self.assertTrue(all(len(line) <= width for line in lines), lines)
                body = "\n".join(lines)
                for whole in ("[ ]", "kb", "tin shad", "claude", UUID_A[:8], UUID_B[:8], "attached  idle", "busy"):
                    self.assertIn(whole, body, (width, body))

    def test_the_state_gives_when_not_even_the_fixed_columns_fit(self) -> None:
        lines = _lines(picker(_rows(), 0, frozenset(), title="t", accept="a", width=60))
        self.assertTrue(all(len(line) <= 60 for line in lines), lines)
        body = "\n".join(lines)
        for whole in ("[ ]", "tin shad", "claude", UUID_A[:8]):
            self.assertIn(whole, body, body)

    def test_a_narrow_width_drops_the_first_prompt_then_the_name(self) -> None:
        body = "\n".join(_lines(picker(_rows(), 0, frozenset(), title="t", accept="a", width=90)))
        self.assertIn("Alpha", body)
        self.assertNotIn("read only", body)
        body = "\n".join(_lines(picker(_rows(), 0, frozenset(), title="t", accept="a", width=66)))
        self.assertNotIn("Alpha", body)
        self.assertIn(UUID_A[:8], body)


class TableTests(unittest.TestCase):
    def _render(self, title: str, rows, width: int) -> list[str]:
        console = Console(width=width, force_terminal=False, record=True)
        with console.capture() as capture:
            console.print(table(title, rows, width))
        return [line for line in capture.get().splitlines() if line.strip()]

    def test_fits_the_width_and_keeps_the_fixed_columns_whole(self) -> None:
        rows = [(live.entry, state(live, duplicate=False)) for live in _rows()]
        for width in (70, 80, 120, 200):
            with self.subTest(width=width):
                lines = self._render("saved", rows, width)
                self.assertTrue(all(len(line) <= width for line in lines), lines)
                body = "\n".join(lines)
                for whole in ("tin shad", "claude", UUID_A[:8], UUID_B[:8], "attached  idle", "busy"):
                    self.assertIn(whole, body, (width, body))

    def test_an_empty_table_says_so(self) -> None:
        self.assertIn("no sessions", "\n".join(self._render("sessions", [], 80)))
