from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shad.sessions import OcSession, OpencodeTarget, pick_opencode_target


class PickOpencodeTargetTests(unittest.TestCase):
    def test_returns_base_command_when_no_sessions_exist(self) -> None:
        with patch("shad.sessions._query_sessions", return_value=[]):
            target = pick_opencode_target(Path("/tmp/project"), "opencode")

        self.assertEqual(target, OpencodeTarget(command="opencode"))

    def test_returns_session_scoped_target_for_existing_session(self) -> None:
        sessions = [
            OcSession(id="sess-123", title="Fix bug", time_updated=0),
        ]

        with patch("shad.sessions._query_sessions", return_value=sessions), patch(
            "shad.sessions._run_picker", return_value=1
        ):
            target = pick_opencode_target(Path("/tmp/project"), "opencode")

        self.assertEqual(
            target,
            OpencodeTarget(command="opencode -s sess-123", session_key="sess-123"),
        )


if __name__ == "__main__":
    unittest.main()
