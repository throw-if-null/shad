"""
What `shad sessions restore` would do for each saved entry.

This module decides and never creates: the one tmux write, the layout for
each step marked "resume" or "new", is applied by restore/command.py.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from shad.projects.open.sessions import OpencodeTarget
from shad.sessions import harness
from shad.sessions.live import Running
from shad.sessions.model import Entry, Snapshot
from shad.shared.config import Config, Project
from shad.shared.tmux import SESSION_PREFIXES, project_session_name, session_exists

Outcome = Literal["resume", "new", "running", "skipped"]


@dataclass(frozen=True)
class Step:
    entry: Entry
    outcome: Outcome
    reason: str = ""
    project: Project | None = None
    session: str | None = None  # the tmux session name
    command: str | None = None  # what the harness pane runs

    @property
    def creates(self) -> bool:
        return self.outcome in ("resume", "new")


def plan(cfg: Config, snapshot: Snapshot, running: Sequence[Running]) -> list[Step]:
    """
    One step per entry, in saved order. *running* is what `live.collect`
    found now.

      resume    the saved conversation is resumed in a new tmux session
      new       a new conversation; the reason says why the saved one is not
      running   the conversation, or a tmux session of the name restore
                would use, exists; it is left alone
      skipped   nothing can be created; the reason says why
    """
    return [_step(cfg, entry, running) for entry in snapshot.entries]


def _step(cfg: Config, entry: Entry, running: Sequence[Running]) -> Step:
    project = _find_project(cfg, entry)
    if project is None:
        return Step(entry, "skipped", reason="project is no longer configured")
    support = harness.for_harness(entry.harness)
    if support is None:
        return Step(entry, "skipped", reason=f"the {entry.harness} harness is not supported")

    live = _holding(running, entry)
    if live is not None:
        return Step(entry, "running", project=project, session=live.session)

    outcome: Outcome
    reason = ""
    if entry.session_id and support.can_resume(project.path, entry.session_id):
        session_id: str | None = entry.session_id
        command = support.resume_command(entry.harness, entry.session_id)
        outcome = "resume"
    else:
        # Keep a saved id even when it has no transcript: the harness starts
        # the conversation under it, so the tmux name stays the same across
        # restores.
        session_id = entry.session_id or support.new_session_id()
        command = support.fresh_command(entry.harness, session_id)
        outcome = "new"
        reason = (
            f"no transcript for {entry.session_id}"
            if entry.session_id
            else "no conversation id was saved"
        )

    target = OpencodeTarget(
        command=command,
        session_key=session_id,
        session_prefix=SESSION_PREFIXES[entry.harness],
    )
    session = project_session_name(project.session, target)
    if session_exists(session):
        return Step(entry, "running", project=project, session=session)
    return Step(
        entry, outcome, reason=reason, project=project, session=session, command=command
    )


def _holding(running: Sequence[Running], entry: Entry) -> Running | None:
    """
    The live session that holds the saved conversation, if any.

    Matched on the harness's id, not on the tmux name: the live session may
    carry a different name (a `fresh-` key, or an id superseded by /clear or
    /resume), and a second process on one conversation must never be
    created.
    """
    if entry.session_id is None:
        return None
    for live in running:
        if (
            live.harness == entry.harness
            and live.conversation is not None
            and live.conversation.id == entry.session_id
        ):
            return live
    return None


def _find_project(cfg: Config, entry: Entry) -> Project | None:
    if entry.group is None:
        return cfg.projects.get(entry.key)
    return cfg.groups.get(entry.group, {}).get(entry.key)


def attach_target(steps: list[Step]) -> str | None:
    """
    The session to attach after the steps are applied: the first one that was
    attached when the snapshot was saved, else the first one that exists now.
    """
    present = [step for step in steps if step.session and step.outcome != "skipped"]
    for step in present:
        if step.entry.attached:
            return step.session
    return present[0].session if present else None


def tab_targets(steps: list[Step], attach: str, attached_now: set[str]) -> list[Step]:
    """
    The steps whose session gets a terminal tab of its own, in saved order:
    attached when the snapshot was saved, other than *attach*, which the
    current terminal takes. A session in *attached_now* already has a
    client, and a second one would mirror it, so it gets no tab.
    """
    return [
        step
        for step in steps
        if step.session
        and step.outcome != "skipped"
        and step.entry.attached
        and step.session != attach
        and step.session not in attached_now
    ]
