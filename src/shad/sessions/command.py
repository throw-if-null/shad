"""`shad sessions`: the group parser; each action registers on it."""

from __future__ import annotations

import argparse

from shad import parsers
from shad.sessions.restore import command as restore
from shad.sessions.save import command as save
from shad.sessions.show import command as show
from shad.sessions.stop import command as stop


def register(sub: parsers.Subparsers) -> None:
    _, actions = parsers.group(
        sub,
        "sessions",
        dest="sessions_action",
        help="Save the running shad sessions, bring them back, or stop them",
        description=(
            "Save which shad sessions are running and recreate them later,\n"
            "for example after a reboot; or pick running sessions to stop.\n\n"
            "Actions:\n"
            "  save      pick the running sessions to record, with the\n"
            "            conversation each harness pane holds\n"
            "  restore   create each saved session that is not running, with\n"
            "            the harness resuming its conversation, then attach\n"
            "  stop      pick running sessions and kill them\n"
            "  show      print what is saved (--json: as JSON)\n\n"
            "save and stop show the same picker: one row per running session\n"
            "with the conversation's name and first prompt, whether it is\n"
            "attached, and whether its harness is busy, idle, or gone. Space\n"
            "toggles a row, a toggles all, Enter accepts, q cancels. In save\n"
            "the rows already in the snapshot start checked, or every row when\n"
            "there is no snapshot yet; the snapshot becomes exactly the\n"
            "selection. In stop nothing starts checked, and the session the\n"
            "command runs in is not listed.\n\n"
            "The snapshot is taken when save runs. Nothing keeps it current\n"
            "afterwards, and stop does not change it.\n\n"
            "Supported harness: claude. A session running opencode can be\n"
            "stopped but not saved; save lists it on stderr with the reason.\n\n"
            "restore attaches to the session that was attached when the\n"
            "snapshot was saved, else the first one. In kitty, each other\n"
            "session that was attached at save gets a tab of its own; this\n"
            "needs allow_remote_control yes in kitty.conf. --no-attach\n"
            "creates the sessions and returns, for use from a script.\n\n"
            "Examples:\n"
            "  shad sessions save\n"
            "  shad sessions save --all          every running session, no picker\n"
            "  shad sessions restore\n"
            "  shad sessions restore --no-attach\n"
            "  shad sessions stop\n"
            "  shad sessions show\n"
            "  shad sessions show --json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    for action in (save, restore, stop, show):
        action.register(actions)
