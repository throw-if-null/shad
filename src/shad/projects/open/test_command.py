from __future__ import annotations

import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from shad.projects.open.command import open_project
from shad.projects.open.sessions import OpencodeTarget
from shad.projects.testing import UUID_A, ProjectsCase
from shad.shared.config import Defaults, Project


class OpenTests(ProjectsCase):
    """
    Feature:    projects/open
    Boundary:   command. `shad projects [<group>] <name> [--harness H]`,
                typed into a shell that a tmux client sits on, or run in a
                terminal pane, against the test's server with Claude Code's
                transcripts under the test home. Contract: exit code +
                screen + the sessions on the server + the client's session.
    """

    def test_open_creates_the_layout_and_attaches(self) -> None:
        """
        Criterion:  open-creates-the-layout-and-attaches
          Given:    kb has no earlier conversation, and a client sits on a
                    shell session.
          When:     `shad projects kb` typed into that shell.
          Then:     the client moves to a session named kb--cc-<uuid>, which
                    has four panes with claude running in one.
        """
        self.shell_with_client()
        self.type_into_shell("shad projects kb")
        session = self.wait_for_client_on(lambda name: name.startswith("kb--cc-"))
        uuid.UUID(session.removeprefix("kb--cc-"))
        self.assertEqual(len(self.pane_commands(session)), 4)
        self.wait_for_harness(session)

    def test_open_shows_the_picker_when_conversations_exist(self) -> None:
        """
        Criterion:  open-shows-the-picker-when-conversations-exist
          Given:    kb has a conversation named Netbird whose first prompt
                    is "Fix the panel".
          When:     `shad projects kb` in a terminal, then `q`.
          Then:     the picker offers a new session, Netbird and the prompt;
                    exit 0, and no kb session exists.
        """
        self.write_transcript("kb", UUID_A, "Fix the panel", name="Netbird")
        pane = self.pane("projects", "kb")
        screen = pane.wait_for("New session")
        for text in ("claude session", "Netbird", "Fix the panel"):
            self.assertIn(text, screen)
        pane.send("q")
        self.assertEqual(pane.wait_exit(), 0)
        self.assertEqual(self.sessions_of("kb"), [])

    def test_open_resumes_the_picked_conversation(self) -> None:
        """
        Criterion:  open-resumes-the-picked-conversation
          Given:    kb has conversation A, and a client sits on a shell.
          When:     `shad projects kb` typed into the shell, Down, Enter.
          Then:     the client moves to kb--cc-A, with claude running in it.
        """
        self.write_transcript("kb", UUID_A, "Fix the panel")
        self.shell_with_client()
        self.type_into_shell("shad projects kb")
        self.wait_for_shell("New session")
        self.server.tmux("send-keys", "-t", "shell", "Down", "Enter")
        session = self.wait_for_client_on(lambda name: name == f"kb--cc-{UUID_A}")
        self.wait_for_harness(session)

    def test_open_attaches_to_the_existing_session_of_a_conversation(self) -> None:
        """
        Criterion:  open-attaches-to-the-existing-session-of-a-conversation
          Given:    kb has conversation A, a session kb--cc-A with one pane
                    runs it, and a client sits on a shell.
          When:     `shad projects kb` typed into the shell, Down, Enter.
          Then:     the client moves to that session, which still has one
                    pane, and kb has no other session.
        """
        self.write_transcript("kb", UUID_A, "Fix the panel")
        existing = f"kb--cc-{UUID_A}"
        self.server.new_session(existing, cwd=self.root / "kb", command="claude")
        self.shell_with_client()
        self.type_into_shell("shad projects kb")
        self.wait_for_shell("New session")
        self.server.tmux("send-keys", "-t", "shell", "Down", "Enter")
        self.wait_for_client_on(lambda name: name == existing)
        self.assertEqual(self.sessions_of("kb"), [existing])
        self.assertEqual(len(self.pane_commands(existing)), 1)

    def test_open_with_a_harness_override_uses_that_harness(self) -> None:
        """
        Criterion:  open-with-a-harness-override-uses-that-harness
          Given:    kb is configured for claude, opencode has no sessions,
                    and a client sits on a shell.
          When:     `shad projects kb --harness opencode` typed into it.
          Then:     the client moves to a session named kb--oc-fresh-<n>.
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


class FreshTargetTests(unittest.TestCase):
    """
    A fresh target that meets an existing session of its name. The pickers
    give every fresh target a new name, so the boundary cannot reach this
    branch; it is tested on the function until the branch is removed.
    """

    def test_open_project_fresh_kills_existing_session_and_recreates(self) -> None:
        project = Project(key="shad", group="tin", path=Path("/tmp/shad"), session="tin-shad")
        target = OpencodeTarget(command="opencode", session_key="fresh-123", fresh=True)

        with (
            patch("shad.projects.open.command.pick_opencode_target", return_value=target),
            patch("shad.projects.open.command.session_exists", return_value=True),
            patch("shad.projects.open.command._run") as run,
            patch("shad.projects.open.command._create_session") as create_session,
            patch("shad.projects.open.command._attach"),
        ):
            open_project(project, Defaults())

        run.assert_called_once_with(
            ["tmux", "kill-session", "-t", "tin-shad--oc-fresh-123"], check=False
        )
        create_session.assert_called_once_with(
            project, Defaults(), "opencode", "tin-shad--oc-fresh-123"
        )
