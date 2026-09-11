from __future__ import annotations

import unittest

from rich import box

from shad.shared.render import make_table


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
