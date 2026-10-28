"""Fixtures shared by the slice's tests. Not imported by the command."""

from __future__ import annotations

from pathlib import Path

from shad.sessions.harness import Conversation
from shad.sessions.live import Running
from shad.shared.config import Config, Defaults, Project

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
