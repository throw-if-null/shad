from __future__ import annotations

import os
import sys
import unittest

from shad import __version__
from shad.testing import PACKAGE_PARENT, Pane, TmuxCase, TmuxServer, run


class RunTests(unittest.TestCase):
    def test_returns_the_exit_code_and_the_streams(self) -> None:
        result = run(["--version"])
        self.assertEqual(result.code, 0)
        self.assertEqual(result.out.strip(), f"shad {__version__}")
        self.assertEqual(result.err, "")

    def test_a_bad_command_line_exits_2_with_the_message_on_stderr(self) -> None:
        result = run(["--nope"])
        self.assertEqual(result.code, 2)
        self.assertEqual(result.out, "")
        self.assertIn("--nope", result.err)

    def test_env_applies_to_the_call_only(self) -> None:
        before = os.environ.get("SHAD_CONFIG")
        result = run(["config", "path"], env={"SHAD_CONFIG": "/x/shad.toml"})
        self.assertEqual(result.out.strip(), "/x/shad.toml")
        self.assertEqual(os.environ.get("SHAD_CONFIG"), before)

    def test_a_none_value_removes_the_variable(self) -> None:
        with_var = run(["config", "path"], env={"SHAD_CONFIG": "/x/shad.toml"})
        without = run(["config", "path"], env={"SHAD_CONFIG": None})
        self.assertNotEqual(with_var.out, without.out)
        self.assertNotIn("/x/shad.toml", without.out)


class TmuxServerTests(unittest.TestCase):
    def test_the_socket_is_private_and_tmux_is_not_inherited(self) -> None:
        server = TmuxServer()
        self.addCleanup(server.kill)
        self.assertEqual(server.socket_path, str(server.socket))
        self.assertTrue(server.socket.is_relative_to(server.directory))
        self.assertNotIn("TMUX", server.env)
        self.assertEqual(server.sessions(), [])

        server.new_session("kb", command="sleep 100000")
        self.assertEqual(server.sessions(), ["kb"])

    def test_kill_removes_the_server_and_its_directory(self) -> None:
        server = TmuxServer()
        server.new_session("kb", command="sleep 100000")
        server.kill()
        self.assertFalse(server.directory.exists())
        # A call after kill must fail, not reach the user's server.
        self.assertEqual(server.sessions(), [])
        self.assertNotEqual(server.tmux("list-sessions", check=False).returncode, 0)


class PaneTests(TmuxCase):
    def test_runs_under_a_terminal_and_reports_the_exit_status(self) -> None:
        pane = Pane(self.server, ["sh", "-c", "tty; exit 3"], env=self.env, cwd=self.root)
        self.assertEqual(pane.wait_exit(), 3)
        self.assertIn("/dev/pts/", pane.screen())

    def test_keys_reach_the_command(self) -> None:
        pane = Pane(
            self.server, ["sh", "-c", 'read line; echo "got:$line"'], env=self.env, cwd=self.root
        )
        pane.type("hello")
        pane.send("Enter")
        self.assertEqual(pane.wait_exit(), 0)
        self.assertIn("got:hello", pane.screen())

    def test_a_shad_pane_runs_the_code_under_test(self) -> None:
        pane = Pane(
            self.server,
            [sys.executable, "-c", "import shad; print(shad.__file__)"],
            env=self.env,
            cwd=self.root,
        )
        self.assertEqual(pane.wait_exit(), 0)
        self.assertIn(str(PACKAGE_PARENT / "shad" / "__init__.py"), pane.screen())

        version = self.pane("--version")
        self.assertEqual(version.wait_exit(), 0)
        self.assertIn(f"shad {__version__}", version.screen())

    def test_the_pane_sees_this_server_and_the_test_environment(self) -> None:
        pane = Pane(
            self.server,
            ["sh", "-c", 'echo "home=$HOME kitty=${KITTY_WINDOW_ID-unset}"; tmux display-message -p "#{socket_path}"'],
            env=self.env, cwd=self.root,
        )
        self.assertEqual(pane.wait_exit(), 0)
        screen = pane.screen()
        self.assertIn(f"home={self.home} kitty=unset", screen)
        self.assertIn(self.server.socket_path, screen)

    def test_a_session_the_server_opens_runs_in_the_test_environment(self) -> None:
        # What a shad layout's panes see: the server's environment, with the
        # `shad` shim first on PATH.
        self.server.new_session("probe", command='echo "home=$HOME"; command -v shad; sleep 100')
        pane = Pane(self.server, ["sleep", "0"], env={}, cwd=self.root)
        pane.wait_exit()
        screen = self.server.tmux("capture-pane", "-p", "-t", "probe").stdout
        self.assertIn(f"home={self.home}", screen)
        self.assertIn(str(self.bin / "shad"), screen)

    def test_run_detached_has_no_terminal_and_reaches_this_server(self) -> None:
        result = self.run_detached("--version")
        self.assertEqual((result.code, result.err), (0, ""))
        self.assertIn(f"shad {__version__}", result.out)

    def test_the_fake_harness_is_the_foreground_command(self) -> None:
        self.fake_harness("claude")
        pane = Pane(self.server, ["claude"], env=self.env, cwd=self.root)
        self.assertEqual(pane.wait_for_command("claude"), "claude")
