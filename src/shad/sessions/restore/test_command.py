from __future__ import annotations

import argparse
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shad.output import Output
from shad.sessions import store
from shad.sessions.model import Entry, Snapshot
from shad.sessions.restore.command import run as restore
from shad.sessions.testing import (
    CFG,
    KB,
    SHAD,
    UUID_A,
    UUID_B,
    SessionsCase,
    entry,
    running,
)
from shad.shared.config import Config, Defaults, Project
from shad.testing import deps

DOC = Project(key="doc", group=None, path=Path("/p/doc"), session="doc", harness="claude")
UUID_C = "33333333-3333-4333-8333-333333333333"


class RestoreTests(SessionsCase):
    """
    Feature:    sessions/restore
    Boundary:   command. `shad sessions restore [--no-attach]` as a process
                with no terminal, or typed into a shell that a tmux client
                is attached to, against the test's server, home and data
                directory. Contract: exit code + stdout + stderr + the
                sessions on the server and the client's session.
    """

    def test_restore_no_attach_creates_the_saved_sessions(self) -> None:
        """
        Criterion:  restore-no-attach-creates-the-saved-sessions
          Given:    the snapshot holds kb on A, whose transcript exists, and
                    tin shad on B, whose transcript does not; nothing runs.
          When:     `shad sessions restore --no-attach`.
          Then:     exit 0, stderr empty, stdout reports kb resumed and tin
                    shad as a new conversation with no transcript, and both
                    sessions exist with the project layout, claude running
                    in a pane of each.
        """
        self.write_transcript("kb", UUID_A, "Fix the panel")
        self.write_snapshot(entry("kb", UUID_A), entry("shad", UUID_B, group="tin"))

        result = self.run_detached("sessions", "restore", "--no-attach")

        self.assertEqual((result.code, result.err), (0, ""), result.out)
        self.assertIn("resumed", result.out)
        self.assertIn("new conversation; no transcript", result.out)
        self.assertEqual(self.sessions_of("kb"), [f"kb--cc-{UUID_A}"])
        self.assertEqual(self.sessions_of("tin-shad"), [f"tin-shad--cc-{UUID_B}"])
        for session in (f"kb--cc-{UUID_A}", f"tin-shad--cc-{UUID_B}"):
            self.assertEqual(len(self.pane_commands(session)), 4, session)
            self.assertIn("claude", self.wait_for_harness(session))

    def test_restore_does_not_recreate_a_live_conversation(self) -> None:
        """
        Criterion:  restore-does-not-recreate-a-live-conversation
          Given:    the snapshot holds kb on A, and a kb session opened
                    under another name runs claude on A now.
          When:     `shad sessions restore --no-attach`.
          Then:     exit 0, stdout reports kb already running, and kb has
                    that one session only.
        """
        live = self.start_session("kb", "fresh-9", conversation=UUID_A)
        self.write_snapshot(entry("kb", UUID_A))
        result = self.run_detached("sessions", "restore", "--no-attach")
        self.assertEqual(result.code, 0, result.err)
        self.assertIn("already running", result.out)
        self.assertEqual(self.sessions_of("kb"), [live])

    def test_restore_skips_a_project_no_longer_configured(self) -> None:
        """
        Criterion:  restore-skips-a-project-no-longer-configured
          Given:    the snapshot holds the project gone, which the config
                    does not name.
          When:     `shad sessions restore --no-attach`.
          Then:     exit 0, stdout reports it skipped with the reason, and
                    no session is created.
        """
        self.write_snapshot(entry("gone", UUID_A, attached=True))
        result = self.run_detached("sessions", "restore", "--no-attach")
        self.assertEqual(result.code, 0, result.err)
        self.assertIn("skipped; project is no longer configured", result.out)
        self.assertEqual(self.server.sessions(), [])

    def test_restore_without_a_snapshot_fails(self) -> None:
        """
        Criterion:  restore-without-a-snapshot-fails
          Given:    no snapshot was saved.
          When:     `shad sessions restore --no-attach`.
          Then:     exit 1, stdout empty, stderr one line `no_snapshot:
                    <non-empty>` saying there are no saved sessions.
        """
        result = self.run_detached("sessions", "restore", "--no-attach")
        self.assertEqual((result.code, result.out), (1, ""), result.err)
        self.assertRegex(result.err, r"^no_snapshot: .+\n$")
        self.assertIn("no saved sessions", result.err)

    def test_restore_attaches_to_the_session_attached_at_save(self) -> None:
        """
        Criterion:  restore-attaches-to-the-session-attached-at-save
          Given:    the snapshot holds kb on A and tin shad on B, both
                    attached at save, and a tmux client sits on a shell
                    session that is not kitty.
          When:     `shad sessions restore` typed into that shell.
          Then:     the client moves to kb's session, and the shell shows
                    (on stderr) that tin shad got no tab because the
                    terminal is not kitty, with the attach command for it.
        """
        self.write_snapshot(
            entry("kb", UUID_A, attached=True), entry("shad", UUID_B, group="tin", attached=True)
        )
        self.server.new_session("shell", cwd=self.root, command="sh")
        self.attach_client("shell")

        self.server.tmux("send-keys", "-t", "shell", "shad sessions restore", "Enter")

        self.wait_for_client_on(lambda name: name == f"kb--cc-{UUID_A}")
        screen = self.server.tmux("capture-pane", "-p", "-S", "-", "-t", "shell").stdout
        self.assertIn("no tab for 1 session(s): the terminal is not kitty", screen)
        self.assertIn(f"tmux attach-session -t =tin-shad--cc-{UUID_B}", screen)

    def wait_for_harness(self, session: str) -> list[str]:
        """The pane commands of *session* once claude is among them."""
        import time

        deadline = time.monotonic() + 10
        while True:
            commands = self.pane_commands(session)
            if "claude" in commands or time.monotonic() > deadline:
                return commands
            time.sleep(0.05)


class KittyTabTests(unittest.TestCase):
    """
    The terminal tabs for the other sessions that were attached at save.

    A kitty with remote control is not available to the suite, so these
    tests patch the terminal crosscut and the tmux writes; they cover the
    tab logic alone (`[TEST-3]`).
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "sessions.json"
        # The tab report goes to stderr; stdout holds the restored table.
        self.output = io.StringIO()
        self.out = Output(stdout=io.StringIO(), stderr=self.output, width=120, color=False)
        for patcher in (
            patch("shad.sessions.store.snapshot_path", return_value=self.path),
            patch("shad.sessions.restore.command.attached_sessions", return_value=set()),
            patch("shad.shared.terminal.current", return_value="kitty"),
            patch("shad.sessions.live.collect", return_value=[]),
            patch("shad.sessions.restore.plan.session_exists", return_value=False),
            patch("shad.sessions.harness.Claude.can_resume", return_value=True),
            patch("shad.sessions.restore.command._create_session"),
            patch("shad.sessions.restore.command._attach", return_value=0),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _args(self, *, no_attach: bool = False) -> argparse.Namespace:
        return argparse.Namespace(sessions_action="restore", no_attach=no_attach)

    def _write_snapshot(self, *entries: Entry) -> None:
        store.write(self.path, Snapshot(saved_at=1, entries=entries))

    def test_opens_a_tab_for_each_other_session_attached_at_save(self) -> None:
        self._write_snapshot(
            _entry("kb", UUID_A, attached=True), _entry("shad", UUID_B, group="tin", attached=True)
        )
        with patch("shad.shared.terminal.open_tab", return_value=None) as open_tab:
            restore(self._args(), deps(CFG, out=self.out))

        open_tab.assert_called_once_with(
            "kitty",
            ["tmux", "attach-session", "-t", f"=tin-shad--cc-{UUID_B}"],
            Path("/p/shad"),
        )
        self.assertNotIn("no tab", self.output.getvalue())

    def test_no_tab_for_a_session_detached_at_save(self) -> None:
        self._write_snapshot(_entry("kb", UUID_A, attached=True), _entry("shad", UUID_B, group="tin"))
        with patch("shad.shared.terminal.open_tab") as open_tab:
            restore(self._args(), deps(CFG, out=self.out))

        open_tab.assert_not_called()

    def test_no_tab_for_a_session_that_has_a_client_now(self) -> None:
        self._write_snapshot(
            _entry("kb", UUID_A, attached=True), _entry("shad", UUID_B, group="tin", attached=True)
        )
        live = running("tin-shad--cc-fresh-1", SHAD, session_id=UUID_B, attached=True)
        with (
            patch("shad.sessions.live.collect", return_value=[live]),
            patch(
                "shad.sessions.restore.command.attached_sessions",
                return_value={"tin-shad--cc-fresh-1"},
            ),
            patch("shad.shared.terminal.open_tab") as open_tab,
        ):
            restore(self._args(), deps(CFG, out=self.out))

        open_tab.assert_not_called()

    def test_no_tabs_with_no_attach(self) -> None:
        self._write_snapshot(
            _entry("kb", UUID_A, attached=True), _entry("shad", UUID_B, group="tin", attached=True)
        )
        with patch("shad.shared.terminal.open_tab") as open_tab:
            restore(self._args(no_attach=True), deps(CFG, out=self.out))

        open_tab.assert_not_called()

    def test_stops_after_the_first_failure_and_prints_the_rest(self) -> None:
        cfg = Config(defaults=Defaults(), projects={"kb": KB, "doc": DOC}, groups=CFG.groups)
        self._write_snapshot(
            _entry("kb", UUID_A, attached=True),
            _entry("shad", UUID_B, group="tin", attached=True),
            _entry("doc", UUID_C, attached=True),
        )
        with patch("shad.shared.terminal.open_tab", return_value="kitty said no") as open_tab:
            restore(self._args(), deps(cfg, out=self.out))

        open_tab.assert_called_once()
        output = self.output.getvalue()
        self.assertIn("no tab for 2 session(s): kitty said no", output)
        self.assertIn(f"tmux attach-session -t =tin-shad--cc-{UUID_B}", output)
        self.assertIn(f"tmux attach-session -t =doc--cc-{UUID_C}", output)


def _entry(
    key: str, session_id: str | None, *, group: str | None = None, attached: bool = False
) -> Entry:
    return Entry(group=group, key=key, harness="claude", session_id=session_id, attached=attached)
