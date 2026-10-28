"""
What `shad sessions` needs from each harness.

Three things differ per harness: how the conversation a running pane holds is
identified and described, whether a saved id can still be resumed, and the
command lines that resume or start one. Everything else in the slice is
harness-neutral and reaches a harness only through `for_harness()`.

Claude Code is supported. OpenCode is not: a tmux session that runs it is
skipped by `save`, with the reason, and an entry naming it is skipped by
`restore`. To support it, add a class with the same methods and register it
in SUPPORTED.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from shad.projects.open.sessions import claude_project_dir, claude_session_title
from shad.shared.tmux import SESSION_PREFIXES

CLAUDE_SESSIONS_DIR = Path.home() / ".claude" / "sessions"

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")


@dataclass(frozen=True)
class RunningSession:
    """One shad tmux session, as `save` sees it."""

    tmux_session: str
    key: str | None  # the id segment of the tmux name; None for a bare base session
    project_path: Path


@dataclass(frozen=True)
class Conversation:
    """What a harness knows about one conversation. Only the id is required."""

    id: str
    name: str | None = None  # what the harness calls it
    title: str | None = None  # its first prompt
    status: str | None = None  # "busy" or "idle"; None when unknown
    status_since: int | None = None  # unix seconds the status was entered


class Harness(Protocol):
    name: str

    def live_conversation(self, running: RunningSession) -> Conversation | None:
        """
        The conversation *running* holds now, or None when it cannot be
        determined. The tmux name's key is the id the session was opened
        with; the harness may have moved to another conversation since.
        """

    def can_resume(self, project_path: Path, session_id: str) -> bool:
        """Whether *session_id* names a conversation of *project_path* that resumes."""

    def resume_command(self, base_cmd: str, session_id: str) -> str:
        """The command line that resumes *session_id*."""

    def fresh_command(self, base_cmd: str, session_id: str | None) -> str:
        """
        The command line for a new conversation, under *session_id* when the
        harness lets the caller choose the id.
        """

    def new_session_id(self) -> str | None:
        """An id for a new conversation, or None when the harness assigns its own."""


class Claude:
    name = "claude"

    def live_conversation(self, running: RunningSession) -> Conversation | None:
        record = _claude_process_record(running.tmux_session)
        if record is not None:
            return Conversation(
                id=record.session_id,
                name=record.name,
                title=self._title(running.project_path, record.session_id),
                status=record.status,
                status_since=record.status_since,
            )
        if running.key and _UUID_RE.match(running.key):
            return Conversation(
                id=running.key, title=self._title(running.project_path, running.key)
            )
        return None

    def _title(self, project_path: Path, session_id: str) -> str | None:
        return claude_session_title(claude_project_dir(project_path) / f"{session_id}.jsonl")

    def can_resume(self, project_path: Path, session_id: str) -> bool:
        return (claude_project_dir(project_path) / f"{session_id}.jsonl").is_file()

    def resume_command(self, base_cmd: str, session_id: str) -> str:
        return f"{base_cmd} --resume {session_id}"

    def fresh_command(self, base_cmd: str, session_id: str | None) -> str:
        if session_id is None:
            return base_cmd
        return f"{base_cmd} --session-id {session_id}"

    def new_session_id(self) -> str | None:
        return str(uuid.uuid4())


@dataclass(frozen=True)
class _Record:
    session_id: str
    started: int
    name: str | None
    status: str | None
    status_since: int | None


def _claude_process_record(tmux_session: str) -> _Record | None:
    """
    What Claude Code records about its process in *tmux_session*.

    Claude Code 2.1 writes ~/.claude/sessions/<pid>.json for every running
    process, with the current `sessionId`, the session's `name`, a `status`
    of busy or idle with `statusUpdatedAt`, and a `tmux` field of the form
    "<session>:@<window>.%<pane>". The record follows /clear and /resume,
    where the tmux session name keeps the id the pane was opened with.

    A record whose process has exited is ignored: Claude Code removes the
    file on a clean exit, but a killed process leaves it behind. When two
    live records name one tmux session, the later start wins, because a
    session stopped and reopened under the same name is the only way that
    happens.
    """
    best: _Record | None = None
    try:
        files = list(CLAUDE_SESSIONS_DIR.glob("*.json"))
    except OSError:
        return None
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        tmux = data.get("tmux")
        if not isinstance(tmux, str) or tmux.split(":", 1)[0] != tmux_session:
            continue
        pid = data.get("pid")
        session_id = data.get("sessionId")
        if not isinstance(pid, int) or not isinstance(session_id, str) or not session_id:
            continue
        if not _alive(pid):
            continue
        record = _Record(
            session_id=session_id,
            started=_int(data.get("startedAt")) or 0,
            name=_text(data.get("name")),
            status=_text(data.get("status")),
            status_since=_seconds(data.get("statusUpdatedAt")) or _seconds(data.get("updatedAt")),
        )
        if best is None or record.started > best.started:
            best = record
    return best


def _text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return " ".join(value.split())
    return None


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _seconds(millis: object) -> int | None:
    """Claude Code's timestamps are unix milliseconds."""
    value = _int(millis)
    return value // 1000 if value else None


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


SUPPORTED: dict[str, Harness] = {Claude.name: Claude()}


def for_harness(name: str) -> Harness | None:
    return SUPPORTED.get(name)


def harness_for_prefix(prefix: str) -> str | None:
    """The harness name whose tmux sessions carry *prefix*."""
    for name, candidate in SESSION_PREFIXES.items():
        if candidate == prefix:
            return name
    return None
