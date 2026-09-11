"""
How shad invokes git.

Owns the subprocess contract and nothing of git's domain: no refs, no
branches, no worktrees. Every rule here exists because getting it wrong fails
silently rather than loudly.

Commands run as `git -C <absolute resolved path>`, never with cwd=. Git
discovery walks *upward*, so a configured path that is not a repository would
otherwise operate on an ancestor repository.

Callers decide from exit codes and plumbing formats, never from message text:
git messages are gettext-translated, `fetch.output = compact` rewrites ref
names, and `git branch` layout depends on terminal width.
"""

from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path

from shad.shared.errors import ShadError

# Minimum git that supports `worktree list --porcelain -z` and the
# locked/prunable annotations this module relies on for safety.
MIN_GIT = (2, 36)


# Timeouts in seconds, by call class.
T_PLUMBING = 15.0


T_STATUS = 60.0


T_LS_REMOTE = 20.0


T_FETCH = 120.0


T_MUTATE = 60.0


# Inherited git environment that would silently retarget every command at a
# different repository — e.g. when shad runs from inside a git hook, or from a
# tmux pane started by one.
_SCRUBBED = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_NAMESPACE",
    "GIT_PREFIX",
    "GIT_CONFIG",
    "GIT_CONFIG_PARAMETERS",
    "GIT_CONFIG_COUNT",
    "GIT_CEILING_DIRECTORIES",
)


# Read-only commands, which may run without taking optional locks.  This keeps
# `git status` from rewriting the index and avoids lock contention with the
# gitui pane shad itself spawns.  Its one side effect — stale stat data read as
# "modified" — fails in the safe direction.
_READ_ONLY = frozenset(
    {
        "rev-parse",
        "for-each-ref",
        "status",
        "merge-base",
        "rev-list",
        "show-ref",
        "ls-remote",
        "symbolic-ref",
        "remote",
        "config",
    }
)


class GitMissing(Exception):
    """git is not installed or not on PATH."""


def _is_read_only(args: list[str]) -> bool:
    """True when *args* names a git command that takes no locks it must keep."""
    if not args:
        return False
    if args[0] == "worktree":
        # `worktree list` is a read; prune and remove are mutations.
        return len(args) > 1 and args[1] == "list"
    return args[0] in _READ_ONLY


def _env(*, read_only: bool) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _SCRUBBED}
    # Never hang waiting for HTTPS credentials.
    env["GIT_TERMINAL_PROMPT"] = "0"
    # git messages are translated; pin them so errors are stable and reportable.
    env["LC_ALL"] = "C"
    env["LANGUAGE"] = ""
    env["GIT_PAGER"] = "cat"
    if read_only:
        env["GIT_OPTIONAL_LOCKS"] = "0"
    # GIT_CONFIG_NOSYSTEM, GIT_CONFIG_GLOBAL and GIT_SSH_COMMAND are left alone
    # on purpose: they carry credential helpers, proxies, url.*.insteadOf,
    # core.sshCommand and safe.directory.  Stripping them turns working repos
    # into failing ones.
    return env


def git(
    repo: Path | None, args: list[str], *, timeout: float = T_PLUMBING
) -> subprocess.CompletedProcess[str]:
    """
    Run one git command and return the completed process.

    Never raises on a non-zero exit — callers decide from the exit code.
    Raises GitMissing when git is not installed, and ShadError on timeout.
    """
    argv = ["git"]
    if repo is not None:
        argv += ["-C", str(repo)]
    argv += args

    read_only = _is_read_only(args)

    try:
        # start_new_session so a timeout can kill the whole process group:
        # `git fetch` spawns ssh / git-remote-https, which outlive a plain
        # kill of the direct child and keep the pipe open.
        with subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            env=_env(read_only=read_only),
            start_new_session=True,
        ) as proc:
            try:
                out, err = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                _kill_group(proc)
                out, err = proc.communicate()
                raise ShadError(f"git {' '.join(args)} timed out after {timeout:.0f}s")
            return subprocess.CompletedProcess(argv, proc.returncode, out, err)
    except FileNotFoundError:
        raise GitMissing("git is not installed or not on PATH") from None


def _kill_group(proc: subprocess.Popen[str]) -> None:
    try:
        pgid = os.getpgid(proc.pid)
    except ProcessLookupError:
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    except ProcessLookupError:
        pass


def first_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def git_version() -> tuple[int, int]:
    """Return (major, minor) of the git on PATH."""
    result = git(None, ["--version"])
    parts = result.stdout.split()
    # "git version 2.55.0" — also tolerates "2.39.5 (Apple Git-154)"
    for part in parts:
        bits = part.split(".")
        if len(bits) >= 2 and bits[0].isdigit() and bits[1].isdigit():
            return int(bits[0]), int(bits[1])
    raise ShadError(f"could not parse git version from: {result.stdout.strip()!r}")


def require_git() -> None:
    """Raise ShadError unless the git on PATH is new enough for this module."""
    try:
        found = git_version()
    except GitMissing as exc:
        raise ShadError(str(exc)) from None
    if found < MIN_GIT:
        raise ShadError(
            f"git {found[0]}.{found[1]} is too old; "
            f"shad git sync needs {MIN_GIT[0]}.{MIN_GIT[1]} or newer"
        )
