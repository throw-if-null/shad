"""
Low-level tmux primitives for shad.

This module owns only stateless subprocess wrappers and session-name helpers.
Higher-level orchestration (open, stop) lives in the respective project slices.
"""

from __future__ import annotations

import os
import re
import subprocess


_SESSION_KEY_RE = re.compile(r"[^A-Za-z0-9_-]+")


def _run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=check, capture_output=True, text=True)


def session_exists(name: str) -> bool:
    result = _run(["tmux", "has-session", "-t", name], check=False)
    return result.returncode == 0


def project_session_name(base_session: str, target: object) -> str:
    """Resolve the tmux session name for a project and AI target."""
    session_key = getattr(target, "session_key", None)
    if not session_key:
        return base_session

    prefix = getattr(target, "session_prefix", "oc")
    sanitised = _SESSION_KEY_RE.sub("_", session_key).strip("_")
    if not sanitised:
        sanitised = "session"

    return f"{base_session}--{prefix}-{sanitised}"


def tmux_server_running() -> bool:
    """Return True if a tmux server is currently running."""
    result = _run(["tmux", "list-sessions"], check=False)
    if result.returncode == 0:
        return True
    # tmux exits 1 with "no server running" or "no sessions" when the server
    # is not up. Only treat the explicit "no server" message as server-down;
    # any other non-zero exit (e.g. socket permission error) is left as True
    # so the caller gets a real tmux error rather than a misleading status.
    return "no server running" not in result.stderr.lower()


def list_project_sessions(base_session: str) -> list[str]:
    """Return tmux sessions belonging to the project's base session name."""
    result = _run(["tmux", "list-sessions", "-F", "#S"], check=False)
    if result.returncode != 0:
        return []

    oc_prefix = f"{base_session}--oc-"
    cc_prefix = f"{base_session}--cc-"
    return [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip() == base_session
        or line.strip().startswith(oc_prefix)
        or line.strip().startswith(cc_prefix)
    ]


def _attach(session: str) -> int:
    """Attach or switch to the named tmux session. Returns the exit code."""
    inside_tmux = os.environ.get("TMUX") is not None

    if inside_tmux:
        cmd = ["tmux", "switch-client", "-t", session]
    else:
        cmd = ["tmux", "attach-session", "-t", session]

    result = subprocess.run(cmd)
    return result.returncode
