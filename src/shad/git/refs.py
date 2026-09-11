"""
Reading git's ref store, worktree list, and remote configuration.

Every function here is a query: it reports what git currently says and changes
nothing. Formats are plumbing with explicit separators, because the
human-readable equivalents are translated and reshaped by user config.
"""

from __future__ import annotations

from pathlib import Path

from shad.git.model import FMT_SEP, NUL, BranchRef, Worktree
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
