from __future__ import annotations

from shad.sessions.testing import UUID_A, UUID_B, SessionsCase


class StopTests(SessionsCase):
    """
    Feature:    sessions/stop
    Boundary:   command. `shad sessions stop --pick` in a terminal pane of the
                test's tmux server, or as a process with no terminal.
                Contract: exit code + screen or streams + the sessions on
                the server.
    """

    def test_stop_cancel_leaves_every_session_running(self) -> None:
        """
        Criterion:  stop-cancel-leaves-every-session-running
          Given:    kb runs claude on A, and no other session.
          When:     `shad sessions stop --pick` in a terminal, then `q`.
          Then:     exit 0, the screen says nothing stopped, and the session
                    still runs.
        """
        session = self.start_session("kb", UUID_A)
        pane = self.pane("sessions", "stop", "--pick")
        pane.wait_for("stop sessions")
        pane.send("q")
        self.assertEqual(pane.wait_exit(), 0)
        self.assertIn("nothing stopped", pane.screen())
        self.assertIn(session, self.server.sessions())

    def test_stop_kills_the_picked_sessions_and_reports_them(self) -> None:
        """
        Criterion:  stop-kills-the-picked-sessions-and-reports-them
          Given:    kb runs claude on A and tin shad on B.
          When:     `shad sessions stop --pick` in a terminal, Down, Space, Enter.
          Then:     exit 0, the screen reports tin shad stopped, kb's
                    session still runs, and tin shad's is gone.
        """
        kb = self.start_session("kb", UUID_A)
        shad = self.start_session("tin-shad", UUID_B)
        pane = self.pane("sessions", "stop", "--pick")
        pane.wait_for("stop sessions")
        pane.send("Down", "Space", "Enter")
        self.assertEqual(pane.wait_exit(), 0)
        screen = pane.screen()
        self.assertIn("stopped", screen)
        self.assertIn("tin shad", screen)
        self.assertIn(kb, self.server.sessions())
        self.assertNotIn(shad, self.server.sessions())

    def test_stop_lists_an_unsupported_session_too(self) -> None:
        """
        Criterion:  stop-lists-an-unsupported-session-too
          Given:    kb runs opencode.
          When:     `shad sessions stop --pick` in a terminal, Space, Enter.
          Then:     the picker shows the session as not supported, exit 0,
                    and the session is gone.
        """
        session = self.start_session("kb", "fresh-1", harness="opencode")
        pane = self.pane("sessions", "stop", "--pick")
        screen = pane.wait_for("stop sessions")
        self.assertIn("not supported", screen)
        pane.send("Space", "Enter")
        self.assertEqual(pane.wait_exit(), 0)
        self.assertNotIn(session, self.server.sessions())

    def test_stop_leaves_out_the_session_it_runs_in(self) -> None:
        """
        Criterion:  stop-leaves-out-the-session-it-runs-in
          Given:    the only shad session is kb, and the command runs in it.
          When:     `shad sessions stop --pick` in a terminal of session kb.
          Then:     exit 0, and the screen says no shad session runs besides
                    this one.
        """
        pane = self.pane("sessions", "stop", session="kb")
        self.assertEqual(pane.wait_exit(), 0)
        self.assertIn("no shad sessions are running besides this one", pane.screen())

    def test_stop_pick_without_a_terminal_fails(self) -> None:
        """
        Criterion:  stop-pick-without-a-terminal-fails
          Given:    kb runs claude on A.
          When:     `shad sessions stop --pick` as a process with no terminal.
          Then:     exit 1, stdout empty, stderr one line `no_terminal:
                    <non-empty>`, and the session still runs.
        """
        session = self.start_session("kb", UUID_A)
        result = self.run_detached("sessions", "stop", "--pick")
        self.assertEqual((result.code, result.out), (1, ""), result.err)
        self.assertRegex(result.err, r"^no_terminal: .+\n$")
        self.assertIn("terminal", result.err)
        self.assertIn(session, self.server.sessions())

    def test_stop_with_nothing_running_says_so(self) -> None:
        """
        Criterion:  stop-with-nothing-running-says-so
          Given:    no shad session runs.
          When:     `shad sessions stop` as a process with no terminal.
          Then:     exit 0, stderr empty, stdout says no shad session runs.
        """
        result = self.run_detached("sessions", "stop", "--all")
        self.assertEqual((result.code, result.err), (0, ""), result.out)
        self.assertIn("no shad sessions are running", result.out)

    def test_stop_reports_each_session_and_continues(self) -> None:
        """
        Criterion:  stop-reports-each-session-and-continues
          Given:    kb runs claude on A, and no session named nope exists.
          When:     `shad sessions stop kb nope`.
          Then:     exit 1, stdout reports kb stopped, stderr reports nope
                    not found and one line `no_such_session: <non-empty>`,
                    and kb no longer exists.
        """
        kb = self.start_session("kb", UUID_A)
        result = self.run_detached("sessions", "stop", "kb", "nope")
        self.assertEqual(result.code, 1, result.err)
        self.assertIn("stopped", result.out)
        self.assertIn("nope", result.err)
        self.assertRegex(result.err, r"no_such_session: .+\n$")
        self.assertNotIn(kb, self.server.sessions())

    def test_stop_all_kills_every_session(self) -> None:
        """
        Criterion:  stop-all-kills-every-session
          Given:    kb runs A and tin shad runs B.
          When:     `shad sessions stop --all`.
          Then:     exit 0, and neither session exists.
        """
        kb = self.start_session("kb", UUID_A)
        shad = self.start_session("tin-shad", UUID_B)
        result = self.run_detached("sessions", "stop", "--all")
        self.assertEqual(result.code, 0, result.err)
        self.assertNotIn(kb, self.server.sessions())
        self.assertNotIn(shad, self.server.sessions())
