"""Fixtures shared by the git slice's tests. Not imported by any command."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from shad.testing import TmuxCase

CONFIG = """\
[projects.kb]
path = "{root}/kb"

[projects.tin.shad]
path = "{root}/tin/shad"

[projects.tin.coral]
path = "{root}/tin/coral"
"""

_ISOLATE = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "shad test",
    "GIT_AUTHOR_EMAIL": "shad@example.invalid",
    "GIT_COMMITTER_NAME": "shad test",
    "GIT_COMMITTER_EMAIL": "shad@example.invalid",
    "LC_ALL": "C",
}


def words(text: str) -> str:
    """*text* with every run of whitespace collapsed: rich wraps at 80 columns."""
    return " ".join(text.split())


def git(cwd: Path, *args: str) -> str:
    """Run git for fixture building, isolated from the developer's config."""
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True, text=True, env={**os.environ, **_ISOLATE}, check=True,
    )
    return result.stdout.strip()


def commit(cwd: Path, filename: str, body: str, message: str) -> str:
    (cwd / filename).write_text(body)
    git(cwd, "add", filename)
    git(cwd, "commit", "-q", "-m", message)
    return git(cwd, "rev-parse", "HEAD")


class GitCase(TmuxCase):
    """
    The projects kb, tin shad and tin coral. `clone` turns one of them into
    a clone of a bare remote under the test root, so fetch and prune run
    for real with no network.
    """

    def setUp(self) -> None:
        super().setUp()
        self.write_config(CONFIG.format(root=self.root))
        (self.root / "remotes").mkdir()

    def path(self, project: str) -> Path:
        return self.root / project

    def clone(self, project: str, *, merged: bool = False, unpushed: bool = False) -> Path:
        """
        *project*'s directory as a clone of a new bare remote, on main with
        one commit. With *merged*, the clone tracks feat/merged, which the
        remote's main has merged. With *unpushed*, the clone's feat/unpushed
        is one commit ahead of its upstream.
        """
        work = self.root / "remotes" / f"{project}-work"
        work.mkdir(parents=True)
        git(work, "init", "-q", "-b", "main")
        commit(work, "README.md", "one\n", "Add readme")
        if merged:
            git(work, "switch", "-q", "-c", "feat/merged")
            commit(work, "merged.txt", "m\n", "Add merged")
            git(work, "switch", "-q", "main")
            git(work, "merge", "--no-ff", "-q", "-m", "Merge merged", "feat/merged")
        bare = self.root / "remotes" / f"{project}.git"
        git(self.root, "clone", "-q", "--bare", str(work), str(bare))
        target = self.path(project)
        target.parent.mkdir(parents=True, exist_ok=True)
        git(self.root, "clone", "-q", str(bare), str(target))
        if merged:
            git(target, "branch", "-q", "--track", "feat/merged", "origin/feat/merged")
        if unpushed:
            git(target, "switch", "-q", "-c", "feat/unpushed")
            git(target, "push", "-q", "-u", "origin", "feat/unpushed")
            commit(target, "local.txt", "l\n", "Local only")
            git(target, "switch", "-q", "main")
        return target

    def advance_remote(self, project: str) -> str:
        """One more commit on the remote's main; returns its OID."""
        work = self.root / "remotes" / f"{project}-work"
        oid = commit(work, "more.txt", "more\n", "Add more")
        git(work, "push", "-q", str(self.root / "remotes" / f"{project}.git"), "main")
        return oid

    def break_remote(self, project: str) -> None:
        """Point the clone's origin at a path that does not exist."""
        git(self.path(project), "remote", "set-url", "origin", str(self.root / "nowhere.git"))

    def branches(self, project: str) -> list[str]:
        return git(self.path(project), "for-each-ref", "--format=%(refname:short)", "refs/heads").split()

    def head(self, project: str) -> str:
        return git(self.path(project), "rev-parse", "HEAD")
