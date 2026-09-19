from __future__ import annotations

import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from unittest.mock import patch

from shad.cli import build_parser
from shad.init.command import (
    Dependency,
    _append_toml,
    _detect_fedora,
    _expand,
    _is_root,
    _key_exists,
    _toml_key,
    ensure_dependencies_installed,
)
from shad.shared.errors import ShadError

# ---------------------------------------------------------------------------
# CLI parser
# ---------------------------------------------------------------------------

class InitCliTests(unittest.TestCase):
    def test_init_accepts_install_deps_flag(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["init", "--install-deps"])
        self.assertEqual(args.command, "init")
        self.assertTrue(args.install_deps)


# ---------------------------------------------------------------------------
# ensure_dependencies_installed
# ---------------------------------------------------------------------------

class InstallDepsTests(unittest.TestCase):
    def test_install_deps_raises_when_not_fedora(self) -> None:
        with (
            patch(
                "shad.init.command._missing_dependencies",
                return_value=[Dependency(binary="tmux", package="tmux")],
            ),
            patch("shad.init.command._detect_fedora", return_value=False),
            self.assertRaises(ShadError) as ctx,
        ):
            ensure_dependencies_installed()
        self.assertIn("Fedora", str(ctx.exception))

    def test_install_deps_raises_when_not_root(self) -> None:
        with (
            patch(
                "shad.init.command._missing_dependencies",
                return_value=[Dependency(binary="tmux", package="tmux")],
            ),
            patch("shad.init.command._detect_fedora", return_value=True),
            patch("shad.init.command._is_root", return_value=False),
            self.assertRaises(ShadError) as ctx,
        ):
            ensure_dependencies_installed()
        self.assertIn("sudo", str(ctx.exception))

    def test_install_deps_installs_missing_packages_and_opencode(self) -> None:
        tmux_installer = unittest.mock.MagicMock()
        opencode_installer = unittest.mock.MagicMock()

        missing = [
            Dependency(binary="tmux", package="tmux", installer=tmux_installer),
            Dependency(binary="opencode", installer=opencode_installer),
        ]

        with patch("shad.init.command._missing_dependencies", return_value=missing), \
             patch("shad.init.command._detect_fedora", return_value=True), \
             patch("shad.init.command._is_root", return_value=True), \
             patch("shad.init.command.console.print"):
            ensure_dependencies_installed()

        tmux_installer.assert_called_once_with()
        opencode_installer.assert_called_once_with()

    def test_install_deps_skips_work_when_everything_is_present(self) -> None:
        with patch("shad.init.command._missing_dependencies", return_value=[]), \
             patch("shad.init.command.console.print") as print_mock:
            ensure_dependencies_installed()
        print_mock.assert_called_once()


# ---------------------------------------------------------------------------
# _detect_fedora
# ---------------------------------------------------------------------------

class DetectFedoraTests(unittest.TestCase):
    def test_returns_true_for_id_equals_fedora(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("ID=fedora\n")
            tmp = Path(f.name)
        try:
            with patch("shad.init.command.Path") as mock_cls:
                real = Path
                mock_cls.side_effect = lambda x: tmp if str(x) == "/etc/os-release" else real(x)
                result = _detect_fedora()
            self.assertTrue(result)
        finally:
            tmp.unlink(missing_ok=True)

    def test_returns_true_for_id_like_fedora_quoted(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write('ID=rhel\nID_LIKE="fedora"\n')
            tmp = Path(f.name)
        try:
            with patch("shad.init.command.Path") as mock_cls:
                real = Path
                mock_cls.side_effect = lambda x: tmp if str(x) == "/etc/os-release" else real(x)
                result = _detect_fedora()
            self.assertTrue(result)
        finally:
            tmp.unlink(missing_ok=True)

    def test_returns_false_for_ubuntu(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("ID=ubuntu\nID_LIKE=debian\n")
            tmp = Path(f.name)
        try:
            with patch("shad.init.command.Path") as mock_cls:
                real = Path
                mock_cls.side_effect = lambda x: tmp if str(x) == "/etc/os-release" else real(x)
                result = _detect_fedora()
            self.assertFalse(result)
        finally:
            tmp.unlink(missing_ok=True)

    def test_returns_false_when_file_does_not_exist(self) -> None:
        with patch("shad.init.command.Path") as mock_cls:
            fake = unittest.mock.MagicMock()
            fake.exists.return_value = False
            real = Path
            mock_cls.side_effect = lambda x: fake if str(x) == "/etc/os-release" else real(x)
            result = _detect_fedora()
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# _is_root
# ---------------------------------------------------------------------------

class IsRootTests(unittest.TestCase):
    def test_returns_true_when_euid_is_0(self) -> None:
        with patch("os.geteuid", return_value=0):
            self.assertTrue(_is_root())

    def test_returns_false_when_euid_is_nonzero(self) -> None:
        with patch("os.geteuid", return_value=1000):
            self.assertFalse(_is_root())

    def test_returns_false_when_geteuid_absent(self) -> None:
        original = getattr(os, "geteuid", None)
        try:
            if hasattr(os, "geteuid"):
                delattr(os, "geteuid")
            result = _is_root()
            self.assertFalse(result)
        finally:
            if original is not None:
                os.geteuid = original  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# _toml_key
# ---------------------------------------------------------------------------

class TomlKeyTests(unittest.TestCase):
    def test_grouped_key(self) -> None:
        self.assertEqual(_toml_key("tin", "shad"), "projects.tin.shad")

    def test_top_level_key(self) -> None:
        self.assertEqual(_toml_key(None, "myapp"), "projects.myapp")


# ---------------------------------------------------------------------------
# _expand
# ---------------------------------------------------------------------------

class ExpandTests(unittest.TestCase):
    def test_tilde_expanded(self) -> None:
        result = _expand("~/gh/myproject")
        self.assertFalse(str(result).startswith("~"))
        self.assertTrue(result.is_absolute())

    def test_relative_path_made_absolute(self) -> None:
        result = _expand("myproject")
        self.assertTrue(result.is_absolute())


# ---------------------------------------------------------------------------
# _key_exists
# ---------------------------------------------------------------------------

class KeyExistsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_returns_false_when_file_does_not_exist(self) -> None:
        self.assertFalse(_key_exists(self.tmp_path / "missing.toml", None, "myapp"))

    def test_top_level_key_that_exists_returns_true(self) -> None:
        cfg = self.tmp_path / "shad.toml"
        cfg.write_text('[projects.myapp]\npath = "/tmp/x"\n')
        self.assertTrue(_key_exists(cfg, None, "myapp"))

    def test_top_level_key_that_does_not_exist_returns_false(self) -> None:
        cfg = self.tmp_path / "shad.toml"
        cfg.write_text('[projects.myapp]\npath = "/tmp/x"\n')
        self.assertFalse(_key_exists(cfg, None, "other"))

    def test_grouped_key_that_exists_returns_true(self) -> None:
        cfg = self.tmp_path / "shad.toml"
        cfg.write_text('[projects.tin.shad]\npath = "/tmp/x"\n')
        self.assertTrue(_key_exists(cfg, "tin", "shad"))

    def test_grouped_key_with_wrong_group_returns_false(self) -> None:
        cfg = self.tmp_path / "shad.toml"
        cfg.write_text('[projects.tin.shad]\npath = "/tmp/x"\n')
        self.assertFalse(_key_exists(cfg, "other", "shad"))


# ---------------------------------------------------------------------------
# _append_toml
# ---------------------------------------------------------------------------

class AppendTomlTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_top_level_project_appended_correctly(self) -> None:
        cfg = self.tmp_path / "shad.toml"
        cfg.write_text("")
        _append_toml(cfg, None, "myapp", Path("/home/user/myapp"), "myapp")
        content = cfg.read_text()
        self.assertIn("[projects.myapp]", content)
        self.assertIn('path    = "/home/user/myapp"', content)
        self.assertIn('session = "myapp"', content)

    def test_grouped_project_uses_two_level_header(self) -> None:
        cfg = self.tmp_path / "shad.toml"
        cfg.write_text("")
        _append_toml(cfg, "tin", "shad", Path("/tmp/shad"), "tin-shad")
        content = cfg.read_text()
        self.assertIn("[projects.tin.shad]", content)

    def test_appends_to_existing_content(self) -> None:
        cfg = self.tmp_path / "shad.toml"
        cfg.write_text("[projects.existing]\npath = \"/tmp/x\"\n")
        _append_toml(cfg, None, "newapp", Path("/tmp/newapp"), "newapp")
        content = cfg.read_text()
        self.assertIn("[projects.existing]", content)
        self.assertIn("[projects.newapp]", content)


if __name__ == "__main__":
    unittest.main()
