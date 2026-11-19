"""
Smoke tests for the todo panel.

Driven through textual's own `App.run_test()` under stdlib
`unittest.IsolatedAsyncioTestCase`. The file logic lives in store.py and is
tested there; these assert that keys reach it and that the directory poll
redraws.
"""

from __future__ import annotations

import contextlib
import functools
import unittest
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from textual.widgets import DataTable, Static

from shad.errors import ShadError
from shad.todo import store
from shad.todo.model import Item
from shad.todo.panel.app import TodoPanel

VOCAB = ["chore", "poc"]


class PanelTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name) / "tin-shad"
        store.add(self.dir, "Write docs", ["chore"], VOCAB)
        store.add(self.dir, "Active work", ["poc"], VOCAB)
        store.set_status(self.dir, "active-work", "in-progress")
        path = store.item_path(self.dir, "write-docs")
        path.write_text(path.read_text() + "Some body text.\n")

    def _app(self) -> TodoPanel:
        return TodoPanel(self.dir, VOCAB)

    @staticmethod
    def _header(app: TodoPanel) -> str:
        return str(app.query_one("#header", Static).content)

    @staticmethod
    def _detail(app: TodoPanel) -> str:
        return str(app.query_one("#detail-text", Static).content)

    async def test_rows_come_from_the_directory_in_display_order(self) -> None:
        app = self._app()
        async with app.run_test(size=(60, 25)) as pilot:
            await pilot.pause()
            table = app.query_one("#items", DataTable)
            self.assertEqual(table.row_count, 2)
            self.assertEqual(app.current_key(), "active-work")
            self.assertTrue(self._header(app).startswith("todo"))
            self.assertIn("2 open", self._header(app))
            self.assertIn("0 done", self._header(app))

    async def test_detail_follows_the_cursor(self) -> None:
        app = self._app()
        async with app.run_test(size=(60, 25)) as pilot:
            await pilot.pause()
            self.assertIn("Active work", self._detail(app))
            await pilot.press("j")
            await pilot.pause()
            self.assertIn("Write docs", self._detail(app))
            self.assertIn("Some body text.", self._detail(app))

    async def test_number_keys_write_the_status_and_keep_the_cursor(self) -> None:
        app = self._app()
        async with app.run_test(size=(60, 25)) as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause()
            text = store.item_path(self.dir, "active-work").read_text()
            self.assertIn("status: done", text)
            # Done sorts last, and the cursor follows the item there.
            self.assertEqual(app.current_key(), "active-work")
            self.assertIn("1 done", self._header(app))

    async def test_delete_asks_first_and_n_cancels(self) -> None:
        app = self._app()
        async with app.run_test(size=(60, 25)) as pilot:
            await pilot.pause()
            await pilot.press("d")
            await pilot.pause()
            self.assertIn("delete 'active-work'?", self._header(app))
            await pilot.press("n")
            await pilot.pause()
            self.assertNotIn("delete", self._header(app))
            self.assertEqual(store.keys(self.dir), ["active-work", "write-docs"])

    async def test_delete_then_y_removes_the_file(self) -> None:
        app = self._app()
        async with app.run_test(size=(60, 25)) as pilot:
            await pilot.pause()
            await pilot.press("d", "y")
            await pilot.pause()
            self.assertEqual(store.keys(self.dir), ["write-docs"])
            self.assertEqual(app.query_one("#items", DataTable).row_count, 1)

    async def test_y_without_a_pending_delete_does_nothing(self) -> None:
        app = self._app()
        async with app.run_test(size=(60, 25)) as pilot:
            await pilot.pause()
            await pilot.press("y")
            await pilot.pause()
            self.assertEqual(len(store.keys(self.dir)), 2)

    async def test_poll_picks_up_a_file_added_elsewhere(self) -> None:
        app = self._app()
        async with app.run_test(size=(60, 25)) as pilot:
            await pilot.pause()
            store.add(self.dir, "From the CLI", [], VOCAB)
            app.poll()
            await pilot.pause()
            self.assertEqual(app.query_one("#items", DataTable).row_count, 3)

    async def test_hand_edited_problem_is_shown_not_fatal(self) -> None:
        path = store.item_path(self.dir, "active-work")
        path.write_text(path.read_text().replace("labels: poc", "labels: nope"))
        app = self._app()
        async with app.run_test(size=(60, 25)) as pilot:
            await pilot.pause()
            self.assertIn("1 to fix", self._header(app))
            self.assertIn("unknown label 'nope'", self._detail(app))

    async def test_e_suspends_the_app_around_the_editor_and_reloads(self) -> None:
        app = self._app()
        path = store.item_path(self.dir, "active-work")

        def fake_editor(argv: list[str], check: bool) -> None:
            # Simulates a hand edit while the app is suspended.
            self.assertEqual(argv[-1], str(path))
            path.write_text(path.read_text().replace("status: in-progress", "status: done"))

        with (
            patch("shad.todo.panel.app.resolve_editor", return_value="fake-editor --wait"),
            patch("shad.todo.panel.app.subprocess.run", side_effect=fake_editor) as run,
            patch.object(TodoPanel, "suspend", return_value=contextlib.nullcontext()) as suspend,
        ):
            async with app.run_test(size=(60, 25)) as pilot:
                await pilot.pause()
                await pilot.press("e")
                await pilot.pause()
                self.assertIn("1 done", self._header(app))

        suspend.assert_called_once()
        self.assertEqual(run.call_args.args[0][:2], ["fake-editor", "--wait"])

    @contextlib.contextmanager
    def _suspend_recorder(self, exits: list[str]) -> Iterator[None]:
        """
        Stands in for App.suspend. Like textual's own, it runs the code after
        its yield only when the block exits normally.
        """
        yield
        exits.append("resumed")

    async def test_a_adds_an_item_in_the_editor_and_selects_it(self) -> None:
        app = self._app()
        exits: list[str] = []

        def fake_add(directory: Path, labels: list[str], vocabulary: list[str]) -> Item:
            self.assertEqual((directory, labels, vocabulary), (self.dir, [], VOCAB))
            return store.add(directory, "Zulu new", [], vocabulary)

        with (
            patch("shad.todo.panel.app.add_in_editor", side_effect=fake_add),
            patch.object(TodoPanel, "suspend", side_effect=functools.partial(self._suspend_recorder, exits)),
        ):
            async with app.run_test(size=(60, 25)) as pilot:
                await pilot.pause()
                await pilot.press("a")
                await pilot.pause()
                self.assertEqual(app.query_one("#items", DataTable).row_count, 3)
                self.assertEqual(app.current_key(), "zulu-new")
                self.assertIn("Zulu new", self._detail(app))

        self.assertEqual(exits, ["resumed"])

    async def test_a_that_creates_nothing_notifies_and_resumes(self) -> None:
        empty = ShadError.validation("empty_todo", "empty title and body; no todo created")
        for failure in (empty, KeyboardInterrupt()):
            with self.subTest(failure=type(failure).__name__):
                app = self._app()
                exits: list[str] = []
                with (
                    patch("shad.todo.panel.app.add_in_editor", side_effect=failure),
                    patch.object(
                        TodoPanel,
                        "suspend",
                        side_effect=functools.partial(self._suspend_recorder, exits),
                    ),
                    patch.object(TodoPanel, "notify") as notify,
                ):
                    async with app.run_test(size=(60, 25)) as pilot:
                        await pilot.pause()
                        await pilot.press("a")
                        await pilot.pause()
                        self.assertEqual(app.query_one("#items", DataTable).row_count, 2)

                self.assertEqual(exits, ["resumed"])
                self.assertIn("no todo created", notify.call_args.args[0])

    async def test_empty_directory_shows_a_hint(self) -> None:
        app = TodoPanel(Path(self._tmp.name) / "empty", VOCAB)
        async with app.run_test(size=(60, 25)) as pilot:
            await pilot.pause()
            self.assertIsNone(app.current_key())
            self.assertIn("press a to add", self._detail(app))
            await pilot.press("3", "d", "y")
            await pilot.pause()


if __name__ == "__main__":
    unittest.main()
