from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from shad.cheat import command as cheat
from shad.cli import build_parser, main
from shad.config import Config, Defaults, Project
from shad.config.show import command as config_show
from shad.errors import ShadError
from shad.git.panel import command as git_panel
from shad.git.sync import command as git_sync
from shad.projects import command as projects
from shad.sessions.restore import command as restore
from shad.sessions.show import command as sessions_show
from shad.testing import TmuxCase, run
from shad.todo.label.list import command as label_list
from shad.todo.list import command as todo_list


class ParserRegistrationTests(unittest.TestCase):
    """Each package registers its own parser and records what the root runs."""

    def test_each_parser_records_its_run(self) -> None:
        parser = build_parser()
        for argv, expected in (
            (["projects"], projects.run),
            (["git", "sync"], git_sync.run),
            (["git", "panel"], git_panel.run),
            (["config"], config_show.run),
            (["config", "show"], config_show.run),
            (["todo", "list"], todo_list.run),
            (["todo", "label", "list"], label_list.run),
            (["sessions", "show"], sessions_show.run),
            (["sessions", "restore"], restore.run),
            (["cheat"], cheat.run),
        ):
            with self.subTest(argv=argv):
                self.assertIs(parser.parse_args(argv).run, expected)

    def test_only_a_read_parser_records_a_render(self) -> None:
        parser = build_parser()
        for argv, reads in (
            (["projects"], True),
            (["config"], True),
            (["config", "get", "k"], True),
            (["config", "validate"], True),
            (["config", "path"], False),
            (["config", "set", "k", "v"], False),
            (["todo", "list"], True),
            (["todo", "add", "x"], False),
            (["sessions", "show"], True),
            (["sessions", "save"], False),
            (["git", "sync"], False),
            (["cheat"], False),
        ):
            with self.subTest(argv=argv):
                self.assertEqual(parser.parse_args(argv).render is not None, reads)

    def test_json_is_accepted_before_and_after_a_read_command(self) -> None:
        parser = build_parser()
        for argv in (["--json", "todo", "list"], ["todo", "list", "--json"], ["todo", "--json", "list"]):
            with self.subTest(argv=argv):
                self.assertTrue(parser.parse_args(argv).json)

    def test_json_is_parsed_in_any_position_on_any_command(self) -> None:
        # The root rejects it where it does not apply, so the rejection has one form.
        self.assertTrue(build_parser().parse_args(["todo", "add", "x", "--json"]).json)

    def test_the_projects_parser_takes_the_harness(self) -> None:
        args = build_parser().parse_args(["projects", "tin", "shad", "--harness", "claude"])
        self.assertEqual(args.harness, "claude")
        self.assertEqual(args.name, ["tin", "shad"])
        self.assertIsNone(build_parser().parse_args(["projects", "shad"]).harness)
        with self.assertRaises(SystemExit), patch("sys.stderr"):
            build_parser().parse_args(["projects", "shad", "--harness", "nope"])


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

    def test_json_on_a_command_without_a_result_is_a_usage_error(self) -> None:
        """
        Criterion:  json-on-a-command-without-a-result-is-a-usage-error
          When:     `shad --json todo add x`, and `shad todo add x --json`.
          Then:     each exits 2, stdout empty, stderr one line
                    `no_json: <non-empty>`, and no item is created.
        """
        self.write_config("[projects.kb]\npath = '/tmp/kb'\n")
        for argv in (("--json", "todo", "add", "x"), ("todo", "add", "x", "--json")):
            with self.subTest(argv=argv):
                result = self.run_shad(*argv)
                self.assertEqual((result.code, result.out), (2, ""), result.err)
                self.assertRegex(result.err, r"^no_json: .+\n$")
        self.assertEqual(self.run_shad("todo", "list", "--keys").out, "")

    def test_interrupt_exits_130(self) -> None:
        """
        Criterion:  interrupt-exits-130
          When:     `shad init --wizard` in a pane, then Ctrl-C at its first prompt.
          Then:     the pane's exit status is 130 and the last line shad
                    printed is `Aborted.`
        """
        pane = self.pane("init", "--wizard")
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
        with patch("shad.wiring.load", side_effect=RuntimeError("boom")):
            result = run(["projects"])
        self.assertEqual((result.code, result.out), (1, ""), result.err)
        self.assertEqual(result.err, "unexpected: RuntimeError: boom\n")

    def test_the_error_line_carries_the_code_and_the_debug_traceback(self) -> None:
        boom = ShadError.conflict("todo_exists", "todo 'x' already exists")
        with patch("shad.wiring.load", side_effect=boom):
            plain = run(["projects"])
            debug = run(["--debug", "projects"])
        self.assertEqual((plain.code, plain.err), (1, "todo_exists: todo 'x' already exists\n"))
        self.assertEqual(debug.code, 1)
        self.assertTrue(debug.err.startswith("todo_exists: todo 'x' already exists\n"), debug.err)
        self.assertIn("Traceback", debug.err)

    def test_shad_error_exits_1(self) -> None:
        with (
            patch("shad.wiring.load", side_effect=ShadError.internal("boom", "boom")),
            patch("sys.stderr"),
        ):
            self.assertEqual(main(["projects"]), 1)

    def test_keyboard_interrupt_exits_130(self) -> None:
        with (
            patch("shad.wiring.load", side_effect=KeyboardInterrupt()),
            patch("sys.stderr"),
        ):
            self.assertEqual(main(["projects"]), 130)

    def test_eof_error_exits_130(self) -> None:
        with (
            patch("shad.wiring.load", side_effect=EOFError()),
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

    def test_the_exit_status_a_hand_over_returns_is_the_exit_code(self) -> None:
        with patch("shad.sessions.restore.command.run", autospec=True, return_value=3):
            self.assertEqual(main(["sessions", "restore"]), 3)
        with patch("shad.cheat.command.run", autospec=True, return_value=4):
            self.assertEqual(main(["cheat"]), 4)

    def test_json_on_a_command_without_a_result_is_refused_before_it_runs(self) -> None:
        for argv in (["--json", "todo", "add", "x"], ["todo", "add", "x", "--json"]):
            with self.subTest(argv=argv), patch("shad.todo.add.command.run") as add:
                result = run(argv)
                self.assertEqual((result.code, result.out), (2, ""), result.err)
                self.assertRegex(result.err, r"^no_json: .+\n$")
                add.assert_not_called()


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

    def test_main_hands_sync_the_projects_of_the_loaded_config(self) -> None:
        cfg = Config(defaults=Defaults(), projects={"kb": Project("kb", None, Path("/kb"), "kb")})
        with (
            patch("shad.wiring.load", return_value=cfg) as load,
            patch("shad.git.sync.command.run", autospec=True, return_value=None) as run_sync,
        ):
            self.assertEqual(main(["git", "sync"]), 0)
            run_sync.assert_called_once()
            self.assertEqual(run_sync.call_args.kwargs["projects"], cfg.project_table)
            self.assertNotIn("config", run_sync.call_args.kwargs)
            load.assert_called_once()

    def test_git_errors_exit_one(self) -> None:
        with (
            patch("shad.git.sync.command.run", side_effect=ShadError.internal("boom", "boom")),
            patch("sys.stderr"),
        ):
            self.assertEqual(main(["git", "sync"]), 1)


if __name__ == "__main__":
    unittest.main()
