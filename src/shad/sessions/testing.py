"""
Fixtures shared by the slice's tests. Not imported by the command.

`running` and `CFG` build the in-memory rows the unit tests use.
`SessionsCase` is the slice as its users see it: projects on the test's
tmux server, with Claude Code's files under the test home.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from shad.sessions.harness import Conversation
from shad.sessions.live import Running
from shad.shared.config import Config, Defaults, Project
from shad.testing import Pane, TmuxCase

UUID_A = "11111111-1111-4111-8111-111111111111"
UUID_B = "22222222-2222-4222-8222-222222222222"

KB = Project(key="kb", group=None, path=Path("/p/kb"), session="kb", harness="claude")
SHAD = Project(key="shad", group="tin", path=Path("/p/shad"), session="tin-shad", harness="claude")
CFG = Config(defaults=Defaults(), projects={"kb": KB}, groups={"tin": {"shad": SHAD}})


def running(
    session: str,
    project: Project = KB,
    *,
    session_id: str | None = UUID_A,
    harness: str = "claude",
    attached: bool = False,
    harness_running: bool = True,
    name: str | None = None,
    title: str | None = None,
    status: str | None = None,
    status_since: int | None = None,
    unsupported: str | None = None,
) -> Running:
    conversation = None
    if session_id is not None:
        conversation = Conversation(
            id=session_id, name=name, title=title, status=status, status_since=status_since
        )
    return Running(
        session=session,
        project=project,
        harness=harness,
        attached=attached,
        harness_running=harness_running,
        conversation=conversation,
        unsupported=unsupported,
    )


# ── the sessions as processes, on the test's tmux server ──────────────────

CONFIG = """\
[defaults]
harness = "claude"

[projects.kb]
path = "{root}/kb"

[projects.tin.shad]
path = "{root}/tin/shad"
"""


def entry(
    key: str,
    session_id: str | None,
    *,
    group: str | None = None,
    attached: bool = False,
    name: str | None = None,
    title: str | None = None,
) -> dict:
    """One snapshot entry as the file spells it."""
    return {
        "group": group, "key": key, "harness": "claude", "session_id": session_id,
        "attached": attached, "name": name, "title": title,
    }


class SessionsCase(TmuxCase):
    """
    The projects kb and tin shad on claude, a fake claude and opencode on
    PATH, and the files `shad sessions` reads under the test home:
    Claude Code's process records and transcripts, and the snapshot in
    the data directory.
    """

    def setUp(self) -> None:
        super().setUp()
        for name in ("kb", "tin/shad"):
            (self.root / name).mkdir(parents=True)
        self.write_config(CONFIG.format(root=self.root))
        self.fake_harness("claude")
        self.fake_harness("opencode")
        self.records = self.home / ".claude" / "sessions"
        self.records.mkdir(parents=True)
        self.snapshot = self.data / "shad" / "sessions.json"

    def project_path(self, project: str) -> Path:
        return {"kb": self.root / "kb", "tin-shad": self.root / "tin" / "shad"}[project]

    def start_session(
        self,
        project: str,
        key: str | None,
        *,
        harness: str = "claude",
        conversation: str | None = None,
        name: str | None = None,
        status: str | None = None,
        title: str | None = "first prompt",
    ) -> str:
        """
        A tmux session as `shad projects` leaves it: named for *project*
        (its base session name) and *key* (the id segment, or None for the
        bare name), with the harness running in its pane. For claude, Claude
        Code's process record names *conversation* (*key* when not given),
        and a transcript holds *title* as the first prompt.
        """
        prefix = "cc" if harness == "claude" else "oc"
        session = f"{project}--{prefix}-{key}" if key else project
        # exec, or dash (/bin/sh on Debian) stays the pane's process around the harness.
        self.server.new_session(session, cwd=self.project_path(project), command=f"exec {harness}")
        deadline = time.monotonic() + 10
        while harness not in self.pane_commands(session):
            if time.monotonic() > deadline:
                raise AssertionError(f"{harness} is not running in {session}")
            time.sleep(0.05)
        if harness == "claude":
            conversation = conversation or key
            if conversation:
                self.write_record(session, conversation, name=name, status=status)
                if title:
                    self.write_transcript(project, conversation, title)
        return session

    def pane_pid(self, session: str) -> int:
        return int(self.server.tmux("display-message", "-p", "-t", session, "#{pane_pid}").stdout)

    def write_record(
        self,
        session: str,
        conversation: str,
        *,
        name: str | None = None,
        status: str | None = None,
        pid: int | None = None,
    ) -> None:
        """Claude Code's record for the process in *session*'s pane."""
        pid = pid or self.pane_pid(session)
        target = self.server.tmux(
            "display-message", "-p", "-t", session, "#S:#{window_id}.#{pane_id}"
        ).stdout.strip()
        now = int(time.time() * 1000)
        record: dict = {"pid": pid, "sessionId": conversation, "tmux": target, "startedAt": now}
        if name:
            record["name"] = name
        if status:
            record["status"] = status
            record["statusUpdatedAt"] = now
        (self.records / f"{pid}.json").write_text(json.dumps(record))

    def write_transcript(self, project: str, conversation: str, prompt: str) -> None:
        """A Claude Code transcript whose first user entry is *prompt*."""
        slug = re.sub(r"[^A-Za-z0-9]", "-", str(self.project_path(project)))
        directory = self.home / ".claude" / "projects" / slug
        directory.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"type": "user", "message": {"role": "user", "content": prompt}})
        (directory / f"{conversation}.jsonl").write_text(line + "\n")

    def write_snapshot(self, *entries: dict) -> None:
        self.snapshot.parent.mkdir(parents=True, exist_ok=True)
        self.snapshot.write_text(
            json.dumps({"format": 1, "saved_at": 1, "sessions": list(entries)}, indent=2) + "\n"
        )

    def read_snapshot(self) -> list[dict]:
        return json.loads(self.snapshot.read_text())["sessions"]

    def sessions_of(self, project: str) -> list[str]:
        return [name for name in self.server.sessions() if name.split("--")[0] == project]

    def pane_commands(self, session: str) -> list[str]:
        result = self.server.tmux("list-panes", "-t", session, "-F", "#{pane_current_command}")
        return result.stdout.split()

    def attach_client(self, session: str) -> Pane:
        """
        A tmux client attached to *session*, running in a pane of its own.
        What a user's terminal is to a session.
        """
        pane = Pane(
            self.server,
            ["tmux", "-S", str(self.server.socket), "-f", "/dev/null",
             "attach-session", "-t", f"={session}"],
            env=self.env, cwd=self.root,
        )
        deadline = time.monotonic() + 10
        while self.clients().get(session) is None:
            if time.monotonic() > deadline:
                raise AssertionError(f"no client attached to {session}; screen:\n{pane.screen()}")
            time.sleep(0.05)
        return pane

    def clients(self) -> dict[str, str]:
        """The session each client is on, by session: {session: client tty}."""
        result = self.server.tmux(
            "list-clients", "-F", "#{client_session} #{client_tty}", check=False
        )
        pairs = (line.split(" ", 1) for line in result.stdout.splitlines() if " " in line)
        return {session: tty for session, tty in pairs}

    def wait_for_client_on(self, session: str, *, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        while session not in self.clients():
            if time.monotonic() > deadline:
                raise AssertionError(f"no client reached {session}; clients: {self.clients()}")
            time.sleep(0.05)
