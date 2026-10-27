"""
What `shad sessions` needs from each harness.

Three things differ per harness: how the conversation a running pane holds is
identified, whether a saved id can still be resumed, and the command lines
that resume or start one. Everything else in the slice is harness-neutral and
reaches a harness only through `for_harness()`.

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

from shad.projects.open.sessions import claude_project_dir
from shad.shared.tmux import SESSION_PREFIXES

CLAUDE_SESSIONS_DIR = Path.home() / ".claude" / "sessions"

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")


@dataclass(frozen=True)
class RunningSession:
    """One shad tmux session, as `save` sees it."""

    tmux_session: str
    key: str | None  # the id segment of the tmux name; None for a bare base session
    project_path: Path


class Harness(Protocol):
    name: str

    def live_session_id(self, running: RunningSession) -> str | None:
        """
        The id of the conversation *running* holds now, or None when it
        cannot be determined. The tmux name's key is the id the session was
        opened with; the harness may have moved to another conversation
        since.
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

    def live_session_id(self, running: RunningSession) -> str | None:
        found = _claude_process_session(running.tmux_session)
        if found:
            return found
        if running.key and _UUID_RE.match(running.key):
            return running.key
        return None

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


def _claude_process_session(tmux_session: str) -> str | None:
    """
    The conversation id Claude Code records for its process in *tmux_session*.

    Claude Code 2.1 writes ~/.claude/sessions/<pid>.json for every running
    process, with the current `sessionId` and a `tmux` field of the form
    "<session>:@<window>.%<pane>". The record follows /clear and /resume,
    where the tmux session name keeps the id the pane was opened with.

    A record whose process has exited is ignored: Claude Code removes the
    file on a clean exit, but a killed process leaves it behind. When two
    live records name one tmux session, the later start wins, because a
    session stopped and reopened under the same name is the only way that
    happens.
    """
    best: tuple[int, str] | None = None
    try:
        files = list(CLAUDE_SESSIONS_DIR.glob("*.json"))
    except OSError:
        return None
    for path in files:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(record, dict):
            continue
        tmux = record.get("tmux")
        if not isinstance(tmux, str) or tmux.split(":", 1)[0] != tmux_session:
            continue
        pid = record.get("pid")
        session_id = record.get("sessionId")
        if not isinstance(pid, int) or not isinstance(session_id, str) or not session_id:
            continue
        if not _alive(pid):
            continue
        started = record.get("startedAt")
        started = started if isinstance(started, int) else 0
        if best is None or started > best[0]:
            best = (started, session_id)
    return best[1] if best else None


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
