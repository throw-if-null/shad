from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from shad.shared.config import (
    CONFIG_ENV,
    Config,
    Defaults,
    Project,
    all_projects,
    config_path,
    default_config_dir,
    load,
    resolve_prefix,
    resolve_target,
)
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

    def test_project_missing_path_raises_shad_error(self) -> None:
        cfg_path = _write_toml(self.tmp_path, """
            [projects.grp.nopathapp]
            session = "something"
        """)
        with self.assertRaises(ShadError) as ctx:
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


# ---------------------------------------------------------------------------
# all_projects / resolve_target
# ---------------------------------------------------------------------------


def _project(key: str, group: str | None = None) -> Project:
    return Project(
        key=key,
        group=group,
        path=Path("/tmp") / key,
        session=f"{group}-{key}" if group else key,
    )


def _config() -> Config:
    return Config(
        defaults=Defaults(),
        projects={"kb": _project("kb"), "orfe": _project("orfe")},
        groups={
            "tin": {"shad": _project("shad", "tin"), "coral": _project("coral", "tin")},
            "cv": {"sol": _project("sol", "cv")},
        },
    )


class AllProjectsTests(unittest.TestCase):
    def test_top_level_projects_come_first_then_groups(self) -> None:
        names = [p.display_name for p in all_projects(_config())]
        self.assertEqual(names, ["kb", "orfe", "cv sol", "tin coral", "tin shad"])

    def test_empty_config_returns_empty_list(self) -> None:
        self.assertEqual(all_projects(Config(defaults=Defaults())), [])


class ResolveTargetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = _config()

    def test_no_tokens_returns_every_project(self) -> None:
        target = resolve_target(self.cfg, [])
        self.assertEqual(len(target.projects), 5)

    def test_one_token_resolves_a_top_level_project(self) -> None:
        target = resolve_target(self.cfg, ["kb"])
        self.assertEqual([p.key for p in target.projects], ["kb"])

    def test_one_token_prefix_resolves_a_top_level_project(self) -> None:
        target = resolve_target(self.cfg, ["or"])
        self.assertEqual([p.key for p in target.projects], ["orfe"])

    def test_one_token_group_expands_to_every_member_sorted(self) -> None:
        target = resolve_target(self.cfg, ["tin"])
        self.assertEqual([p.key for p in target.projects], ["coral", "shad"])

    def test_two_tokens_resolve_one_grouped_project(self) -> None:
        target = resolve_target(self.cfg, ["tin", "shad"])
        self.assertEqual([p.display_name for p in target.projects], ["tin shad"])

    def test_two_tokens_use_prefix_matching_at_each_level(self) -> None:
        target = resolve_target(self.cfg, ["ti", "sh"])
        self.assertEqual([p.display_name for p in target.projects], ["tin shad"])

    def test_unknown_single_token_raises(self) -> None:
        with self.assertRaises(ShadError) as ctx:
            resolve_target(self.cfg, ["nope"])
        self.assertIn("no project or group matching 'nope'", str(ctx.exception))

    def test_ambiguous_single_token_raises(self) -> None:
        cfg = Config(
            defaults=Defaults(),
            projects={"shad": _project("shad"), "shell": _project("shell")},
        )
        with self.assertRaises(ShadError) as ctx:
            resolve_target(cfg, ["sh"])
        self.assertIn("ambiguous", str(ctx.exception))

    def test_unknown_group_raises(self) -> None:
        with self.assertRaises(ShadError) as ctx:
            resolve_target(self.cfg, ["zzz", "shad"])
        self.assertIn("no group matching 'zzz'", str(ctx.exception))

    def test_unknown_project_in_group_lists_available(self) -> None:
        with self.assertRaises(ShadError) as ctx:
            resolve_target(self.cfg, ["tin", "zzz"])
        message = str(ctx.exception)
        self.assertIn("no project matching 'zzz' in group 'tin'", message)
        self.assertIn("coral, shad", message)

    def test_top_level_project_used_as_a_group_hint_uses_the_usage_string(self) -> None:
        with self.assertRaises(ShadError) as ctx:
            resolve_target(self.cfg, ["kb", "shad"], usage="shad git sync")
        self.assertIn("did you mean: shad git sync kb?", str(ctx.exception))

    def test_too_many_tokens_uses_the_usage_string(self) -> None:
        with self.assertRaises(ShadError) as ctx:
            resolve_target(self.cfg, ["a", "b", "c"], usage="shad git sync")
        message = str(ctx.exception)
        self.assertIn("too many arguments (3)", message)
        self.assertIn("shad git sync [<group>] [<name>]", message)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# config path resolution
# ---------------------------------------------------------------------------


class DefaultConfigDirTests(unittest.TestCase):
    """The per-OS default. Each branch is asserted on, not just the host's."""

    def _dir(self, *, platform: str, env: dict[str, str]) -> Path:
        with (
            patch("shad.shared.config.sys.platform", platform),
            patch.dict("shad.shared.config.os.environ", env, clear=True),
            patch.object(Path, "home", return_value=Path("/home/u")),
        ):
            return default_config_dir()

    def test_linux_uses_xdg_config_home(self) -> None:
        found = self._dir(
            platform="linux", env={"XDG_CONFIG_HOME": "/xdg"}
        )
        self.assertEqual(found, Path("/xdg/shad"))

    def test_linux_falls_back_to_dot_config(self) -> None:
        found = self._dir(platform="linux", env={})
        self.assertEqual(found, Path("/home/u/.config/shad"))

    def test_a_relative_xdg_config_home_is_ignored(self) -> None:
        # The XDG spec says a relative value is invalid. Honouring it would
        # resolve against the working directory and give a different config
        # per invocation.
        found = self._dir(
            platform="linux", env={"XDG_CONFIG_HOME": "relative/path"}
        )
        self.assertEqual(found, Path("/home/u/.config/shad"))

    def test_macos_uses_application_support(self) -> None:
        found = self._dir(platform="darwin", env={"XDG_CONFIG_HOME": "/xdg"})
        self.assertEqual(found, Path("/home/u/Library/Application Support/shad"))

    def test_windows_uses_appdata(self) -> None:
        found = self._dir(
            platform="win32", env={"APPDATA": "/Users/u/AppData/Roaming"}
        )
        self.assertEqual(found, Path("/Users/u/AppData/Roaming/shad"))

    def test_windows_without_appdata_falls_back(self) -> None:
        found = self._dir(platform="win32", env={})
        self.assertEqual(found, Path("/home/u/AppData/Roaming/shad"))


class ConfigPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def _touch(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
        return path

    def test_the_env_var_wins_outright(self) -> None:
        explicit = self.root / "scratch" / "custom.toml"
        with patch.dict("shad.shared.config.os.environ", {CONFIG_ENV: str(explicit)}):
            self.assertEqual(config_path(), explicit)

    def test_the_env_var_expands_a_tilde(self) -> None:
        env = {CONFIG_ENV: "~/scratch.toml", "HOME": "/home/u"}
        with patch.dict("shad.shared.config.os.environ", env):
            self.assertEqual(config_path(), Path("/home/u/scratch.toml"))

    def test_the_env_var_need_not_exist(self) -> None:
        # `shad init` must be able to create it, and `load` reports a missing
        # file with a better message than this function could.
        missing = self.root / "nope.toml"
        with patch.dict("shad.shared.config.os.environ", {CONFIG_ENV: str(missing)}):
            self.assertEqual(config_path(), missing)

    def test_the_per_os_default_is_used_when_it_exists(self) -> None:
        preferred = self._touch(self.root / "os" / "shad.toml")
        with (
            patch.dict("shad.shared.config.os.environ", {}, clear=True),
            patch("shad.shared.config.default_config_dir", return_value=self.root / "os"),
            patch("shad.shared.config.legacy_config_dir", return_value=self.root / "legacy"),
        ):
            self.assertEqual(config_path(), preferred)

    def _resolve(self, platform: str = "darwin") -> Path:
        with (
            patch("shad.shared.config.sys.platform", platform),
            patch.dict("shad.shared.config.os.environ", {}, clear=True),
            patch("shad.shared.config.default_config_dir", return_value=self.root / "os"),
            patch("shad.shared.config.legacy_config_dir", return_value=self.root / "legacy"),
        ):
            return config_path()

    def test_an_existing_legacy_config_is_not_orphaned(self) -> None:
        # The case that matters on macOS and Windows: the per-OS default moved,
        # but the user's real config is still in ~/.config/shad.
        legacy = self._touch(self.root / "legacy" / "shad.toml")
        self.assertEqual(self._resolve("darwin"), legacy)
        self.assertEqual(self._resolve("win32"), legacy)

    def test_an_explicit_xdg_location_is_never_overridden_by_legacy(self) -> None:
        # On an XDG platform ~/.config *is* the default, so default_config_dir
        # returning something else means XDG_CONFIG_HOME was set deliberately.
        # Falling back would silently ignore the directory the user chose, for
        # readers and writers alike.
        self._touch(self.root / "legacy" / "shad.toml")
        self.assertEqual(self._resolve("linux"), self.root / "os" / "shad.toml")

    def test_the_per_os_default_wins_over_legacy_when_both_exist(self) -> None:
        preferred = self._touch(self.root / "os" / "shad.toml")
        self._touch(self.root / "legacy" / "shad.toml")
        self.assertEqual(self._resolve("darwin"), preferred)

    def test_with_nothing_on_disk_it_names_the_per_os_default(self) -> None:
        # Never returns the legacy path as a *destination* — `shad init` would
        # then write to the old location on a fresh install.
        self.assertEqual(self._resolve("darwin"), self.root / "os" / "shad.toml")


class LoadUsesTheResolverTests(unittest.TestCase):
    def test_load_with_no_argument_resolves_the_path(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            target = Path(name) / "shad.toml"
            target.write_text('[projects.kb]\npath = "/tmp/kb"\n')
            with patch("shad.shared.config.config_path", return_value=target):
                cfg = load()
        self.assertEqual(list(cfg.projects), ["kb"])


# ---------------------------------------------------------------------------
# duplicate project paths
# ---------------------------------------------------------------------------


class DuplicatePathTests(unittest.TestCase):
    """Two projects must not name the same directory."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def _load(self, body: str) -> Config:
        target = self.root / "shad.toml"
        target.write_text(textwrap.dedent(body))
        return load(target)

    def test_two_top_level_projects_on_one_directory_are_rejected(self) -> None:
        with self.assertRaises(ShadError) as ctx:
            self._load(f'''
                [projects.kb]
                path = "{self.root}/kb"

                [projects.notes]
                path = "{self.root}/kb"
            ''')
        message = str(ctx.exception)
        self.assertIn("both point at", message)
        self.assertIn("kb", message)
        self.assertIn("notes", message)

    def test_a_collision_across_a_group_boundary_is_rejected(self) -> None:
        with self.assertRaises(ShadError) as ctx:
            self._load(f'''
                [projects.kb]
                path = "{self.root}/kb"

                [projects.tin.kb]
                path = "{self.root}/kb"
            ''')
        self.assertIn("tin kb", str(ctx.exception))

    def test_a_trailing_slash_does_not_hide_a_collision(self) -> None:
        with self.assertRaises(ShadError):
            self._load(f'''
                [projects.kb]
                path = "{self.root}/kb"

                [projects.notes]
                path = "{self.root}/kb/"
            ''')

    def test_a_relative_segment_does_not_hide_a_collision(self) -> None:
        with self.assertRaises(ShadError):
            self._load(f'''
                [projects.kb]
                path = "{self.root}/kb"

                [projects.notes]
                path = "{self.root}/other/../kb"
            ''')

    def test_a_tilde_does_not_hide_a_collision(self) -> None:
        with (
            patch.dict("os.environ", {"HOME": str(self.root)}),
            self.assertRaises(ShadError),
        ):
            self._load(f'''
                [projects.kb]
                path = "{self.root}/kb"

                [projects.notes]
                path = "~/kb"
            ''')

    def test_distinct_directories_are_fine(self) -> None:
        # Two clones, or two worktrees, of one repository live in different
        # directories and stay legal. shad git sync deduplicates the
        # shared-ref-store case on --git-common-dir instead.
        cfg = self._load(f'''
            [projects.kb]
            path = "{self.root}/kb"

            [projects.notes]
            path = "{self.root}/notes"
        ''')
        self.assertEqual(sorted(cfg.projects), ["kb", "notes"])
