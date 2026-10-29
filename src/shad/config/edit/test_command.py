from __future__ import annotations

from unittest.mock import patch

from shad.config.testing import ConfigCase
from shad.shared.errors import ShadError


class EditTests(ConfigCase):
    def test_runs_the_editor_then_validates(self) -> None:
        with (
            patch.dict("os.environ", {"EDITOR": "true"}),
            patch("shad.config.edit.command.subprocess.run") as run,
        ):
            run.return_value.returncode = 0
            self._run("edit")
        run.assert_called_once_with(["true", str(self.path)], check=False)

    def test_reports_an_editor_failure(self) -> None:
        with (
            patch.dict("os.environ", {"EDITOR": "false"}),
            patch("shad.config.edit.command.subprocess.run") as run,
        ):
            run.return_value.returncode = 1
            with self.assertRaises(ShadError) as ctx:
                self._run("edit")
        self.assertIn("editor exited", str(ctx.exception))
