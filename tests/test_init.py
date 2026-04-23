from __future__ import annotations

import argparse
import sys
import unittest
import unittest.mock
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shad.cli import build_parser
from shad.errors import ShadError
from shad.init import Dependency, ensure_dependencies_installed


class InitCliTests(unittest.TestCase):
    def test_init_accepts_install_deps_flag(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["init", "--install-deps"])

        self.assertEqual(args.command, "init")
        self.assertTrue(args.install_deps)


class InstallDepsTests(unittest.TestCase):
    def test_install_deps_raises_when_not_fedora(self) -> None:
        with patch("shad.init._missing_dependencies", return_value=[Dependency(binary="tmux", package="tmux")]), patch(
            "shad.init._detect_fedora", return_value=False
        ):
            with self.assertRaises(ShadError) as ctx:
                ensure_dependencies_installed()

        self.assertIn("Fedora", str(ctx.exception))

    def test_install_deps_raises_when_not_root(self) -> None:
        with patch("shad.init._missing_dependencies", return_value=[Dependency(binary="tmux", package="tmux")]), patch(
            "shad.init._detect_fedora", return_value=True
        ), patch("shad.init._is_root", return_value=False):
            with self.assertRaises(ShadError) as ctx:
                ensure_dependencies_installed()

        self.assertIn("sudo", str(ctx.exception))

    def test_install_deps_installs_missing_packages_and_opencode(self) -> None:
        tmux_installer = unittest.mock.MagicMock()
        gitui_installer = unittest.mock.MagicMock()
        opencode_installer = unittest.mock.MagicMock()

        missing = [
            Dependency(binary="tmux", package="tmux", installer=tmux_installer),
            Dependency(binary="gitui", package="gitui", installer=gitui_installer),
            Dependency(binary="opencode", installer=opencode_installer),
        ]

        with patch("shad.init._missing_dependencies", return_value=missing), patch(
            "shad.init._detect_fedora", return_value=True
        ), patch("shad.init._is_root", return_value=True), patch(
            "shad.init.console.print"
        ):
            ensure_dependencies_installed()

        tmux_installer.assert_called_once_with()
        gitui_installer.assert_called_once_with()
        opencode_installer.assert_called_once_with()

    def test_install_deps_skips_work_when_everything_is_present(self) -> None:
        with patch("shad.init._missing_dependencies", return_value=[]), patch("shad.init.console.print") as print_mock:
            ensure_dependencies_installed()

        print_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
