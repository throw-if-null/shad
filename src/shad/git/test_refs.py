from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from shad.git import refs
from shad.git.model import Worktree

REPO = Path("/tmp/repo")


def _completed(
    returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["git"], returncode=returncode, stdout=stdout, stderr=stderr
    )


class WorktreeParsingTests(unittest.TestCase):
    def _run(self, payload: str) -> list[Worktree]:
        with patch.object(refs, "git", return_value=_completed(stdout=payload)):
            return refs.list_worktrees(REPO)

    def test_detached_record_has_no_branch(self) -> None:
        payload = "worktree /tmp/a\x00HEAD abc\x00detached\x00\x00"
        (entry,) = self._run(payload)
        self.assertTrue(entry.detached)
        self.assertIsNone(entry.branch)
        self.assertEqual(entry.head, "abc")

    def test_locked_without_a_reason_is_still_locked(self) -> None:
        payload = "worktree /tmp/a\x00HEAD abc\x00branch refs/heads/x\x00locked\x00\x00"
        (entry,) = self._run(payload)
        self.assertTrue(entry.locked)
        self.assertEqual(entry.locked_reason, "")

    def test_prunable_reason_containing_spaces_is_kept_whole(self) -> None:
        payload = (
            "worktree /tmp/a\x00HEAD abc\x00detached\x00"
            "prunable gitdir file points to non-existent location\x00\x00"
        )
        (entry,) = self._run(payload)
        self.assertTrue(entry.prunable)
        self.assertEqual(
            entry.prunable_reason, "gitdir file points to non-existent location"
        )

    def test_multiple_records_keep_their_order(self) -> None:
        payload = (
            "worktree /tmp/main\x00HEAD a\x00branch refs/heads/main\x00\x00"
            "worktree /tmp/feat\x00HEAD b\x00branch refs/heads/feat\x00\x00"
        )
        entries = self._run(payload)
        self.assertEqual([str(e.path) for e in entries], ["/tmp/main", "/tmp/feat"])

    def test_failed_command_yields_no_records(self) -> None:
        with patch.object(refs, "git", return_value=_completed(128, stderr="boom")):
            self.assertEqual(refs.list_worktrees(REPO), [])


class RemoteTests(unittest.TestCase):
    def test_single_remote_wins_even_when_not_named_origin(self) -> None:
        self.assertEqual(refs.primary_remote(["upstream"]), "upstream")

    def test_origin_wins_when_several_remotes_exist(self) -> None:
        self.assertEqual(refs.primary_remote(["fork", "origin"]), "origin")

    def test_several_remotes_without_origin_is_ambiguous(self) -> None:
        self.assertIsNone(refs.primary_remote(["fork", "upstream"]))
        self.assertIsNone(refs.primary_remote([]))

    def test_full_refspec_is_recognised(self) -> None:
        payload = "+refs/heads/*:refs/remotes/origin/*\n"
        with patch.object(refs, "git", return_value=_completed(stdout=payload)):
            self.assertTrue(refs.has_full_refspec(REPO, "origin"))

    def test_narrow_refspec_is_rejected(self) -> None:
        payload = "+refs/heads/main:refs/remotes/origin/main\n"
        with patch.object(refs, "git", return_value=_completed(stdout=payload)):
            self.assertFalse(refs.has_full_refspec(REPO, "origin"))


class DefaultBranchTests(unittest.TestCase):
    def test_stale_symref_is_discarded_and_ls_remote_is_consulted(self) -> None:
        # origin/HEAD still points at master, but that ref no longer exists.
        calls = {
            "symbolic-ref": _completed(stdout="refs/remotes/origin/master\n"),
            "show-ref": _completed(1),
            "ls-remote": _completed(stdout="ref: refs/heads/main\tHEAD\nabc\tHEAD\n"),
        }

        def fake(_repo: Path, args: list[str], **_kw: object) -> subprocess.CompletedProcess[str]:
            return calls[args[0]]

        with patch.object(refs, "git", side_effect=fake):
            self.assertEqual(refs.default_branch(REPO, "origin"), "main")

    def test_offline_mode_falls_back_to_main(self) -> None:
        def fake(_repo: Path, args: list[str], **_kw: object) -> subprocess.CompletedProcess[str]:
            if args[0] == "symbolic-ref":
                return _completed(1)
            if args[0] == "show-ref":
                ok = args[-1] == "refs/remotes/origin/main"
                return _completed(0 if ok else 1)
            raise AssertionError(f"unexpected network call: {args}")

        with patch.object(refs, "git", side_effect=fake):
            self.assertEqual(refs.default_branch(REPO, "origin", allow_network=False), "main")

    def test_unresolvable_default_branch_returns_none(self) -> None:
        with patch.object(refs, "git", return_value=_completed(1)):
            self.assertIsNone(refs.default_branch(REPO, "origin", allow_network=False))


class RemoteBranchRefsTests(unittest.TestCase):
    def test_remote_branch_refs_maps_heads_to_tracking_names(self) -> None:
        payload = "abc\trefs/heads/main\ndef\trefs/heads/feat/x\nghi\trefs/tags/v1\n"
        with patch.object(refs, "git", return_value=_completed(stdout=payload)):
            found = refs.remote_branch_refs(REPO, "origin")
        self.assertEqual(
            found, {"refs/remotes/origin/main", "refs/remotes/origin/feat/x"}
        )

    def test_remote_branch_refs_returns_none_when_unreachable(self) -> None:
        with patch.object(refs, "git", return_value=_completed(128, stderr="fatal: no host")):
            self.assertIsNone(refs.remote_branch_refs(REPO, "origin"))

if __name__ == "__main__":
    unittest.main()
