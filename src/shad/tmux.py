"""
tmux as shad drives it: the invocation contract, the session-name table and
its round trip, and the queries whose parsing every slice must agree on.

`Tmux` is constructed once per run by the root from the environment and
injected. It holds no connection and no cache: each method is one
independent subprocess call, so one instance is shared-and-safe across
threads. The name functions are pure.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Mapping

from shad.errors import ShadError

_SESSION_KEY_RE = re.compile(r"[^A-Za-z0-9_-]+")

# The segment each harness puts in its scoped tmux session names,
# "<base>--<prefix>-<session key>". The pickers in projects/open set it per
# target, and shad.sessions maps a live name back to its harness through it.
SESSION_PREFIXES = {"opencode": "oc", "claude": "cc"}


def project_session_name(base_session: str, prefix: str, session_key: str | None) -> str:
    """The tmux session name for a project and a harness conversation."""
    if not session_key:
        return base_session
    sanitised = _SESSION_KEY_RE.sub("_", session_key).strip("_")
    if not sanitised:
        sanitised = "session"
    return f"{base_session}--{prefix}-{sanitised}"


def split_session_name(base_session: str, session: str) -> tuple[str, str] | None:
    """
    The (prefix, key) a scoped session name carries, or None for the bare
    base session. The inverse of project_session_name() for the names that
    `Tmux.list_project_sessions` returns; any other name raises ValueError.
    """
    if session == base_session:
        return None
    for prefix in SESSION_PREFIXES.values():
        head = f"{base_session}--{prefix}-"
        if session.startswith(head):
            return prefix, session[len(head):]
    raise ValueError(f"{session!r} is not a session of {base_session!r}")


class Tmux:
    """
    The tmux this run drives. *env* is the environment its processes get,
    read once: TMUX says whether shad runs inside tmux, which decides how
    `attach` reaches a session, and TMUX_TMPDIR, through it, which server.
    *socket* names a server outright (`-S`).
    """

    def __init__(self, env: Mapping[str, str], *, socket: str | None = None) -> None:
        self.env: dict[str, str] = dict(env)
        self.inside: bool = env.get("TMUX") is not None
        self.socket = socket

    def _argv(self, args: tuple[str, ...]) -> list[str]:
        argv = ["tmux"]
        if self.socket:
            argv += ["-S", self.socket]
        return argv + list(args)

    def run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        """
        One tmux command, output captured. A tmux that is not installed
        raises `infrastructure`/`tmux_missing`; with *check*, a non-zero
        exit raises `infrastructure`/`tmux_failed`.
        """
        try:
            return subprocess.run(
                self._argv(args), check=check, capture_output=True, text=True, env=self.env
            )
        except FileNotFoundError:
            raise ShadError.infrastructure(
                "tmux_missing", "tmux is not installed or not on PATH"
            ) from None
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or "").strip().splitlines()
            raise ShadError.infrastructure(
                "tmux_failed", f"tmux {args[0]} failed: {detail[0] if detail else exc.returncode}"
            ) from None

    def hand_over(self, *args: str) -> int:
        """One tmux command that takes the terminal; returns its exit status."""
        try:
            result = subprocess.run(self._argv(args), check=False, env=self.env)
        except FileNotFoundError:
            raise ShadError.infrastructure(
                "tmux_missing", "tmux is not installed or not on PATH"
            ) from None
        return result.returncode

    def attach(self, session: str) -> int:
        """Attach to *session*, or switch the client to it inside tmux. Returns the exit status."""
        if self.inside:
            return self.hand_over("switch-client", "-t", session)
        return self.hand_over("attach-session", "-t", session)

    def popup(self, command: str, *, width: int, height: int) -> int:
        """Run *command* in a popup over the current client; returns its exit status."""
        return self.hand_over("display-popup", "-E", "-w", str(width), "-h", str(height), command)

    def session_exists(self, name: str) -> bool:
        return self.run("has-session", "-t", name, check=False).returncode == 0

    def server_running(self) -> bool:
        """Whether a tmux server is running."""
        result = self.run("list-sessions", check=False)
        if result.returncode == 0:
            return True
        # tmux exits 1 with "no server running" or "no sessions" when the server
        # is not up. Only the explicit "no server" message is server-down; any
        # other non-zero exit (a socket permission error, say) is left as True
        # so the caller gets a real tmux error rather than a misleading status.
        return "no server running" not in result.stderr.lower()

    def list_project_sessions(self, base_session: str) -> list[str]:
        """The sessions of the project whose base session name is *base_session*."""
        result = self.run("list-sessions", "-F", "#S", check=False)
        if result.returncode != 0:
            return []
        scoped = tuple(f"{base_session}--{prefix}-" for prefix in SESSION_PREFIXES.values())
        return [
            line.strip()
            for line in result.stdout.splitlines()
            if line.strip() == base_session or line.strip().startswith(scoped)
        ]

    def attached_sessions(self) -> set[str]:
        """The sessions that have at least one client attached."""
        result = self.run("list-sessions", "-F", "#S\t#{session_attached}", check=False)
        if result.returncode != 0:
            return set()
        attached: set[str] = set()
        for line in result.stdout.splitlines():
            name, _, count = line.strip().rpartition("\t")
            if name and count.isdigit() and int(count) > 0:
                attached.add(name)
        return attached

    def pane_commands(self) -> dict[str, set[str]]:
        """The foreground command of every pane, grouped by session name."""
        result = self.run("list-panes", "-a", "-F", "#S\t#{pane_current_command}", check=False)
        if result.returncode != 0:
            return {}
        commands: dict[str, set[str]] = {}
        for line in result.stdout.splitlines():
            name, _, command = line.strip().rpartition("\t")
            if name:
                commands.setdefault(name, set()).add(command)
        return commands

    def current_session(self) -> str | None:
        """The session this process runs in, or None outside tmux."""
        if not self.inside:
            return None
        result = self.run("display-message", "-p", "#S", check=False)
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    def kill_session(self, session: str) -> None:
        """Kill exactly *session*; the `=` stops tmux from matching a prefix."""
        self.run("kill-session", "-t", f"={session}")

    @staticmethod
    def attach_command(session: str) -> list[str]:
        """The command a new terminal runs to attach exactly *session*."""
        return ["tmux", "attach-session", "-t", f"={session}"]
