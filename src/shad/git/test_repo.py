from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from shad.git import repo as R
from shad.shared.errors import ShadError

REPO = Path("/tmp/repo")


def _completed(
    returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["git"], returncode=returncode, stdout=stdout, stderr=stderr
    )


class ReadOnlyDispatchTests(unittest.TestCase):
    def test_worktree_list_is_read_only_but_prune_and_remove_are_not(self) -> None:
        self.assertTrue(R._is_read_only(["worktree", "list", "--porcelain"]))
        self.assertFalse(R._is_read_only(["worktree", "prune"]))
        self.assertFalse(R._is_read_only(["worktree", "remove", "x"]))

    def test_reads_and_mutations_are_separated(self) -> None:
        self.assertTrue(R._is_read_only(["status", "--porcelain=v2"]))
        self.assertTrue(R._is_read_only(["for-each-ref"]))
        self.assertFalse(R._is_read_only(["fetch", "--prune"]))
        self.assertFalse(R._is_read_only(["branch", "-d", "x"]))
        self.assertFalse(R._is_read_only([]))


class EnvironmentTests(unittest.TestCase):
    def test_inherited_git_env_is_scrubbed(self) -> None:
        with patch.dict(
            "os.environ",
            {"GIT_DIR": "/elsewhere/.git", "GIT_WORK_TREE": "/elsewhere", "PATH": "/usr/bin"},
            clear=True,
        ):
            env = R._env(read_only=True)
        self.assertNotIn("GIT_DIR", env)
        self.assertNotIn("GIT_WORK_TREE", env)
        self.assertEqual(env["PATH"], "/usr/bin")

    def test_non_interactive_and_stable_locale_are_forced(self) -> None:
        env = R._env(read_only=False)
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")
        self.assertEqual(env["LC_ALL"], "C")
        self.assertEqual(env["LANGUAGE"], "")
        self.assertNotIn("GIT_OPTIONAL_LOCKS", env)

    def test_optional_locks_are_dropped_for_reads_only(self) -> None:
        self.assertEqual(R._env(read_only=True)["GIT_OPTIONAL_LOCKS"], "0")

    def test_user_config_env_is_left_alone(self) -> None:
        env = R._env(read_only=False)
        for name in ("GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_GLOBAL", "GIT_SSH_COMMAND"):
            self.assertNotIn(name, env)


class VersionTests(unittest.TestCase):
    def test_version_is_parsed_from_the_banner(self) -> None:
        with patch.object(R, "git", return_value=_completed(stdout="git version 2.55.0\n")):
            self.assertEqual(R.git_version(), (2, 55))

    def test_vendor_suffixes_are_tolerated(self) -> None:
        with patch.object(
            R, "git", return_value=_completed(stdout="git version 2.39.5 (Apple Git-154)\n")
        ):
            self.assertEqual(R.git_version(), (2, 39))

    def test_old_git_is_refused_with_the_found_version(self) -> None:
        with (
            patch.object(R, "git_version", return_value=(2, 30)),
            self.assertRaises(ShadError) as ctx,
        ):
            R.require_git()
        self.assertIn("2.30 is too old", str(ctx.exception))

    def test_missing_git_becomes_a_shad_error(self) -> None:
        with (
            patch.object(R, "git_version", side_effect=R.GitMissing("git is not installed")),
            self.assertRaises(ShadError) as ctx,
        ):
            R.require_git()
        self.assertIn("not installed", str(ctx.exception))


class DiscoverTests(unittest.TestCase):
    def _flags(self, bare: str, work: str, gitdir: str, shallow: str) -> str:
        return f"{bare}\n{work}\n{gitdir}\n{shallow}\n"

    def test_missing_directory_is_refused(self) -> None:
        with self.assertRaises(R.NotUsable) as ctx:
            R.discover(Path("/tmp/definitely-not-here-shad"))
        self.assertIn("path does not exist", str(ctx.exception))

    def test_non_repository_is_refused(self) -> None:
        result = _completed(128, stderr="fatal: not a git repository (or any parent)\n")
        with (
            patch.object(Path, "is_dir", return_value=True),
            patch.object(R, "git", return_value=result),
            self.assertRaises(R.NotUsable) as ctx,
        ):
            R.discover(REPO)
        self.assertIn("not a git repository", str(ctx.exception))

    def test_dubious_ownership_suggests_safe_directory(self) -> None:
        result = _completed(128, stderr="fatal: detected dubious ownership in repository\n")
        with (
            patch.object(Path, "is_dir", return_value=True),
            patch.object(R, "git", return_value=result),
            self.assertRaises(R.NotUsable) as ctx,
        ):
            R.discover(REPO)
        self.assertIn("safe.directory", str(ctx.exception))

    def test_bare_repository_is_refused(self) -> None:
        flags = self._flags("true", "false", "false", "false")
        with (
            patch.object(Path, "is_dir", return_value=True),
            patch.object(R, "git", return_value=_completed(stdout=flags)),
            self.assertRaises(R.NotUsable) as ctx,
        ):
            R.discover(REPO)
        self.assertIn("bare repository", str(ctx.exception))

    def test_path_inside_the_git_directory_is_refused(self) -> None:
        flags = self._flags("false", "false", "true", "false")
        with (
            patch.object(Path, "is_dir", return_value=True),
            patch.object(R, "git", return_value=_completed(stdout=flags)),
            self.assertRaises(R.NotUsable) as ctx,
        ):
            R.discover(REPO)
        self.assertIn("inside a .git directory", str(ctx.exception))

    def test_subdirectory_is_refused_and_never_retargeted(self) -> None:
        here = Path("/tmp/repo/src").resolve()
        top = Path("/tmp/repo").resolve()
        responses = [
            _completed(stdout=self._flags("false", "true", "false", "false")),
            _completed(stdout=f"{top}\n{top}/.git\n{top}/.git\n"),
        ]
        with (
            patch.object(Path, "is_dir", return_value=True),
            patch.object(R, "git", side_effect=responses),
            self.assertRaises(R.NotUsable) as ctx,
        ):
            R.discover(here)
        self.assertIn("is not its root", str(ctx.exception))

    def test_shallow_repository_is_flagged_but_accepted(self) -> None:
        top = Path("/tmp/repo").resolve()
        responses = [
            _completed(stdout=self._flags("false", "true", "false", "true")),
            _completed(stdout=f"{top}\n{top}/.git\n{top}/.git\n"),
        ]
        with (
            patch.object(Path, "is_dir", return_value=True),
            patch.object(R, "git", side_effect=responses),
        ):
            found = R.discover(top)
        self.assertTrue(found.shallow)
        self.assertEqual(found.root, top)

    def test_linked_worktree_is_rerooted_onto_the_main_worktree(self) -> None:
        here = Path("/tmp/wt-feat").resolve()
        main = Path("/tmp/repo").resolve()
        responses = [
            _completed(stdout=self._flags("false", "true", "false", "false")),
            _completed(stdout=f"{here}\n{main}/.git/worktrees/wt-feat\n{main}/.git\n"),
        ]
        worktrees = [R.Worktree(path=main), R.Worktree(path=here)]
        with (
            patch.object(Path, "is_dir", return_value=True),
            patch.object(R, "git", side_effect=responses),
            patch.object(R, "list_worktrees", return_value=worktrees),
        ):
            found = R.discover(here)
        self.assertEqual(found.root, main)
        self.assertEqual(found.relinked_from, here)
        self.assertEqual(found.common_dir, (main / ".git").resolve())


class WorktreeParsingTests(unittest.TestCase):
    def _run(self, payload: str) -> list[R.Worktree]:
        with patch.object(R, "git", return_value=_completed(stdout=payload)):
            return R.list_worktrees(REPO)

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
        with patch.object(R, "git", return_value=_completed(128, stderr="boom")):
            self.assertEqual(R.list_worktrees(REPO), [])


class RemoteTests(unittest.TestCase):
    def test_single_remote_wins_even_when_not_named_origin(self) -> None:
        self.assertEqual(R.primary_remote(["upstream"]), "upstream")

    def test_origin_wins_when_several_remotes_exist(self) -> None:
        self.assertEqual(R.primary_remote(["fork", "origin"]), "origin")

    def test_several_remotes_without_origin_is_ambiguous(self) -> None:
        self.assertIsNone(R.primary_remote(["fork", "upstream"]))
        self.assertIsNone(R.primary_remote([]))

    def test_full_refspec_is_recognised(self) -> None:
        payload = "+refs/heads/*:refs/remotes/origin/*\n"
        with patch.object(R, "git", return_value=_completed(stdout=payload)):
            self.assertTrue(R.has_full_refspec(REPO, "origin"))

    def test_narrow_refspec_is_rejected(self) -> None:
        payload = "+refs/heads/main:refs/remotes/origin/main\n"
        with patch.object(R, "git", return_value=_completed(stdout=payload)):
            self.assertFalse(R.has_full_refspec(REPO, "origin"))


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

        with patch.object(R, "git", side_effect=fake):
            self.assertEqual(R.default_branch(REPO, "origin"), "main")

    def test_offline_mode_falls_back_to_main(self) -> None:
        def fake(_repo: Path, args: list[str], **_kw: object) -> subprocess.CompletedProcess[str]:
            if args[0] == "symbolic-ref":
                return _completed(1)
            if args[0] == "show-ref":
                ok = args[-1] == "refs/remotes/origin/main"
                return _completed(0 if ok else 1)
            raise AssertionError(f"unexpected network call: {args}")

        with patch.object(R, "git", side_effect=fake):
            self.assertEqual(R.default_branch(REPO, "origin", allow_network=False), "main")

    def test_unresolvable_default_branch_returns_none(self) -> None:
        with patch.object(R, "git", return_value=_completed(1)):
            self.assertIsNone(R.default_branch(REPO, "origin", allow_network=False))


def _branch(
    name: str,
    *,
    oid: str = "a" * 40,
    upstream: str = "",
    remotename: str = "",
    trackshort: str = "",
) -> R.BranchRef:
    return R.BranchRef(
        refname=f"refs/heads/{name}",
        oid=oid,
        upstream=upstream,
        remotename=remotename,
        trackshort=trackshort,
    )


class ClassifyBranchTests(unittest.TestCase):
    def _classify(
        self,
        branch: R.BranchRef,
        *,
        merged: bool | None = False,
        pushed: bool | None = None,
        pruned_oids: dict[str, str] | None = None,
        upstream_exists: bool = True,
        checked_out: dict[str, Path] | None = None,
        gone_allowed: bool = True,
        shallow: bool = False,
    ) -> R.BranchInfo | R.BranchKept:
        def fake_is_ancestor(_repo: Path, _a: str, b: str) -> bool | None:
            return pushed if b == "last-known" else merged

        with (
            patch.object(R, "is_ancestor", side_effect=fake_is_ancestor),
            patch.object(R, "ref_exists", return_value=upstream_exists),
        ):
            return R.classify_branch(
                REPO,
                branch,
                default_tips=["tip"],
                checked_out=checked_out or {},
                pruned_oids=pruned_oids or {},
                gone_allowed=gone_allowed,
                shallow=shallow,
            )

    def test_merged_branch_is_deleted_without_force(self) -> None:
        verdict = self._classify(_branch("feat", upstream="refs/remotes/origin/feat",
                                         remotename="origin"), merged=True)
        assert isinstance(verdict, R.BranchInfo)
        self.assertEqual(verdict.reason, "merged")
        self.assertFalse(verdict.force)

    def test_pushed_then_gone_branch_is_force_deleted(self) -> None:
        verdict = self._classify(
            _branch("feat", upstream="refs/remotes/origin/feat", remotename="origin"),
            merged=False,
            pushed=True,
            pruned_oids={"refs/remotes/origin/feat": "last-known"},
        )
        assert isinstance(verdict, R.BranchInfo)
        self.assertEqual(verdict.reason, "pushed-then-gone")
        self.assertTrue(verdict.force)

    def test_gone_branch_with_unpushed_commits_is_kept(self) -> None:
        verdict = self._classify(
            _branch("feat", upstream="refs/remotes/origin/feat", remotename="origin"),
            pushed=False,
            pruned_oids={"refs/remotes/origin/feat": "last-known"},
        )
        assert isinstance(verdict, R.BranchKept)
        self.assertIn("unpushed", verdict.reason)

    def test_gone_branch_with_unknown_ancestry_is_kept(self) -> None:
        verdict = self._classify(
            _branch("feat", upstream="refs/remotes/origin/feat", remotename="origin"),
            pushed=None,
            pruned_oids={"refs/remotes/origin/feat": "last-known"},
        )
        assert isinstance(verdict, R.BranchKept)
        self.assertIn("last-known state unavailable", verdict.reason)

    def test_branch_pruned_before_this_run_is_kept(self) -> None:
        verdict = self._classify(
            _branch("feat", upstream="refs/remotes/origin/feat", remotename="origin"),
            pruned_oids={},
            upstream_exists=False,
        )
        assert isinstance(verdict, R.BranchKept)
        self.assertIn("pruned before this run", verdict.reason)

    def test_narrow_refspec_disables_gone_based_deletion(self) -> None:
        verdict = self._classify(
            _branch("feat", upstream="refs/remotes/origin/feat", remotename="origin"),
            pushed=True,
            pruned_oids={"refs/remotes/origin/feat": "last-known"},
            gone_allowed=False,
        )
        assert isinstance(verdict, R.BranchKept)
        self.assertEqual(verdict.reason, "narrow fetch refspec")

    def test_checked_out_branch_is_never_deleted(self) -> None:
        verdict = self._classify(
            _branch("feat", upstream="refs/remotes/origin/feat", remotename="origin"),
            merged=True,
            checked_out={"refs/heads/feat": Path("/tmp/wt")},
        )
        assert isinstance(verdict, R.BranchKept)
        self.assertIn("checked out at", verdict.reason)

    def test_ahead_branch_is_never_deleted(self) -> None:
        verdict = self._classify(
            _branch("feat", upstream="refs/remotes/origin/feat",
                    remotename="origin", trackshort=">"),
            merged=True,
        )
        assert isinstance(verdict, R.BranchKept)
        self.assertEqual(verdict.reason, "unpushed commits")

    def test_branch_without_upstream_is_kept_even_when_merged(self) -> None:
        verdict = self._classify(_branch("scratch"), merged=True)
        assert isinstance(verdict, R.BranchKept)
        self.assertEqual(verdict.reason, "no upstream")

    def test_local_tracking_branch_is_kept(self) -> None:
        verdict = self._classify(
            _branch("mirror", upstream="refs/heads/main", remotename="."), merged=False
        )
        assert isinstance(verdict, R.BranchKept)
        self.assertEqual(verdict.reason, "tracks a local branch")

    def test_shallow_clone_keeps_everything(self) -> None:
        verdict = self._classify(
            _branch("feat", upstream="refs/remotes/origin/feat", remotename="origin"),
            merged=True,
            shallow=True,
        )
        assert isinstance(verdict, R.BranchKept)
        self.assertEqual(verdict.reason, "shallow clone")

    def test_default_branch_is_skipped_entirely(self) -> None:
        with (
            patch.object(R, "is_ancestor", return_value=True),
            patch.object(R, "ref_exists", return_value=True),
        ):
            plan = R.classify_branches(
                REPO,
                [_branch("main"), _branch("feat", upstream="refs/remotes/origin/feat",
                                          remotename="origin")],
                default="main",
                default_tips=["tip"],
                checked_out={},
                pruned_oids={},
                gone_allowed=True,
                shallow=False,
            )
        names = [b.name for b in plan.delete] + [b.name for b in plan.keep]
        self.assertNotIn("main", names)


class ClassifyWorktreeTests(unittest.TestCase):
    def test_main_worktree_is_never_a_candidate(self) -> None:
        main = R.Worktree(path=Path("/tmp/repo"), branch="refs/heads/main")
        plan = R.classify_worktrees(REPO, [main], deleting=set(), known_branches=set())
        self.assertEqual(plan.remove, [])
        self.assertEqual(plan.keep, [])

    def test_locked_worktree_is_kept_with_its_reason(self) -> None:
        wt = R.Worktree(
            path=Path("/tmp/gone"), branch="refs/heads/x", locked=True,
            locked_reason="usb stick", prunable=True,
        )
        verdict = R.classify_worktree(REPO, wt, deleting=set(), known_branches=set())
        assert isinstance(verdict, R.WorktreeKept)
        self.assertEqual(verdict.reason, "locked: usb stick")

    def test_bare_record_is_ignored(self) -> None:
        wt = R.Worktree(path=Path("/tmp/bare"), bare=True)
        self.assertIsNone(
            R.classify_worktree(REPO, wt, deleting=set(), known_branches=set())
        )

    def test_prunable_worktree_is_prune_only(self) -> None:
        wt = R.Worktree(
            path=Path("/tmp/gone"), branch="refs/heads/x",
            prunable=True, prunable_reason="gitdir file points to non-existent location",
        )
        verdict = R.classify_worktree(REPO, wt, deleting=set(), known_branches=set())
        assert isinstance(verdict, R.WorktreeInfo)
        self.assertTrue(verdict.prune_only)
        self.assertIn("non-existent", verdict.reason)

    def test_worktree_with_a_live_branch_is_kept(self) -> None:
        wt = R.Worktree(path=Path("/tmp/live"), branch="refs/heads/x")
        with patch.object(Path, "is_dir", return_value=True):
            verdict = R.classify_worktree(
                REPO, wt, deleting=set(), known_branches={"refs/heads/x"}
            )
        assert isinstance(verdict, R.WorktreeKept)
        self.assertEqual(verdict.reason, "branch still in use")

    def test_dirty_worktree_is_kept_with_counts(self) -> None:
        wt = R.Worktree(path=Path("/tmp/dirty"), branch="refs/heads/x")
        with (
            patch.object(Path, "is_dir", return_value=True),
            patch.object(Path, "is_file", return_value=False),
            patch.object(R, "in_progress", return_value=None),
            patch.object(R, "is_clean", return_value=(False, 3, 12)),
        ):
            verdict = R.classify_worktree(
                REPO, wt, deleting={"refs/heads/x"}, known_branches={"refs/heads/x"}
            )
        assert isinstance(verdict, R.WorktreeKept)
        self.assertEqual(verdict.reason, "3 modified, 12 untracked")

    def test_worktree_with_submodules_is_kept(self) -> None:
        wt = R.Worktree(path=Path("/tmp/subs"), branch="refs/heads/x")
        with (
            patch.object(Path, "is_dir", return_value=True),
            patch.object(Path, "is_file", return_value=True),
        ):
            verdict = R.classify_worktree(
                REPO, wt, deleting={"refs/heads/x"}, known_branches={"refs/heads/x"}
            )
        assert isinstance(verdict, R.WorktreeKept)
        self.assertEqual(verdict.reason, "contains submodules")

    def test_worktree_mid_rebase_is_kept(self) -> None:
        wt = R.Worktree(path=Path("/tmp/reb"), branch="refs/heads/x")
        with (
            patch.object(Path, "is_dir", return_value=True),
            patch.object(Path, "is_file", return_value=False),
            patch.object(R, "in_progress", return_value="rebase"),
        ):
            verdict = R.classify_worktree(
                REPO, wt, deleting={"refs/heads/x"}, known_branches={"refs/heads/x"}
            )
        assert isinstance(verdict, R.WorktreeKept)
        self.assertEqual(verdict.reason, "rebase in progress")

    def test_clean_worktree_of_a_deleted_branch_is_removed(self) -> None:
        wt = R.Worktree(path=Path("/tmp/dead"), branch="refs/heads/x")
        with (
            patch.object(Path, "is_dir", return_value=True),
            patch.object(Path, "is_file", return_value=False),
            patch.object(R, "in_progress", return_value=None),
            patch.object(R, "is_clean", return_value=(True, 0, 0)),
        ):
            verdict = R.classify_worktree(
                REPO, wt, deleting={"refs/heads/x"}, known_branches={"refs/heads/x"}
            )
        assert isinstance(verdict, R.WorktreeInfo)
        self.assertEqual(verdict.reason, "branch is being deleted")
        self.assertFalse(verdict.prune_only)

    def test_detached_worktree_with_unreachable_head_is_kept(self) -> None:
        wt = R.Worktree(path=Path("/tmp/det"), head="abc", detached=True)
        with (
            patch.object(Path, "is_dir", return_value=True),
            patch.object(R, "any_ref_contains", return_value=False),
        ):
            verdict = R.classify_worktree(REPO, wt, deleting=set(), known_branches=set())
        assert isinstance(verdict, R.WorktreeKept)
        self.assertIn("not reachable from any ref", verdict.reason)


class MutationTests(unittest.TestCase):
    def test_delete_branch_passes_force_only_when_asked(self) -> None:
        with patch.object(R, "git", return_value=_completed()) as run:
            self.assertIsNone(R.delete_branch(REPO, "feat", force=False))
        self.assertEqual(run.call_args.args[1], ["branch", "--delete", "feat"])

        with patch.object(R, "git", return_value=_completed()) as run:
            self.assertIsNone(R.delete_branch(REPO, "feat", force=True))
        self.assertEqual(run.call_args.args[1], ["branch", "--delete", "--force", "feat"])

    def test_delete_branch_refuses_an_option_like_name(self) -> None:
        with patch.object(R, "git") as run:
            error = R.delete_branch(REPO, "--all", force=True)
        run.assert_not_called()
        assert error is not None
        self.assertIn("starts with '-'", error)

    def test_delete_branch_reports_the_first_stderr_line(self) -> None:
        result = _completed(1, stderr="error: the branch 'feat' is not fully merged\nhint: x\n")
        with patch.object(R, "git", return_value=result):
            self.assertEqual(
                R.delete_branch(REPO, "feat", force=False),
                "error: the branch 'feat' is not fully merged",
            )

    def test_remove_worktree_never_passes_force(self) -> None:
        with patch.object(R, "git", return_value=_completed()) as run:
            R.remove_worktree(REPO, Path("/tmp/wt"))
        self.assertNotIn("--force", run.call_args.args[1])
        self.assertIn("--", run.call_args.args[1])

    def test_fetch_prunes_when_asked_and_never_prunes_tags(self) -> None:
        with patch.object(R, "git", return_value=_completed()) as run:
            result = R.fetch(REPO, "origin", prune=True)
        args = run.call_args.args[1]
        self.assertTrue(result.ok)
        self.assertIn("--prune", args)
        self.assertIn("--no-recurse-submodules", args)
        self.assertNotIn("--prune-tags", args)
        self.assertNotIn("--atomic", args)
        self.assertNotIn("--dry-run", args)
        self.assertEqual(args[-2:], ["--", "origin"])

    def test_fetch_without_prune_still_fetches_for_real(self) -> None:
        # The dry-run path fetches for real so the report is accurate, but must
        # not prune: a pruned ref takes its last-known OID with it.
        with patch.object(R, "git", return_value=_completed()) as run:
            R.fetch(REPO, "origin", prune=False)
        args = run.call_args.args[1]
        self.assertNotIn("--prune", args)
        self.assertNotIn("--dry-run", args)

    def test_fetch_failure_is_reported_not_raised(self) -> None:
        result = _completed(128, stderr="fatal: could not read from remote repository\n")
        with patch.object(R, "git", return_value=result):
            outcome = R.fetch(REPO, "origin", prune=True)
        self.assertFalse(outcome.ok)
        assert outcome.error is not None
        self.assertIn("could not read from remote", outcome.error)

    def test_fetch_timeout_is_reported_not_raised(self) -> None:
        with patch.object(R, "git", side_effect=ShadError("git fetch timed out after 120s")):
            outcome = R.fetch(REPO, "origin", prune=True)
        self.assertFalse(outcome.ok)
        assert outcome.error is not None
        self.assertIn("timed out", outcome.error)

    def test_remote_branch_refs_maps_heads_to_tracking_names(self) -> None:
        payload = "abc\trefs/heads/main\ndef\trefs/heads/feat/x\nghi\trefs/tags/v1\n"
        with patch.object(R, "git", return_value=_completed(stdout=payload)):
            refs = R.remote_branch_refs(REPO, "origin")
        self.assertEqual(
            refs, {"refs/remotes/origin/main", "refs/remotes/origin/feat/x"}
        )

    def test_remote_branch_refs_returns_none_when_unreachable(self) -> None:
        with patch.object(R, "git", return_value=_completed(128, stderr="fatal: no host")):
            self.assertIsNone(R.remote_branch_refs(REPO, "origin"))

    def test_fast_forward_unchecked_uses_a_non_forcing_local_refspec(self) -> None:
        with patch.object(R, "git", return_value=_completed()) as run:
            R.fast_forward_unchecked(REPO, "main", "refs/remotes/origin/main")
        args = run.call_args.args[1]
        self.assertIn(".", args)
        self.assertIn("refs/remotes/origin/main:refs/heads/main", args)
        self.assertFalse(any(a.startswith("+") for a in args))


if __name__ == "__main__":
    unittest.main()
