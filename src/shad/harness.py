"""
What shad knows about Claude Code and opencode as programs: where each keeps
its conversations, how a conversation is identified, resumed and started,
and what a running process reports about itself.

`Harnesses` is constructed once per run by the root from the home
directory, where both programs keep their files, and injected. Its `known`
holds both harnesses, for the pickers in `projects open`; its `supported`
holds the ones `shad sessions` can save and restore: Claude Code. To
support OpenCode there, implement `live_conversation` and `can_resume` on
`Opencode` and add it to `supported`.

Reads files other programs own and never writes them; shared-and-safe.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from shad.tmux import SESSION_PREFIXES

SESSION_LIMIT = 5

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")

# Claude Code writes one transcript per session. The first prompt is in the
# opening entries, so that scan stops well before the end of a long file.
_CLAUDE_TITLE_SCAN_LINES = 200

# The entry types that name a session: a /rename, and the name Claude Code
# generates. The name scan matches these bytes before it parses a line, because
# a transcript can be tens of megabytes.
_CLAUDE_NAME_FIELDS = {"custom-title": "customTitle", "ai-title": "aiTitle"}
_CLAUDE_NAME_MARKERS = tuple(f'"{kind}"'.encode() for kind in _CLAUDE_NAME_FIELDS)

_CLAUDE_SLUG_RE = re.compile(r"[^A-Za-z0-9]")

# Slash commands, hook output and pasted attachments are recorded as user
# entries wrapped in these tags. None of them is a prompt the user typed.
_CLAUDE_WRAPPER_RE = re.compile(
    r"^<(local-command-caveat|local-command-stdout|command-name|command-message"
    r"|command-args|bash-input|bash-stdout|bash-stderr|system-reminder)\b"
)


class Unreadable(Exception):
    """A session store exists but could not be read; the message says why."""


def is_uuid(value: str) -> bool:
    """Whether *value* is a conversation id Claude Code assigns."""
    return _UUID_RE.match(value) is not None


# ── recorded conversations, and the target that runs one ─────────────────


@dataclass
class Recorded:
    """One conversation a harness has on disk, as the pickers list it."""

    id: str
    title: str  # the first prompt
    updated: int  # epoch ms
    name: str | None = None  # Claude Code only; opencode's title is its name


@dataclass(frozen=True)
class Target:
    """
    What a harness pane runs, and the tmux session key that names it. A
    picker resolves a concrete key before returning, because the tmux
    session name is derived from it: a constant key would map every resumed
    conversation onto one tmux session.
    """

    command: str
    session_key: str | None = None
    fresh: bool = False
    session_prefix: str = "oc"


# ── Claude Code's transcripts, read by path ──────────────────────────────


def claude_session_title(transcript: Path) -> str | None:
    """The first real user prompt in *transcript*, or None if it has none.

    Entries flagged ``isMeta`` and the command wrappers Claude Code records for
    slash commands are not prompts the user typed, so they are skipped. A
    transcript with no prompt at all is an empty session and is not offered.
    """
    try:
        with transcript.open(encoding="utf-8") as handle:
            for _, line in zip(range(_CLAUDE_TITLE_SCAN_LINES), handle, strict=False):
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("type") != "user" or entry.get("isMeta"):
                    continue
                text = _claude_entry_text(entry)
                if text:
                    return text
    except OSError:
        return None
    return None


def claude_session_name(transcript: Path) -> str | None:
    """The session's name, or None if it has none.

    The name is the last ``custom-title`` entry (set by /rename), else the last
    ``ai-title`` entry. Either can be appended anywhere in the transcript, so
    the whole file is read.
    """
    latest: dict[str, str] = {}
    try:
        with transcript.open("rb") as handle:
            for line in handle:
                if not any(marker in line for marker in _CLAUDE_NAME_MARKERS):
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict):
                    continue
                kind = entry.get("type")
                if kind not in _CLAUDE_NAME_FIELDS:
                    continue
                value = entry.get(_CLAUDE_NAME_FIELDS[kind])
                if isinstance(value, str) and value.strip():
                    latest[kind] = " ".join(value.split())
    except OSError:
        return None
    return latest.get("custom-title") or latest.get("ai-title")


def _claude_entry_text(entry: dict) -> str | None:
    """The prompt text of a transcript user entry, or None."""
    content = entry.get("message", {}).get("content")
    if isinstance(content, str):
        blocks = [content]
    elif isinstance(content, list):
        blocks = [b.get("text", "") for b in content if b.get("type") == "text"]
    else:
        return None

    for block in blocks:
        text = " ".join(block.split())
        if text and not _CLAUDE_WRAPPER_RE.match(text):
            return text
    return None


# ── what `shad sessions` and the pickers need from a harness ─────────────


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
    prefix: str  # the segment of this harness's tmux session names

    def recorded(self, project_path: Path, limit: int = SESSION_LIMIT) -> list[Recorded]:
        """
        Up to *limit* most-recent conversations the harness has on disk for
        *project_path*, newest first. Raises Unreadable when its store
        exists but cannot be read.
        """

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


@dataclass(frozen=True)
class _Record:
    session_id: str
    started: int
    name: str | None
    status: str | None
    status_since: int | None


class Claude:
    name = "claude"
    prefix = SESSION_PREFIXES["claude"]

    def __init__(self, home: Path) -> None:
        """*home* is where Claude Code keeps `.claude/projects` and `.claude/sessions`."""
        self.projects_dir = home / ".claude" / "projects"
        self.sessions_dir = home / ".claude" / "sessions"

    def project_dir(self, project_path: Path) -> Path:
        """The transcript directory for *project_path*.

        Claude Code derives the directory name from the working directory by
        replacing every character outside [A-Za-z0-9] with a hyphen.
        """
        return self.projects_dir / _CLAUDE_SLUG_RE.sub("-", str(project_path))

    def recorded(self, project_path: Path, limit: int = SESSION_LIMIT) -> list[Recorded]:
        directory = self.project_dir(project_path)
        try:
            transcripts = sorted(
                directory.glob("*.jsonl"),
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            )
        except OSError as exc:
            raise Unreadable(f"could not read the Claude Code session directory: {exc}") from None

        sessions: list[Recorded] = []
        for transcript in transcripts:
            if len(sessions) == limit:
                break
            title = claude_session_title(transcript)
            if title is None:
                continue
            sessions.append(
                Recorded(
                    id=transcript.stem,
                    title=title,
                    updated=int(transcript.stat().st_mtime * 1000),
                    name=claude_session_name(transcript),
                )
            )
        return sessions

    def live_conversation(self, running: RunningSession) -> Conversation | None:
        record = self._process_record(running.tmux_session)
        if record is not None:
            return Conversation(
                id=record.session_id,
                name=record.name,
                title=self._title(running.project_path, record.session_id),
                status=record.status,
                status_since=record.status_since,
            )
        if running.key and is_uuid(running.key):
            return Conversation(
                id=running.key, title=self._title(running.project_path, running.key)
            )
        return None

    def _title(self, project_path: Path, session_id: str) -> str | None:
        return claude_session_title(self.project_dir(project_path) / f"{session_id}.jsonl")

    def can_resume(self, project_path: Path, session_id: str) -> bool:
        return (self.project_dir(project_path) / f"{session_id}.jsonl").is_file()

    def resume_command(self, base_cmd: str, session_id: str) -> str:
        return f"{base_cmd} --resume {session_id}"

    def fresh_command(self, base_cmd: str, session_id: str | None) -> str:
        if session_id is None:
            return base_cmd
        return f"{base_cmd} --session-id {session_id}"

    def new_session_id(self) -> str | None:
        return str(uuid.uuid4())

    def _process_record(self, tmux_session: str) -> _Record | None:
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
            files = list(self.sessions_dir.glob("*.json"))
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
            if not isinstance(pid, int) or not isinstance(session_id, str) or not is_uuid(session_id):
                continue
            if not _alive(pid):
                continue
            record = _Record(
                session_id=session_id,
                started=_int(data.get("startedAt")) or 0,
                name=_text(data.get("name")),
                status=_text(data.get("status")),
                status_since=_seconds(data.get("statusUpdatedAt"))
                or _seconds(data.get("updatedAt")),
            )
            if best is None or record.started > best.started:
                best = record
        return best


class Opencode:
    """
    opencode as the pickers drive it. Its sessions cannot be saved or
    restored: it keeps no process record, and it assigns every id itself,
    so a fresh session is named by the moment it was opened.
    """

    name = "opencode"
    prefix = SESSION_PREFIXES["opencode"]

    def __init__(self, home: Path) -> None:
        """*home* is where opencode keeps `.local/share/opencode/opencode.db`."""
        self.db_path = home / ".local" / "share" / "opencode" / "opencode.db"

    def recorded(self, project_path: Path, limit: int = SESSION_LIMIT) -> list[Recorded]:
        if not self.db_path.exists():
            return []
        try:
            with sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True) as con:
                cur = con.cursor()
                cur.execute(
                    """
                    SELECT s.id, s.title, s.time_updated
                    FROM session s
                    JOIN project p ON s.project_id = p.id
                    WHERE p.worktree = ?
                      AND s.time_archived IS NULL
                    ORDER BY s.time_updated DESC
                    LIMIT ?
                    """,
                    (str(project_path), limit),
                )
                rows = cur.fetchall()
            return [Recorded(id=r[0], title=r[1], updated=r[2]) for r in rows]
        except sqlite3.DatabaseError as exc:
            raise Unreadable(f"could not read the opencode session database: {exc}") from None

    def live_conversation(self, running: RunningSession) -> Conversation | None:
        return None

    def can_resume(self, project_path: Path, session_id: str) -> bool:
        return False

    def resume_command(self, base_cmd: str, session_id: str) -> str:
        return f"{base_cmd} -s {session_id}"

    def fresh_command(self, base_cmd: str, session_id: str | None) -> str:
        return base_cmd

    def new_session_id(self) -> str | None:
        return None


def resume_target(harness: Harness, base_cmd: str, session_id: str) -> Target:
    """The target that resumes *session_id* under *harness*."""
    return Target(
        command=harness.resume_command(base_cmd, session_id),
        session_key=session_id,
        session_prefix=harness.prefix,
    )


def fresh_target(harness: Harness, base_cmd: str) -> Target:
    """
    The target for a new conversation under *harness*. A harness that lets
    shad choose the id gets one, and the tmux session name is derived from
    it, so `shad sessions save` can map the session back to its
    conversation even without the harness's own process record. A harness
    that assigns its own id gets a unique `fresh-<hex>` key, which names
    the tmux session and nothing else, so two opens cannot collide.
    """
    session_id = harness.new_session_id()
    return Target(
        command=harness.fresh_command(base_cmd, session_id),
        session_key=session_id or f"fresh-{uuid.uuid4().hex}",
        fresh=True,
        session_prefix=harness.prefix,
    )


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


class Harnesses:
    """
    The harnesses this run knows, each reading its files under *home*.

    The root constructs one per run from the environment and injects it; a
    test constructs it on a temporary home.
    """

    def __init__(self, home: Path) -> None:
        self.claude = Claude(home)
        self.opencode = Opencode(home)
        # Every harness a project may be configured with, for the pickers.
        self.known: dict[str, Harness] = {
            self.opencode.name: self.opencode,
            self.claude.name: self.claude,
        }
        # The ones `shad sessions` can save and restore.
        self.supported: dict[str, Harness] = {self.claude.name: self.claude}

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Harnesses:
        """Built from HOME, else the account's home directory."""
        home = env.get("HOME")
        return cls(Path(home) if home else Path.home())

    def for_harness(self, name: str) -> Harness | None:
        """The harness `shad sessions` can save and restore under *name*, or None."""
        return self.supported.get(name)


def harness_for_prefix(prefix: str) -> str | None:
    """The harness name whose tmux sessions carry *prefix*."""
    for name, candidate in SESSION_PREFIXES.items():
        if candidate == prefix:
            return name
    return None
