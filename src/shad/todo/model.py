"""
The todo item and its on-disk form.

One item is one text file: a header block, a blank line, then the body.

    title: Fix panel resize
    status: in-progress
    labels: chore, investigation
    created: 2026-10-07T10:12:00+02:00

    Free text. Markdown is fine; the panel shows it as text.

The headers are `name: value` lines up to the first blank line. The body is
everything after that blank line, byte for byte. A file is edited by hand as
often as by shad, so the parser is lenient: an unknown status or label is
reported through problems(), not raised, and headers shad does not know are
kept and written back in place.

The file name is the item key, a slug of the title. This module decides
nothing about directories; see store.py for where the files live.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from shad.config import LABEL_RE
from shad.errors import ShadError


class Status(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in-progress"
    DONE = "done"
    WONT_DO = "wont-do"


STATUSES: tuple[str, ...] = tuple(status.value for status in Status)

# Display order: work in progress first, then what is waiting, then what is
# finished. An unknown status sorts before everything because it needs fixing.
_DISPLAY_ORDER = (Status.IN_PROGRESS, Status.TODO, Status.DONE, Status.WONT_DO)
_STATUS_RANK = {status.value: rank for rank, status in enumerate(_DISPLAY_ORDER, start=1)}

KEY_MAX = 40
_HEADER = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):[ \t]?(.*)$")
_NOT_KEY = re.compile(r"[^a-z0-9]+")

TITLE = "title"
STATUS = "status"
LABELS = "labels"
CREATED = "created"
KNOWN_HEADERS = (TITLE, STATUS, LABELS, CREATED)


@dataclass(frozen=True)
class Item:
    key: str
    title: str
    status: str  # a Status value, or whatever a hand edit left here
    labels: tuple[str, ...] = ()
    created: str = ""  # ISO 8601, as written; never parsed back
    body: str = ""  # verbatim text after the first blank line
    extra: tuple[tuple[str, str], ...] = ()  # headers shad does not define, in file order
    updated: int = 0  # unix seconds, the file mtime

    @property
    def finished(self) -> bool:
        return self.status in (Status.DONE, Status.WONT_DO)

    def with_status(self, status: str) -> Item:
        return replace(self, status=status)


def sort_key(item: Item) -> tuple[int, str]:
    return _STATUS_RANK.get(item.status, 0), item.title.lower()


def slugify(title: str) -> str:
    """
    The item key for *title*: lowercase, runs of other characters collapsed
    to one hyphen, at most KEY_MAX characters. Raises when nothing survives,
    because a key must name a file.
    """
    key = _NOT_KEY.sub("-", title.lower()).strip("-")
    key = key[:KEY_MAX].rstrip("-")
    if not key:
        raise ShadError.validation(
            "invalid_title", f"title {title!r} has no letters or digits to make a key from"
        )
    return key


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def parse(text: str, *, key: str, updated: int = 0) -> Item:
    """
    Read one file's text. Never raises: a file with no headers is an item with
    an empty title, and problems() reports what is wrong.
    """
    head, _, body = text.partition("\n\n")
    headers: dict[str, str] = {}
    extra: list[tuple[str, str]] = []
    for line in head.splitlines():
        match = _HEADER.match(line)
        if match is None:
            continue
        name, value = match.group(1).lower(), match.group(2).strip()
        if name in KNOWN_HEADERS:
            headers.setdefault(name, value)
        else:
            extra.append((name, value))

    labels = tuple(
        label.strip() for label in headers.get(LABELS, "").split(",") if label.strip()
    )
    return Item(
        key=key,
        title=headers.get(TITLE, ""),
        status=headers.get(STATUS, ""),
        labels=labels,
        created=headers.get(CREATED, ""),
        body=body,
        extra=tuple(extra),
        updated=updated,
    )


def serialize(item: Item) -> str:
    """The file text for *item*. parse(serialize(item)) round-trips the body exactly."""
    lines = [
        f"{TITLE}: {item.title}",
        f"{STATUS}: {item.status}",
        f"{LABELS}: {', '.join(item.labels)}",
        f"{CREATED}: {item.created}",
    ]
    lines.extend(f"{name}: {value}" for name, value in item.extra)
    return "\n".join(lines) + "\n\n" + item.body


def template(labels: list[str], vocabulary: list[str]) -> str:
    """
    The text `shad todo add` opens in the editor: a new item's header block
    with an empty title, help lines, and a blank line before the body.

    The help lines start with '#', which parse() skips because a header name
    must start with a letter. They never reach the item file.
    """
    known = ", ".join(vocabulary) if vocabulary else "none configured"
    lines = [
        f"{TITLE}: ",
        f"{STATUS}: {Status.TODO.value}",
        f"{LABELS}: {', '.join(labels)}",
        f"# statuses: {', '.join(STATUSES)}",
        f"# labels: {known}",
        "# Write the body below the blank line. Leave the title and body empty to cancel.",
    ]
    return "\n".join(lines) + "\n\n"


def problems(item: Item, vocabulary: list[str]) -> list[str]:
    """What a hand edit got wrong, as short phrases for a table cell or a header."""
    found: list[str] = []
    if not item.title:
        found.append("no title")
    if item.status not in STATUSES:
        found.append(f"unknown status '{item.status}'" if item.status else "no status")
    unknown = [label for label in item.labels if label not in vocabulary]
    if unknown:
        found.append(f"unknown label {', '.join(repr(label) for label in unknown)}")
    return found


def check_labels(labels: list[str], vocabulary: list[str]) -> None:
    """Reject a label the config does not list, naming the ones it does."""
    for label in labels:
        if not LABEL_RE.match(label):
            raise ShadError.validation(
                "invalid_label",
                f"invalid label {label!r}; use lowercase letters, digits and hyphens"
            )
        if label not in vocabulary:
            known = ", ".join(vocabulary) if vocabulary else "none configured"
            raise ShadError.validation(
                "unknown_label",
                f"unknown label {label!r}; configured labels: {known}; "
                f"add it with 'shad todo label add {label}'"
            )
