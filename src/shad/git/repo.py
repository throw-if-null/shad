"""
Low-level git primitives for shad.

This module owns only stateless subprocess wrappers, output parsing, and the
result dataclasses they produce.  Higher-level orchestration lives in
shad.git.command; all rendering lives in shad.git.report.

Every command runs as `git -C <absolute resolved path> ...` — never with
cwd=, because git discovery walks *upward* and a configured path that is not
a repository would then silently operate on an ancestor repository.

Decisions are made from exit codes and plumbing formats, never from message
text: git messages are gettext-translated, `fetch.output = compact` rewrites
ref names, and `git branch` layout depends on terminal width.
"""

from __future__ import annotations

import os
import signal
import subprocess
from dataclasses import dataclass, field
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

# What we split git output on, and what we ask git to emit as a separator.
# `%00` is git's own escape; a real NUL cannot be passed in argv.
NUL = "\x00"
FMT_SEP = "%00"


# ── result types ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Repo:
    """A resolved git repository, rooted at its main worktree."""

    root: Path  # main worktree (or the configured path when it is the main one)
    common_dir: Path  # resolved --git-common-dir; the repo identity for dedupe
    shallow: bool = False
    relinked_from: Path | None = None  # set when the configured path was a linked worktree


@dataclass(frozen=True)
class BranchRef:
    """One entry of `for-each-ref refs/heads`."""

    refname: str  # refs/heads/<name>
    oid: str
    upstream: str  # refs/remotes/<remote>/<name>, or "" when unset
    remotename: str  # "origin", "." for a local-tracking branch, or ""
    trackshort: str  # ">" ahead, "<" behind, "<>" diverged, "=" in sync, "" unknown

    @property
    def name(self) -> str:
        return self.refname[len("refs/heads/") :]

    @property
    def short_oid(self) -> str:
        return self.oid[:7]


@dataclass(frozen=True)
class Worktree:
    """One record of `worktree list --porcelain -z`."""

    path: Path
    head: str | None = None
    branch: str | None = None  # full refname, None when detached or bare
    bare: bool = False
    detached: bool = False
    locked: bool = False
    locked_reason: str = ""
    prunable: bool = False
    prunable_reason: str = ""


@dataclass(frozen=True)
class FetchResult:
    ok: bool
    pruned: list[str] = field(default_factory=list)  # short names, e.g. "origin/feat/x"
    error: str | None = None


@dataclass(frozen=True)
class FastForward:
    branch: str
    status: str  # "advanced" | "current" | "skipped"
    before: str | None = None
    after: str | None = None
    ahead: int = 0
    detail: str | None = None


@dataclass(frozen=True)
class BranchInfo:
    """A branch the plan intends to delete."""

    name: str
    sha: str
    reason: str  # "merged" | "pushed-then-gone"
    force: bool = False  # -D rather than -d


@dataclass(frozen=True)
class BranchKept:
    """A branch deliberately not deleted, and why."""

    name: str
    sha: str
    reason: str


def short_branch(refname: str | None) -> str:
    """Strip the refs/heads/ prefix for display."""
    if not refname:
        return ""
    return refname.removeprefix("refs/heads/")


@dataclass(frozen=True)
class WorktreeInfo:
    """A worktree the plan intends to remove or prune."""

    path: Path
    branch: str | None
    reason: str  # "prunable" | "branch gone" | "branch merged"
    prune_only: bool = False  # directory is gone; `worktree prune` handles it

    @property
    def branch_name(self) -> str:
        return short_branch(self.branch)


@dataclass(frozen=True)
class WorktreeKept:
    path: Path
    branch: str | None
    reason: str

    @property
    def branch_name(self) -> str:
        return short_branch(self.branch)


# ── subprocess ────────────────────────────────────────────────────────────


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


# ── repository detection ──────────────────────────────────────────────────


class NotUsable(Exception):
    """This path cannot be synced. The message is shown to the user as-is."""


def discover(path: Path) -> Repo:
    """
    Resolve *path* to the repository shad should operate on.

    Raises NotUsable with a user-facing reason when the path cannot be synced.
    A linked worktree is re-rooted onto its main worktree, because refs,
    remotes and the worktree list belong to the shared repository — git has no
    worktree-scoped fetch.
    """
    if not path.is_dir():
        raise NotUsable("path does not exist")

    here = path.resolve()

    flags = git(
        here,
        [
            "rev-parse",
            "--is-bare-repository",
            "--is-inside-work-tree",
            "--is-inside-git-dir",
            "--is-shallow-repository",
        ],
    )
    if flags.returncode != 0:
        stderr = flags.stderr.lower()
        if "not a git repository" in stderr:
            raise NotUsable("not a git repository")
        if "dubious ownership" in stderr:
            raise NotUsable(
                f"{first_line(flags.stderr)}\n"
                f"       git config --global --add safe.directory {here}"
            )
        raise NotUsable(first_line(flags.stderr) or "git rev-parse failed")

    values = flags.stdout.split()
    if len(values) != 4:
        raise NotUsable("unexpected git rev-parse output")
    is_bare, _in_worktree, in_git_dir, is_shallow = (v == "true" for v in values)

    if in_git_dir:
        raise NotUsable("path points inside a .git directory")
    if is_bare:
        raise NotUsable("bare repository: not supported")

    paths = git(
        here,
        [
            "rev-parse",
            "--path-format=absolute",
            "--show-toplevel",
            "--git-dir",
            "--git-common-dir",
        ],
    )
    if paths.returncode != 0:
        raise NotUsable(first_line(paths.stderr) or "git rev-parse failed")

    lines = paths.stdout.splitlines()
    if len(lines) != 3:
        raise NotUsable("unexpected git rev-parse output")
    toplevel, git_dir, common_dir = (Path(v.strip()).resolve() for v in lines)

    if here != toplevel:
        # Never retarget to the toplevel: a project path that was never cloned
        # would otherwise have branches deleted in whatever repo contains it.
        raise NotUsable(
            f"is inside repository {toplevel} but is not its root\n"
            f"       fix the project path, or sync {toplevel} instead"
        )

    if git_dir == common_dir:
        return Repo(root=toplevel, common_dir=common_dir, shallow=is_shallow)

    # Linked worktree: re-root onto the main worktree, which git lists first.
    worktrees = list_worktrees(toplevel)
    if not worktrees:
        raise NotUsable("could not list worktrees")
    return Repo(
        root=worktrees[0].path,
        common_dir=common_dir,
        shallow=is_shallow,
        relinked_from=toplevel,
    )


_IN_PROGRESS = (
    ("MERGE_HEAD", "merge"),
    ("rebase-merge", "rebase"),
    ("rebase-apply", "rebase"),
    ("CHERRY_PICK_HEAD", "cherry-pick"),
    ("REVERT_HEAD", "revert"),
    ("BISECT_LOG", "bisect"),
)


def in_progress(worktree: Path) -> str | None:
    """
    Return the name of an operation in progress in *worktree*, or None.

    The marker files are per-worktree (they live in .git/worktrees/<id>/), so
    they must be located with --git-path rather than assumed under .git/.
    git status does not report in-progress state at all.
    """
    args = ["rev-parse", "--path-format=absolute"]
    for marker, _ in _IN_PROGRESS:
        args += ["--git-path", marker]

    result = git(worktree, args)
    if result.returncode != 0:
        return None

    lines = result.stdout.splitlines()
    if len(lines) != len(_IN_PROGRESS):
        return None
    for (_, label), line in zip(_IN_PROGRESS, lines, strict=True):
        if Path(line.strip()).exists():
            return label
    return None


def head_branch(worktree: Path) -> str | None:
    """Full refname of the branch HEAD points at, or None when detached."""
    result = git(worktree, ["symbolic-ref", "--quiet", "HEAD"])
    return result.stdout.strip() if result.returncode == 0 else None


def is_clean(worktree: Path, *, untracked: bool) -> tuple[bool, int, int]:
    """
    Return (clean, changed, untracked_count) for *worktree*.

    `untracked=True` mirrors what `git worktree remove` itself checks, so a
    removal preview never disagrees with the outcome.
    """
    result = git(
        worktree,
        [
            "status",
            "--porcelain=v2",
            f"--untracked-files={'all' if untracked else 'no'}",
            "--ignore-submodules=none",
        ],
        timeout=T_STATUS,
    )
    if result.returncode != 0:
        # Treat an unreadable status as dirty — failing safe.
        return False, 0, 0

    changed = untracked_count = 0
    for line in result.stdout.splitlines():
        if not line:
            continue
        if line.startswith("? "):
            untracked_count += 1
        elif line[0] in "12u":
            changed += 1
    return (changed + untracked_count) == 0, changed, untracked_count


# ── refs ──────────────────────────────────────────────────────────────────


def snapshot_remotes(repo: Path) -> tuple[dict[str, str], set[str]]:
    """
    Return ({refname: oid} for refs/remotes, {symbolic refnames}).

    Fields are NUL-separated and records newline-terminated, which is safe:
    git ref names cannot contain newlines or control characters.
    """
    result = git(
        repo,
        [
            "for-each-ref",
            f"--format=%(refname){FMT_SEP}%(objectname){FMT_SEP}%(symref)",
            "refs/remotes",
        ],
    )
    refs: dict[str, str] = {}
    symrefs: set[str] = set()
    if result.returncode != 0:
        return refs, symrefs

    for line in result.stdout.splitlines():
        if not line:
            continue
        parts = line.split(NUL)
        if len(parts) != 3:
            continue
        refname, oid, symref = parts
        refs[refname] = oid
        if symref:
            symrefs.add(refname)
    return refs, symrefs


def list_branches(repo: Path) -> list[BranchRef]:
    """
    Enumerate refs/heads with upstream and tracking state.

    Uses %(upstream:trackshort) rather than %(upstream:track): the latter's
    "[gone]" and "ahead N" strings are gettext msgids. %(worktreepath) is
    deliberately absent — it is a filesystem path, which unlike a ref name can
    contain a newline and would corrupt the record stream. Checked-out state
    comes from list_worktrees instead.
    """
    fmt = FMT_SEP.join(
        (
            "%(refname)",
            "%(objectname)",
            "%(upstream)",
            "%(upstream:remotename)",
            "%(upstream:trackshort)",
        )
    )
    result = git(repo, ["for-each-ref", f"--format={fmt}", "refs/heads"])
    if result.returncode != 0:
        return []

    branches: list[BranchRef] = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        parts = line.split(NUL)
        if len(parts) != 5:
            continue
        refname, oid, upstream, remotename, trackshort = parts
        branches.append(
            BranchRef(
                refname=refname,
                oid=oid,
                upstream=upstream,
                remotename=remotename,
                trackshort=trackshort,
            )
        )
    return branches


def ref_oid(repo: Path, refname: str) -> str | None:
    """Current OID of *refname*, or None when it does not exist."""
    result = git(repo, ["for-each-ref", "--format=%(objectname)", refname])
    oid = result.stdout.strip()
    return oid or None


def ref_exists(repo: Path, refname: str) -> bool:
    return git(repo, ["show-ref", "--verify", "--quiet", refname]).returncode == 0


def is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool | None:
    """
    True when *ancestor* is reachable from *descendant*.

    Returns None when git cannot answer (exit 128, e.g. a garbage-collected
    OID) so callers can treat "unknown" as "do not delete".
    """
    result = git(repo, ["merge-base", "--is-ancestor", ancestor, descendant])
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    return None


def ahead_behind(repo: Path, left: str, right: str) -> tuple[int, int]:
    """Commits on *left* not on *right*, and vice versa."""
    result = git(repo, ["rev-list", "--left-right", "--count", f"{left}...{right}"])
    parts = result.stdout.split()
    if result.returncode != 0 or len(parts) != 2:
        return 0, 0
    return int(parts[0]), int(parts[1])


def count_commits(repo: Path, old: str, new: str) -> int:
    result = git(repo, ["rev-list", "--count", f"{old}..{new}"])
    value = result.stdout.strip()
    return int(value) if result.returncode == 0 and value.isdigit() else 0


def any_ref_contains(repo: Path, oid: str) -> bool:
    """True when *oid* is reachable from at least one ref."""
    result = git(
        repo, ["for-each-ref", "--count=1", f"--contains={oid}", "--format=%(refname)"]
    )
    return result.returncode == 0 and bool(result.stdout.strip())


# ── worktrees ─────────────────────────────────────────────────────────────


def list_worktrees(repo: Path) -> list[Worktree]:
    """
    Parse `worktree list --porcelain -z`.

    Records are NUL-terminated attribute lines ending at an empty element;
    each attribute splits on the first space. -z is required: without it a
    `locked` reason is C-quoted per core.quotePath and an exotic path breaks
    the framing. The main worktree is listed first.
    """
    result = git(repo, ["worktree", "list", "--porcelain", "-z"])
    if result.returncode != 0:
        return []

    worktrees: list[Worktree] = []
    record: dict[str, str | None] = {}

    def flush() -> None:
        if not record.get("worktree"):
            record.clear()
            return
        raw = record.get("worktree")
        assert raw is not None
        worktrees.append(
            Worktree(
                path=Path(raw),
                head=record.get("HEAD"),
                branch=record.get("branch"),
                bare="bare" in record,
                detached="detached" in record,
                locked="locked" in record,
                locked_reason=record.get("locked") or "",
                prunable="prunable" in record,
                prunable_reason=record.get("prunable") or "",
            )
        )
        record.clear()

    for element in result.stdout.split(NUL):
        if not element:
            flush()
            continue
        label, _, value = element.partition(" ")
        record[label] = value or None
    flush()

    return worktrees


# ── remote and default branch ─────────────────────────────────────────────


def list_remotes(repo: Path) -> list[str]:
    result = git(repo, ["remote"])
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def primary_remote(remotes: list[str]) -> str | None:
    """The remote to sync against, or None when it is ambiguous."""
    if len(remotes) == 1:
        return remotes[0]
    if "origin" in remotes:
        return "origin"
    return None


def has_full_refspec(repo: Path, remote: str) -> bool:
    """
    True when *remote* fetches every branch into refs/remotes/<remote>/*.

    With a narrowed refspec (a --single-branch clone), `origin/foo` is absent
    because it was never fetched, not because the server deleted it — so
    upstream-gone deletion must be disabled for that remote.
    """
    result = git(repo, ["config", "--get-all", f"remote.{remote}.fetch"])
    if result.returncode != 0:
        return False
    want = f":refs/remotes/{remote}/*"
    return any(line.rstrip().endswith(want) for line in result.stdout.splitlines())


def default_branch(repo: Path, remote: str, *, allow_network: bool = True) -> str | None:
    """
    Resolve the default branch name, first success wins.

    A dangling refs/remotes/<remote>/HEAD still resolves, so the symref answer
    is only trusted when the branch it names actually exists — otherwise an
    upstream master->main rename leaves the stale answer in place forever.
    """
    prefix = f"refs/remotes/{remote}/"
    result = git(repo, ["symbolic-ref", "--quiet", f"{prefix}HEAD"])
    if result.returncode == 0:
        target = result.stdout.strip()
        if target.startswith(prefix):
            name = target[len(prefix) :]
            if ref_exists(repo, f"{prefix}{name}"):
                return name

    if allow_network:
        result = git(repo, ["ls-remote", "--symref", remote, "HEAD"], timeout=T_LS_REMOTE)
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if line.startswith("ref: "):
                    ref = line[len("ref: ") :].split("\t", 1)[0].strip()
                    if ref.startswith("refs/heads/"):
                        return ref[len("refs/heads/") :]

    for candidate in ("main", "master"):
        if ref_exists(repo, f"{prefix}{candidate}"):
            return candidate
    for candidate in ("main", "master"):
        if ref_exists(repo, f"refs/heads/{candidate}"):
            return candidate
    return None


# ── mutations ─────────────────────────────────────────────────────────────


def fetch(repo: Path, remote: str, *, prune: bool) -> FetchResult:
    """
    Fetch from *remote*, optionally pruning stale remote-tracking refs.

    Always a real fetch, including under `shad git sync --dry-run`: it touches
    only remote-tracking refs, never a local branch, worktree, or working tree,
    and skipping it would leave the whole classification computed against
    stale refs.

    `prune` is False under --dry-run, because pruning is a one-shot event.
    A pruned ref takes its reflog with it, so its last-known OID — which the
    gone-branch rule needs — cannot be recovered afterwards. Pruning during a
    preview would consume that evidence and leave the real run unable to make
    the deletion the preview promised. remote_branch_refs() supplies the same
    answer without destroying anything.

    No --prune-tags (it deletes local-only tags), no explicit refspec (it would
    prune against a refspec the repo does not have), no --atomic (partial
    progress beats aborting everything).
    """
    args = ["fetch", "--no-recurse-submodules", "--no-auto-gc", "--quiet"]
    if prune:
        args.append("--prune")
    args += ["--", remote]

    try:
        result = git(repo, args, timeout=T_FETCH)
    except ShadError as exc:
        return FetchResult(ok=False, error=str(exc))

    if result.returncode != 0:
        return FetchResult(ok=False, error=first_line(result.stderr) or "git fetch failed")
    return FetchResult(ok=True)


def remote_branch_refs(repo: Path, remote: str) -> set[str] | None:
    """
    The branches *remote* actually has, named as local remote-tracking refs.

    Used to answer "what would --prune remove?" without removing it. Returns
    None when the remote cannot be reached, so callers can tell "no stale refs"
    from "could not ask".
    """
    result = git(repo, ["ls-remote", "--heads", remote], timeout=T_LS_REMOTE)
    if result.returncode != 0:
        return None

    refs: set[str] = set()
    for line in result.stdout.splitlines():
        _oid, _, refname = line.partition("\t")
        refname = refname.strip()
        if refname.startswith("refs/heads/"):
            refs.add(f"refs/remotes/{remote}/{refname[len('refs/heads/') :]}")
    return refs


def fast_forward_checked_out(worktree: Path, upstream_ref: str) -> str | None:
    """Fast-forward the branch checked out in *worktree*. Returns an error, or None."""
    result = git(
        worktree,
        ["merge", "--ff-only", "--no-stat", "--quiet", upstream_ref],
        timeout=T_MUTATE,
    )
    if result.returncode != 0:
        return first_line(result.stderr) or "git merge --ff-only failed"
    return None


def fast_forward_unchecked(repo: Path, branch: str, upstream_ref: str) -> str | None:
    """
    Fast-forward a branch that is not checked out anywhere.

    Uses a refspec fetch from `.` rather than update-ref: the refspec has no
    leading '+', so the ref backend enforces fast-forward-only, and git fetch
    refuses to move a branch checked out in a worktree. update-ref has neither
    guard and would desynchronise that worktree's HEAD and index. Source '.'
    means no network — the remote-tracking ref is already current.
    """
    result = git(
        repo,
        [
            "fetch",
            "--no-write-fetch-head",
            "--quiet",
            "--",
            ".",
            f"{upstream_ref}:refs/heads/{branch}",
        ],
        timeout=T_MUTATE,
    )
    if result.returncode != 0:
        return first_line(result.stderr) or "fast-forward failed"
    return None


def delete_branch(repo: Path, name: str, *, force: bool) -> str | None:
    """Delete a local branch. Returns an error message, or None on success."""
    if name.startswith("-"):
        return "refusing to delete a branch whose name starts with '-'"
    args = ["branch", "--delete"]
    if force:
        args.append("--force")
    args.append(name)
    result = git(repo, args, timeout=T_MUTATE)
    if result.returncode != 0:
        return first_line(result.stderr) or "git branch --delete failed"
    return None


def remove_worktree(repo: Path, path: Path) -> str | None:
    """Remove a worktree. Never passes --force. Returns an error, or None."""
    result = git(repo, ["worktree", "remove", "--", str(path)], timeout=T_MUTATE)
    if result.returncode != 0:
        return first_line(result.stderr) or "git worktree remove failed"
    return None


def prune_worktrees(repo: Path) -> str | None:
    """Drop admin records whose directory is gone. Touches no working tree."""
    result = git(repo, ["worktree", "prune"], timeout=T_MUTATE)
    if result.returncode != 0:
        return first_line(result.stderr) or "git worktree prune failed"
    return None



# ── classification ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BranchPlan:
    delete: list[BranchInfo] = field(default_factory=list)
    keep: list[BranchKept] = field(default_factory=list)


@dataclass(frozen=True)
class WorktreePlan:
    remove: list[WorktreeInfo] = field(default_factory=list)
    keep: list[WorktreeKept] = field(default_factory=list)


def classify_branch(
    repo: Path,
    branch: BranchRef,
    *,
    default_tips: list[str],
    checked_out: dict[str, Path],
    pruned_oids: dict[str, str],
    gone_allowed: bool,
    shallow: bool,
) -> BranchInfo | BranchKept:
    """
    Decide the fate of one local branch.

    The rule: delete iff the branch is not protected AND either (a) its tip is
    reachable from a default tip, or (b) its upstream was pruned in *this* run
    and its tip was reachable from that ref's last-known OID.

    Clause (b) is what makes squash-merged PR branches deletable. `git branch
    -d` falls back to "merged into HEAD" once the upstream ref is gone, so it
    refuses them — by commit ancestry a squash-merged branch really is
    unmerged. Rather than guessing, (b) asks the only question that matters:
    were all of this branch's commits on the server before the server deleted
    the ref? If so, deleting cannot lose work.

    *pruned_oids* maps a pruned refs/remotes ref to its last-known OID, so (b)
    only ever applies to refs pruned in this run. A branch whose upstream was
    pruned by an earlier fetch has no recoverable OID and is kept.
    """
    name, sha = branch.name, branch.short_oid

    def kept(reason: str) -> BranchKept:
        return BranchKept(name=name, sha=sha, reason=reason)

    if shallow:
        return kept("shallow clone")

    worktree = checked_out.get(branch.refname)
    if worktree is not None:
        # Only the main worktree pins a branch outright — it is never removed.
        # A branch held by a *linked* worktree stays a candidate here; the
        # worktree pass decides whether that worktree can go, and reconcile()
        # moves the branch back to "kept" when it cannot.
        return kept(f"checked out at {worktree}")

    if branch.trackshort in (">", "<>"):
        return kept("unpushed commits")

    # The never-delete checks come first, including "no upstream": a purely
    # local branch is a deliberate bookmark, and is kept even when its tip is
    # already reachable from the default branch.
    if not branch.upstream:
        return kept("no upstream")

    if branch.remotename == ".":
        # Tracks another local branch; says nothing about the server.
        return kept("tracks a local branch")

    if any(is_ancestor(repo, branch.oid, tip) is True for tip in default_tips):
        return BranchInfo(name=name, sha=sha, reason="merged", force=False)

    if branch.upstream in pruned_oids:
        if not gone_allowed:
            return kept("narrow fetch refspec")
        pushed = is_ancestor(repo, branch.oid, pruned_oids[branch.upstream])
        if pushed is True:
            return BranchInfo(name=name, sha=sha, reason="pushed-then-gone", force=True)
        if pushed is False:
            return kept("upstream gone, has unpushed commits")
        return kept("upstream gone, last-known state unavailable")

    if not ref_exists(repo, branch.upstream):
        # Pruned by an earlier fetch: no last-known OID exists, so whether the
        # work reached the server cannot be proven. Keep it.
        return kept("upstream gone, merge state unknown (pruned before this run)")

    return kept("not merged")


def classify_branches(
    repo: Path,
    branches: list[BranchRef],
    *,
    default: str,
    default_tips: list[str],
    checked_out: dict[str, Path],
    pruned_oids: dict[str, str],
    gone_allowed: bool,
    shallow: bool,
) -> BranchPlan:
    """Apply classify_branch to every branch except the default one."""
    plan = BranchPlan()
    default_ref = f"refs/heads/{default}"

    for branch in branches:
        if branch.refname == default_ref:
            continue  # never a candidate, never listed
        verdict = classify_branch(
            repo,
            branch,
            default_tips=default_tips,
            checked_out=checked_out,
            pruned_oids=pruned_oids,
            gone_allowed=gone_allowed,
            shallow=shallow,
        )
        if isinstance(verdict, BranchInfo):
            plan.delete.append(verdict)
        else:
            plan.keep.append(verdict)

    return plan


def classify_worktree(
    repo: Path,
    wt: Worktree,
    *,
    deleting: set[str],
    known_branches: set[str],
) -> WorktreeInfo | WorktreeKept | None:
    """
    Decide the fate of one linked worktree. None means "not a candidate".

    Locked and bare records are filtered here rather than relying on git's
    refusal, because a plan that lists something git will reject is a bad
    plan. Locked especially: a locked worktree's directory being absent is
    expected (an unmounted disk), and pruning its record destroys bookkeeping
    for a worktree that still exists.
    """
    branch = wt.branch

    def kept(reason: str) -> WorktreeKept:
        return WorktreeKept(path=wt.path, branch=branch, reason=reason)

    if wt.bare:
        return None
    if wt.locked:
        suffix = f": {wt.locked_reason}" if wt.locked_reason else ""
        return kept(f"locked{suffix}")

    if wt.prunable or not wt.path.is_dir():
        return WorktreeInfo(
            path=wt.path,
            branch=branch,
            reason=wt.prunable_reason or "directory gone",
            prune_only=True,
        )

    if wt.detached or branch is None:
        if wt.head and not any_ref_contains(repo, wt.head):
            return kept("detached HEAD not reachable from any ref")
        return kept("detached HEAD")

    if branch in deleting:
        reason = "branch is being deleted"
    elif branch not in known_branches:
        reason = "branch gone"
    else:
        return kept("branch still in use")

    if (wt.path / ".gitmodules").is_file():
        return kept("contains submodules")

    operation = in_progress(wt.path)
    if operation is not None:
        return kept(f"{operation} in progress")

    clean, changed, untracked = is_clean(wt.path, untracked=True)
    if not clean:
        parts = []
        if changed:
            parts.append(f"{changed} modified")
        if untracked:
            parts.append(f"{untracked} untracked")
        return kept(", ".join(parts) or "not clean")

    return WorktreeInfo(path=wt.path, branch=branch, reason=reason, prune_only=False)


def classify_worktrees(
    repo: Path,
    worktrees: list[Worktree],
    *,
    deleting: set[str],
    known_branches: set[str],
) -> WorktreePlan:
    """Apply classify_worktree to every worktree except the main one (index 0)."""
    plan = WorktreePlan()

    for wt in worktrees[1:]:
        verdict = classify_worktree(
            repo, wt, deleting=deleting, known_branches=known_branches
        )
        if isinstance(verdict, WorktreeInfo):
            plan.remove.append(verdict)
        elif isinstance(verdict, WorktreeKept):
            plan.keep.append(verdict)

    return plan
