"""
The snapshot `shad sessions save` writes and `shad sessions restore` reads.

One entry per saved shad tmux session: the project it belongs to, the
harness it runs, that harness's conversation id when one was found, and the
conversation's name and first prompt as they were at save time, for display.
An entry without an id restores the project session with a new conversation.

The file is JSON: the stdlib has no TOML writer, and nothing edits it by
hand. This module does no I/O.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from shad.shared.errors import ShadError

FORMAT = 1


@dataclass(frozen=True)
class Entry:
    group: str | None
    key: str
    harness: str
    session_id: str | None
    attached: bool
    name: str | None = None
    title: str | None = None

    @property
    def display_name(self) -> str:
        return f"{self.group} {self.key}" if self.group else self.key


@dataclass(frozen=True)
class Snapshot:
    saved_at: int  # unix seconds
    entries: tuple[Entry, ...]


def serialize(snapshot: Snapshot) -> str:
    data = {
        "format": FORMAT,
        "saved_at": snapshot.saved_at,
        "sessions": [asdict(entry) for entry in snapshot.entries],
    }
    return json.dumps(data, indent=2) + "\n"


def parse(text: str) -> Snapshot:
    """Raises ShadError on anything serialize() would not have written."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ShadError(f"saved sessions are not valid JSON: {exc}") from None
    if not isinstance(data, dict):
        raise ShadError("saved sessions are not a JSON object")
    if data.get("format") != FORMAT:
        raise ShadError(f"saved sessions format {data.get('format')!r} is not supported")

    saved_at = data.get("saved_at")
    if not isinstance(saved_at, int):
        raise ShadError("saved sessions have no saved_at timestamp")
    raw_entries = data.get("sessions")
    if not isinstance(raw_entries, list):
        raise ShadError("saved sessions have no sessions list")

    entries = []
    for index, raw in enumerate(raw_entries):
        if not isinstance(raw, dict):
            raise ShadError(f"saved session {index} is not a JSON object")
        key = raw.get("key")
        group = raw.get("group")
        harness = raw.get("harness")
        session_id = raw.get("session_id")
        attached = raw.get("attached", False)
        if not isinstance(key, str) or not key:
            raise ShadError(f"saved session {index} has no project key")
        if group is not None and not isinstance(group, str):
            raise ShadError(f"saved session {index} has an invalid group")
        if not isinstance(harness, str) or not harness:
            raise ShadError(f"saved session {index} has no harness")
        if session_id is not None and not isinstance(session_id, str):
            raise ShadError(f"saved session {index} has an invalid session_id")
        if not isinstance(attached, bool):
            raise ShadError(f"saved session {index} has an invalid attached flag")
        name = raw.get("name")
        title = raw.get("title")
        if name is not None and not isinstance(name, str):
            raise ShadError(f"saved session {index} has an invalid name")
        if title is not None and not isinstance(title, str):
            raise ShadError(f"saved session {index} has an invalid title")
        entries.append(
            Entry(
                group=group,
                key=key,
                harness=harness,
                session_id=session_id,
                attached=attached,
                name=name,
                title=title,
            )
        )
    return Snapshot(saved_at=saved_at, entries=tuple(entries))
