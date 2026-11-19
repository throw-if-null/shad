"""
Behavioural tests for the generated bash completion script.

The script is not Python, so it is tested the way a shell would use it: a
real bash process sources it, `COMP_WORDS` and `COMP_CWORD` are set to a
typed command line, `_shad_complete` runs, and `COMPREPLY` is read back.

A stub `shad` on `PATH` makes the script's `shad config keys` call reach this
source tree. That coupling is deliberate — the script parses that command's
output, so a change to it must fail here rather than in the user's shell.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import shad
from shad.cli import build_parser
from shad.completion.command import BASH_COMPLETION
from shad.shared.config import HARNESSES
from shad.testing import run
from shad.todo import store
from shad.todo.model import STATUSES

BASH = shutil.which("bash") or ""
SHELLCHECK = shutil.which("shellcheck") or ""
SHFMT = shutil.which("shfmt") or ""


def _subcommands() -> list[str]:
    """Every subcommand name the parser accepts. argparse exposes no public API."""
    for action in build_parser()._actions:
        if isinstance(action, argparse._SubParsersAction):
            return list(action.choices)
    raise AssertionError("shad parser has no subcommands")

_CONFIG = """\
[defaults]
harness = "claude"

[projects.kb]
path = "{root}/kb"

[projects.web]
path = "{root}/web"

# `al` is a top-level project *and* a prefix of the `alvr` group.
[projects.al]
path = "{root}/al"

[projects.alvr.db]
path = "{root}/alvr/db"

[projects.alvr.api]
path = "{root}/alvr/api"

[todo]
labels = ["chore", "poc"]
"""

_OTHER_CONFIG = """\
[projects.elsewhere]
path = "{root}/elsewhere"
"""

# Sources the script, then drives it once. `compopt` is a builtin that only
# works inside a real completion, so it is stubbed out to a log file.
_DRIVER = """\
source "$1"
_shad_compopt_log="$4"
compopt() { printf '%s\\n' "$*" >>"$_shad_compopt_log"; }
mapfile -t COMP_WORDS <"$2"
COMP_CWORD="$3"
COMPREPLY=()
_shad_complete
((${#COMPREPLY[@]} > 0)) && printf '%s\\n' "${COMPREPLY[@]}"
exit 0
"""


class CompletionCommandTests(unittest.TestCase):
    """
    Feature:    completion
    Boundary:   command. `shad completion <shell>`, through main(argv).
                Contract: exit code + stdout + stderr. The output is a
                published surface: a shell sources it.
    """

    def test_completion_bash_prints_the_script(self) -> None:
        """
        Criterion:  completion-bash-prints-the-script
          When:     `shad completion bash`.
          Then:     exit 0, stderr empty, stdout is the bash completion
                    script, which defines `_shad_complete` and registers it.
        """
        result = run(["completion", "bash"])
        self.assertEqual((result.code, result.err), (0, ""), result.out)
        self.assertEqual(result.out, BASH_COMPLETION + "\n")
        self.assertIn("_shad_complete()", result.out)
        self.assertIn("complete -F _shad_complete shad", result.out)

    def test_completion_of_another_shell_is_a_usage_error(self) -> None:
        """
        Criterion:  completion-of-another-shell-is-a-usage-error
          When:     `shad completion zsh`.
          Then:     exit 2, stdout empty, stderr names bash.
        """
        result = run(["completion", "zsh"])
        self.assertEqual((result.code, result.out), (2, ""), result.err)
        self.assertIn("bash", result.err)


@unittest.skipUnless(BASH, "bash is required to run the completion script")
class CompletionScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        for name in ("kb", "web", "al", "elsewhere", "alvr/db", "alvr/api"):
            (self.root / name).mkdir(parents=True)

        self.config = self.root / "shad.toml"
        self.config.write_text(_CONFIG.format(root=self.root))
        self.other_config = self.root / "other.toml"
        self.other_config.write_text(_OTHER_CONFIG.format(root=self.root))

        self.script = self.root / "shad-completion.bash"
        self.script.write_text(BASH_COMPLETION + "\n")
        self.driver = self.root / "driver.bash"
        self.driver.write_text(_DRIVER)

        # A `shad` that runs this source tree, so the script's own
        # `shad config keys` call is the one under test.
        self.bin = self.root / "bin"
        self.bin.mkdir()
        stub = self.bin / "shad"
        stub.write_text(
            "#!/bin/sh\n"
            f'exec "{sys.executable}" -c '
            "'from shad.cli import main; main()' \"$@\"\n"
        )
        stub.chmod(0o755)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- helpers ----------------------------------------------------------

    def _run(self, line: str, *, config: Path | None = None) -> list[str]:
        """
        Complete *line*, whose final word is the one being completed.

        A trailing space means the next word is being started, matching what
        bash reports when the user presses TAB after a space.
        """
        words = line.split(" ")
        cword = len(words) - 1

        words_file = self.root / "words"
        words_file.write_text("".join(f"{word}\n" for word in words))
        self.compopt_log = self.root / "compopt"
        self.compopt_log.write_text("")

        env = dict(os.environ)
        env["PATH"] = f"{self.bin}{os.pathsep}{env['PATH']}"
        env["PYTHONPATH"] = str(Path(shad.__file__).parent.parent)
        env["SHAD_CONFIG"] = str(config or self.config)
        # Todo files for the key completions live under here, not in ~.
        env["XDG_DATA_HOME"] = str(self.root / "xdg")

        result = subprocess.run(
            [BASH, str(self.driver), str(self.script), str(words_file),
             str(cword), str(self.compopt_log)],
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        self.assertEqual(result.stderr, "")
        return result.stdout.split()

    def _compopt(self) -> list[str]:
        return self.compopt_log.read_text().split()

    # -- top level --------------------------------------------------------

    def test_every_subcommand_is_offered(self) -> None:
        """
        Guards against the failure this module was missing: a subcommand
        added to the parser but never added to the completion script.
        """
        offered = self._run("shad ")
        for name in _subcommands():
            self.assertIn(name, offered)

    def test_top_level_offers_the_global_options(self) -> None:
        offered = self._run("shad ")
        self.assertIn("--config", offered)
        self.assertIn("--json", offered)

    def test_top_level_filters_on_the_partial_word(self) -> None:
        self.assertEqual(self._run("shad co"), ["config", "completion"])

    # -- the global --config option ---------------------------------------

    def test_config_option_value_falls_back_to_filenames(self) -> None:
        self.assertEqual(self._run("shad --config "), [])
        self.assertEqual(self._compopt(), ["-o", "default"])

    def test_config_option_does_not_suppress_subcommands(self) -> None:
        offered = self._run(f"shad --config {self.other_config} ")
        self.assertIn("projects", offered)
        self.assertIn("git", offered)
        self.assertNotIn("--config", offered)

    def test_config_option_selects_the_file_project_names_come_from(self) -> None:
        offered = self._run(f"shad --config {self.other_config} projects ")
        self.assertEqual(offered, ["elsewhere", "--json", "--harness"])

    # -- the projects --harness option ------------------------------------

    def test_projects_offers_the_harness_flag(self) -> None:
        self.assertIn("--harness", self._run("shad projects "))

    def test_harness_flag_offers_every_known_harness(self) -> None:
        """A harness added to config.HARNESSES must reach the script too."""
        self.assertEqual(
            sorted(self._run("shad projects --harness ")), sorted(HARNESSES)
        )

    def test_harness_flag_offers_values_for_the_equals_spelling(self) -> None:
        self.assertEqual(
            sorted(self._run("shad projects --harness = ")), sorted(HARNESSES)
        )

    def test_harness_value_does_not_shift_project_positions(self) -> None:
        self.assertEqual(
            sorted(self._run("shad projects --harness claude ")),
            ["--json", "al", "alvr", "kb", "web"],
        )

    def test_harness_value_does_not_shift_sub_project_positions(self) -> None:
        self.assertEqual(
            sorted(self._run("shad projects --harness claude alvr ")), ["api", "db"]
        )

    def test_harness_flag_is_not_offered_twice(self) -> None:
        self.assertNotIn("--harness", self._run("shad projects --harness claude "))

    def test_harness_flag_is_not_offered_after_an_action(self) -> None:
        self.assertNotIn("--harness", self._run("shad projects kb status "))

    def test_harness_flag_is_not_offered_for_git(self) -> None:
        self.assertNotIn("--harness", self._run("shad git sync "))

    # -- projects ---------------------------------------------------------

    def test_projects_offers_top_level_keys_and_group_names(self) -> None:
        # With no name the line lists, so --json is offered beside --harness.
        self.assertEqual(
            sorted(self._run("shad projects ")),
            ["--harness", "--json", "al", "alvr", "kb", "web"],
        )

    def test_projects_offers_sub_projects_of_a_group(self) -> None:
        self.assertEqual(
            sorted(self._run("shad projects alvr ")), ["--harness", "api", "db"]
        )

    def test_projects_offers_actions_for_a_top_level_project(self) -> None:
        self.assertEqual(
            sorted(self._run("shad projects kb ")), ["--harness", "status"]
        )

    def test_projects_offers_actions_for_a_prefix_of_a_project(self) -> None:
        self.assertEqual(
            sorted(self._run("shad projects k ")), ["--harness", "status"]
        )

    def test_projects_offers_actions_for_a_grouped_project(self) -> None:
        self.assertEqual(
            sorted(self._run("shad projects alvr db ")),
            ["--harness", "status"],
        )

    def test_project_that_is_also_a_group_prefix_offers_both_continuations(self) -> None:
        # `shad projects al` opens the project; `shad projects al db` opens
        # the grouped one. Both resolve, so both are completable.
        self.assertEqual(
            sorted(self._run("shad projects al ")),
            ["--harness", "api", "db", "status"],
        )

    def test_projects_offers_only_json_after_an_action(self) -> None:
        self.assertEqual(self._run("shad projects kb status "), ["--json"])
        self.assertEqual(self._run("shad projects alvr db status "), ["--json"])
        self.assertEqual(self._run("shad projects alvr db status --json "), [])

    def test_projects_offers_nothing_beyond_a_grouped_project(self) -> None:
        self.assertEqual(self._run("shad projects alvr db extra "), [])

    # -- git sync ---------------------------------------------------------

    def test_git_offers_its_actions(self) -> None:
        self.assertEqual(sorted(self._run("shad git ")), ["panel", "sync"])

    def test_git_offers_nothing_for_an_unknown_action(self) -> None:
        self.assertEqual(self._run("shad git bogus "), [])

    def test_git_sync_offers_projects_and_flags(self) -> None:
        offered = self._run("shad git sync ")
        self.assertEqual(sorted(offered),
                         ["--dry-run", "--switch", "--yes", "al", "alvr", "kb", "web"])

    def test_git_sync_still_offers_projects_after_a_flag(self) -> None:
        offered = self._run("shad git sync --dry-run ")
        self.assertIn("kb", offered)
        self.assertIn("alvr", offered)

    def test_git_sync_does_not_repeat_a_flag(self) -> None:
        self.assertNotIn("--dry-run", self._run("shad git sync --dry-run "))
        self.assertNotIn("--yes", self._run("shad git sync kb --yes "))

    def test_git_panel_offers_projects_and_its_own_flag(self) -> None:
        offered = self._run("shad git panel ")
        self.assertEqual(sorted(offered), ["--no-fetch", "al", "alvr", "kb", "web"])

    def test_git_panel_does_not_offer_sync_flags(self) -> None:
        offered = self._run("shad git panel ")
        for flag in ("--switch", "--yes", "--dry-run"):
            self.assertNotIn(flag, offered)

    def test_git_panel_offers_subprojects_of_a_group(self) -> None:
        self.assertIn("db", self._run("shad git panel alvr "))

    def test_git_sync_offers_flags_after_a_grouped_project(self) -> None:
        self.assertEqual(sorted(self._run("shad git sync alvr db ")),
                         ["--dry-run", "--switch", "--yes"])

    def test_git_sync_offers_sub_projects_of_a_group(self) -> None:
        offered = self._run("shad git sync alvr ")
        self.assertIn("db", offered)
        self.assertIn("api", offered)

    def test_git_sync_offers_no_project_actions(self) -> None:
        offered = self._run("shad git sync kb ")
        self.assertNotIn("status", offered)

    # -- config -----------------------------------------------------------

    def test_config_offers_every_action(self) -> None:
        self.assertEqual(
            sorted(self._run("shad config ")),
            ["edit", "get", "keys", "path", "set", "show", "unset", "validate"],
        )

    def test_config_get_offers_keys(self) -> None:
        offered = self._run("shad config get ")
        self.assertIn("defaults.harness", offered)
        self.assertIn("projects.kb.path", offered)
        self.assertIn("projects.alvr.db.session", offered)

    def test_config_get_filters_keys_on_the_partial_word(self) -> None:
        offered = self._run("shad config get projects.al")
        self.assertIn("projects.al.path", offered)
        self.assertIn("projects.alvr.db.path", offered)
        self.assertNotIn("projects.kb.path", offered)

    def test_config_set_offers_enum_values(self) -> None:
        self.assertEqual(sorted(self._run("shad config set defaults.harness ")),
                         ["claude", "opencode"])
        self.assertEqual(sorted(self._run("shad config set defaults.oc_position ")),
                         ["bottom", "left", "top"])
        self.assertEqual(sorted(self._run("shad config set projects.alvr.db.harness ")),
                         ["claude", "opencode"])

    def test_config_set_offers_true_and_false_for_a_panel_switch(self) -> None:
        for key in ("defaults.git_panel", "defaults.todo_panel"):
            with self.subTest(key=key):
                self.assertEqual(sorted(self._run(f"shad config set {key} ")),
                                 ["false", "true"])

    def test_config_set_completes_a_path_value_as_a_directory(self) -> None:
        self.assertEqual(self._run("shad config set projects.kb.path "), [])
        self.assertEqual(self._compopt(), ["-o", "dirnames"])

    def test_config_set_completes_the_todo_path_as_a_directory(self) -> None:
        self.assertIn("todo.path", self._run("shad config set to"))
        self.assertEqual(self._run("shad config set todo.path "), [])
        self.assertEqual(self._compopt(), ["-o", "dirnames"])

    def test_config_set_offers_nothing_for_a_free_form_value(self) -> None:
        self.assertEqual(self._run("shad config set projects.kb.session "), [])

    def test_config_show_does_not_repeat_its_flags(self) -> None:
        self.assertEqual(self._run("shad config show "), ["--json", "--raw"])
        self.assertEqual(self._run("shad config show --raw "), ["--json"])
        self.assertEqual(self._run("shad config show --raw --json "), [])

    def test_config_reads_offer_json(self) -> None:
        self.assertEqual(self._run("shad config validate "), ["--json"])
        self.assertEqual(self._run("shad config get defaults.harness "), ["--json"])

    def test_config_plain_actions_offer_nothing(self) -> None:
        for action in ("path", "keys", "edit"):
            self.assertEqual(self._run(f"shad config {action} "), [], action)

    # -- todo -------------------------------------------------------------

    def _todo_items(self, *titles: str) -> None:
        directory = self.root / "xdg" / "shad" / "todo"
        for title in titles:
            store.add(directory, title, [], [])

    def test_todo_offers_its_actions(self) -> None:
        self.assertEqual(
            sorted(self._run("shad todo ")),
            ["add", "edit", "label", "list", "panel", "rm", "status"],
        )

    def test_todo_panel_offers_nothing(self) -> None:
        self.assertEqual(self._run("shad todo panel "), [])

    def test_todo_add_offers_the_label_flag_repeatedly_and_label_values(self) -> None:
        self.assertEqual(self._run("shad todo add t "), ["--label"])
        self.assertEqual(self._run("shad todo add t --label chore "), ["--label"])
        self.assertEqual(sorted(self._run("shad todo add t --label ")), ["chore", "poc"])

    def test_todo_list_offers_its_flags_once(self) -> None:
        self.assertEqual(self._run("shad todo list "), ["--json", "--keys"])
        self.assertEqual(self._run("shad todo list --keys "), ["--json"])

    def test_todo_status_offers_every_status_after_the_key(self) -> None:
        self.assertEqual(
            sorted(self._run("shad todo status some-key ")), sorted(STATUSES)
        )
        self.assertEqual(self._run("shad todo status some-key done "), [])

    def test_todo_offers_the_item_keys(self) -> None:
        self._todo_items("Fix panel", "Write docs")
        self.assertEqual(sorted(self._run("shad todo rm ")), ["fix-panel", "write-docs"])
        self.assertEqual(
            sorted(self._run("shad todo status ")), ["fix-panel", "write-docs"]
        )
        self.assertEqual(self._run("shad todo edit fi"), ["fix-panel"])
        self.assertEqual(self._run("shad todo edit fix-panel "), [])

    def test_todo_keys_come_from_the_todo_path_of_the_selected_config(self) -> None:
        notes = self.root / "notes"
        self.other_config.write_text(
            _OTHER_CONFIG.format(root=self.root) + f'\n[todo]\npath = "{notes}"\n'
        )
        store.add(notes, "Elsewhere", [], [])
        self._todo_items("Fix panel")
        self.assertEqual(
            self._run(f"shad --config {self.other_config} todo rm "), ["elsewhere"]
        )

    def test_todo_label_offers_its_actions_and_configured_labels(self) -> None:
        self.assertEqual(sorted(self._run("shad todo label ")), ["add", "list", "rm"])
        self.assertEqual(sorted(self._run("shad todo label rm ")), ["chore", "poc"])
        self.assertEqual(self._run("shad todo label rm chore "), ["--force"])
        self.assertEqual(self._run("shad todo label add "), [])
        self.assertEqual(self._run("shad todo label list "), [])

    # -- other subcommands ------------------------------------------------

    def test_completion_offers_only_supported_shells(self) -> None:
        self.assertEqual(self._run("shad completion "), ["bash"])

    def test_init_offers_its_flag_once(self) -> None:
        self.assertEqual(self._run("shad init "), ["--install-deps"])
        self.assertEqual(self._run("shad init --install-deps "), [])

    def test_cheat_offers_nothing(self) -> None:
        self.assertEqual(self._run("shad cheat "), [])

    def test_unknown_subcommand_offers_nothing(self) -> None:
        self.assertEqual(self._run("shad nonsense "), [])


class CompletionScriptSessionsTests(CompletionScriptTests):
    def test_sessions_offers_its_actions(self) -> None:
        self.assertEqual(self._run("shad sessions "), ["save", "restore", "stop", "show"])

    def test_sessions_save_offers_its_flag_once(self) -> None:
        self.assertEqual(self._run("shad sessions save "), ["--all"])
        self.assertEqual(self._run("shad sessions save --all "), [])

    def test_sessions_stop_offers_nothing_and_show_offers_json(self) -> None:
        self.assertEqual(self._run("shad sessions stop "), [])
        self.assertEqual(self._run("shad sessions show "), ["--json"])
        self.assertEqual(self._run("shad sessions show --json "), [])

    def test_sessions_restore_offers_its_flag_once(self) -> None:
        self.assertEqual(self._run("shad sessions restore "), ["--no-attach"])
        self.assertEqual(self._run("shad sessions restore --no-attach "), [])


class CompletionScriptLintTests(unittest.TestCase):
    def _write(self) -> Path:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        path = Path(self._tmp.name) / "shad-completion.bash"
        path.write_text("#!/usr/bin/env bash\n" + BASH_COMPLETION + "\n")
        return path

    @unittest.skipUnless(SHELLCHECK, "shellcheck is not installed")
    def test_script_passes_shellcheck(self) -> None:
        result = subprocess.run(
            [SHELLCHECK, str(self._write())],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)

    @unittest.skipUnless(SHFMT, "shfmt is not installed")
    def test_script_is_formatted(self) -> None:
        result = subprocess.run(
            [SHFMT, "-i", "4", "-d", str(self._write())],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)


if __name__ == "__main__":
    unittest.main()
