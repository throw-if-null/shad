"""
What is running now: the shad tmux sessions, as snapshot entries.

Reads tmux and each harness's own session record. Nothing here writes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from shad.sessions import harness
from shad.sessions.harness import RunningSession
from shad.sessions.model import Entry
from shad.shared.config import Config, Project, all_projects
from shad.shared.tmux import (
    attached_sessions,
    list_project_sessions,
    split_session_name,
)


@dataclass(frozen=True)
class Skipped:
    session: str  # the tmux session name
    project: Project
    reason: str


@dataclass(frozen=True)
class Running:
    session: str  # the tmux session name
    entry: Entry


@dataclass
class Collected:
    running: list[Running] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)

    @property
    def entries(self) -> list[Entry]:
        return [running.entry for running in self.running]


def collect(cfg: Config) -> Collected:
    """
    Every running shad tmux session, in config order.

    A session whose conversation id cannot be determined is still an entry,
    without an id, so the project session itself is restored. A bare base
    session carries no harness segment and is recorded under the project's
    configured harness. A session of an unsupported harness is skipped.
    """
    attached = attached_sessions()
    collected = Collected()
    for project in all_projects(cfg):
        for session in list_project_sessions(project.session):
            scoped = split_session_name(project.session, session)
            if scoped is None:
                entry = _entry(project, project.harness, None, session in attached)
                collected.running.append(Running(session, entry))
                continue
            prefix, key = scoped
            name = _harness_for_prefix(prefix)
            support = harness.for_harness(name)
            if support is None:
                collected.skipped.append(
                    Skipped(session, project, f"the {name} harness is not supported")
                )
                continue
            running = RunningSession(tmux_session=session, key=key, project_path=project.path)
            session_id = support.live_session_id(running)
            entry = _entry(project, name, session_id, session in attached)
            collected.running.append(Running(session, entry))
    return collected


def _harness_for_prefix(prefix: str) -> str:
    name = harness.harness_for_prefix(prefix)
    if name is None:
        # list_project_sessions filters on the same table, so this is unreachable.
        raise ValueError(f"no harness uses the session prefix {prefix!r}")
    return name


def _entry(project: Project, harness_name: str, session_id: str | None, attached: bool) -> Entry:
    return Entry(
        group=project.group,
        key=project.key,
        harness=harness_name,
        session_id=session_id,
        attached=attached,
    )
