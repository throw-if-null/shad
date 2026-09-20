from __future__ import annotations

import io
import tempfile
import time
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from rich.console import Console

from shad.git.model import Commit
from shad.projects.status import command as C


@contextmanager
def _capture(width: int = 200) -> Iterator[io.StringIO]:
    """Render into a real Console; a rich Table has no useful __str__."""
    buffer = io.StringIO()
    console = Console(file=buffer, width=width, force_terminal=False, highlight=False)
    with patch.object(C, "console", console):
        yield buffer


def _text(buffer: io.StringIO) -> str:
    raw = buffer.getvalue()
    for char in "│╭╮╰╯├┤┬┴┼─":
        raw = raw.replace(char, " ")
    return " ".join(raw.split())


class PrintGitTests(unittest.TestCase):
    """
    The git section, with the queries stubbed.

    The repository is a real directory carrying a .git marker so the gate is
    exercised rather than patched; what git itself returns is covered against
    a real repository in git/test_real_git.py.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name) / "repo"
        (self.repo / ".git").mkdir(parents=True)
        self.plain = Path(self._tmp.name) / "plain"
        self.plain.mkdir()

    @contextmanager
    def _git_state(
        self,
        *,
        head: str | None = "refs/heads/main",
        tag: str = "",
        clean: tuple[bool, int, int] = (True, 0, 0),
        commits: list[Commit] | None = None,
    ) -> Iterator[None]:
        with (
            patch.object(C, "head_branch", return_value=head),
            patch.object(C.refs, "latest_tag", return_value=tag),
            patch.object(C, "is_clean", return_value=clean),
            patch.object(C.refs, "recent_commits", return_value=commits or []),
        ):
            yield

    def _render(self, **state: object) -> str:
        with _capture() as buffer, self._git_state(**state):  # type: ignore[arg-type]
            C._print_git(self.repo)
        return _text(buffer)

    def test_a_directory_without_git_is_reported_and_queries_nothing(self) -> None:
        with _capture() as buffer, patch.object(C, "head_branch") as head:
            C._print_git(self.plain)
        self.assertIn("(not a git repository)", _text(buffer))
        head.assert_not_called()

    def test_branch_tag_and_clean_state_are_rendered(self) -> None:
        out = self._render(tag="v1.2.3")
        self.assertIn("branch main", out)
        self.assertIn("latest tag v1.2.3", out)
        self.assertIn("uncommitted clean", out)

    def test_a_detached_head_is_labelled_not_left_blank(self) -> None:
        self.assertIn("branch detached", self._render(head=None))

    def test_a_repository_with_no_tags_renders_a_dash(self) -> None:
        self.assertIn("latest tag —", self._render(tag=""))

    def test_the_dirty_count_sums_changed_and_untracked(self) -> None:
        self.assertIn("uncommitted 5 file(s)", self._render(clean=(False, 2, 3)))

    def test_commits_render_oid_subject_and_age(self) -> None:
        now = int(time.time())
        commits = [
            Commit(short_oid="abc1234", subject="Add a thing", timestamp=now - 7200),
            Commit(short_oid="def5678", subject="Fix a thing", timestamp=now - 86400 * 3),
        ]
        out = self._render(commits=commits)
        self.assertIn("abc1234 Add a thing 2h", out)
        self.assertIn("def5678 Fix a thing 3d", out)

    def test_an_unborn_head_reports_no_commits(self) -> None:
        self.assertIn("commits none", self._render(commits=[]))

    def test_only_the_configured_count_of_commits_is_requested(self) -> None:
        with _capture(), self._git_state(), patch.object(
            C.refs, "recent_commits", return_value=[]
        ) as recent:
            C._print_git(self.repo)
        self.assertEqual(recent.call_args.args[1], C.RECENT_COMMITS)


class NoRawGitCallsTests(unittest.TestCase):
    def test_the_status_slice_shells_out_to_git_nowhere(self) -> None:
        """
        _capture applies no env scrubbing and no timeout and uses cwd=, so a
        git call through it reports whichever repository an inherited GIT_DIR
        names. Every git query must go through shad.git.run instead.
        """
        source = Path(C.__file__).read_text()
        self.assertNotIn('["git"', source)


if __name__ == "__main__":
    unittest.main()
