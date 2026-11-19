"""
Where todo files live, and every read and write of them.

    <todo dir>/<item key>.md

The todo dir is `Config.todo_dir`: the [todo] path from shad.toml, or
<data dir>/todo when it is not set. There is one list, and no item belongs to a project: the todo pane
in every project session shows the same files.

Every write touches one file, through `shad.atomic`: a new item is an
exclusive create, so two adds of the same key cannot both succeed, and a
status change is a replacement, so a reader never sees a partial file.
Nothing here holds a lock, because nothing here reads one file to write
another.

This module is synchronous and does no rendering: the panel calls it from the
UI thread (a directory of tens of files reads in well under a millisecond)
and the tests drive it without a terminal.
"""

from __future__ import annotations

from pathlib import Path

from shad import atomic
from shad.addressing import resolve_prefix
from shad.errors import ShadError
from shad.todo.model import (
    STATUSES,
    Item,
    Status,
    check_labels,
    now_iso,
    parse,
    serialize,
    slugify,
    sort_key,
)

SUFFIX = ".md"


def item_path(directory: Path, key: str) -> Path:
    return directory / f"{key}{SUFFIX}"


def signature(directory: Path) -> frozenset[tuple[str, int, int]]:
    """
    What the panel polls: every item file's name, mtime and size.

    Any add, delete, or edit changes this set. A file removed between the
    listing and its stat is skipped rather than raised; the next poll sees
    the steady state.
    """
    found: set[tuple[str, int, int]] = set()
    for path in _item_files(directory):
        try:
            stat = path.stat()
        except FileNotFoundError:
            continue
        found.add((path.name, stat.st_mtime_ns, stat.st_size))
    return frozenset(found)


def list_items(directory: Path) -> list[Item]:
    """Every item in *directory*, in display order. A missing directory is empty."""
    items = []
    for path in _item_files(directory):
        try:
            item = _read(path)
        except FileNotFoundError:
            continue
        items.append(item)
    return sorted(items, key=sort_key)


def keys(directory: Path) -> list[str]:
    return sorted(path.stem for path in _item_files(directory))


def resolve_key(directory: Path, token: str) -> str:
    """The one item key *token* names, by the exact-then-prefix rule projects use."""
    known = keys(directory)
    match = resolve_prefix(known, token)
    if match is None:
        if not known:
            raise ShadError.not_found(
                "no_such_todo", f"no todo matching '{token}'; the list is empty"
            )
        raise ShadError.not_found("no_such_todo", f"no todo matching '{token}'")
    return match


def read_item(directory: Path, key: str) -> Item:
    path = item_path(directory, key)
    try:
        return _read(path)
    except FileNotFoundError:
        raise ShadError.not_found("no_such_todo", f"no todo '{key}' in {directory}") from None


def add(
    directory: Path,
    title: str,
    labels: list[str],
    vocabulary: list[str],
    *,
    status: str = Status.TODO.value,
    body: str = "",
    extra: tuple[tuple[str, str], ...] = (),
) -> Item:
    """
    Create the file for a new item. Its key is the slug of *title*. Blank
    lines around *body* are dropped, and a body of only whitespace is empty.
    """
    title = " ".join(title.split())
    if not title:
        raise ShadError.validation("empty_title", "title must not be empty")
    if status not in STATUSES:
        raise ShadError.validation(
            "invalid_status", f"unknown status '{status}'; must be one of: {', '.join(STATUSES)}"
        )
    check_labels(labels, vocabulary)
    key = slugify(title)
    body = body.strip("\n")
    item = Item(
        key=key,
        title=title,
        status=status,
        labels=tuple(dict.fromkeys(labels)),
        created=now_iso(),
        body=f"{body}\n" if body.strip() else "",
        extra=extra,
    )

    path = item_path(directory, key)
    try:
        atomic.create(path, serialize(item))
    except FileExistsError:
        raise ShadError.conflict("todo_exists", f"todo '{key}' already exists: {path}") from None
    return item


def set_status(directory: Path, key: str, status: str) -> Item:
    """Rewrite the headers of one item; the body is copied byte for byte."""
    if status not in STATUSES:
        raise ShadError.validation(
            "invalid_status", f"unknown status '{status}'; must be one of: {', '.join(STATUSES)}"
        )
    item = read_item(directory, key).with_status(status)
    _write(item_path(directory, key), serialize(item))
    return item


def remove(directory: Path, key: str) -> Path:
    path = item_path(directory, key)
    try:
        path.unlink()
    except FileNotFoundError:
        raise ShadError.not_found("no_such_todo", f"no todo '{key}' in {directory}") from None
    return path


def label_usage(directory: Path, label: str) -> int:
    """How many items in *directory* carry *label*."""
    return sum(1 for item in list_items(directory) if label in item.labels)


# ── file primitives ───────────────────────────────────────────────────────


def _item_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    # A leading dot excludes the temporary files _write creates beside the
    # item, and anything an editor leaves behind.
    return sorted(
        path
        for path in directory.iterdir()
        if path.suffix == SUFFIX and not path.name.startswith(".") and path.is_file()
    )


def _read(path: Path) -> Item:
    stat = path.stat()
    text = path.read_text(encoding="utf-8", errors="replace")
    return parse(text, key=path.stem, updated=int(stat.st_mtime))


def _write(path: Path, text: str) -> None:
    atomic.replace(path, text)
