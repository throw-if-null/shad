"""
The todo panel — the pane that shows one project's todo files.

A list over a detail box, under a one-line header. Every read and write goes
through store.py; this module only draws and dispatches keys. It polls the
directory once a second, so an item added from the CLI or edited in another
pane appears without a keypress.

The pane is about 25 rows by 50 to 60 columns at the default todo_percent, so
the list and the detail are stacked rather than side by side, and the header
is one line.

textual is imported by this module only, and shad.todo.command imports this
module lazily, so `shad todo add` never pays for it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import DataTable, Footer, Static

from shad.config.command import resolve_editor
from shad.shared.errors import ShadError
from shad.shared.render import relative_age
from shad.todo import store
from shad.todo.command import add_in_editor
from shad.todo.model import Item, Status, problems
from shad.todo.render import labels_text, status_glyph, status_word, title_text

POLL_SECONDS = 1.0


class TodoPanel(App[None]):
    """One project's todo list, with status, add, delete and edit keys."""

    CSS = """
    Screen { layers: base; }
    #header { height: 1; padding: 0 1; background: $panel; color: $text; }
    #items { height: 1fr; }
    #detail { height: 40%; border-top: solid $panel-lighten-2; padding: 0 1; }
    """

    ENABLE_COMMAND_PALETTE = False

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("1", f"set_status('{Status.TODO.value}')", "todo"),
        Binding("2", f"set_status('{Status.IN_PROGRESS.value}')", "doing"),
        Binding("3", f"set_status('{Status.DONE.value}')", "done"),
        Binding("4", f"set_status('{Status.WONT_DO.value}')", "wont"),
        Binding("a", "add", "add"),
        Binding("d", "delete", "delete"),
        Binding("e", "edit", "edit"),
        Binding("y", "confirm", "confirm", show=False),
        Binding("n", "cancel", "cancel", show=False),
        Binding("escape", "cancel", "cancel", show=False),
        Binding("r", "refresh", "refresh", show=False),
        Binding("q", "quit", "quit", show=False),
        Binding("j", "cursor_down", "down", show=False),
        Binding("k", "cursor_up", "up", show=False),
    ]

    def __init__(self, directory: Path, labels: list[str], *, name: str) -> None:
        super().__init__()
        self._directory = directory
        self._labels = labels
        self._project_name = name
        self._items: dict[str, Item] = {}
        self._signature = store.signature(directory)
        self._pending_delete: str | None = None

    # ── layout ────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Static("", id="header")
        table: DataTable[Text] = DataTable(id="items")
        table.cursor_type = "row"
        table.zebra_stripes = True
        table.show_header = False
        yield table
        with VerticalScroll(id="detail"):
            yield Static("", id="detail-text")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#items", DataTable).add_columns("", "title", "labels")
        self.load()
        self.set_interval(POLL_SECONDS, self.poll)

    # ── data ──────────────────────────────────────────────────────────────

    def load(self) -> None:
        """Re-read the directory and redraw, keeping the cursor on the same item."""
        table: DataTable[Text] = self.query_one("#items", DataTable)
        current = self.current_key()
        self._signature = store.signature(self._directory)
        items = store.list_items(self._directory)
        self._items = {item.key: item for item in items}

        table.clear()
        for item in items:
            table.add_row(
                status_glyph(item.status),
                title_text(item),
                labels_text(item.labels, self._labels),
                key=item.key,
            )
        if current in self._items:
            table.move_cursor(row=table.get_row_index(current))
        self._render_header()
        self._show(self.current_key())

    def poll(self) -> None:
        if store.signature(self._directory) != self._signature:
            self.load()

    def current_key(self) -> str | None:
        table: DataTable[Text] = self.query_one("#items", DataTable)
        if table.row_count == 0:
            return None
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        return str(row_key.value) if row_key.value is not None else None

    # ── rendering ─────────────────────────────────────────────────────────

    def _render_header(self) -> None:
        if self._pending_delete is not None:
            text = Text(f"delete '{self._pending_delete}'?  y / n", style="bold red")
        else:
            open_count = sum(1 for item in self._items.values() if not item.finished)
            done_count = len(self._items) - open_count
            wrong = sum(1 for item in self._items.values() if problems(item, self._labels))
            bits = [self._project_name, f"{open_count} open", f"{done_count} done"]
            if wrong:
                bits.append(f"{wrong} to fix")
            text = Text("  ·  ".join(bits))
        self.query_one("#header", Static).update(text)

    def _show(self, key: str | None) -> None:
        detail = self.query_one("#detail-text", Static)
        item = self._items.get(key) if key else None
        if item is None:
            detail.update(Text("no todos — press a to add one", style="dim"))
            return

        text = Text()
        text.append(item.title or f"({item.key})", style="bold")
        text.append("\n")
        text.append_text(status_word(item.status))
        if item.labels:
            text.append("  ")
            text.append_text(labels_text(item.labels, self._labels))
        text.append("\n")
        text.append(f"created {item.created or '—'}  ·  updated {relative_age(item.updated)}", style="dim")
        for problem in problems(item, self._labels):
            text.append(f"\n! {problem}", style="bold red")
        if item.body.strip():
            text.append("\n\n")
            text.append(item.body.rstrip("\n"))
        detail.update(text)

    # ── interaction ───────────────────────────────────────────────────────

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._cancel()
        self._show(str(event.row_key.value) if event.row_key.value is not None else None)

    def action_set_status(self, status: str) -> None:
        self._cancel()
        key = self.current_key()
        if key is None:
            return
        store.set_status(self._directory, key, status)
        self.load()

    def action_delete(self) -> None:
        key = self.current_key()
        if key is None:
            return
        self._pending_delete = key
        self._render_header()

    def action_confirm(self) -> None:
        key = self._pending_delete
        if key is None:
            return
        self._pending_delete = None
        if key in self._items:
            store.remove(self._directory, key)
        self.load()

    def action_cancel(self) -> None:
        self._cancel()
        self._render_header()

    def _cancel(self) -> None:
        if self._pending_delete is not None:
            self._pending_delete = None
            self._render_header()

    def action_add(self) -> None:
        self._cancel()
        item: Item | None = None
        error = ""
        # suspend() resumes the app only when its block exits normally
        # (textual 8.2), so every exception is caught inside the block.
        # Ctrl-C at the "Edit again?" prompt raises KeyboardInterrupt here,
        # because the terminal is in cooked mode while the app is suspended.
        with self.suspend():
            try:
                item = add_in_editor(self._directory, [], self._labels)
            except ShadError as exc:
                error = str(exc)
            except (KeyboardInterrupt, EOFError):
                error = "no todo created"
        if error:
            self.notify(error, severity="warning", markup=False)
        self.load()
        if item is not None and item.key in self._items:
            table: DataTable[Text] = self.query_one("#items", DataTable)
            table.move_cursor(row=table.get_row_index(item.key))

    def action_edit(self) -> None:
        self._cancel()
        key = self.current_key()
        if key is None:
            return
        path = store.item_path(self._directory, key)
        editor = resolve_editor()
        # The editor takes the terminal over; textual restores it on exit.
        with self.suspend():
            subprocess.run([*editor.split(), str(path)], check=False)
        self.load()

    def action_refresh(self) -> None:
        self._cancel()
        self.load()

    def action_cursor_down(self) -> None:
        self.query_one("#items", DataTable).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one("#items", DataTable).action_cursor_up()


def run_panel(directory: Path, labels: list[str], *, name: str) -> None:
    TodoPanel(directory, labels, name=name).run()
