from __future__ import annotations

import unittest
from collections.abc import Iterator

from shad.shared.picker import erase, select_many, select_one

ESC_UP, ESC_DOWN, ENTER, ESC = "\x1b[A", "\x1b[B", "\r", "\x1b"


def _keys(*keys: str) -> Iterator[str]:
    return iter(keys)


class SelectOneTests(unittest.TestCase):
    def test_enter_accepts_the_first_row(self) -> None:
        self.assertEqual(select_one(_keys(ENTER), 3, lambda c: None), 0)

    def test_arrows_and_vi_keys_move_the_cursor(self) -> None:
        self.assertEqual(select_one(_keys(ESC_DOWN, "j", ENTER), 5, lambda c: None), 2)
        self.assertEqual(select_one(_keys("j", "j", "k", ESC_UP, ENTER), 5, lambda c: None), 0)

    def test_the_cursor_wraps(self) -> None:
        self.assertEqual(select_one(_keys("k", ENTER), 3, lambda c: None), 2)
        self.assertEqual(select_one(_keys("j", "j", "j", ENTER), 3, lambda c: None), 0)

    def test_q_and_escape_cancel(self) -> None:
        self.assertIsNone(select_one(_keys("j", "q"), 3, lambda c: None))
        self.assertIsNone(select_one(_keys(ESC), 3, lambda c: None))

    def test_exhausted_keys_cancel(self) -> None:
        self.assertIsNone(select_one(_keys(), 3, lambda c: None))

    def test_draws_before_the_first_key_and_after_each_move(self) -> None:
        drawn: list[int] = []
        select_one(_keys("j", "x", "j", ENTER), 3, drawn.append)
        self.assertEqual(drawn, [0, 1, 2])

    def test_rejects_an_empty_list(self) -> None:
        with self.assertRaises(ValueError):
            select_one(_keys(ENTER), 0, lambda c: None)


class SelectManyTests(unittest.TestCase):
    def test_enter_returns_the_initial_selection(self) -> None:
        self.assertEqual(select_many(_keys(ENTER), 3, [0, 2], lambda c, s: None), {0, 2})

    def test_space_toggles_the_row_under_the_cursor(self) -> None:
        result = select_many(_keys(" ", "j", " ", "j", " ", " ", ENTER), 3, [0], lambda c, s: None)
        self.assertEqual(result, {1})

    def test_a_checks_every_row_then_clears_them(self) -> None:
        self.assertEqual(select_many(_keys("a", ENTER), 3, [1], lambda c, s: None), {0, 1, 2})
        self.assertEqual(select_many(_keys("a", ENTER), 3, [0, 1, 2], lambda c, s: None), set())

    def test_an_empty_selection_is_accepted(self) -> None:
        result = select_many(_keys(" ", ENTER), 2, [0], lambda c, s: None)
        self.assertEqual(result, frozenset())
        self.assertIsNotNone(result)

    def test_cancel_returns_none(self) -> None:
        self.assertIsNone(select_many(_keys(" ", "q"), 2, [], lambda c, s: None))
        self.assertIsNone(select_many(_keys(ESC), 2, [], lambda c, s: None))
        self.assertIsNone(select_many(_keys(" "), 2, [], lambda c, s: None))

    def test_out_of_range_initial_rows_are_dropped(self) -> None:
        self.assertEqual(select_many(_keys(ENTER), 2, [1, 7, -1], lambda c, s: None), {1})

    def test_draws_the_cursor_and_the_selection(self) -> None:
        drawn: list[tuple[int, frozenset[int]]] = []
        select_many(_keys("j", " ", "x", ENTER), 3, [], lambda c, s: drawn.append((c, s)))
        self.assertEqual(drawn, [(0, frozenset()), (1, frozenset()), (1, frozenset({1}))])

    def test_rejects_an_empty_list(self) -> None:
        with self.assertRaises(ValueError):
            select_many(_keys(ENTER), 0, [], lambda c, s: None)


class EraseTests(unittest.TestCase):
    def test_moves_up_over_the_frame_and_clears_from_there(self) -> None:
        self.assertEqual(erase(12), b"\r\x1b[12A\x1b[J")

    def test_nothing_to_erase_writes_nothing(self) -> None:
        """CSI 0 A would move up one row on most terminals."""
        self.assertEqual(erase(0), b"")
        self.assertEqual(erase(-1), b"")
