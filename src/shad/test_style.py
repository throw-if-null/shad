from __future__ import annotations

import unittest

from rich import box

from shad.style import make_table, relative_age


class MakeTableTests(unittest.TestCase):
    def test_make_table_uses_the_shared_shad_style(self) -> None:
        table = make_table("fetch")

        self.assertEqual(table.title, "fetch")
        self.assertIs(table.box, box.ROUNDED)
        self.assertFalse(table.show_header)
        self.assertEqual(table.title_justify, "left")
        self.assertEqual(table.title_style, "bold cyan")
        self.assertEqual(table.border_style, "bright_black")
        self.assertEqual(table.padding, (0, 1, 0, 1))

    def test_make_table_returns_a_fresh_table_each_call(self) -> None:
        first = make_table("a")
        second = make_table("b")

        first.add_row("x")
        self.assertEqual(len(first.rows), 1)
        self.assertEqual(len(second.rows), 0)


if __name__ == "__main__":
    unittest.main()


class RelativeAgeTests(unittest.TestCase):
    """
    Shared by the git panel's stash column and `shad projects ... status`.

    Computed from a unix timestamp rather than read from git's %cr, which is
    gettext-translated.
    """

    NOW = 1_700_000_000.0

    def _age(self, seconds: int) -> str:
        return relative_age(int(self.NOW) - seconds, now=self.NOW)

    def test_units_step_up_with_the_interval(self) -> None:
        self.assertEqual(self._age(5), "5s")
        self.assertEqual(self._age(90), "1m")
        self.assertEqual(self._age(7200), "2h")
        self.assertEqual(self._age(3 * 86400), "3d")
        self.assertEqual(self._age(14 * 86400), "2w")
        self.assertEqual(self._age(60 * 86400), "2mo")
        self.assertEqual(self._age(800 * 86400), "2y")

    def test_boundaries_do_not_skip_a_unit(self) -> None:
        self.assertEqual(self._age(59), "59s")
        self.assertEqual(self._age(60), "1m")
        self.assertEqual(self._age(3599), "59m")
        self.assertEqual(self._age(3600), "1h")

    def test_a_missing_timestamp_renders_a_dash(self) -> None:
        self.assertEqual(relative_age(0, now=self.NOW), "—")

    def test_a_future_timestamp_does_not_render_a_negative_age(self) -> None:
        self.assertEqual(relative_age(int(self.NOW) + 60, now=self.NOW), "now")
