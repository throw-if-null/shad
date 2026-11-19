"""
What is running now: every shad tmux session, with what its harness knows.

Reads tmux and each harness's own session record. Nothing here writes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from shad.config import Config, Project, all_projects
from shad.harness import Conversation, Harnesses, RunningSession, harness_for_prefix
from shad.sessions.model import Entry
from shad.tmux import Tmux, split_session_name


@dataclass(frozen=True)
class Running:
    session: str  # the tmux session name
    project: Project
    harness: str
    attached: bool
    harness_running: bool  # the harness process is still in one of the panes
    conversation: Conversation | None  # None when unknown, or the harness is unsupported
    unsupported: str | None = None  # why `save` cannot record this session

    @property
    def entry(self) -> Entry:
        conversation = self.conversation
        return Entry(
            group=self.project.group,
            key=self.project.key,
            harness=self.harness,
            session_id=conversation.id if conversation else None,
            attached=self.attached,
            name=conversation.name if conversation else None,
            title=conversation.title if conversation else None,
        )


def collect(cfg: Config, tmux: Tmux, harnesses: Harnesses) -> list[Running]:
    """
    Every running shad tmux session, in config order.

    A bare base session carries no harness segment and is recorded under the
    project's configured harness. The harness is asked for the conversation
    even then, because its own record is keyed by the tmux session, not by
    the name's key. A session of an unsupported harness has no conversation
    and says why in `unsupported`.
    """
    attached = tmux.attached_sessions()
    commands = tmux.pane_commands()
    found: list[Running] = []
    for project in all_projects(cfg):
        for session in tmux.list_project_sessions(project.session):
            scoped = split_session_name(project.session, session)
            if scoped is None:
                name, key = project.harness, None
            else:
                prefix, key = scoped
                name = _harness_for_prefix(prefix)
            support = harnesses.for_harness(name)
            conversation = None
            unsupported = None
            if support is None:
                unsupported = f"the {name} harness is not supported"
            else:
                running = RunningSession(
                    tmux_session=session, key=key, project_path=project.path
                )
                conversation = support.live_conversation(running)
            found.append(
                Running(
                    session=session,
                    project=project,
                    harness=name,
                    attached=session in attached,
                    harness_running=name in commands.get(session, set()),
                    conversation=conversation,
                    unsupported=unsupported,
                )
            )
    return found


def duplicates(running: Sequence[Running]) -> set[str]:
    """The tmux sessions whose conversation another live session also holds."""
    holders: dict[tuple[str, str], list[str]] = {}
    for live in running:
        if live.conversation is not None:
            holders.setdefault((live.harness, live.conversation.id), []).append(live.session)
    return {session for sessions in holders.values() if len(sessions) > 1 for session in sessions}


def _harness_for_prefix(prefix: str) -> str:
    name = harness_for_prefix(prefix)
    if name is None:
        # list_project_sessions filters on the same table, so this is unreachable.
        raise ValueError(f"no harness uses the session prefix {prefix!r}")
    return name
