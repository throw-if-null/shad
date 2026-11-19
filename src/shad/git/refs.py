"""
Reading git's ref store, worktree list, and remote configuration.

Every function here is a query: it reports what git currently says and changes
nothing. Formats are plumbing with explicit separators, because the
human-readable equivalents are translated and reshaped by user config.
"""

from __future__ import annotations

from pathlib import Path

from shad.git.model import FMT_SEP, LOG_SEP, NUL, BranchRef, Commit, Stash, Worktree
from shad.git.run import T_LS_REMOTE, git


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


def merged_branches(repo: Path, tip: str) -> set[str]:
    """
    Refnames under refs/heads whose tip is reachable from *tip*.

    Exactly what `merge-base --is-ancestor <branch> <tip>` answers, but once
    for the whole ref store instead of once per branch — a repository with
    fifty branches cost fifty subprocesses before.

    An error yields the empty set, so an unreadable ref store reports nothing
    as merged. That is the same direction the per-branch form failed in.
    """
    result = git(repo, ["for-each-ref", "--format=%(refname)", f"--merged={tip}", "refs/heads"])
    if result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def any_ref_contains(repo: Path, oid: str) -> bool:
    """True when *oid* is reachable from at least one ref."""
    result = git(
        repo, ["for-each-ref", "--count=1", f"--contains={oid}", "--format=%(refname)"]
    )
    return result.returncode == 0 and bool(result.stdout.strip())


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
        raw = record.get("worktree")
        if not raw:
            record.clear()
            return
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


def list_stashes(repo: Path) -> list[Stash]:
    """
    Enumerate the stash reflog.

    Uses LOG_SEP, not FMT_SEP: this is the log pretty-format family, which
    emits `%00` as three literal characters and needs `%x00` instead.

    -z terminates each record with the same NUL the fields are separated by,
    so the output is one flat field stream and records are recovered by
    counting fields, not by splitting on a record separator. %gs is the
    reflog subject, which git flattens to a single line even when the stash
    message spans several.

    The date is %ct, not %cr: the relative form is gettext-translated, and a
    caller that formats a unix timestamp itself cannot be broken by a locale.
    """
    fields = ("%gd", "%gs", "%ct")
    fmt = LOG_SEP.join(fields)
    result = git(repo, ["stash", "list", "-z", f"--format={fmt}"])
    if result.returncode != 0:
        return []

    parts = result.stdout.split(NUL)
    if parts and parts[-1] == "":
        parts.pop()  # the final record's terminator

    stashes: list[Stash] = []
    for i in range(0, len(parts) - len(fields) + 1, len(fields)):
        ref, subject, when = parts[i], parts[i + 1], parts[i + 2]
        stashes.append(
            Stash(
                ref=ref,
                subject=subject,
                timestamp=int(when) if when.isdigit() else 0,
                branch=_stash_branch(subject),
            )
        )
    return stashes


def latest_tag(repo: Path) -> str:
    """
    The most recent tag reachable from HEAD, or "" when there is none.

    Exit 128 covers both "no tags" and "no commits yet", and neither is an
    error worth reporting — the caller renders an em dash either way.
    """
    result = git(repo, ["describe", "--tags", "--abbrev=0"])
    return result.stdout.strip() if result.returncode == 0 else ""


def recent_commits(repo: Path, count: int) -> list[Commit]:
    """
    The newest *count* commits on HEAD, newest first.

    Same framing as list_stashes, and for the same reason: this is the log
    pretty-format language, so the separator is LOG_SEP and -z terminates each
    record with that same byte. %s is the subject line alone, so it cannot
    contain a newline. An unborn HEAD exits 128 and yields [].
    """
    fields = ("%h", "%s", "%ct")
    fmt = LOG_SEP.join(fields)
    result = git(repo, ["log", "-z", f"--format={fmt}", f"-{count}"])
    if result.returncode != 0:
        return []

    parts = result.stdout.split(NUL)
    if parts and parts[-1] == "":
        parts.pop()

    commits: list[Commit] = []
    for i in range(0, len(parts) - len(fields) + 1, len(fields)):
        short_oid, subject, when = parts[i], parts[i + 1], parts[i + 2]
        commits.append(
            Commit(
                short_oid=short_oid,
                subject=subject,
                timestamp=int(when) if when.isdigit() else 0,
            )
        )
    return commits


def _stash_branch(subject: str) -> str:
    """The branch named in a stash reflog subject, or "" when it has none."""
    head, sep, _ = subject.partition(": ")
    if not sep:
        return ""
    for prefix in ("WIP on ", "On "):
        if head.startswith(prefix):
            return head[len(prefix) :]
    return ""


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

    Both sides have to match. A refspec like
    `+refs/heads/release/*:refs/remotes/origin/*` has the expected
    destination but stores server branch `release/v1` at `origin/v1`, so
    remote_branch_refs() would build `origin/release/v1`, find none of the
    real tracking refs, and call every one of them stale.
    """
    result = git(repo, ["config", "--get-all", f"remote.{remote}.fetch"])
    if result.returncode != 0:
        return False
    want = f"refs/heads/*:refs/remotes/{remote}/*"
    return any(
        line.strip().removeprefix("+") == want for line in result.stdout.splitlines()
    )


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
