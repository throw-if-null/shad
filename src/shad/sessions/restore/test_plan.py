from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shad.sessions.live import Running
from shad.sessions.model import Entry, Snapshot
from shad.sessions.restore.plan import Step, attach_target, plan, tab_targets
from shad.sessions.testing import CFG, KB, SHAD, UUID_A, UUID_B, running


def _entry(
    key: str,
    session_id: str | None,
    *,
    group: str | None = None,
    harness: str = "claude",
    attached: bool = False,
) -> Entry:
    return Entry(group=group, key=key, harness=harness, session_id=session_id, attached=attached)


class PlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.projects = Path(self._tmp.name)
        (self.projects / "-p-kb").mkdir()
        (self.projects / "-p-kb" / f"{UUID_A}.jsonl").write_text("")
        self.existing: set[str] = set()
        for patcher in (
            patch("shad.projects.open.sessions.CLAUDE_PROJECTS_DIR", self.projects),
            patch("shad.sessions.restore.plan.session_exists", side_effect=self.existing.__contains__),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _plan(self, *entries: Entry, live: list[Running] | None = None) -> list[Step]:
        return plan(CFG, Snapshot(saved_at=0, entries=entries), live or [])

    def test_resumes_a_saved_conversation_that_has_a_transcript(self) -> None:
        (step,) = self._plan(_entry("kb", UUID_A))
        self.assertEqual(step.outcome, "resume")
        self.assertEqual(step.project, KB)
        self.assertEqual(step.session, f"kb--cc-{UUID_A}")
        self.assertEqual(step.command, f"claude --resume {UUID_A}")
        self.assertTrue(step.creates)

    def test_starts_a_new_conversation_under_an_id_without_a_transcript(self) -> None:
        (step,) = self._plan(_entry("kb", UUID_B))
        self.assertEqual(step.outcome, "new")
        self.assertIn(UUID_B, step.reason)
        self.assertEqual(step.session, f"kb--cc-{UUID_B}")
        self.assertEqual(step.command, f"claude --session-id {UUID_B}")

    def test_chooses_an_id_when_none_was_saved(self) -> None:
        (step,) = self._plan(_entry("kb", None))
        self.assertEqual(step.outcome, "new")
        self.assertEqual(step.reason, "no conversation id was saved")
        assert step.session is not None and step.command is not None
        chosen = step.session.removeprefix("kb--cc-")
        self.assertEqual(step.command, f"claude --session-id {chosen}")

    def test_leaves_a_session_of_the_computed_name_alone(self) -> None:
        self.existing.add(f"kb--cc-{UUID_A}")
        (step,) = self._plan(_entry("kb", UUID_A))
        self.assertEqual(step.outcome, "running")
        self.assertEqual(step.session, f"kb--cc-{UUID_A}")
        self.assertIsNone(step.command)
        self.assertFalse(step.creates)

    def test_a_conversation_live_under_another_tmux_name_is_running(self) -> None:
        """A `fresh-` name, or an id superseded by /clear: never a second process."""
        live = running("kb--cc-fresh-9", session_id=UUID_A)
        (step,) = self._plan(_entry("kb", UUID_A), live=[live])
        self.assertEqual(step.outcome, "running")
        self.assertEqual(step.session, "kb--cc-fresh-9")
        self.assertFalse(step.creates)

    def test_a_live_session_holding_another_conversation_does_not_count(self) -> None:
        live = running("kb--cc-fresh-9", session_id=UUID_B)
        (step,) = self._plan(_entry("kb", UUID_A), live=[live])
        self.assertEqual(step.outcome, "resume")

    def test_a_live_session_without_a_conversation_does_not_count(self) -> None:
        live = running("kb--cc-fresh-9", session_id=None)
        (step,) = self._plan(_entry("kb", None), live=[live])
        self.assertEqual(step.outcome, "new")

    def test_skips_a_project_that_is_no_longer_configured(self) -> None:
        (step,) = self._plan(_entry("gone", UUID_A))
        self.assertEqual(step.outcome, "skipped")
        self.assertEqual(step.reason, "project is no longer configured")
        self.assertIsNone(step.session)

    def test_skips_a_grouped_project_under_the_wrong_group(self) -> None:
        (step,) = self._plan(_entry("shad", UUID_A, group="other"))
        self.assertEqual(step.outcome, "skipped")

    def test_resolves_a_grouped_project(self) -> None:
        (step,) = self._plan(_entry("shad", None, group="tin"))
        self.assertEqual(step.project, SHAD)
        assert step.session is not None
        self.assertTrue(step.session.startswith("tin-shad--cc-"))

    def test_skips_an_unsupported_harness(self) -> None:
        (step,) = self._plan(_entry("kb", "ses_1", harness="opencode"))
        self.assertEqual(step.outcome, "skipped")
        self.assertEqual(step.reason, "the opencode harness is not supported")

    def test_keeps_saved_order(self) -> None:
        steps = self._plan(_entry("shad", None, group="tin"), _entry("kb", UUID_A))
        self.assertEqual([s.entry.key for s in steps], ["shad", "kb"])


class AttachTargetTests(unittest.TestCase):
    def _step(self, session: str | None, outcome: str, attached: bool = False) -> Step:
        return Step(_entry("kb", None, attached=attached), outcome, session=session)  # type: ignore[arg-type]

    def test_prefers_the_session_that_was_attached_at_save(self) -> None:
        steps = [
            self._step("kb--cc-a", "resume"),
            self._step("kb--cc-b", "running", attached=True),
        ]
        self.assertEqual(attach_target(steps), "kb--cc-b")

    def test_falls_back_to_the_first_session_that_exists(self) -> None:
        steps = [self._step(None, "skipped"), self._step("kb--cc-a", "new")]
        self.assertEqual(attach_target(steps), "kb--cc-a")

    def test_none_when_nothing_exists(self) -> None:
        self.assertIsNone(attach_target([self._step(None, "skipped")]))
        self.assertIsNone(attach_target([]))


class TabTargetsTests(unittest.TestCase):
    def _step(self, session: str | None, outcome: str, attached: bool = False) -> Step:
        return Step(_entry("kb", None, attached=attached), outcome, session=session)  # type: ignore[arg-type]

    def test_the_other_sessions_attached_at_save_in_saved_order(self) -> None:
        steps = [
            self._step("kb--cc-a", "resume", attached=True),
            self._step("kb--cc-b", "new", attached=True),
            self._step("kb--cc-c", "running", attached=True),
        ]
        self.assertEqual(
            [step.session for step in tab_targets(steps, "kb--cc-a", set())],
            ["kb--cc-b", "kb--cc-c"],
        )

    def test_leaves_out_what_was_detached_skipped_or_is_attached_now(self) -> None:
        steps = [
            self._step("kb--cc-a", "resume", attached=True),
            self._step("kb--cc-b", "resume"),
            self._step(None, "skipped", attached=True),
            self._step("kb--cc-d", "running", attached=True),
        ]
        self.assertEqual(tab_targets(steps, "kb--cc-a", {"kb--cc-d"}), [])
