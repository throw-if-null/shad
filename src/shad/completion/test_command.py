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
from shad.completion.command import BASH_COMPLETION, print_completion
from shad.shared.config import HARNESSES
from shad.shared.errors import ShadError

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

    def test_top_level_offers_the_global_option(self) -> None:
        self.assertIn("--config", self._run("shad "))

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
        self.assertEqual(offered, ["elsewhere", "--harness"])

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
            ["al", "alvr", "kb", "web"],
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
        self.assertEqual(
            sorted(self._run("shad projects ")),
            ["--harness", "al", "alvr", "kb", "web"],
        )

    def test_projects_offers_sub_projects_of_a_group(self) -> None:
        self.assertEqual(
            sorted(self._run("shad projects alvr ")), ["--harness", "api", "db"]
        )

    def test_projects_offers_actions_for_a_top_level_project(self) -> None:
        self.assertEqual(
            sorted(self._run("shad projects kb ")), ["--harness", "status", "stop"]
        )

    def test_projects_offers_actions_for_a_prefix_of_a_project(self) -> None:
        self.assertEqual(
            sorted(self._run("shad projects k ")), ["--harness", "status", "stop"]
        )

    def test_projects_offers_actions_for_a_grouped_project(self) -> None:
        self.assertEqual(
            sorted(self._run("shad projects alvr db ")),
            ["--harness", "status", "stop"],
        )

    def test_project_that_is_also_a_group_prefix_offers_both_continuations(self) -> None:
        # `shad projects al` opens the project; `shad projects al db` opens
        # the grouped one. Both resolve, so both are completable.
        self.assertEqual(
            sorted(self._run("shad projects al ")),
            ["--harness", "api", "db", "status", "stop"],
        )

    def test_projects_stops_completing_after_an_action(self) -> None:
        self.assertEqual(self._run("shad projects kb status "), [])
        self.assertEqual(self._run("shad projects alvr db stop "), [])

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
        self.assertNotIn("stop", offered)

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

    def test_config_set_completes_a_path_value_as_a_directory(self) -> None:
        self.assertEqual(self._run("shad config set projects.kb.path "), [])
        self.assertEqual(self._compopt(), ["-o", "dirnames"])

    def test_config_set_offers_nothing_for_a_free_form_value(self) -> None:
        self.assertEqual(self._run("shad config set projects.kb.session "), [])

    def test_config_show_does_not_repeat_its_flag(self) -> None:
        self.assertEqual(self._run("shad config show "), ["--raw"])
        self.assertEqual(self._run("shad config show --raw "), [])

    def test_config_read_only_actions_offer_nothing(self) -> None:
        for action in ("path", "keys", "edit", "validate"):
            self.assertEqual(self._run(f"shad config {action} "), [], action)

    # -- other subcommands ------------------------------------------------

    def test_completion_offers_only_supported_shells(self) -> None:
        self.assertEqual(self._run("shad completion "), ["bash"])
        with self.assertRaises(ShadError):
            print_completion("zsh")

    def test_init_offers_its_flag_once(self) -> None:
        self.assertEqual(self._run("shad init "), ["--install-deps"])
        self.assertEqual(self._run("shad init --install-deps "), [])

    def test_cheat_offers_nothing(self) -> None:
        self.assertEqual(self._run("shad cheat "), [])

    def test_unknown_subcommand_offers_nothing(self) -> None:
        self.assertEqual(self._run("shad nonsense "), [])


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
