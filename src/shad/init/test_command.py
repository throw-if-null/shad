from __future__ import annotations

import hashlib
import io
import os
import stat
import tarfile
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from unittest.mock import patch

from shad.cli import build_parser
from shad.errors import ShadError
from shad.init import command as init_command
from shad.init.command import (
    Dependency,
    _append_toml,
    _detect_fedora,
    _expand,
    _install_opencode_systemwide,
    _is_root,
    _key_exists,
    _toml_key,
    ensure_dependencies_installed,
)
from shad.testing import Pane, TmuxCase

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
# _install_opencode_systemwide
# ---------------------------------------------------------------------------

def _release_archive(binary: bytes) -> bytes:
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:gz") as tar:
        info = tarfile.TarInfo("opencode")
        info.size = len(binary)
        tar.addfile(info, io.BytesIO(binary))
    return archive.getvalue()


class InstallOpencodeTests(unittest.TestCase):
    def test_download_directory_is_private_and_removed(self) -> None:
        release = _release_archive(b"binary")
        captured: list[tuple[Path, int, bytes]] = []
        run_install_command = init_command._run_install_command

        def run(command: list[str], description: str) -> None:
            if command[0] != "install":
                run_install_command(command, description)
                return
            binary = Path(command[-2])
            mode = stat.S_IMODE(binary.parent.stat().st_mode)
            captured.append((binary.parent, mode, binary.read_bytes()))

        with patch("shad.init.command.urllib.request.urlopen", return_value=io.BytesIO(release)), \
             patch("shad.init.command.OPENCODE_LINUX_X64_SHA256", hashlib.sha256(release).hexdigest()), \
             patch("shad.init.command.platform.machine", return_value="x86_64"), \
             patch("shad.init.command._run_install_command", side_effect=run), \
             patch("shad.init.command.console.print"):
            _install_opencode_systemwide()

        self.assertEqual(len(captured), 1)
        directory, mode, content = captured[0]
        self.assertEqual(content, b"binary")
        self.assertEqual(mode, 0o700)
        self.assertNotEqual(directory, Path("/tmp") / f"shad-opencode-{os.getpid()}")
        self.assertFalse(directory.exists())

    def test_checksum_mismatch_installs_nothing(self) -> None:
        release = _release_archive(b"tampered")

        with patch("shad.init.command.urllib.request.urlopen", return_value=io.BytesIO(release)), \
             patch("shad.init.command.platform.machine", return_value="x86_64"), \
             patch("shad.init.command._run_install_command") as run, \
             patch("shad.init.command.console.print"), \
             self.assertRaises(ShadError) as ctx:
            _install_opencode_systemwide()

        self.assertIn("checksum mismatch", str(ctx.exception))
        run.assert_not_called()

    def test_other_architectures_are_refused_before_download(self) -> None:
        with patch("shad.init.command.urllib.request.urlopen") as urlopen, \
             patch("shad.init.command.platform.machine", return_value="aarch64"), \
             self.assertRaises(ShadError) as ctx:
            _install_opencode_systemwide()

        self.assertIn("aarch64", str(ctx.exception))
        urlopen.assert_not_called()


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


# ---------------------------------------------------------------------------
# the wizard, as a user runs it
# ---------------------------------------------------------------------------


class InitWizardTests(TmuxCase):
    """
    Feature:    init
    Boundary:   command. `shad init` in a terminal pane of the test's tmux
                server, with SHAD_CONFIG under the test root, answering
                the prompts by typing. Contract: exit code + screen + the
                config file, read back through `shad projects`.
    """

    def _answer(self, pane: Pane, prompt: str, text: str = "") -> None:
        pane.wait_for(prompt)
        if text:
            pane.type(text)
        pane.send("Enter")

    def test_init_adds_a_project_through_the_wizard(self) -> None:
        """
        Criterion:  init-adds-a-project-through-the-wizard
          Given:    no config file exists, and <root>/kb is a directory.
          When:     `shad init`, answering path <root>/kb, no group, the
                    default key, the default session, and yes.
          Then:     exit 0, the screen says the project was added and how to
                    open it, the file starts with the commented defaults and
                    holds [projects.kb] with that path and session kb, and
                    `shad projects` lists kb.
        """
        (self.root / "kb").mkdir()
        pane = self.pane("init")
        self._answer(pane, "e.g. ~/gh/myproject", str(self.root / "kb"))
        self._answer(pane, "leave blank for top-level")
        self._answer(pane, "key")
        self._answer(pane, "session name")
        self._answer(pane, "Add to config?", "y")
        self.assertEqual(pane.wait_exit(), 0)
        screen = pane.screen()
        self.assertIn(f"Added to {self.config}", screen)
        self.assertIn("shad projects kb", screen)
        text = self.config.read_text()
        self.assertTrue(text.startswith("# ~/.config/shad/shad.toml\n\n[defaults]\n"), text[:60])
        self.assertIn("[projects.kb]\n", text)
        self.assertIn(f'path    = "{self.root / "kb"}"\n', text)
        self.assertIn('session = "kb"\n', text)
        self.assertIn("kb", self.run_shad("projects").out)

    def test_init_adds_a_grouped_project_with_derived_defaults(self) -> None:
        """
        Criterion:  init-adds-a-grouped-project-with-derived-defaults
          When:     `shad init`, answering path <root>/tin/shad, group tin,
                    the default key, the default session, and yes.
          Then:     exit 0, and the file holds [projects.tin.shad] with
                    session tin-shad.
        """
        (self.root / "tin" / "shad").mkdir(parents=True)
        pane = self.pane("init")
        self._answer(pane, "e.g. ~/gh/myproject", str(self.root / "tin" / "shad"))
        self._answer(pane, "leave blank for top-level", "tin")
        self._answer(pane, "key")
        self._answer(pane, "session name")
        self._answer(pane, "Add to config?", "y")
        self.assertEqual(pane.wait_exit(), 0)
        text = self.config.read_text()
        self.assertIn("[projects.tin.shad]\n", text)
        self.assertIn('session = "tin-shad"\n', text)

    def test_init_asks_again_for_a_path_that_does_not_exist(self) -> None:
        """
        Criterion:  init-asks-again-for-a-path-that-does-not-exist
          When:     `shad init`, answering a path that does not exist, then
                    one that does, and the defaults.
          Then:     the screen says the first path does not exist, the
                    wizard goes on, and the file holds the second path.
        """
        (self.root / "kb").mkdir()
        pane = self.pane("init")
        self._answer(pane, "e.g. ~/gh/myproject", str(self.root / "nope"))
        pane.wait_for("path does not exist")
        pane.type(str(self.root / "kb"))
        pane.send("Enter")
        self._answer(pane, "leave blank for top-level")
        self._answer(pane, "key")
        self._answer(pane, "session name")
        self._answer(pane, "Add to config?", "y")
        self.assertEqual(pane.wait_exit(), 0)
        self.assertIn(f'path    = "{self.root / "kb"}"\n', self.config.read_text())

    def test_init_refuses_a_key_that_exists_and_asks_again(self) -> None:
        """
        Criterion:  init-refuses-a-key-that-exists-and-asks-again
          Given:    the config holds [projects.kb].
          When:     `shad init` for <root>/other, answering key kb, then
                    key other, and the defaults.
          Then:     the screen says kb exists, exit 0, and the file holds
                    both projects.
        """
        (self.root / "kb").mkdir()
        (self.root / "other").mkdir()
        self.write_config(f'[projects.kb]\npath = "{self.root / "kb"}"\n')
        pane = self.pane("init")
        self._answer(pane, "e.g. ~/gh/myproject", str(self.root / "other"))
        self._answer(pane, "leave blank for top-level")
        self._answer(pane, "key", "kb")
        pane.wait_for("already exists")
        pane.type("other")
        pane.send("Enter")
        self._answer(pane, "session name")
        self._answer(pane, "Add to config?", "y")
        self.assertEqual(pane.wait_exit(), 0)
        text = self.config.read_text()
        self.assertIn("[projects.kb]\n", text)
        self.assertIn("[projects.other]\n", text)
        self.assertNotIn("[defaults]", text)

    def test_init_declined_at_the_confirmation_writes_nothing(self) -> None:
        """
        Criterion:  init-declined-at-the-confirmation-writes-nothing
          Given:    no config file exists.
          When:     `shad init`, answering the prompts and then no.
          Then:     exit 0, the screen says aborted, and no file exists.
        """
        (self.root / "kb").mkdir()
        pane = self.pane("init")
        self._answer(pane, "e.g. ~/gh/myproject", str(self.root / "kb"))
        self._answer(pane, "leave blank for top-level")
        self._answer(pane, "key")
        self._answer(pane, "session name")
        self._answer(pane, "Add to config?", "n")
        self.assertEqual(pane.wait_exit(), 0)
        self.assertIn("Aborted", pane.screen())
        self.assertFalse(self.config.exists())


if __name__ == "__main__":
    unittest.main()
