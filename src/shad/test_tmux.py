from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from shad.errors import ShadError
from shad.tmux import Tmux, project_session_name, split_session_name


def _completed(
    returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _tmux(**env: str) -> Tmux:
    return Tmux(env)


class SessionNameTests(unittest.TestCase):
    def test_scopes_a_session_key_under_the_prefix(self) -> None:
        self.assertEqual(project_session_name("tin-shad", "oc", "sess-123"), "tin-shad--oc-sess-123")

    def test_returns_the_base_when_there_is_no_key(self) -> None:
        self.assertEqual(project_session_name("tin-shad", "oc", None), "tin-shad")
        self.assertEqual(project_session_name("tin-shad", "oc", ""), "tin-shad")

    def test_sanitises_special_characters(self) -> None:
        self.assertEqual(project_session_name("proj", "oc", "abc/def:ghi"), "proj--oc-abc_def_ghi")

    def test_falls_back_when_the_key_is_all_special(self) -> None:
        self.assertEqual(project_session_name("proj", "oc", "!!!"), "proj--oc-session")

    def test_split_inverts_the_name(self) -> None:
        for prefix in ("oc", "cc"):
            with self.subTest(prefix=prefix):
                name = project_session_name("tin-shad", prefix, "abc-1")
                self.assertEqual(split_session_name("tin-shad", name), (prefix, "abc-1"))

    def test_split_returns_none_for_the_base_session(self) -> None:
        self.assertIsNone(split_session_name("tin-shad", "tin-shad"))

    def test_split_rejects_a_foreign_name(self) -> None:
        with self.assertRaises(ValueError):
            split_session_name("tin-shad", "tin-shad-extra--cc-abc")


class RunTests(unittest.TestCase):
    def test_prepends_tmux_and_the_socket_and_passes_the_env(self) -> None:
        tmux = Tmux({"HOME": "/h"}, socket="/tmp/s")
        with patch("shad.tmux.subprocess.run", return_value=_completed()) as run:
            tmux.run("list-sessions", check=False)
        self.assertEqual(run.call_args.args[0], ["tmux", "-S", "/tmp/s", "list-sessions"])
        self.assertEqual(run.call_args.kwargs["env"], {"HOME": "/h"})
        self.assertFalse(run.call_args.kwargs["check"])

    def test_a_missing_tmux_is_an_infrastructure_error(self) -> None:
        with (
            patch("shad.tmux.subprocess.run", side_effect=FileNotFoundError),
            self.assertRaises(ShadError) as ctx,
        ):
            _tmux().run("list-sessions")
        self.assertEqual(ctx.exception.code, "tmux_missing")

    def test_a_failed_command_carries_the_first_stderr_line(self) -> None:
        error = subprocess.CalledProcessError(1, ["tmux"], stderr="no such session\nmore\n")
        with patch("shad.tmux.subprocess.run", side_effect=error), self.assertRaises(ShadError) as ctx:
            _tmux().run("kill-session", "-t", "x")
        self.assertEqual(ctx.exception.code, "tmux_failed")
        self.assertIn("kill-session failed: no such session", str(ctx.exception))


class ListProjectSessionsTests(unittest.TestCase):
    def _sessions(self, result: subprocess.CompletedProcess) -> list[str]:
        with patch("shad.tmux.subprocess.run", return_value=result):
            return _tmux().list_project_sessions("tin-shad")

    def test_matches_the_base_and_the_scoped_sessions(self) -> None:
        result = _completed(stdout="tin-shad\ntin-shad--oc-sess-123\ntin-shad-extra\nother\n")
        self.assertEqual(self._sessions(result), ["tin-shad", "tin-shad--oc-sess-123"])

    def test_returns_nothing_on_a_nonzero_exit(self) -> None:
        self.assertEqual(self._sessions(_completed(returncode=1)), [])

    def test_strips_whitespace_from_lines(self) -> None:
        result = _completed(stdout="  tin-shad  \n  tin-shad--oc-abc  \n")
        self.assertEqual(self._sessions(result), ["tin-shad", "tin-shad--oc-abc"])

    def test_matches_claude_sessions_and_no_other_prefix(self) -> None:
        result = _completed(stdout="tin-shad--cc-uuid-a\ntin-shad--xx-uuid-b\n")
        self.assertEqual(self._sessions(result), ["tin-shad--cc-uuid-a"])


class QueryTests(unittest.TestCase):
    def test_attached_sessions_are_those_with_a_client(self) -> None:
        result = _completed(stdout="kb\t1\ntin-shad--cc-a\t0\nother\t2\n")
        with patch("shad.tmux.subprocess.run", return_value=result):
            self.assertEqual(_tmux().attached_sessions(), {"kb", "other"})

    def test_attached_sessions_is_empty_without_a_server(self) -> None:
        with patch("shad.tmux.subprocess.run", return_value=_completed(returncode=1)):
            self.assertEqual(_tmux().attached_sessions(), set())

    def test_pane_commands_group_by_session(self) -> None:
        result = _completed(stdout="kb\tclaude\nkb\tbash\nother\tsh\n")
        with patch("shad.tmux.subprocess.run", return_value=result):
            self.assertEqual(
                _tmux().pane_commands(), {"kb": {"claude", "bash"}, "other": {"sh"}}
            )

    def test_session_exists_follows_the_exit_status(self) -> None:
        with patch("shad.tmux.subprocess.run", return_value=_completed(returncode=0)):
            self.assertTrue(_tmux().session_exists("tin-shad"))
        with patch("shad.tmux.subprocess.run", return_value=_completed(returncode=1)):
            self.assertFalse(_tmux().session_exists("tin-shad"))

    def test_server_running_reads_the_no_server_message_only(self) -> None:
        with patch("shad.tmux.subprocess.run", return_value=_completed(returncode=0)):
            self.assertTrue(_tmux().server_running())
        no_server = _completed(returncode=1, stderr="error: no server running on /tmp/tmux-1000/default")
        with patch("shad.tmux.subprocess.run", return_value=no_server):
            self.assertFalse(_tmux().server_running())
        other = _completed(returncode=1, stderr="socket permission denied")
        with patch("shad.tmux.subprocess.run", return_value=other):
            self.assertTrue(_tmux().server_running())

    def test_current_session_is_none_outside_tmux(self) -> None:
        with patch("shad.tmux.subprocess.run") as run:
            self.assertIsNone(_tmux().current_session())
        run.assert_not_called()

    def test_current_session_asks_tmux_inside(self) -> None:
        with patch("shad.tmux.subprocess.run", return_value=_completed(stdout="kb\n")):
            self.assertEqual(_tmux(TMUX="/tmp/tmux-1/default,1,0").current_session(), "kb")

    def test_kill_session_names_the_session_exactly(self) -> None:
        with patch("shad.tmux.subprocess.run", return_value=_completed()) as run:
            _tmux().kill_session("tin-shad")
        self.assertEqual(run.call_args.args[0], ["tmux", "kill-session", "-t", "=tin-shad"])


class AttachTests(unittest.TestCase):
    def test_outside_tmux_attaches(self) -> None:
        with patch("shad.tmux.subprocess.run", return_value=_completed(returncode=0)) as run:
            code = _tmux().attach("tin-shad")
        self.assertEqual(run.call_args.args[0], ["tmux", "attach-session", "-t", "tin-shad"])
        self.assertEqual(code, 0)

    def test_inside_tmux_switches_the_client(self) -> None:
        with patch("shad.tmux.subprocess.run", return_value=_completed(returncode=0)) as run:
            _tmux(TMUX="/tmp/tmux-1234/default,12,0").attach("tin-shad")
        self.assertEqual(run.call_args.args[0], ["tmux", "switch-client", "-t", "tin-shad"])

    def test_returns_the_exit_status(self) -> None:
        with patch("shad.tmux.subprocess.run", return_value=_completed(returncode=42)):
            self.assertEqual(_tmux().attach("tin-shad"), 42)

    def test_popup_runs_the_command_over_the_client(self) -> None:
        with patch("shad.tmux.subprocess.run", return_value=_completed(returncode=3)) as run:
            code = _tmux(TMUX="x").popup("less", width=88, height=40)
        self.assertEqual(
            run.call_args.args[0], ["tmux", "display-popup", "-E", "-w", "88", "-h", "40", "less"]
        )
        self.assertEqual(code, 3)

    def test_attach_command_names_the_session_exactly(self) -> None:
        self.assertEqual(
            Tmux.attach_command("tin-shad"), ["tmux", "attach-session", "-t", "=tin-shad"]
        )


if __name__ == "__main__":
    unittest.main()
