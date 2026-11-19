from __future__ import annotations

import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

from shad.config import Defaults, Project
from shad.errors import ShadError
from shad.harness import Harnesses
from shad.projects.open.command import open_project
from shad.projects.testing import UUID_A, ProjectsCase
from shad.tmux import Tmux


class OpenTests(ProjectsCase):
    """
    Feature:    projects/open
    Boundary:   command. `shad projects [<group>] <name> [--harness H]`,
                typed into a shell that a tmux client sits on, or run in a
                terminal pane, against the test's server with Claude Code's
                transcripts under the test home. Contract: exit code +
                screen + the sessions on the server + the client's session.
    """

    def _wait_for_session(self, ready, *, timeout: float = 10.0) -> list[str]:
        """The kb sessions once *ready* holds for them, polling the server."""
        import time

        deadline = time.monotonic() + timeout
        while True:
            names = self.sessions_of("kb")
            if ready(names):
                return names
            if time.monotonic() > deadline:
                raise AssertionError(f"kb sessions never satisfied the wait: {names}")
            time.sleep(0.05)

    def test_open_creates_the_layout_and_attaches(self) -> None:
        """
        Criterion:  open-creates-the-layout-and-attaches
          Given:    a client sits on a shell session.
          When:     `shad projects kb` typed into that shell (a new
                    conversation, the default).
          Then:     the client moves to a session named kb--cc-<uuid>, which
                    has four panes with claude running in one.
        """
        self.shell_with_client()
        self.type_into_shell("shad projects kb")
        session = self.wait_for_client_on(lambda name: name.startswith("kb--cc-"))
        uuid.UUID(session.removeprefix("kb--cc-"))
        self.assertEqual(len(self.pane_commands(session)), 4)
        self.wait_for_harness(session)

    def test_open_pick_shows_the_picker_when_conversations_exist(self) -> None:
        """
        Criterion:  open-pick-shows-the-picker-when-conversations-exist
          Given:    kb has a conversation named Netbird whose first prompt
                    is "Fix the panel".
          When:     `shad projects kb --pick` in a terminal, then `q`.
          Then:     the picker offers a new session, Netbird and the prompt;
                    exit 0, and no kb session exists.
        """
        self.write_transcript("kb", UUID_A, "Fix the panel", name="Netbird")
        pane = self.pane("projects", "kb", "--pick")
        screen = pane.wait_for("New session")
        for text in ("claude session", "Netbird", "Fix the panel"):
            self.assertIn(text, screen)
        pane.send("q")
        self.assertEqual(pane.wait_exit(), 0)
        self.assertEqual(self.sessions_of("kb"), [])

    def test_open_pick_resumes_the_picked_conversation(self) -> None:
        """
        Criterion:  open-pick-resumes-the-picked-conversation
          Given:    kb has conversation A, and a client sits on a shell.
          When:     `shad projects kb --pick` typed into the shell, Down, Enter.
          Then:     the client moves to kb--cc-A, with claude running in it.
        """
        self.write_transcript("kb", UUID_A, "Fix the panel")
        self.shell_with_client()
        self.type_into_shell("shad projects kb --pick")
        self.wait_for_shell("New session")
        self.server.tmux("send-keys", "-t", "shell", "Down", "Enter")
        session = self.wait_for_client_on(lambda name: name == f"kb--cc-{UUID_A}")
        self.wait_for_harness(session)

    def test_open_resume_attaches_to_the_existing_session(self) -> None:
        """
        Criterion:  open-resume-attaches-to-the-existing-session
          Given:    kb has conversation A, a session kb--cc-A with one pane
                    runs it, and a client sits on a shell.
          When:     `shad projects kb --resume <A>` typed into the shell.
          Then:     the client moves to that session, which still has one
                    pane, and kb has no other session.
        """
        self.write_transcript("kb", UUID_A, "Fix the panel")
        existing = f"kb--cc-{UUID_A}"
        self.server.new_session(existing, cwd=self.root / "kb", command="claude")
        self.shell_with_client()
        self.type_into_shell(f"shad projects kb --resume {UUID_A}")
        self.wait_for_client_on(lambda name: name == existing)
        self.assertEqual(self.sessions_of("kb"), [existing])
        self.assertEqual(len(self.pane_commands(existing)), 1)

    def test_open_twice_creates_two_sessions(self) -> None:
        """
        Criterion:  open-twice-creates-two-sessions
          Given:    kb has no session.
          When:     `shad projects kb` in a pane, detached, then again.
          Then:     two kb--cc-<uuid> sessions exist, each with four panes.
        """
        self.pane("projects", "kb")
        one = self._wait_for_session(lambda names: len(names) == 1)[0]
        self.wait_for_harness(one)
        self.pane("projects", "kb")
        two = self._wait_for_session(lambda names: len(names) == 2)
        self.assertEqual(len(two), 2)
        self.assertIn(one, two)

    def test_open_resume_uses_the_saved_id(self) -> None:
        """
        Criterion:  open-resume-uses-the-saved-id
          Given:    a transcript <A>.jsonl with one prompt in kb's Claude dir.
          When:     `shad projects kb --resume <A>` in a pane.
          Then:     a session kb--cc-<A> exists whose harness pane runs
                    `claude --resume <A>`.
        """
        self.write_transcript("kb", UUID_A, "Fix the panel")
        self.pane("projects", "kb", "--resume", UUID_A)
        self._wait_for_session(lambda names: f"kb--cc-{UUID_A}" in names)
        self.wait_for_harness(f"kb--cc-{UUID_A}")

    def test_open_pick_without_a_terminal_is_an_error(self) -> None:
        """
        Criterion:  open-pick-without-terminal-is-an-error
          When:     `shad projects kb --pick` as a process with no terminal.
          Then:     exit 1, stderr one line `no_terminal: <non-empty>`, and
                    no kb session is created.
        """
        self.write_transcript("kb", UUID_A, "Fix the panel")
        result = self.run_detached("projects", "kb", "--pick")
        self.assertEqual(result.code, 1, result.err)
        self.assertRegex(result.err, r"^no_terminal: .+\n$")
        self.assertEqual(self.sessions_of("kb"), [])

    def test_open_with_a_harness_override_uses_that_harness(self) -> None:
        """
        Criterion:  open-with-a-harness-override-uses-that-harness
          Given:    kb is configured for claude, opencode has no sessions,
                    and a client sits on a shell.
          When:     `shad projects kb --harness opencode` typed into it.
          Then:     the client moves to a session named kb--oc-fresh-<hex>.
        """
        self.fake_harness("opencode")
        self.shell_with_client()
        self.type_into_shell("shad projects kb --harness opencode")
        self.wait_for_client_on(lambda name: name.startswith("kb--oc-fresh-"))

    def test_open_of_an_unknown_project_fails(self) -> None:
        """
        Criterion:  open-of-an-unknown-project-fails
          When:     `shad projects nope`.
          Then:     exit 1, stdout empty, stderr one line `no_such_project:
                    <non-empty>` naming nope.
        """
        result = self.run_shad("projects", "nope")
        self.assertEqual((result.code, result.out), (1, ""), result.err)
        self.assertRegex(result.err, r"^no_such_project: .+\n$")
        self.assertIn("nope", result.err)

    def test_open_of_an_ambiguous_prefix_fails(self) -> None:
        """
        Criterion:  open-of-an-ambiguous-prefix-fails
          Given:    the projects kb and kc exist.
          When:     `shad projects k`.
          Then:     exit 2, stdout empty, stderr one line
                    `ambiguous_name: <non-empty>` that lists both.
        """
        result = self.run_shad("projects", "k")
        self.assertEqual((result.code, result.out), (2, ""), result.err)
        self.assertRegex(result.err, r"^ambiguous_name: .+\n$")
        self.assertIn("ambiguous", result.err)
        self.assertIn("kb, kc", result.err)

    def test_open_rejects_an_action_on_a_group(self) -> None:
        """
        Criterion:  open-rejects-an-action-on-a-group
          When:     `shad projects tin status`.
          Then:     exit 2, stdout empty, stderr one line
                    `group_needs_project: <non-empty>` that says tin is a group.
        """
        result = self.run_shad("projects", "tin", "status")
        self.assertEqual((result.code, result.out), (2, ""), result.err)
        self.assertRegex(result.err, r"^group_needs_project: .+\n$")
        self.assertIn("group", result.err)

    def test_open_rejects_too_many_tokens(self) -> None:
        """
        Criterion:  open-rejects-too-many-tokens
          When:     `shad projects a b c d`.
          Then:     exit 2, stdout empty, stderr one line
                    `too_many_arguments: <non-empty>`.
        """
        result = self.run_shad("projects", "a", "b", "c", "d")
        self.assertEqual((result.code, result.out), (2, ""), result.err)
        self.assertRegex(result.err, r"^too_many_arguments: .+\n$")
        self.assertIn("too many arguments", result.err)

    def test_open_rejects_an_unknown_harness(self) -> None:
        """
        Criterion:  open-rejects-an-unknown-harness
          When:     `shad projects kb --harness nope`.
          Then:     exit 2, stdout empty, stderr lists the harnesses.
        """
        result = self.run_shad("projects", "kb", "--harness", "nope")
        self.assertEqual((result.code, result.out), (2, ""), result.err)
        self.assertIn("claude", result.err)


class OpenFunctionTests(unittest.TestCase):
    """Paths easier to force on the function than through a terminal. [TEST-3]."""

    def test_a_fresh_open_creates_without_checking_or_killing(self) -> None:
        # A fresh target's key is unique, so open never probes for or kills an
        # existing session of that name.
        project = Project(key="shad", group="tin", path=Path("/tmp/shad"), session="tin-shad")
        tmux = Mock(spec=Tmux)
        tmux.attach.return_value = 0
        harnesses = Harnesses(Path("/home"))
        with patch("shad.projects.open.command.create_session") as create_session:
            open_project(project, Defaults(), tmux, harnesses, harness="opencode")
        tmux.session_exists.assert_not_called()
        tmux.run.assert_not_called()
        create_session.assert_called_once()
        self.assertTrue(create_session.call_args.args[4].startswith("tin-shad--oc-fresh-"))

    def test_resume_most_recent_with_no_conversation_is_not_found(self) -> None:
        project = Project(key="kb", group=None, path=Path("/tmp/kb"), session="kb")
        tmux = Mock(spec=Tmux)
        harnesses = Harnesses(Path("/home"))
        with (
            patch("shad.projects.open.command.recorded_or_note", return_value=([], None)),
            self.assertRaises(ShadError) as ctx,
        ):
            open_project(project, Defaults(), tmux, harnesses, resume="")
        self.assertEqual(ctx.exception.code, "no_conversation")

    def test_open_without_tmux_is_infrastructure(self) -> None:
        """
        Criterion:  open-without-tmux-is-infrastructure
          Given:    PATH has no tmux.
          When:     opening a project.
          Then:     the failure is infrastructure/tmux_missing.
        """
        project = Project(key="kb", group=None, path=Path("/tmp/kb"), session="kb")
        tmux = Tmux({"PATH": "/nonexistent-dir"})
        harnesses = Harnesses(Path("/home"))
        with self.assertRaises(ShadError) as ctx:
            open_project(project, Defaults(), tmux, harnesses, harness="opencode")
        self.assertEqual(ctx.exception.code, "tmux_missing")
