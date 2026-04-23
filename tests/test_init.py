from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shad.cli import build_parser
from shad.init import Dependency, ensure_dependencies_installed


class InitCliTests(unittest.TestCase):
    def test_init_accepts_install_deps_flag(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["init", "--install-deps"])

        self.assertEqual(args.command, "init")
        self.assertTrue(args.install_deps)


class InstallDepsTests(unittest.TestCase):
    def test_install_deps_exits_when_not_fedora(self) -> None:
        with patch("shad.init._missing_dependencies", return_value=[Dependency(binary="tmux", package="tmux")]), patch(
            "shad.init._detect_fedora", return_value=False
        ), patch("shad.init.err_console.print"):
            with self.assertRaises(SystemExit) as ctx:
                ensure_dependencies_installed()

        self.assertEqual(ctx.exception.code, 1)

    def test_install_deps_exits_when_not_root(self) -> None:
        with patch("shad.init._missing_dependencies", return_value=[Dependency(binary="tmux", package="tmux")]), patch(
            "shad.init._detect_fedora", return_value=True
        ), patch("shad.init._is_root", return_value=False), patch("shad.init.err_console.print"):
            with self.assertRaises(SystemExit) as ctx:
                ensure_dependencies_installed()

        self.assertEqual(ctx.exception.code, 1)

    def test_install_deps_installs_missing_packages_and_opencode(self) -> None:
        missing = [
            Dependency(binary="tmux", package="tmux"),
            Dependency(binary="gitui", package="gitui"),
            Dependency(binary="opencode"),
        ]

        with patch("shad.init._missing_dependencies", return_value=missing), patch(
            "shad.init._detect_fedora", return_value=True
        ), patch("shad.init._is_root", return_value=True), patch(
            "shad.init._run_install_command"
        ) as run_install, patch("shad.init._install_opencode_systemwide") as install_opencode, patch(
            "shad.init.console.print"
        ):
            ensure_dependencies_installed()

        run_install.assert_called_once_with(
            ["dnf", "install", "-y", "tmux", "gitui"],
            "installing tmux, gitui with dnf",
        )
        install_opencode.assert_called_once_with()

    def test_install_deps_skips_work_when_everything_is_present(self) -> None:
        with patch("shad.init._missing_dependencies", return_value=[]), patch("shad.init.console.print") as print_mock:
            ensure_dependencies_installed()

        print_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
