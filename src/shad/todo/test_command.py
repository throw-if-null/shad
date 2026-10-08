from __future__ import annotations

import contextlib
import io
import subprocess
import textwrap
import unittest
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from shad.cli import build_parser
from shad.shared.config import load
from shad.shared.errors import ShadError
from shad.todo import store
from shad.todo.command import cmd_todo
from shad.todo.model import template

CONFIG = """\
[defaults]
harness = "claude"   # keep me

[projects.kb]
path = "{root}/kb"

[projects.alvr.db]
path = "{root}/alvr/db"

[projects.alvr.api]
path = "{root}/alvr/api"

# the vocabulary
[todo]
labels = ["chore", "poc"]   # trailing comment
"""

DRAFT = """\
title: Fix panel resize
status: todo
labels: chore
# a help line

The resize handler fires twice.
"""


class TodoCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        for name in ("kb", "alvr/db", "alvr/api", "data"):
            (self.root / name).mkdir(parents=True)
        self.config = self.root / "shad.toml"
        self.config.write_text(CONFIG.format(root=self.root))
        self.cfg = load(self.config)

        patcher = patch("shad.todo.store.default_data_dir", return_value=self.root / "data")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self, *argv: str) -> str:
        args = build_parser().parse_args(["todo", *argv])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cmd_todo(self.cfg, args, path=self.config)
        return out.getvalue()

    def _dir(self) -> Path:
        return self.root / "data" / "todo"

    @contextlib.contextmanager
    def _editor(
        self, *drafts: str | None, confirm: tuple[bool, ...] = (), status: int = 0
    ) -> Iterator[list[tuple[Path, str]]]:
        """
        A fake editor on a terminal. Each run records the file it was given and
        the text it found there, then saves the next of *drafts* over it; None
        leaves the file as it was.
        """
        shown: list[tuple[Path, str]] = []
        queue = list(drafts)

        def edit(command: list[str], check: bool) -> subprocess.CompletedProcess[bytes]:
            path = Path(command[-1])
            shown.append((path, path.read_text()))
            draft = queue.pop(0)
            if draft is not None:
                path.write_text(draft)
            return subprocess.CompletedProcess(command, status)

        with (
            patch("shad.todo.command.resolve_editor", return_value="nano"),
            patch("shad.todo.command.subprocess.run", side_effect=edit),
            patch("shad.todo.command.sys.stdin") as stdin,
            patch("shad.todo.command.Confirm.ask", side_effect=list(confirm)),
        ):
            stdin.isatty.return_value = True
            yield shown

    # -- add / list / status / rm -----------------------------------------

    def test_add_writes_into_the_todo_dir(self) -> None:
        out = self._run("add", "Fix panel resize", "--label", "chore")
        self.assertIn("fix-panel-resize", out)
        self.assertTrue((self._dir() / "fix-panel-resize.md").exists())

    def test_the_project_flag_is_not_accepted(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self._run("add", "Elsewhere", "--project", "kb")

    def test_add_rejects_an_unknown_label(self) -> None:
        with self.assertRaises(ShadError):
            self._run("add", "x", "--label", "nope")

    def test_add_writes_under_the_configured_todo_path(self) -> None:
        notes = self.root / "notes"
        self.config.write_text(f'{CONFIG.format(root=self.root)}path = "{notes}"\n')
        self.cfg = load(self.config)
        self._run("add", "Fix panel resize")
        self.assertTrue((notes / "fix-panel-resize.md").exists())
        self.assertFalse(self._dir().exists())

    def test_add_with_a_title_never_opens_the_editor(self) -> None:
        with patch("shad.todo.command.subprocess.run") as run:
            self._run("add", "Plain")
        run.assert_not_called()

    def test_list_keys_prints_one_key_per_line(self) -> None:
        self._run("add", "Beta")
        self._run("add", "Alpha")
        self.assertEqual(self._run("list", "--keys"), "alpha\nbeta\n")

    def test_list_renders_every_item_and_flags_problems(self) -> None:
        self._run("add", "Good one", "--label", "poc")
        path = store.item_path(self._dir(), "good-one")
        path.write_text(path.read_text().replace("status: todo", "status: doing"))
        out = self._run("list")
        self.assertIn("good-one", out)
        self.assertIn("Good one", out)
        self.assertIn("unknown status 'doing'", out)

    def test_list_of_nothing_says_so(self) -> None:
        self.assertIn("no todos", self._run("list"))

    def test_status_accepts_a_prefix_and_rewrites_the_file(self) -> None:
        self._run("add", "Fix panel resize")
        self._run("status", "fix", "in-progress")
        text = store.item_path(self._dir(), "fix-panel-resize").read_text()
        self.assertIn("status: in-progress", text)

    def test_status_rejects_a_value_outside_the_enum_at_parse_time(self) -> None:
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["todo", "status", "x", "doing"])

    def test_rm_deletes_the_file(self) -> None:
        self._run("add", "Gone")
        self._run("rm", "go")
        self.assertEqual(store.keys(self._dir()), [])

    def test_unknown_key_is_an_error(self) -> None:
        with self.assertRaises(ShadError):
            self._run("rm", "nothing")

    # -- add in the editor ------------------------------------------------

    def test_add_without_a_title_creates_the_item_from_the_editor(self) -> None:
        with self._editor(DRAFT) as shown:
            out = self._run("add")
        self.assertIn("fix-panel-resize", out)
        draft, text = shown[0]
        self.assertEqual(draft.suffix, ".md")
        self.assertTrue(text.startswith("title: \n"))
        self.assertIn("# labels: chore, poc", text)
        self.assertFalse(draft.exists())

        item = store.read_item(self._dir(), "fix-panel-resize")
        self.assertEqual((item.title, item.status), ("Fix panel resize", "todo"))
        self.assertEqual(item.labels, ("chore",))
        self.assertEqual(item.body, "The resize handler fires twice.\n")
        self.assertNotIn("#", store.item_path(self._dir(), item.key).read_text())

    def test_add_label_flag_fills_in_the_template(self) -> None:
        with self._editor(DRAFT) as shown:
            self._run("add", "--label", "poc")
        self.assertIn("\nlabels: poc\n", shown[0][1])

    def test_add_label_flag_is_checked_before_the_editor_opens(self) -> None:
        with self._editor() as shown, self.assertRaises(ShadError):
            self._run("add", "--label", "nope")
        self.assertEqual(shown, [])

    def test_an_untouched_template_creates_nothing(self) -> None:
        with self._editor(None) as shown, self.assertRaises(ShadError) as ctx:
            self._run("add")
        self.assertEqual(shown[0][1], template([], ["chore", "poc"]))
        self.assertIn("no todo created", str(ctx.exception))
        self.assertEqual(store.keys(self._dir()), [])
        self.assertFalse(shown[0][0].exists())

    def test_an_invalid_draft_reopens_with_the_typed_text(self) -> None:
        bad = DRAFT.replace("labels: chore", "labels: nope")
        with self._editor(bad, DRAFT, confirm=(True,)) as shown:
            self._run("add")
        self.assertEqual(shown[1], (shown[0][0], bad))
        self.assertEqual(store.keys(self._dir()), ["fix-panel-resize"])
        self.assertFalse(shown[0][0].exists())

    def test_a_body_without_a_title_is_not_discarded(self) -> None:
        untitled = DRAFT.replace("Fix panel resize", "")
        with self._editor(untitled, DRAFT, confirm=(True,)) as shown:
            self._run("add")
        self.assertEqual(shown[1][1], untitled)
        self.assertEqual(store.keys(self._dir()), ["fix-panel-resize"])

    def test_declining_to_edit_again_keeps_the_draft(self) -> None:
        bad = DRAFT.replace("status: todo", "status: doing")
        with self._editor(bad, confirm=(False,)) as shown, self.assertRaises(ShadError) as ctx:
            self._run("add")
        draft = shown[0][0]
        self.addCleanup(draft.unlink, missing_ok=True)
        self.assertIn(str(draft), str(ctx.exception))
        self.assertEqual(draft.read_text(), bad)
        self.assertEqual(store.keys(self._dir()), [])

    def test_a_failing_editor_creates_nothing(self) -> None:
        with self._editor(DRAFT, status=1) as shown, self.assertRaises(ShadError) as ctx:
            self._run("add")
        self.assertIn("status 1", str(ctx.exception))
        self.assertEqual(store.keys(self._dir()), [])
        self.assertFalse(shown[0][0].exists())

    def test_add_without_a_terminal_does_not_open_an_editor(self) -> None:
        with (
            patch("shad.todo.command.sys.stdin") as stdin,
            patch("shad.todo.command.subprocess.run") as run,
            self.assertRaises(ShadError) as ctx,
        ):
            stdin.isatty.return_value = False
            self._run("add")
        self.assertIn("not a terminal", str(ctx.exception))
        run.assert_not_called()

    # -- labels -----------------------------------------------------------

    def test_label_list_prints_the_vocabulary(self) -> None:
        self.assertEqual(self._run("label", "list"), "chore\npoc\n")

    def test_label_add_appends_and_keeps_comments(self) -> None:
        self._run("label", "add", "docs")
        text = self.config.read_text()
        self.assertIn('labels = ["chore", "poc", "docs"]   # trailing comment', text)
        self.assertIn("# the vocabulary", text)
        self.assertIn('harness = "claude"   # keep me', text)
        self.assertEqual(load(self.config).todo_labels, ["chore", "poc", "docs"])

    def test_label_add_creates_the_table_when_missing(self) -> None:
        self.config.write_text(textwrap.dedent(f"""\
            [projects.kb]
            path = "{self.root}/kb"
            """))
        self.cfg = load(self.config)
        self._run("label", "add", "chore")
        self.assertEqual(load(self.config).todo_labels, ["chore"])

    def test_label_add_rejects_duplicates_and_bad_names(self) -> None:
        with self.assertRaises(ShadError):
            self._run("label", "add", "chore")
        with self.assertRaises(ShadError):
            self._run("label", "add", "Not Valid")

    def test_label_rm_removes_an_unused_label(self) -> None:
        self._run("label", "rm", "poc")
        self.assertEqual(load(self.config).todo_labels, ["chore"])

    def test_label_rm_refuses_a_label_in_use_unless_forced(self) -> None:
        self._run("add", "Uses it", "--label", "poc")
        with self.assertRaises(ShadError) as ctx:
            self._run("label", "rm", "poc")
        self.assertIn("1 item(s)", str(ctx.exception))
        self._run("label", "rm", "poc", "--force")
        self.assertEqual(load(self.config).todo_labels, ["chore"])

    def test_label_rm_counts_items_under_the_configured_todo_path(self) -> None:
        notes = self.root / "notes"
        self.config.write_text(f'{CONFIG.format(root=self.root)}path = "{notes}"\n')
        self.cfg = load(self.config)
        self._run("add", "Uses it", "--label", "poc")
        with self.assertRaises(ShadError) as ctx:
            self._run("label", "rm", "poc")
        self.assertIn("1 item(s)", str(ctx.exception))

    def test_label_rm_of_an_unknown_label_is_an_error(self) -> None:
        with self.assertRaises(ShadError):
            self._run("label", "rm", "nope")

    # -- dispatch ---------------------------------------------------------

    def test_no_action_is_an_error(self) -> None:
        args = build_parser().parse_args(["todo"])
        with self.assertRaises(ShadError):
            cmd_todo(self.cfg, args, path=self.config)

    def test_panel_is_imported_lazily(self) -> None:
        """textual must not load for `shad todo add`; only open_panel may import it."""
        import shad.todo.command as module

        source = Path(module.__file__).read_text()
        self.assertNotIn("\nfrom shad.todo.panel", source)
        self.assertNotIn("\nimport shad.todo.panel", source)
        self.assertIn("    from shad.todo.panel import run_panel", source)


if __name__ == "__main__":
    unittest.main()
