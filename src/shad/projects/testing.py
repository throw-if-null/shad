"""Fixtures shared by the projects slices' tests. Not imported by any command."""

from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

from shad.testing import TmuxCase

UUID_A = "11111111-1111-4111-8111-111111111111"
UUID_B = "22222222-2222-4222-8222-222222222222"

CONFIG = """\
[defaults]
harness = "claude"

[projects.kb]
path = "{root}/kb"

[projects.kc]
path = "{root}/kc"

[projects.tin.shad]
path = "{root}/tin/shad"

[projects.tin.coral]
path = "{root}/tin/coral"
"""


def plain(text: str) -> str:
    """Table output as words: box characters dropped, runs of space collapsed."""
    for char in "│╭╮╰╯├┤┬┴┼─":
        text = text.replace(char, " ")
    return " ".join(text.split())


def git(repo: Path, *args: str) -> str:
    """Run git in *repo* with a fixed identity, for building fixtures."""
    env = {
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "HOME": str(repo),
        "PATH": "/usr/bin:/bin",
    }
    result = subprocess.run(
        ["git", "-C", str(repo), *args], env=env, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


class ProjectsCase(TmuxCase):
    """
    The projects kb, kc, tin shad and tin coral on claude, with a fake
    claude on PATH and Claude Code's transcript directory under the test
    home.
    """

    def setUp(self) -> None:
        super().setUp()
        for name in ("kb", "kc", "tin/shad", "tin/coral"):
            (self.root / name).mkdir(parents=True)
        self.write_config(CONFIG.format(root=self.root))
        self.fake_harness("claude")

    def repo(self, project: str, *, commits: tuple[str, ...] = ("Add a thing",), tag: str | None = None) -> Path:
        """Turn *project*'s directory into a repository on main with *commits* and *tag*."""
        path = self.root / project
        git(path, "init", "-q", "-b", "main")
        for index, subject in enumerate(commits):
            (path / f"file-{index}.txt").write_text(subject + "\n")
            git(path, "add", ".")
            git(path, "commit", "-q", "-m", subject)
        if tag:
            git(path, "tag", tag)
        return path

    def write_transcript(self, project: str, conversation: str, prompt: str, *, name: str | None = None) -> None:
        """A Claude Code transcript for *project* whose first user entry is *prompt*."""
        slug = re.sub(r"[^A-Za-z0-9]", "-", str(self.root / project))
        directory = self.home / ".claude" / "projects" / slug
        directory.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps({"type": "user", "message": {"role": "user", "content": prompt}})]
        if name:
            lines.append(json.dumps({"type": "custom-title", "customTitle": name}))
        (directory / f"{conversation}.jsonl").write_text("\n".join(lines) + "\n")

    def sessions_of(self, base: str) -> list[str]:
        return [name for name in self.server.sessions() if name.split("--")[0] == base]

    def pane_commands(self, session: str) -> list[str]:
        result = self.server.tmux("list-panes", "-t", session, "-F", "#{pane_current_command}")
        return result.stdout.split()

    def wait_for_harness(self, session: str, *, timeout: float = 10.0) -> list[str]:
        """The pane commands of *session* once claude is among them."""
        deadline = time.monotonic() + timeout
        while True:
            commands = self.pane_commands(session)
            if "claude" in commands:
                return commands
            if time.monotonic() > deadline:
                raise AssertionError(f"claude is not running in {session}: {commands}")
            time.sleep(0.05)
