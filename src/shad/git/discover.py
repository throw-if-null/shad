"""
Resolving a configured path to the repository shad should act on.

Also answers the per-worktree questions that gate every destructive step:
is an operation in progress, what is HEAD on, and is the tree clean.
"""

from __future__ import annotations

from pathlib import Path

from shad.git import refs
from shad.git.model import Repo
from shad.git.run import T_STATUS, first_line, git


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
    worktrees = refs.list_worktrees(toplevel)
    if not worktrees:
        raise NotUsable("could not list worktrees")
    if worktrees[0].bare:
        # The bare check above only sees the configured path. A worktree of a
        # bare repository re-roots onto the bare directory itself, which would
        # put a bare record at index 0 of every later worktree scan — and the
        # user's own working directory at index 1, where it becomes a removal
        # candidate.
        raise NotUsable(
            "worktree of a bare repository: not supported\n"
            f"       the repository is {worktrees[0].path}"
        )
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


# What in_progress() reports when git could not answer. Callers must treat it
# exactly like a real operation: never removable.
UNKNOWN_OPERATION = "unknown operation"


def in_progress(worktree: Path) -> str | None:
    """
    Return the name of an operation in progress in *worktree*, or None.

    The marker files are per-worktree (they live in .git/worktrees/<id>/), so
    they must be located with --git-path rather than assumed under .git/.
    git status does not report in-progress state at all.

    A git failure reports UNKNOWN_OPERATION, not None. This gate protects an
    in-progress rebase from having its worktree removed, so "cannot tell" has
    to fail the same direction as is_clean(): toward not touching anything.
    """
    args = ["rev-parse", "--path-format=absolute"]
    for marker, _ in _IN_PROGRESS:
        args += ["--git-path", marker]

    result = git(worktree, args)
    if result.returncode != 0:
        return UNKNOWN_OPERATION

    lines = result.stdout.splitlines()
    if len(lines) != len(_IN_PROGRESS):
        return UNKNOWN_OPERATION
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
