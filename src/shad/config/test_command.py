from __future__ import annotations

import argparse
import io
import tomllib
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from shad.config.command import cmd_config
from shad.shared.errors import ShadError

_CONFIG = """\
[defaults]
oc_position   = "top"
panel_percent = 35  # bundle width

[projects.kb]
path    = "{root}/kb"
session = "kb"

[projects.alvr.db]
path    = "{root}/alvr/db"
"""


def _args(action: str | None, **kwargs: object) -> argparse.Namespace:
    kwargs.setdefault("force", False)
    kwargs.setdefault("raw", False)
    return argparse.Namespace(config_action=action, **kwargs)


class ConfigCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "kb").mkdir()
        (self.root / "alvr" / "db").mkdir(parents=True)
        self.path = self.root / "shad.toml"
        self.path.write_text(_CONFIG.format(root=self.root))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- helpers ----------------------------------------------------------

    def _run(self, action: str | None, **kwargs: object) -> str:
        buffer = io.StringIO()
        with patch("shad.config.command.console"), redirect_stdout(buffer):
            cmd_config(_args(action, **kwargs), self.path)
        return buffer.getvalue()

    def _raw(self) -> dict:
        with self.path.open("rb") as fh:
            return tomllib.load(fh)

    # -- read-only actions ------------------------------------------------

    def test_path_prints_config_path(self) -> None:
        self.assertEqual(self._run("path").strip(), str(self.path))

    def test_keys_lists_defaults_and_every_project_field(self) -> None:
        keys = self._run("keys").split()
        self.assertIn("defaults.oc_position", keys)
        self.assertIn("defaults.harness", keys)
        self.assertIn("projects.kb.session", keys)
        self.assertIn("projects.alvr.db.harness", keys)

    def test_get_prints_scalar_value(self) -> None:
        self.assertEqual(self._run("get", key="defaults.panel_percent").strip(), "35")

    def test_get_expands_table_into_dotted_lines(self) -> None:
        output = self._run("get", key="projects.alvr")
        self.assertIn(f'projects.alvr.db.path = "{self.root}/alvr/db"', output)

    def test_get_falls_back_to_effective_default(self) -> None:
        self.path.write_text(f'[projects.kb]\npath = "{self.root}/kb"\n')
        self.assertEqual(self._run("get", key="defaults.oc_position").strip(), "top")

    def test_get_falls_back_to_derived_session(self) -> None:
        self.assertEqual(self._run("get", key="projects.alvr.db.session").strip(), "alvr-db")

    def test_get_falls_back_to_default_harness(self) -> None:
        self.assertEqual(self._run("get", key="projects.kb.harness").strip(), "opencode")

    def test_get_unknown_project_raises(self) -> None:
        with self.assertRaises(ShadError):
            self._run("get", key="projects.nope.session")

    def test_get_unknown_key_raises(self) -> None:
        with self.assertRaises(ShadError) as ctx:
            self._run("get", key="defaults.nope")
        self.assertIn("key not found", str(ctx.exception))

    def test_show_raw_prints_file_verbatim(self) -> None:
        self.assertEqual(self._run("show", raw=True), self.path.read_text())

    def test_show_renders_without_error(self) -> None:
        self._run("show")

    def test_default_action_is_show(self) -> None:
        self._run(None)

    def test_validate_accepts_a_good_config(self) -> None:
        self._run("validate")

    def test_validate_rejects_a_broken_config(self) -> None:
        self.path.write_text('[defaults]\noc_position = "sideways"\n')
        with self.assertRaises(ShadError):
            self._run("validate")

    def test_missing_file_reports_init_hint(self) -> None:
        self.path.unlink()
        with self.assertRaises(ShadError) as ctx:
            self._run("get", key="defaults.harness")
        self.assertIn("shad init", str(ctx.exception))

    def test_unknown_action_raises(self) -> None:
        with self.assertRaises(ShadError):
            self._run("frobnicate")

    # -- set --------------------------------------------------------------

    def test_set_updates_value_and_keeps_comment(self) -> None:
        self._run("set", key="defaults.panel_percent", value="42")
        self.assertEqual(self._raw()["defaults"]["panel_percent"], 42)
        self.assertIn("panel_percent = 42  # bundle width", self.path.read_text())

    def test_set_normalises_enum_case(self) -> None:
        self._run("set", key="defaults.harness", value="CLAUDE")
        self.assertEqual(self._raw()["defaults"]["harness"], "claude")

    def test_set_rejects_invalid_enum(self) -> None:
        with self.assertRaises(ShadError) as ctx:
            self._run("set", key="defaults.oc_position", value="sideways")
        self.assertIn("must be one of", str(ctx.exception))
        self.assertEqual(self._raw()["defaults"]["oc_position"], "top")

    def test_set_rejects_percent_out_of_range(self) -> None:
        with self.assertRaises(ShadError):
            self._run("set", key="defaults.split_percent", value="200")

    def test_set_rejects_non_integer_percent(self) -> None:
        with self.assertRaises(ShadError):
            self._run("set", key="defaults.panel_percent", value="wide")

    def test_set_rejects_unknown_key_without_force(self) -> None:
        with self.assertRaises(ShadError) as ctx:
            self._run("set", key="defaults.nope", value="1")
        self.assertIn("unknown key", str(ctx.exception))

    def test_set_forced_unknown_key_infers_type(self) -> None:
        self._run("set", key="defaults.nope", value="7", force=True)
        self.assertEqual(self._raw()["defaults"]["nope"], 7)

    def test_set_rejects_missing_project_path(self) -> None:
        with self.assertRaises(ShadError) as ctx:
            self._run("set", key="projects.kb.path", value=str(self.root / "gone"))
        self.assertIn("path does not exist", str(ctx.exception))

    def test_set_forced_missing_project_path_is_written(self) -> None:
        target = self.root / "gone"
        self._run("set", key="projects.kb.path", value=str(target), force=True)
        self.assertEqual(self._raw()["projects"]["kb"]["path"], str(target))

    def test_set_expands_user_in_paths(self) -> None:
        with patch.dict("os.environ", {"HOME": str(self.root)}):
            self._run("set", key="projects.kb.path", value="~/kb")
        self.assertEqual(self._raw()["projects"]["kb"]["path"], str(self.root / "kb"))

    def test_set_creates_a_new_project_table(self) -> None:
        fresh = self.root / "fresh"
        fresh.mkdir()
        self._run("set", key="projects.fresh.path", value=str(fresh))
        self.assertEqual(self._raw()["projects"]["fresh"]["path"], str(fresh))

    def test_set_refuses_a_path_another_project_already_uses(self) -> None:
        # _commit validates through load() before replacing the file, so the
        # duplicate-directory rule is enforced on writes without extra wiring.
        before = self.path.read_text()
        with self.assertRaises(ShadError) as ctx:
            self._run("set", key="projects.fresh.path", value=str(self.root / "kb"))
        self.assertIn("both point at", str(ctx.exception))
        self.assertEqual(self.path.read_text(), before)

    def test_set_refuses_to_point_a_project_at_another_projects_path(self) -> None:
        before = self.path.read_text()
        with self.assertRaises(ShadError) as ctx:
            self._run(
                "set",
                key="projects.alvr.db.path",
                value=str(self.root / "kb"),
                force=True,
            )
        self.assertIn("both point at", str(ctx.exception))
        self.assertEqual(self.path.read_text(), before)

    def test_set_refuses_a_project_without_a_path(self) -> None:
        before = self.path.read_text()
        with self.assertRaises(ShadError) as ctx:
            self._run("set", key="projects.grp.sub.session", value="x")
        self.assertIn("set its 'path' first", str(ctx.exception))
        self.assertEqual(self.path.read_text(), before)

    def test_set_keeps_file_mode(self) -> None:
        self.path.chmod(0o600)
        self._run("set", key="defaults.panel_percent", value="40")
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_set_leaves_no_temporary_files_behind(self) -> None:
        self._run("set", key="defaults.panel_percent", value="40")
        self.assertEqual(
            [p.name for p in self.root.iterdir() if p.name.startswith(".shad.toml")], []
        )

    # -- unset ------------------------------------------------------------

    def test_unset_removes_a_key(self) -> None:
        self._run("unset", key="projects.kb.session")
        self.assertNotIn("session", self._raw()["projects"]["kb"])

    def test_unset_removes_a_whole_project(self) -> None:
        self._run("unset", key="projects.kb")
        self.assertNotIn("kb", self._raw()["projects"])

    def test_unset_guards_a_required_project_path(self) -> None:
        with self.assertRaises(ShadError) as ctx:
            self._run("unset", key="projects.kb.path")
        self.assertIn("is required", str(ctx.exception))
        self.assertIn(f"{self.root}/kb", self.path.read_text())

    def test_unset_forced_required_key_is_removed(self) -> None:
        self._run("unset", key="projects.kb.session")
        self._run("unset", key="projects.kb.path", force=True)
        self.assertEqual(self._raw()["projects"]["kb"], {})

    def test_unset_forced_key_still_refused_when_it_breaks_the_config(self) -> None:
        before = self.path.read_text()
        with self.assertRaises(ShadError) as ctx:
            self._run("unset", key="projects.kb.path", force=True)
        self.assertIn("resulting config is invalid", str(ctx.exception))
        self.assertEqual(self.path.read_text(), before)

    def test_unset_unknown_key_raises(self) -> None:
        with self.assertRaises(ShadError):
            self._run("unset", key="projects.nothere")

    # -- edit -------------------------------------------------------------

    def test_edit_runs_editor_then_validates(self) -> None:
        with (
            patch.dict("os.environ", {"EDITOR": "true"}),
            patch("shad.config.command.subprocess.run") as run,
        ):
            run.return_value.returncode = 0
            self._run("edit")
        run.assert_called_once_with(["true", str(self.path)], check=False)

    def test_edit_reports_editor_failure(self) -> None:
        with (
            patch.dict("os.environ", {"EDITOR": "false"}),
            patch("shad.config.command.subprocess.run") as run,
        ):
            run.return_value.returncode = 1
            with self.assertRaises(ShadError) as ctx:
                self._run("edit")
        self.assertIn("editor exited", str(ctx.exception))
