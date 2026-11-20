"""
`shad projects <name>` — open the project's tmux session.

By default a new conversation is opened. `--resume [ID]` resumes a
conversation (the most recent when no ID is given), `--pick` chooses one in
a picker, and `--harness` overrides the project's harness for this open.
Orchestration: choose the harness target, then create the layout or attach.
"""

from __future__ import annotations

import argparse

from shad.config import HARNESSES, Defaults, Project
from shad.errors import ShadError
from shad.harness import Harness, Harnesses, Target, fresh_target, resume_target
from shad.layout import create_session
from shad.projects.open.sessions import pick_target, recorded_or_note
from shad.tmux import Tmux, project_session_name

# --resume given with no id; distinct from --resume absent (None).
_MOST_RECENT = ""


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """The options of the `projects` line that open alone reads."""
    parser.add_argument(
        "--harness",
        choices=HARNESSES,
        help=(
            "Open with this harness instead of the project's configured one. "
            "Applies to open only; status ignores it."
        ),
    )
    how = parser.add_mutually_exclusive_group()
    how.add_argument(
        "--resume",
        nargs="?",
        const=_MOST_RECENT,
        metavar="ID",
        help="Resume a conversation by id, or the most recent when no id is given",
    )
    how.add_argument(
        "--pick",
        action="store_true",
        help="Choose the conversation in a picker (needs a terminal)",
    )


def open_project(
    project: Project,
    defaults: Defaults,
    tmux: Tmux,
    harnesses: Harnesses,
    *,
    harness: str | None = None,
    resume: str | None = None,
    pick: bool = False,
) -> int | None:
    """
    Open *project*'s session, creating it with the configured layout or
    attaching to the one the chosen conversation already runs in.

    *harness* overrides the project's configured harness for this open only.
    *resume* resumes a conversation (`""` for the most recent); *pick* opens
    the picker. With neither, a new conversation is opened. Returns the tmux
    exit code, or None when the picker was cancelled.
    """
    selected = harness or project.harness
    chosen = harnesses.known[selected]

    if pick:
        target = pick_target(chosen, project.path, selected)
        if target is None:
            return None  # the user cancelled the picker
    elif resume is not None:
        target = _resume_target(chosen, project, selected, resume)
    else:
        target = fresh_target(chosen, selected)

    session = project_session_name(project.session, target.session_prefix, target.session_key)

    # A fresh target's key is unique, so its session never exists yet; only a
    # resumed or picked conversation can already be running.
    if not target.fresh and tmux.session_exists(session):
        return tmux.attach(session)

    create_session(tmux, project, defaults, target.command, session)
    return tmux.attach(session)


def _resume_target(harness: Harness, project: Project, base_cmd: str, resume: str) -> Target:
    """The target that resumes *resume* (an id), or the most recent conversation."""
    if resume != _MOST_RECENT:
        return resume_target(harness, base_cmd, resume)
    sessions, note = recorded_or_note(harness, project.path)
    if not sessions:
        raise ShadError.not_found(
            "no_conversation",
            note
            or f"no conversation to resume in {project.display_name}; omit --resume to start one",
        )
    return resume_target(harness, base_cmd, sessions[0].id)
