"""
Where todo files live, and every read and write of them.

    <data dir>/todo/<group>-<key>/<item key>.md

The directory is named from the project's config identity, which is unique by
construction and reads well in an editor command line. Renaming a project in
shad.toml orphans its directory; `mv` reconnects it.

Every write touches one file. A new item is created with O_EXCL, so two adds
of the same key cannot both succeed, and a status change goes through a
temporary file and os.replace, so a reader never sees a partial file. Nothing
here holds a lock, because nothing here reads one file to write another.

This module is synchronous and does no rendering: the panel calls it from the
UI thread (a directory of tens of files reads in well under a millisecond)
and the tests drive it without a terminal.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from shad.shared.config import Project, default_data_dir, resolve_prefix
from shad.shared.errors import ShadError
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


def todo_root() -> Path:
    return default_data_dir() / "todo"


def project_dir_name(project: Project) -> str:
    return f"{project.group}-{project.key}" if project.group else project.key


def project_dir(project: Project) -> Path:
    return todo_root() / project_dir_name(project)


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
            raise ShadError(f"no todo matching '{token}'; the list is empty")
        raise ShadError(f"no todo matching '{token}'")
    return match


def read_item(directory: Path, key: str) -> Item:
    path = item_path(directory, key)
    try:
        return _read(path)
    except FileNotFoundError:
        raise ShadError(f"no todo '{key}' in {directory}") from None


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
        raise ShadError("title must not be empty")
    if status not in STATUSES:
        raise ShadError(f"unknown status '{status}'; must be one of: {', '.join(STATUSES)}")
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

    directory.mkdir(parents=True, exist_ok=True)
    path = item_path(directory, key)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        raise ShadError(f"todo '{key}' already exists: {path}") from None
    with os.fdopen(fd, "w") as fh:
        fh.write(serialize(item))
    return item


def set_status(directory: Path, key: str, status: str) -> Item:
    """Rewrite the headers of one item; the body is copied byte for byte."""
    if status not in STATUSES:
        raise ShadError(f"unknown status '{status}'; must be one of: {', '.join(STATUSES)}")
    item = read_item(directory, key).with_status(status)
    _write(item_path(directory, key), serialize(item))
    return item


def remove(directory: Path, key: str) -> Path:
    path = item_path(directory, key)
    try:
        path.unlink()
    except FileNotFoundError:
        raise ShadError(f"no todo '{key}' in {directory}") from None
    return path


def label_usage(root: Path, label: str) -> dict[str, int]:
    """How many items in each project directory under *root* carry *label*."""
    usage: dict[str, int] = {}
    if not root.is_dir():
        return usage
    for directory in sorted(p for p in root.iterdir() if p.is_dir()):
        count = sum(1 for item in list_items(directory) if label in item.labels)
        if count:
            usage[directory.name] = count
    return usage


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
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        tmp.chmod(0o644)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
