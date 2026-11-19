from __future__ import annotations

from shad.sessions.testing import UUID_A, UUID_B, SessionsCase, entry


class ShowTests(SessionsCase):
    """
    Feature:    sessions/show
    Boundary:   command. `shad sessions show`, through main(argv) with
                XDG_DATA_HOME under the test root. Contract: exit code +
                stdout + stderr.
    """

    def test_show_prints_the_saved_sessions(self) -> None:
        """
        Criterion:  show-prints-the-saved-sessions
          Given:    the snapshot holds kb (attached, named Netbird, first
                    prompt "Fix the panel") and tin shad.
          When:     `shad sessions show`.
          Then:     exit 0, stderr empty, stdout names both projects, the
                    start of each conversation id, the name, the prompt,
                    which one was attached, and a count of 2 sessions.
        """
        self.write_snapshot(
            entry("kb", UUID_A, attached=True, name="Netbird", title="Fix the panel"),
            entry("shad", UUID_B, group="tin"),
        )
        result = self.run_shad("sessions", "show")
        self.assertEqual((result.code, result.err), (0, ""), result.out)
        for text in ("kb", "tin shad", UUID_A[:8], UUID_B[:8], "attached", "Netbird",
                     "Fix the panel", "2 sessions"):
            self.assertIn(text, result.out)

    def test_show_with_an_empty_snapshot_says_so(self) -> None:
        """
        Criterion:  show-with-an-empty-snapshot-says-so
          Given:    the snapshot holds no entry.
          When:     `shad sessions show`.
          Then:     exit 0, stderr empty, stdout says no sessions, 0 sessions.
        """
        self.write_snapshot()
        result = self.run_shad("sessions", "show")
        self.assertEqual((result.code, result.err), (0, ""), result.out)
        self.assertIn("no sessions", result.out)
        self.assertIn("0 sessions", result.out)

    def test_show_without_a_snapshot_fails(self) -> None:
        """
        Criterion:  show-without-a-snapshot-fails
          Given:    no snapshot was saved.
          When:     `shad sessions show`.
          Then:     exit 1, stdout empty, stderr one line `no_snapshot:
                    <non-empty>` that says there are no saved sessions and
                    names `shad sessions save`.
        """
        result = self.run_shad("sessions", "show")
        self.assertEqual((result.code, result.out), (1, ""), result.err)
        self.assertRegex(result.err, r"^no_snapshot: .+\n$")
        self.assertIn("no saved sessions", result.err)
        self.assertIn("shad sessions save", result.err)
