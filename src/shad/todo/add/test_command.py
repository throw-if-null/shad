from __future__ import annotations

from shad.todo.testing import CONFIG, DRAFT, TodoCase, TodoTerminalCase


class AddTests(TodoCase):
    """
    Feature:    todo/add
    Boundary:   command. `shad todo add [TITLE] [--label L]`, through
                main(argv) with SHAD_CONFIG and XDG_DATA_HOME under the test
                root. Contract: exit code + stdout + stderr + the todo
                directory, read back through `shad todo list --keys`.
    """

    def test_add_with_a_title_creates_the_item(self) -> None:
        """
        Criterion:  add-with-a-title-creates-the-item
          Given:    `shad todo list --keys` prints nothing.
          When:     `shad todo add "Fix panel resize" --label chore`.
          Then:     exit 0, stderr empty, stdout names the key
                    fix-panel-resize, `shad todo list --keys` prints that
                    key, and the item file holds the title, status todo and
                    the label.
        """
        self.assertEqual(self._run("list", "--keys"), "")
        out = self._run("add", "Fix panel resize", "--label", "chore")
        self.assertIn("fix-panel-resize", out)
        self.assertEqual(self._run("list", "--keys"), "fix-panel-resize\n")
        text = (self._dir() / "fix-panel-resize.md").read_text()
        for line in ("title: Fix panel resize\n", "status: todo\n", "labels: chore\n"):
            self.assertIn(line, text)

    def test_add_with_a_title_never_opens_the_editor(self) -> None:
        """
        Criterion:  add-with-a-title-never-opens-the-editor
          Given:    EDITOR is `false`, a command that fails when run.
          When:     `shad todo add Plain`.
          Then:     exit 0.
        """
        self.env["EDITOR"] = "false"
        self._run("add", "Plain")

    def test_add_of_a_duplicate_key_fails_and_keeps_the_item(self) -> None:
        """
        Criterion:  add-of-a-duplicate-key-fails-and-keeps-the-item
          Given:    `shad todo add "Fix panel resize" --label chore` ran.
          When:     `shad todo add "Fix panel resize"`.
          Then:     exit 1, stdout empty, stderr one line `todo_exists:
                    <non-empty>`, and the item file is byte-identical.
        """
        self._run("add", "Fix panel resize", "--label", "chore")
        before = (self._dir() / "fix-panel-resize.md").read_text()
        self.assertIn("already exists", self._fail("add", "Fix panel resize", code="todo_exists"))
        self.assertEqual((self._dir() / "fix-panel-resize.md").read_text(), before)

    def test_add_rejects_an_unknown_label_before_any_effect(self) -> None:
        """
        Criterion:  add-rejects-an-unknown-label-before-any-effect
          Given:    the configured labels are chore and poc.
          When:     `shad todo add x --label nope`.
          Then:     exit 1, stdout empty, stderr one line `unknown_label:
                    <non-empty>` naming nope and the configured labels, and
                    `shad todo list --keys` still prints nothing.
        """
        err = self._fail("add", "x", "--label", "nope", code="unknown_label")
        self.assertIn("nope", err)
        self.assertIn("chore, poc", err)
        self.assertEqual(self._run("list", "--keys"), "")

    def test_add_writes_under_the_configured_todo_path(self) -> None:
        """
        Criterion:  add-writes-under-the-configured-todo-path
          Given:    shad.toml sets [todo] path to <root>/notes.
          When:     `shad todo add "Fix panel resize"`.
          Then:     exit 0, <root>/notes/fix-panel-resize.md exists, and the
                    data directory's todo dir does not.
        """
        notes = self.root / "notes"
        self.config.write_text(f'{CONFIG.format(root=self.root)}path = "{notes}"\n')
        self._run("add", "Fix panel resize")
        self.assertTrue((notes / "fix-panel-resize.md").exists())
        self.assertFalse(self._dir().exists())

    def test_add_rejects_an_unknown_flag(self) -> None:
        """
        Criterion:  add-rejects-an-unknown-flag
          When:     `shad todo add Elsewhere --project kb`.
          Then:     exit 2, stdout empty, stderr names the flag.
        """
        result = self._result("add", "Elsewhere", "--project", "kb")
        self.assertEqual((result.code, result.out), (2, ""))
        self.assertIn("--project", result.err)

    def test_add_without_a_title_needs_a_terminal(self) -> None:
        """
        Criterion:  add-without-a-title-needs-a-terminal
          Given:    stdin is not a terminal, and EDITOR is `false`.
          When:     `shad todo add`.
          Then:     exit 1, stdout empty, stderr one line `no_terminal:
                    <non-empty>`, and no item exists.
        """
        self.env["EDITOR"] = "false"
        self.assertIn("not a terminal", self._fail("add", code="no_terminal"))
        self.assertEqual(self._run("list", "--keys"), "")


class AddInEditorTests(TodoTerminalCase):
    """
    Feature:    todo/add without a title
    Boundary:   command. `shad todo add [--label L]` in a terminal pane of an
                isolated tmux server, with EDITOR a real program that saves
                a draft. Contract: exit code + screen + the todo directory.
    """

    def test_add_without_a_title_creates_the_item_from_the_editor(self) -> None:
        """
        Criterion:  add-without-a-title-creates-the-item-from-the-editor
          Given:    EDITOR saves a draft with a title, a label and a body.
          When:     `shad todo add` in a terminal.
          Then:     exit 0, the screen names the key, the editor received a
                    .md draft starting with an empty title and listing the
                    configured labels, that draft is gone, and the item file
                    holds the draft's title, status, label and body with no
                    help line.
        """
        editor = self.editor(DRAFT)
        pane = self.pane("todo", "add")
        self.assertEqual(pane.wait_exit(), 0)
        self.assertIn("fix-panel-resize", pane.screen())

        [(draft, text)] = editor.shown()
        self.assertEqual(draft.suffix, ".md")
        self.assertTrue(text.startswith("title: \n"))
        self.assertIn("# labels: chore, poc", text)
        self.assertFalse(draft.exists())

        item = (self.todo_dir / "fix-panel-resize.md").read_text()
        for line in ("title: Fix panel resize\n", "status: todo\n", "labels: chore\n"):
            self.assertIn(line, item)
        self.assertTrue(item.endswith("\n\nThe resize handler fires twice.\n"))
        self.assertNotIn("#", item)

    def test_the_label_flag_fills_in_the_template(self) -> None:
        editor = self.editor(DRAFT)
        pane = self.pane("todo", "add", "--label", "poc")
        self.assertEqual(pane.wait_exit(), 0)
        self.assertIn("\nlabels: poc\n", editor.shown()[0][1])

    def test_the_label_flag_is_checked_before_the_editor_opens(self) -> None:
        """
        Criterion:  the-label-flag-is-checked-before-the-editor-opens
          When:     `shad todo add --label nope` in a terminal.
          Then:     exit 1 with `unknown_label` on the screen, and the editor
                    never ran.
        """
        editor = self.editor()
        pane = self.pane("todo", "add", "--label", "nope")
        self.assertEqual(pane.wait_exit(), 1)
        self.assertIn("unknown_label: ", pane.screen())
        self.assertEqual(editor.shown(), [])

    def test_an_untouched_template_creates_nothing(self) -> None:
        """
        Criterion:  an-untouched-template-creates-nothing
          Given:    EDITOR leaves the draft as it was.
          When:     `shad todo add` in a terminal.
          Then:     exit 1, the screen holds one line `empty_todo:
                    <non-empty>` saying no todo was created, no item exists,
                    and the draft is gone.
        """
        editor = self.editor(None)
        pane = self.pane("todo", "add")
        self.assertEqual(pane.wait_exit(), 1)
        self.assertIn("empty_todo: ", pane.screen())
        self.assertIn("no todo created", pane.screen())
        [(draft, text)] = editor.shown()
        self.assertIn("# statuses:", text)
        self.assertEqual(self.keys(), [])
        self.assertFalse(draft.exists())

    def test_an_invalid_draft_reopens_after_confirmation(self) -> None:
        """
        Criterion:  an-invalid-draft-reopens-after-confirmation
          Given:    EDITOR saves a draft with an unknown label, then a valid
                    one.
          When:     `shad todo add` in a terminal, and `y` at "Edit again?".
          Then:     exit 0, the editor received the same file twice with the
                    typed text kept, the item exists, and the draft is gone.
        """
        bad = DRAFT.replace("labels: chore", "labels: nope")
        editor = self.editor(bad, DRAFT)
        pane = self.pane("todo", "add")
        pane.wait_for("Edit again?")
        pane.send("y", "Enter")
        self.assertEqual(pane.wait_exit(), 0)
        shown = editor.shown()
        self.assertEqual(shown[1], (shown[0][0], bad))
        self.assertEqual(self.keys(), ["fix-panel-resize"])
        self.assertFalse(shown[0][0].exists())

    def test_a_body_without_a_title_is_not_discarded(self) -> None:
        untitled = DRAFT.replace("Fix panel resize", "")
        editor = self.editor(untitled, DRAFT)
        pane = self.pane("todo", "add")
        pane.wait_for("Edit again?")
        pane.send("y", "Enter")
        self.assertEqual(pane.wait_exit(), 0)
        self.assertEqual(editor.shown()[1][1], untitled)
        self.assertEqual(self.keys(), ["fix-panel-resize"])

    def test_declining_to_edit_again_keeps_the_draft(self) -> None:
        """
        Criterion:  declining-to-edit-again-keeps-the-draft
          Given:    EDITOR saves a draft with an unknown status.
          When:     `shad todo add` in a terminal, and `n` at "Edit again?".
          Then:     exit 1, the screen holds one line `draft_rejected:
                    <non-empty>` naming the kept draft, the draft holds the
                    typed text, and no item exists.
        """
        bad = DRAFT.replace("status: todo", "status: doing")
        editor = self.editor(bad)
        pane = self.pane("todo", "add")
        pane.wait_for("Edit again?")
        pane.send("n", "Enter")
        self.assertEqual(pane.wait_exit(), 1)
        [(draft, _)] = editor.shown()
        self.addCleanup(draft.unlink, missing_ok=True)
        self.assertIn("draft_rejected: ", pane.screen())
        self.assertIn(str(draft), pane.screen())
        self.assertEqual(draft.read_text(), bad)
        self.assertEqual(self.keys(), [])

    def test_a_failing_editor_creates_nothing(self) -> None:
        """
        Criterion:  a-failing-editor-creates-nothing
          Given:    EDITOR exits with status 1.
          When:     `shad todo add` in a terminal.
          Then:     exit 1, the screen holds one line `editor_failed:
                    <non-empty>` naming the status, no item exists, and the
                    draft is gone.
        """
        editor = self.editor(DRAFT, status=1)
        pane = self.pane("todo", "add")
        self.assertEqual(pane.wait_exit(), 1)
        self.assertIn("editor_failed: ", pane.screen())
        self.assertIn("status 1", pane.screen())
        self.assertEqual(self.keys(), [])
        self.assertFalse(editor.shown()[0][0].exists())
