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
# git panel pane shad itself spawns.  Its one side effect — stale stat data
# read as "modified" — fails in the safe direction.
_READ_ONLY = frozenset(
    {
        "rev-parse",
        "for-each-ref",
        "status",
        "describe",
        "log",
        "merge-base",
        "rev-list",
        "show-ref",
        "ls-remote",
        "symbolic-ref",
        "remote",
        "config",
    }
)


# git has two --format languages and they do not share escapes.  ref-filter
# (`for-each-ref`, `branch`, `tag`) spells a NUL `%00`; the pretty-format
# family (`log`, `show`, `stash list`, `reflog`) spells it `%x00` and emits
# `%00` as three literal characters.  Neither reports the other's spelling as
# an error: git exits 0, the separator never appears, and the parse yields
# plausible garbage rather than nothing.  _check_format_dialect makes that
# swap loud at the one place every git call passes through.
_REF_FILTER_FORMAT = frozenset({"for-each-ref", "branch", "tag"})


_PRETTY_FORMAT = frozenset({"log", "show", "reflog", "whatchanged", "stash", "rev-list"})


_FORMAT_FLAGS = ("--format", "--pretty")


class GitMissing(Exception):
    """git is not installed or not on PATH."""


def _is_read_only(args: list[str]) -> bool:
    """True when *args* names a git command that takes no locks it must keep."""
    if not args:
        return False
    if args[0] == "worktree":
        # `worktree list` is a read; prune and remove are mutations.
        return len(args) > 1 and args[1] == "list"
    if args[0] == "stash":
        # `stash list` is a read; push, pop, apply and drop are mutations.
        return len(args) > 1 and args[1] == "list"
    return args[0] in _READ_ONLY


def _formats(args: list[str]) -> list[str]:
    """Every --format / --pretty value in *args*, in either spelling."""
    found: list[str] = []
    for index, arg in enumerate(args):
        for flag in _FORMAT_FLAGS:
            if arg.startswith(f"{flag}="):
                found.append(arg[len(flag) + 1 :])
            elif arg == flag and index + 1 < len(args):
                found.append(args[index + 1])
    return found


def _check_format_dialect(args: list[str]) -> None:
    """
    Raise when a format uses the other command family's NUL escape.

    A caller contract violation, not a runtime condition: it can only happen
    by writing the wrong constant, it corrupts the parse silently, and no exit
    code or stderr reveals it. ValueError rather than ShadError because there
    is no user action that produces it and none that recovers from it.
    """
    if not args:
        return
    verb = args[0]
    if verb in _REF_FILTER_FORMAT:
        wrong, right = "%x00", "FMT_SEP (%00)"
    elif verb in _PRETTY_FORMAT:
        wrong, right = "%00", "LOG_SEP (%x00)"
    else:
        return

    for fmt in _formats(args):
        # "%x00" does not contain the substring "%00", so this test is exact
        # in both directions.
        if wrong in fmt:
            raise ValueError(
                f"git {verb}: format uses {wrong!r}, which this command emits "
                f"literally; use {right} instead — {fmt!r}"
            )


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

    _check_format_dialect(args)
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


def git_version_string() -> str:
    """The git version as git reports it, e.g. "2.55.0", or "" when unparseable."""
    result = git(None, ["--version"])
    if result.returncode != 0:
        return ""
    for part in first_line(result.stdout).split():
        bits = part.split(".")
        if len(bits) >= 2 and bits[0].isdigit() and bits[1].isdigit():
            return part
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
