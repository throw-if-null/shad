from __future__ import annotations

import re
import time

from shad.testing import TmuxCase


class CheatTests(TmuxCase):
    """
    Feature:    cheat
    Boundary:   command. `shad cheat` as a process with no terminal outside
                tmux, or typed into a shell that a tmux client sits on.
                Contract: exit code + stdout + stderr, or the popup.
    """

    def test_cheat_outside_tmux_prints_the_sheet(self) -> None:
        """
        Criterion:  cheat-outside-tmux-prints-the-sheet
          Given:    TMUX is not set.
          When:     `shad cheat`.
          Then:     exit 0, stderr empty, stdout holds the cheat sheet with
                    its sections.
        """
        result = self.run_detached("cheat")
        self.assertEqual((result.code, result.err), (0, ""), result.out)
        for text in ("tmux cheat sheet", "PANES", "WINDOWS", "SESSIONS", "COPY MODE"):
            self.assertIn(text, result.out)

    def test_cheat_inside_tmux_hands_over_to_a_popup(self) -> None:
        """
        Criterion:  cheat-inside-tmux-hands-over-to-a-popup
          Given:    a client of 50 rows sits on a shell session (the popup
                    is 40 rows tall).
          When:     `shad cheat` typed into the shell, then the popup is
                    closed.
          Then:     the sheet is not printed into the shell, the command
                    returns only once the popup closes, and the shell goes on.
        """
        returned = re.compile(r"^rc=\d+$", re.MULTILINE)
        self.shell_with_client(height=50)
        self.type_into_shell("shad cheat; echo rc=$?")
        time.sleep(1.0)
        screen = self.shell_screen()
        self.assertIsNone(returned.search(screen), screen)
        self.assertNotIn("PANES", screen)
        self.server.tmux("display-popup", "-C", "-c", self.clients()["shell"])
        deadline = time.monotonic() + 10
        while returned.search(self.shell_screen()) is None:
            self.assertLess(time.monotonic(), deadline, self.shell_screen())
            time.sleep(0.05)
        self.assertNotIn("PANES", self.shell_screen())
