from __future__ import annotations

from shad.sessions.testing import UUID_A, UUID_B, SessionsCase, entry


class SaveAllTests(SessionsCase):
    """
    Feature:    sessions/save --all
    Boundary:   command. `shad sessions save --all` as a process with no
                terminal, against the test's tmux server, home and data
                directory. Contract: exit code + stdout + stderr + the
                snapshot, read back through `shad sessions show`.
    """

    def test_save_all_records_every_savable_session(self) -> None:
        """
        Criterion:  save-all-records-every-savable-session
          Given:    kb runs claude on conversation A (named Netbird, first
                    prompt "Fix the panel"), tin shad runs claude on B (first
                    prompt "first prompt"), and kb also runs an opencode
                    session.
          When:     `shad sessions save --all`.
          Then:     exit 0, stdout reports 2 sessions saved, stderr lists
                    the opencode session as not supported, and the snapshot
                    holds kb with A, Netbird and its prompt, and tin shad
                    with B and its prompt, neither attached.
        """
        self.start_session("kb", UUID_A, name="Netbird", title="Fix the panel", status="idle")
        self.start_session("tin-shad", UUID_B)
        opencode = self.start_session("kb", "fresh-1", harness="opencode")

        result = self.run_detached("sessions", "save", "--all")

        self.assertEqual(result.code, 0, result.err)
        self.assertIn("2 sessions saved", result.out)
        self.assertNotIn(opencode, result.out)
        self.assertIn(opencode, result.err)
        self.assertIn("not supported", result.err)
        self.assertEqual(
            self.read_snapshot(),
            [
                entry("kb", UUID_A, name="Netbird", title="Fix the panel"),
                entry("shad", UUID_B, group="tin", title="first prompt"),
            ],
        )
        self.assertIn("2 sessions", self.run_shad("sessions", "show").out)

    def test_save_all_records_a_bare_session_through_the_harness_record(self) -> None:
        """
        Criterion:  save-all-records-a-bare-session-through-the-harness-record
          Given:    the bare session kb runs claude, whose process record
                    names conversation A.
          When:     `shad sessions save --all`.
          Then:     exit 0, and the snapshot holds kb with A.
        """
        self.start_session("kb", None, conversation=UUID_A, title=None)
        result = self.run_detached("sessions", "save", "--all")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(self.read_snapshot(), [entry("kb", UUID_A)])

    def test_save_all_with_nothing_running_fails(self) -> None:
        """
        Criterion:  save-all-with-nothing-running-fails
          Given:    no shad session runs.
          When:     `shad sessions save --all`.
          Then:     exit 1, stdout empty, stderr one line
                    `no_running_sessions: <non-empty>`, and no snapshot is
                    written.
        """
        result = self.run_detached("sessions", "save", "--all")
        self.assertEqual((result.code, result.out), (1, ""), result.err)
        self.assertRegex(result.err, r"^no_running_sessions: .+\n$")
        self.assertIn("no shad sessions are running", result.err)
        self.assertFalse(self.snapshot.exists())

    def test_save_all_with_only_unsupported_sessions_fails(self) -> None:
        """
        Criterion:  save-all-with-only-unsupported-sessions-fails
          Given:    the only shad session runs opencode.
          When:     `shad sessions save --all`.
          Then:     exit 1, stdout empty, stderr one line
                    `no_saveable_session: <non-empty>` that names the
                    session and why, and no snapshot is written.
        """
        session = self.start_session("kb", "fresh-1", harness="opencode")
        result = self.run_detached("sessions", "save", "--all")
        self.assertEqual((result.code, result.out), (1, ""), result.err)
        self.assertRegex(result.err, r"^no_saveable_session: .+\n$")
        self.assertIn("no session could be saved", result.err)
        self.assertIn(session, result.err)
        self.assertIn("not supported", result.err)
        self.assertFalse(self.snapshot.exists())


class SavePickerTests(SessionsCase):
    """
    Feature:    sessions/save (the picker)
    Boundary:   command. `shad sessions save` in a terminal pane of the
                test's tmux server. Contract: exit code + screen + the
                snapshot.
    """

    def test_save_picker_starts_with_every_row_checked_without_a_snapshot(self) -> None:
        """
        Criterion:  save-picker-starts-with-every-row-checked-without-a-snapshot
          Given:    kb runs claude on A and tin shad on B, and no snapshot
                    exists.
          When:     `shad sessions save` in a terminal, then Enter.
          Then:     the picker shows both rows checked, exit 0, and the
                    snapshot holds A and B.
        """
        self.start_session("kb", UUID_A)
        self.start_session("tin-shad", UUID_B)
        pane = self.pane("sessions", "save")
        screen = pane.wait_for("save sessions")
        self.assertEqual(screen.count("[x]"), 2)
        pane.send("Enter")
        self.assertEqual(pane.wait_exit(), 0)
        self.assertEqual([e["session_id"] for e in self.read_snapshot()], [UUID_A, UUID_B])

    def test_save_picker_prechecks_the_rows_the_snapshot_holds(self) -> None:
        """
        Criterion:  save-picker-prechecks-the-rows-the-snapshot-holds
          Given:    the snapshot holds B, and kb runs A while tin shad runs B.
          When:     `shad sessions save` in a terminal, then Enter.
          Then:     the picker shows one row unchecked and one checked, exit
                    0, and the snapshot still holds B only.
        """
        self.write_snapshot(entry("shad", UUID_B, group="tin"))
        self.start_session("kb", UUID_A)
        self.start_session("tin-shad", UUID_B)
        pane = self.pane("sessions", "save")
        screen = pane.wait_for("save sessions")
        self.assertEqual((screen.count("[ ]"), screen.count("[x]")), (1, 1))
        pane.send("Enter")
        self.assertEqual(pane.wait_exit(), 0)
        self.assertEqual([e["session_id"] for e in self.read_snapshot()], [UUID_B])

    def test_save_picker_writes_the_toggled_rows(self) -> None:
        """
        Criterion:  save-picker-writes-the-toggled-rows
          Given:    kb runs A and tin shad runs B, and no snapshot exists.
          When:     `shad sessions save` in a terminal, Space on the first
                    row, then Enter.
          Then:     exit 0, and the snapshot holds B only.
        """
        self.start_session("kb", UUID_A)
        self.start_session("tin-shad", UUID_B)
        pane = self.pane("sessions", "save")
        pane.wait_for("save sessions")
        pane.send("Space", "Enter")
        self.assertEqual(pane.wait_exit(), 0)
        self.assertEqual([e["session_id"] for e in self.read_snapshot()], [UUID_B])

    def test_save_picker_accepts_an_empty_selection(self) -> None:
        """
        Criterion:  save-picker-accepts-an-empty-selection
          Given:    the snapshot holds A, and kb runs A.
          When:     `shad sessions save` in a terminal, `a` to clear every
                    row, then Enter.
          Then:     exit 0, and the snapshot holds no entry.
        """
        self.write_snapshot(entry("kb", UUID_A))
        self.start_session("kb", UUID_A)
        pane = self.pane("sessions", "save")
        pane.wait_for("save sessions")
        pane.send("a", "Enter")
        self.assertEqual(pane.wait_exit(), 0)
        self.assertEqual(self.read_snapshot(), [])

    def test_save_picker_cancel_leaves_the_snapshot_alone(self) -> None:
        """
        Criterion:  save-picker-cancel-leaves-the-snapshot-alone
          Given:    the snapshot holds A, and kb runs B.
          When:     `shad sessions save` in a terminal, then `q`.
          Then:     exit 0, the screen says cancelled, and the snapshot is
                    byte-identical.
        """
        self.write_snapshot(entry("kb", UUID_A))
        before = self.snapshot.read_text()
        self.start_session("kb", UUID_B)
        pane = self.pane("sessions", "save")
        pane.wait_for("save sessions")
        pane.send("q")
        self.assertEqual(pane.wait_exit(), 0)
        self.assertIn("cancelled", pane.screen())
        self.assertEqual(self.snapshot.read_text(), before)

    def test_save_without_a_terminal_points_at_all(self) -> None:
        """
        Criterion:  save-without-a-terminal-points-at-all
          Given:    kb runs A.
          When:     `shad sessions save` as a process with no terminal.
          Then:     exit 1, stdout empty, stderr one line `no_terminal:
                    <non-empty>` that names `--all`, and no snapshot is
                    written.
        """
        self.start_session("kb", UUID_A)
        result = self.run_detached("sessions", "save")
        self.assertEqual((result.code, result.out), (1, ""), result.err)
        self.assertRegex(result.err, r"^no_terminal: .+\n$")
        self.assertIn("--all", result.err)
        self.assertFalse(self.snapshot.exists())
