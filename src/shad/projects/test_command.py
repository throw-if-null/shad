"""
What `shad projects` makes of its names: list, open, or status. The
boundary tests of the three slices cover the outcomes; these cover the
resolution on the function, with the slices patched out. `[TEST-3]`.
"""

from __future__ import annotations

import argparse
import unittest
from pathlib import Path
from unittest.mock import ANY, patch

from shad.config import Config, Defaults, Project
from shad.errors import ShadError
from shad.projects.command import run
from shad.projects.list.command import ProjectList
from shad.testing import deps


def _make_project(key: str, group: str | None = None, session: str | None = None) -> Project:
    return Project(
        key=key,
        group=group,
        path=Path("/tmp") / key,
        session=session or (f"{group}-{key}" if group else key),
    )


def _args(name: list[str], harness: str | None = None, json: bool = False) -> argparse.Namespace:
    args = argparse.Namespace(name=name, harness=harness)
    if json:
        args.json = True
    return args


class ResolutionTests(unittest.TestCase):
    def test_a_grouped_name_opens_the_project(self) -> None:
        project = _make_project("shad", group="tin")
        cfg = Config(defaults=Defaults(), groups={"tin": {"shad": project}})
        with (
            patch("shad.projects.command.print_banner"),
            patch("shad.projects.command.open_project", return_value=0) as open_project,
        ):
            code = run(_args(["tin", "shad"]), deps(cfg))
        self.assertEqual(code, 0)
        open_project.assert_called_once_with(project, cfg.defaults, ANY, ANY, harness=None, resume=None, pick=False)

    def test_a_top_level_name_opens_the_project(self) -> None:
        project = _make_project("shad")
        cfg = Config(defaults=Defaults(), projects={"shad": project})
        with (
            patch("shad.projects.command.print_banner"),
            patch("shad.projects.command.open_project", return_value=0) as open_project,
        ):
            code = run(_args(["shad"]), deps(cfg))
        self.assertEqual(code, 0)
        open_project.assert_called_once_with(project, cfg.defaults, ANY, ANY, harness=None, resume=None, pick=False)

    def test_no_name_lists_everything(self) -> None:
        cfg = Config(
            defaults=Defaults(),
            projects={"myapp": _make_project("myapp")},
            groups={"tin": {"shad": _make_project("shad", group="tin")}},
        )
        result = run(_args([]), deps(cfg))
        self.assertIsInstance(result, ProjectList)
        assert isinstance(result, ProjectList)
        self.assertIsNone(result.group)
        self.assertEqual([p.key for p in result.projects], ["myapp", "shad"])

    def test_a_group_name_lists_the_group(self) -> None:
        cfg = Config(
            defaults=Defaults(),
            groups={"tin": {"shad": _make_project("shad", group="tin")}},
        )
        result = run(_args(["tin"]), deps(cfg))
        assert isinstance(result, ProjectList)
        self.assertEqual(result.group, "tin")
        self.assertEqual([p.key for p in result.projects], ["shad"])

    def test_an_unknown_name_is_not_found(self) -> None:
        with self.assertRaises(ShadError) as ctx:
            run(_args(["xyz"]), deps(Config(defaults=Defaults())))
        self.assertEqual(ctx.exception.code, "no_such_project")
        self.assertIn("xyz", str(ctx.exception))

    def test_an_ambiguous_prefix_is_a_usage_error(self) -> None:
        cfg = Config(
            defaults=Defaults(),
            projects={"shad": _make_project("shad"), "shell": _make_project("shell")},
        )
        with self.assertRaises(ShadError) as ctx:
            run(_args(["sh"]), deps(cfg))
        self.assertIn("ambiguous", str(ctx.exception))

    def test_an_action_on_a_group_is_a_usage_error(self) -> None:
        cfg = Config(
            defaults=Defaults(),
            groups={"tin": {"shad": _make_project("shad", group="tin")}},
        )
        with self.assertRaises(ShadError) as ctx:
            run(_args(["tin", "status"]), deps(cfg))
        self.assertEqual(ctx.exception.code, "group_needs_project")

    def test_an_action_without_a_project_is_a_usage_error(self) -> None:
        with self.assertRaises(ShadError) as ctx:
            run(_args(["status"]), deps(Config(defaults=Defaults())))
        self.assertEqual(ctx.exception.code, "no_project")

    def test_status_reads_the_project(self) -> None:
        project = _make_project("shad", group="tin")
        cfg = Config(defaults=Defaults(), groups={"tin": {"shad": project}})
        with patch("shad.projects.command.status") as status:
            run(_args(["tin", "shad", "status"]), deps(cfg))
        status.assert_called_once()
        self.assertIs(status.call_args.args[0], project)

    def test_a_project_name_in_the_group_position_points_at_the_project(self) -> None:
        cfg = Config(defaults=Defaults(), projects={"shad": _make_project("shad")})
        with self.assertRaises(ShadError) as ctx:
            run(_args(["shad", "something"]), deps(cfg))
        self.assertEqual(ctx.exception.code, "no_such_group")
        self.assertIn("did you mean", str(ctx.exception))

    def test_an_unknown_group_is_not_found(self) -> None:
        with self.assertRaises(ShadError) as ctx:
            run(_args(["xyz", "proj"]), deps(Config(defaults=Defaults())))
        self.assertIn("no group matching", str(ctx.exception))

    def test_an_unknown_project_within_a_group_is_not_found(self) -> None:
        cfg = Config(
            defaults=Defaults(),
            groups={"tin": {"shad": _make_project("shad", group="tin")}},
        )
        with self.assertRaises(ShadError) as ctx:
            run(_args(["tin", "zzz"]), deps(cfg))
        self.assertIn("no project matching", str(ctx.exception))
        self.assertIn("tin", str(ctx.exception))

    def test_too_many_names_is_a_usage_error(self) -> None:
        with self.assertRaises(ShadError) as ctx:
            run(_args(["a", "b", "c"]), deps(Config(defaults=Defaults())))
        self.assertEqual(ctx.exception.code, "too_many_arguments")

    def test_a_cancelled_open_returns_none(self) -> None:
        project = _make_project("shad")
        cfg = Config(defaults=Defaults(), projects={"shad": project})
        with (
            patch("shad.projects.command.print_banner"),
            patch("shad.projects.command.open_project", return_value=None),
        ):
            self.assertIsNone(run(_args(["shad"]), deps(cfg)))

    def test_the_attach_exit_code_is_returned(self) -> None:
        project = _make_project("shad")
        cfg = Config(defaults=Defaults(), projects={"shad": project})
        with (
            patch("shad.projects.command.print_banner"),
            patch("shad.projects.command.open_project", return_value=3),
        ):
            self.assertEqual(run(_args(["shad"]), deps(cfg)), 3)

    def test_json_on_an_open_is_refused_before_the_banner(self) -> None:
        project = _make_project("shad")
        cfg = Config(defaults=Defaults(), projects={"shad": project})
        with (
            patch("shad.projects.command.print_banner") as banner,
            patch("shad.projects.command.open_project") as open_project,
            self.assertRaises(ShadError) as ctx,
        ):
            run(_args(["shad"], json=True), deps(cfg))
        self.assertEqual(ctx.exception.code, "no_json")
        banner.assert_not_called()
        open_project.assert_not_called()


class HarnessOverrideTests(unittest.TestCase):
    def test_the_override_reaches_a_top_level_open(self) -> None:
        project = _make_project("shad")
        cfg = Config(defaults=Defaults(), projects={"shad": project})
        with (
            patch("shad.projects.command.print_banner"),
            patch("shad.projects.command.open_project", return_value=0) as open_project,
        ):
            run(_args(["shad"], harness="claude"), deps(cfg))
        open_project.assert_called_once_with(project, cfg.defaults, ANY, ANY, harness="claude", resume=None, pick=False)

    def test_the_override_reaches_a_grouped_open(self) -> None:
        project = _make_project("shad", group="tin")
        cfg = Config(defaults=Defaults(), groups={"tin": {"shad": project}})
        with (
            patch("shad.projects.command.print_banner"),
            patch("shad.projects.command.open_project", return_value=0) as open_project,
        ):
            run(_args(["tin", "shad"], harness="opencode"), deps(cfg))
        open_project.assert_called_once_with(project, cfg.defaults, ANY, ANY, harness="opencode", resume=None, pick=False)

    def test_status_ignores_the_override(self) -> None:
        project = _make_project("shad")
        cfg = Config(defaults=Defaults(), projects={"shad": project})
        with (
            patch("shad.projects.command.status") as status,
            patch("shad.projects.command.open_project") as open_project,
        ):
            run(_args(["shad", "status"], harness="claude"), deps(cfg))
        status.assert_called_once()
        self.assertIs(status.call_args.args[0], project)
        open_project.assert_not_called()


if __name__ == "__main__":
    unittest.main()
