from __future__ import annotations

import argparse
import unittest
from pathlib import Path
from unittest.mock import patch

from shad.cli import (
    _run_action,
    build_parser,
    cmd_projects,
    cmd_sessions,
    cmd_todo,
    main,
)
from shad.errors import ShadError
from shad.shared.config import Config, Defaults, Project
from shad.testing import TmuxCase, run
from shad.trace import Trace


def _make_project(
    key: str, group: str | None = None, session: str | None = None
) -> Project:
    return Project(
        key=key,
        group=group,
        path=Path("/tmp") / key,
        session=session or (f"{group}-{key}" if group else key),
    )


def _make_args(name: list[str], harness: str | None = None) -> argparse.Namespace:
    return argparse.Namespace(name=name, harness=harness)


# ---------------------------------------------------------------------------
# cmd_projects dispatch
# ---------------------------------------------------------------------------


class ProjectsCommandTests(unittest.TestCase):
    def test_grouped_project_open_dispatches_to_open_project(self) -> None:
        project = _make_project("shad", group="tin")
        cfg = Config(defaults=Defaults(), groups={"tin": {"shad": project}})
        args = _make_args(["tin", "shad"])

        with (
            patch("shad.cli.print_banner"),
            patch("shad.cli.open_project", return_value=0) as open_project,
        ):
            code = cmd_projects(cfg, args)

        self.assertEqual(code, 0)
        open_project.assert_called_once_with(project, cfg.defaults, harness=None)

    def test_top_level_project_open_dispatches_to_open_project(self) -> None:
        project = _make_project("shad")
        cfg = Config(defaults=Defaults(), projects={"shad": project})
        args = _make_args(["shad"])

        with (
            patch("shad.cli.print_banner"),
            patch("shad.cli.open_project", return_value=0) as open_project,
        ):
            code = cmd_projects(cfg, args)

        self.assertEqual(code, 0)
        open_project.assert_called_once_with(project, cfg.defaults, harness=None)


class ProjectsListTests(unittest.TestCase):
    def test_no_args_lists_all_with_no_projects(self) -> None:
        cfg = Config(defaults=Defaults())
        args = _make_args([])

        with patch("shad.cli.console") as mock_console:
            cmd_projects(cfg, args)

        output = " ".join(str(c) for c in mock_console.print.call_args_list)
        self.assertIn("no projects configured", output)

    def test_no_args_lists_top_level_and_groups(self) -> None:
        cfg = Config(
            defaults=Defaults(),
            projects={"myapp": _make_project("myapp")},
            groups={"tin": {"shad": _make_project("shad", group="tin")}},
        )
        args = _make_args([])

        with patch("shad.cli.console"):
            cmd_projects(cfg, args)

    def test_single_token_resolves_to_group_and_lists_subprojects(self) -> None:
        cfg = Config(
            defaults=Defaults(),
            groups={"tin": {"shad": _make_project("shad", group="tin")}},
        )
        args = _make_args(["tin"])

        with patch("shad.cli.console"):
            cmd_projects(cfg, args)

    def test_single_token_unknown_raises_shad_error(self) -> None:
        cfg = Config(defaults=Defaults())
        args = _make_args(["xyz"])

        with self.assertRaises(ShadError) as ctx:
            cmd_projects(cfg, args)

        self.assertIn("xyz", str(ctx.exception))

    def test_single_token_ambiguous_raises_shad_error(self) -> None:
        cfg = Config(
            defaults=Defaults(),
            projects={
                "shad": _make_project("shad"),
                "shell": _make_project("shell"),
            },
        )
        args = _make_args(["sh"])

        with self.assertRaises(ShadError) as ctx:
            cmd_projects(cfg, args)

        self.assertIn("ambiguous", str(ctx.exception))

    def test_action_on_group_raises_shad_error(self) -> None:
        cfg = Config(
            defaults=Defaults(),
            groups={"tin": {"shad": _make_project("shad", group="tin")}},
        )
        args = _make_args(["tin", "status"])

        with self.assertRaises(ShadError) as ctx:
            cmd_projects(cfg, args)

        self.assertIn("group", str(ctx.exception))

    def test_two_tokens_status_action_calls_print_status(self) -> None:
        project = _make_project("shad", group="tin")
        cfg = Config(defaults=Defaults(), groups={"tin": {"shad": project}})
        args = _make_args(["tin", "shad", "status"])

        with patch("shad.cli.print_status") as mock_status:
            cmd_projects(cfg, args)

        mock_status.assert_called_once()
        self.assertIs(mock_status.call_args.args[0], project)

    def test_group_token_resolves_to_top_level_project_raises_helpful_error(
        self,
    ) -> None:
        cfg = Config(
            defaults=Defaults(),
            projects={"shad": _make_project("shad")},
        )
        args = _make_args(["shad", "something"])

        with self.assertRaises(ShadError) as ctx:
            cmd_projects(cfg, args)

        self.assertIn("did you mean", str(ctx.exception))

    def test_unknown_group_raises_shad_error(self) -> None:
        cfg = Config(defaults=Defaults())
        args = _make_args(["xyz", "proj"])

        with self.assertRaises(ShadError) as ctx:
            cmd_projects(cfg, args)

        self.assertIn("no group matching", str(ctx.exception))

    def test_unknown_project_within_group_raises_shad_error(self) -> None:
        cfg = Config(
            defaults=Defaults(),
            groups={"tin": {"shad": _make_project("shad", group="tin")}},
        )
        args = _make_args(["tin", "zzz"])

        with self.assertRaises(ShadError) as ctx:
            cmd_projects(cfg, args)

        self.assertIn("no project matching", str(ctx.exception))
        self.assertIn("tin", str(ctx.exception))

    def test_too_many_tokens_raises_shad_error(self) -> None:
        cfg = Config(defaults=Defaults())
        args = _make_args(["a", "b", "c"])

        with self.assertRaises(ShadError) as ctx:
            cmd_projects(cfg, args)

        self.assertIn("too many arguments", str(ctx.exception))

    def test_a_cancelled_open_returns_none(self) -> None:
        project = _make_project("shad")
        cfg = Config(defaults=Defaults(), projects={"shad": project})
        args = _make_args(["shad"])

        with (
            patch("shad.cli.print_banner"),
            patch("shad.cli.open_project", return_value=None),
        ):
            self.assertIsNone(cmd_projects(cfg, args))

    def test_the_attach_exit_code_is_returned(self) -> None:
        project = _make_project("shad")
        cfg = Config(defaults=Defaults(), projects={"shad": project})
        args = _make_args(["shad"])

        with (
            patch("shad.cli.print_banner"),
            patch("shad.cli.open_project", return_value=3),
        ):
            self.assertEqual(cmd_projects(cfg, args), 3)

    def test_unknown_action_raises_shad_error(self) -> None:
        project = _make_project("shad")
        cfg = Config(defaults=Defaults(), projects={"shad": project})

        with self.assertRaises(ShadError) as ctx:
            _run_action(cfg, project, "restart", None, Trace())

        self.assertIn("unknown action", str(ctx.exception))


# ---------------------------------------------------------------------------
# main() error handling
# ---------------------------------------------------------------------------



class ProjectsHarnessOverrideTests(unittest.TestCase):
    def test_override_is_forwarded_for_a_top_level_project(self) -> None:
        project = _make_project("shad")
        cfg = Config(defaults=Defaults(), projects={"shad": project})
        args = _make_args(["shad"], harness="claude")

        with (
            patch("shad.cli.print_banner"),
            patch("shad.cli.open_project", return_value=0) as open_project,
        ):
            cmd_projects(cfg, args)

        open_project.assert_called_once_with(project, cfg.defaults, harness="claude")

    def test_override_is_forwarded_for_a_grouped_project(self) -> None:
        project = _make_project("shad", group="tin")
        cfg = Config(defaults=Defaults(), groups={"tin": {"shad": project}})
        args = _make_args(["tin", "shad"], harness="opencode")

        with (
            patch("shad.cli.print_banner"),
            patch("shad.cli.open_project", return_value=0) as open_project,
        ):
            cmd_projects(cfg, args)

        open_project.assert_called_once_with(project, cfg.defaults, harness="opencode")

    def test_status_action_ignores_the_override(self) -> None:
        project = _make_project("shad")
        cfg = Config(defaults=Defaults(), projects={"shad": project})
        args = _make_args(["shad", "status"], harness="claude")

        with (
            patch("shad.cli.print_status") as print_status,
            patch("shad.cli.open_project") as open_project,
        ):
            cmd_projects(cfg, args)

        print_status.assert_called_once()
        self.assertIs(print_status.call_args.args[0], project)
        open_project.assert_not_called()

    def test_parser_accepts_harness_on_the_projects_subcommand(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["projects", "tin", "shad", "--harness", "claude"])

        self.assertEqual(args.harness, "claude")
        self.assertEqual(args.name, ["tin", "shad"])

    def test_parser_defaults_harness_to_none(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["projects", "shad"])

        self.assertIsNone(args.harness)

    def test_parser_rejects_an_unknown_harness(self) -> None:
        parser = build_parser()

        with self.assertRaises(SystemExit), patch("sys.stderr"):
            parser.parse_args(["projects", "shad", "--harness", "nope"])


class SessionsCommandTests(unittest.TestCase):
    def _cfg(self) -> Config:
        return Config(defaults=Defaults(), projects={"kb": _make_project("kb")})

    def test_each_action_dispatches_to_its_slice(self) -> None:
        for action, target in (
            ("save", "save_sessions"),
            ("restore", "restore_sessions"),
            ("stop", "stop_sessions"),
            ("show", "show_sessions"),
        ):
            with self.subTest(action=action), patch(f"shad.cli.{target}") as mock:
                args = argparse.Namespace(sessions_action=action)
                cmd_sessions(self._cfg(), args)
                mock.assert_called_once_with(self._cfg(), args)

    def test_restore_exit_code_is_returned(self) -> None:
        with patch("shad.cli.restore_sessions", return_value=3):
            code = cmd_sessions(self._cfg(), argparse.Namespace(sessions_action="restore"))
        self.assertEqual(code, 3)

    def test_missing_action_raises_shad_error(self) -> None:
        with self.assertRaises(ShadError):
            cmd_sessions(self._cfg(), argparse.Namespace(sessions_action=None))


class TodoCommandTests(unittest.TestCase):
    def test_each_action_dispatches_to_its_slice(self) -> None:
        cfg = Config(defaults=Defaults())
        for action, target in (
            ("panel", "open_todo_panel"),
            ("add", "add_todo"),
            ("list", "list_todos"),
            ("status", "set_todo_status"),
            ("edit", "edit_todo"),
            ("rm", "remove_todo"),
        ):
            with self.subTest(action=action), patch(f"shad.cli.{target}") as mock:
                args = argparse.Namespace(todo_action=action)
                cmd_todo(cfg, args)
                mock.assert_called_once_with(cfg, args)

    def test_label_gets_the_config_path(self) -> None:
        cfg = Config(defaults=Defaults())
        args = argparse.Namespace(todo_action="label")
        with patch("shad.cli.manage_labels") as mock:
            cmd_todo(cfg, args, path=Path("/x/shad.toml"))
        mock.assert_called_once_with(cfg, args, Path("/x/shad.toml"))

    def test_missing_action_raises_shad_error(self) -> None:
        with self.assertRaises(ShadError):
            cmd_todo(Config(defaults=Defaults()), argparse.Namespace(todo_action=None))


class ErrorContractTests(TmuxCase):
    """
    Feature:    the root error contract
    Boundary:   any command, run through main(argv) or in a terminal pane.
                Contract: exit code + the one stderr line.
    Assumes:    the ERR-5 taxonomy; usage -> 2, every other category -> 1.
    """

    def test_usage_error_exits_2(self) -> None:
        """
        Criterion:  usage-error-exits-2
          When:     `shad projects a b c d`.
          Then:     exit 2, stdout empty, stderr is one line
                    `too_many_arguments: <non-empty>`.
        """
        self.write_config("[projects.kb]\npath = '/tmp/kb'\n")
        result = self.run_shad("projects", "a", "b", "c", "d")
        self.assertEqual((result.code, result.out), (2, ""), result.err)
        self.assertRegex(result.err, r"^too_many_arguments: .+\n$")

    def test_unknown_project_is_not_found(self) -> None:
        """
        Criterion:  unknown-project-is-not-found
          Given:    the config has projects `kb` and `alvr db`.
          When:     `shad projects nope status`.
          Then:     exit 1, stdout empty, stderr is one line
                    `no_such_project: <non-empty>`.
        """
        self.write_config("[projects.kb]\npath = '/tmp/kb'\n[projects.alvr.db]\npath = '/tmp/db'\n")
        result = self.run_shad("projects", "nope", "status")
        self.assertEqual((result.code, result.out), (1, ""), result.err)
        self.assertRegex(result.err, r"^no_such_project: .+\n$")

    def test_invalid_config_is_validation(self) -> None:
        """
        Criterion:  invalid-config-is-validation
          Given:    the config file is not valid TOML.
          When:     `shad projects`.
          Then:     exit 1, stdout empty, stderr is one line
                    `invalid_config: <non-empty>`, and no traceback.
        """
        self.write_config("[projects\n")
        result = self.run_shad("projects")
        self.assertEqual((result.code, result.out), (1, ""), result.err)
        self.assertRegex(result.err, r"^invalid_config: .+\n$")
        self.assertNotIn("Traceback", result.err)

    def test_debug_adds_traceback_to_stderr_only(self) -> None:
        """
        Criterion:  debug-adds-traceback-to-stderr-only
          Given:    the config file is not valid TOML.
          When:     `shad --debug projects`, and `shad projects --debug`.
          Then:     each exits 1, stdout empty, stderr starts with
                    `invalid_config:` and contains `Traceback`.
        """
        self.write_config("[projects\n")
        for argv in (("--debug", "projects"), ("projects", "--debug")):
            with self.subTest(argv=argv):
                result = self.run_shad(*argv)
                self.assertEqual((result.code, result.out), (1, ""), result.err)
                self.assertTrue(result.err.startswith("invalid_config: "), result.err)
                self.assertIn("Traceback", result.err)

    def test_interrupt_exits_130(self) -> None:
        """
        Criterion:  interrupt-exits-130
          When:     `shad init` in a pane, then Ctrl-C at its first prompt.
          Then:     the pane's exit status is 130 and the last line shad
                    printed is `Aborted.`
        """
        pane = self.pane("init")
        pane.wait_for("e.g. ~/gh/myproject")
        pane.send("C-c")
        self.assertEqual(pane.wait_exit(), 130)
        # tmux adds its own "Pane is dead" marker under the output.
        printed = [
            line for line in pane.screen().splitlines()
            if line.strip() and not line.startswith("Pane is dead")
        ]
        self.assertEqual(printed[-1], "Aborted.", pane.screen())


class MainErrorHandlingTests(unittest.TestCase):
    """
    The paths a boundary cannot provoke: an exception of a type the model does
    not declare, and the exit code a slice hands back. `[TEST-3]` unit tests.
    """

    def test_an_undeclared_exception_is_internal(self) -> None:
        with patch("shad.cli.load", side_effect=RuntimeError("boom")):
            result = run(["projects"])
        self.assertEqual((result.code, result.out), (1, ""), result.err)
        self.assertEqual(result.err, "unexpected: RuntimeError: boom\n")

    def test_the_error_line_carries_the_code_and_the_debug_traceback(self) -> None:
        boom = ShadError.conflict("todo_exists", "todo 'x' already exists")
        with patch("shad.cli.load", side_effect=boom):
            plain = run(["projects"])
            debug = run(["--debug", "projects"])
        self.assertEqual((plain.code, plain.err), (1, "todo_exists: todo 'x' already exists\n"))
        self.assertEqual(debug.code, 1)
        self.assertTrue(debug.err.startswith("todo_exists: todo 'x' already exists\n"), debug.err)
        self.assertIn("Traceback", debug.err)

    def test_shad_error_exits_1(self) -> None:
        with (
            patch("shad.cli.load", side_effect=ShadError.internal("boom", "boom")),
            patch("sys.stderr"),
        ):
            self.assertEqual(main(["projects"]), 1)

    def test_keyboard_interrupt_exits_130(self) -> None:
        with (
            patch("shad.cli.load", side_effect=KeyboardInterrupt()),
            patch("sys.stderr"),
        ):
            self.assertEqual(main(["projects"]), 130)

    def test_eof_error_exits_130(self) -> None:
        with (
            patch("shad.cli.load", side_effect=EOFError()),
            patch("sys.stderr"),
        ):
            self.assertEqual(main(["projects"]), 130)

    def test_a_bad_command_line_exits_2(self) -> None:
        with patch("sys.stderr"):
            self.assertEqual(main(["--nope"]), 2)

    def test_version_exits_0(self) -> None:
        with patch("sys.stdout"):
            self.assertEqual(main(["--version"]), 0)

    def test_no_command_prints_help_and_exits_0(self) -> None:
        with patch("shad.cli.print_banner"), patch("sys.stdout"):
            self.assertEqual(main([]), 0)

    def test_the_sessions_exit_code_is_returned(self) -> None:
        with (
            patch("shad.cli.load", return_value=Config(defaults=Defaults())),
            patch("shad.cli.cmd_sessions", return_value=3),
        ):
            self.assertEqual(main(["sessions", "restore"]), 3)

    def test_the_cheat_exit_code_is_returned(self) -> None:
        with patch("shad.cli.cmd_cheat", return_value=4):
            self.assertEqual(main(["cheat"]), 4)


# ---------------------------------------------------------------------------
# git command
# ---------------------------------------------------------------------------


class GitCliTests(unittest.TestCase):
    def test_sync_parses_tokens_and_flags(self) -> None:
        args = build_parser().parse_args(["git", "sync", "tin", "shad", "--yes"])
        self.assertEqual(args.command, "git")
        self.assertEqual(args.git_action, "sync")
        self.assertEqual(args.name, ["tin", "shad"])
        self.assertTrue(args.yes)
        self.assertFalse(args.dry_run)

    def test_sync_without_tokens_parses(self) -> None:
        args = build_parser().parse_args(["git", "sync", "--dry-run"])
        self.assertEqual(args.name, [])
        self.assertTrue(args.dry_run)
        self.assertFalse(args.yes)

    def test_bare_git_parses_with_no_action(self) -> None:
        args = build_parser().parse_args(["git"])
        self.assertEqual(args.command, "git")
        self.assertIsNone(args.git_action)

    def test_main_dispatches_git_after_loading_the_config(self) -> None:
        cfg = Config(defaults=Defaults())
        with (
            patch("shad.cli.load", return_value=cfg) as load,
            patch("shad.cli.cmd_git") as cmd_git,
        ):
            self.assertEqual(main(["git", "sync"]), 0)
        load.assert_called_once()
        cmd_git.assert_called_once()
        self.assertIs(cmd_git.call_args.args[0], cfg)

    def test_git_errors_exit_one(self) -> None:
        with (
            patch("shad.cli.load", return_value=Config(defaults=Defaults())),
            patch("shad.cli.cmd_git", side_effect=ShadError.internal("boom", "boom")),
            patch("sys.stderr"),
        ):
            self.assertEqual(main(["git", "sync"]), 1)


if __name__ == "__main__":
    unittest.main()
