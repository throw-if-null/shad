from __future__ import annotations

import textwrap
import unittest
from pathlib import Path

from shad.shared.config import Config, Defaults, Project, load, resolve_prefix
from shad.shared.errors import ShadError


# ---------------------------------------------------------------------------
# resolve_prefix
# ---------------------------------------------------------------------------

class ResolvePrefixTests(unittest.TestCase):
    def test_exact_match_returned_directly(self) -> None:
        result = resolve_prefix(["shad", "shell"], "shad")
        self.assertEqual(result, "shad")

    def test_unique_prefix_returns_candidate(self) -> None:
        result = resolve_prefix(["shad", "shell"], "sha")
        self.assertEqual(result, "shad")

    def test_ambiguous_prefix_raises_shad_error(self) -> None:
        with self.assertRaises(ShadError) as ctx:
            resolve_prefix(["shad", "shell", "sheep"], "sh")
        self.assertIn("ambiguous", str(ctx.exception))
        self.assertIn("shad", str(ctx.exception))
        self.assertIn("sheep", str(ctx.exception))

    def test_no_match_returns_none(self) -> None:
        result = resolve_prefix(["shad", "shell"], "xyz")
        self.assertIsNone(result)

    def test_empty_candidates_returns_none(self) -> None:
        result = resolve_prefix([], "shad")
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Project.display_name
# ---------------------------------------------------------------------------

class ProjectDisplayNameTests(unittest.TestCase):
    def test_grouped_project_display_name(self) -> None:
        p = Project(key="shad", group="tin", path=Path("/tmp"), session="tin-shad")
        self.assertEqual(p.display_name, "tin shad")

    def test_top_level_project_display_name(self) -> None:
        p = Project(key="shad", group=None, path=Path("/tmp"), session="shad")
        self.assertEqual(p.display_name, "shad")


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------

def _write_toml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "shad.toml"
    p.write_text(textwrap.dedent(content))
    return p


class LoadConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_missing_file_raises_shad_error(self) -> None:
        with self.assertRaises(ShadError) as ctx:
            load(self.tmp_path / "nonexistent.toml")
        self.assertIn("config file not found", str(ctx.exception))

    def test_no_defaults_section_falls_back_to_defaults(self) -> None:
        cfg_path = _write_toml(self.tmp_path, """
            [projects.myapp]
            path = "/tmp/myapp"
        """)
        cfg = load(cfg_path)
        self.assertEqual(cfg.defaults.oc_position, "top")
        self.assertEqual(cfg.defaults.panel_percent, 35)
        self.assertEqual(cfg.defaults.split_percent, 35)

    def test_defaults_section_fully_parsed(self) -> None:
        cfg_path = _write_toml(self.tmp_path, """
            [defaults]
            oc_position = "bottom"
            panel_percent = 40
            split_percent = 50
        """)
        cfg = load(cfg_path)
        self.assertEqual(cfg.defaults.oc_position, "bottom")
        self.assertEqual(cfg.defaults.panel_percent, 40)
        self.assertEqual(cfg.defaults.split_percent, 50)

    def test_invalid_oc_position_raises_shad_error(self) -> None:
        cfg_path = _write_toml(self.tmp_path, """
            [defaults]
            oc_position = "right"
        """)
        with self.assertRaises(ShadError) as ctx:
            load(cfg_path)
        self.assertIn("invalid oc_position", str(ctx.exception))
        self.assertIn("right", str(ctx.exception))

    def test_non_integer_panel_percent_raises_shad_error(self) -> None:
        cfg_path = _write_toml(self.tmp_path, """
            [defaults]
            panel_percent = "abc"
        """)
        with self.assertRaises(ShadError) as ctx:
            load(cfg_path)
        self.assertIn("panel_percent", str(ctx.exception))

    def test_non_integer_split_percent_raises_shad_error(self) -> None:
        cfg_path = _write_toml(self.tmp_path, """
            [defaults]
            split_percent = "abc"
        """)
        with self.assertRaises(ShadError) as ctx:
            load(cfg_path)
        self.assertIn("split_percent", str(ctx.exception))

    def test_top_level_project_parsed_correctly(self) -> None:
        cfg_path = _write_toml(self.tmp_path, """
            [projects.myapp]
            path = "/tmp/myapp"
            session = "my-session"
        """)
        cfg = load(cfg_path)
        self.assertIn("myapp", cfg.projects)
        p = cfg.projects["myapp"]
        self.assertEqual(p.key, "myapp")
        self.assertIsNone(p.group)
        self.assertEqual(p.path, Path("/tmp/myapp"))
        self.assertEqual(p.session, "my-session")

    def test_top_level_project_defaults_session_to_key(self) -> None:
        cfg_path = _write_toml(self.tmp_path, """
            [projects.myapp]
            path = "/tmp/myapp"
        """)
        cfg = load(cfg_path)
        self.assertEqual(cfg.projects["myapp"].session, "myapp")

    def test_grouped_project_parsed_correctly(self) -> None:
        cfg_path = _write_toml(self.tmp_path, """
            [projects.tin.shad]
            path = "/tmp/shad"
        """)
        cfg = load(cfg_path)
        self.assertIn("tin", cfg.groups)
        self.assertIn("shad", cfg.groups["tin"])
        p = cfg.groups["tin"]["shad"]
        self.assertEqual(p.key, "shad")
        self.assertEqual(p.group, "tin")
        self.assertEqual(p.session, "tin-shad")

    def test_grouped_project_defaults_session_to_group_dash_key(self) -> None:
        cfg_path = _write_toml(self.tmp_path, """
            [projects.mygroup.mykey]
            path = "/tmp/x"
        """)
        cfg = load(cfg_path)
        self.assertEqual(cfg.groups["mygroup"]["mykey"].session, "mygroup-mykey")

    def test_empty_projects_section_returns_empty_config(self) -> None:
        cfg_path = _write_toml(self.tmp_path, "")
        cfg = load(cfg_path)
        self.assertEqual(cfg.projects, {})
        self.assertEqual(cfg.groups, {})

    def test_scalar_project_value_raises_shad_error(self) -> None:
        cfg_path = self.tmp_path / "shad.toml"
        cfg_path.write_text('projects = {myapp = "string"}\n')
        with self.assertRaises(ShadError) as ctx:
            load(cfg_path)
        self.assertIn("must be a TOML table", str(ctx.exception))

    def test_project_missing_path_raises_value_error(self) -> None:
        cfg_path = _write_toml(self.tmp_path, """
            [projects.grp.nopathapp]
            session = "something"
        """)
        with self.assertRaises(ValueError) as ctx:
            load(cfg_path)
        self.assertIn("missing required field 'path'", str(ctx.exception))

    def test_multiple_projects_and_groups_parsed(self) -> None:
        cfg_path = _write_toml(self.tmp_path, """
            [projects.standalone]
            path = "/tmp/standalone"

            [projects.grp.alpha]
            path = "/tmp/alpha"

            [projects.grp.beta]
            path = "/tmp/beta"
        """)
        cfg = load(cfg_path)
        self.assertIn("standalone", cfg.projects)
        self.assertIn("grp", cfg.groups)
        self.assertIn("alpha", cfg.groups["grp"])
        self.assertIn("beta", cfg.groups["grp"])


if __name__ == "__main__":
    unittest.main()
