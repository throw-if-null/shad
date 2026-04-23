from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shad.cli import cmd_projects
from shad.config import Config, Defaults, Project


class ProjectsCommandTests(unittest.TestCase):
    def test_grouped_project_open_dispatches_to_open_project(self) -> None:
        project = Project(
            key="shad",
            group="tin",
            path=Path("/tmp/shad"),
            session="tin-shad",
        )
        cfg = Config(defaults=Defaults(), groups={"tin": {"shad": project}})
        args = type("Args", (), {"name": ["tin", "shad"]})()

        with patch("shad.cli.print_banner"), patch("shad.cli.open_project") as open_project:
            cmd_projects(cfg, args)

        open_project.assert_called_once_with(project, cfg.defaults)

    def test_top_level_project_open_dispatches_to_open_project(self) -> None:
        project = Project(
            key="shad",
            group=None,
            path=Path("/tmp/shad"),
            session="shad",
        )
        cfg = Config(defaults=Defaults(), projects={"shad": project})
        args = type("Args", (), {"name": ["shad"]})()

        with patch("shad.cli.print_banner"), patch("shad.cli.open_project") as open_project:
            cmd_projects(cfg, args)

        open_project.assert_called_once_with(project, cfg.defaults)


if __name__ == "__main__":
    unittest.main()
