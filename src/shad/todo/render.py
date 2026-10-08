"""
rich styling shared by `shad todo list` and the panel.

Kept apart from panel.py so the CLI never imports textual, and apart from
model.py so the data layer never imports rich.
"""

from __future__ import annotations

from rich.text import Text

from shad.todo.model import Item, Status

# Glyph and style per status. In-progress is the one state that must stand out
# in a column of rows, so it is the only bold, bright one.
_STATUS: dict[str, tuple[str, str]] = {
    Status.TODO: ("○", ""),
    Status.IN_PROGRESS: ("◐", "bold yellow"),
    Status.DONE: ("●", "dim green"),
    Status.WONT_DO: ("✕", "dim strike"),
}
_UNKNOWN = ("?", "bold red")

# Label colours by position in the configured vocabulary. Yellow is left out
# because in-progress owns it.
_PALETTE = ("cyan", "magenta", "blue", "bright_green", "bright_magenta", "bright_cyan")


def status_glyph(status: str) -> Text:
    glyph, style = _STATUS.get(status, _UNKNOWN)
    return Text(glyph, style=style)


def status_word(status: str) -> Text:
    _, style = _STATUS.get(status, _UNKNOWN)
    return Text(status or "?", style=style)


def title_text(item: Item) -> Text:
    _, style = _STATUS.get(item.status, _UNKNOWN)
    return Text(item.title or f"({item.key})", style=style)


def label_style(label: str, vocabulary: list[str]) -> str:
    if label not in vocabulary:
        return "red"
    return _PALETTE[vocabulary.index(label) % len(_PALETTE)]


def labels_text(labels: tuple[str, ...], vocabulary: list[str]) -> Text:
    text = Text()
    for index, label in enumerate(labels):
        if index:
            text.append(" ")
        text.append(label, style=label_style(label, vocabulary))
    return text
