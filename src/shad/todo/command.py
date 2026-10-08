"""
`shad todo` — the CLI side of the todo pane.

Actions:
  panel          the pane; a thin textual view over the same files
  add            create an item file; with no title, write it in $EDITOR first
  list           print the items, or just their keys with --keys
  status         set one item's status
  edit           open one item in $EDITOR
  rm             delete one item's file
  label          add, rm, list: the label vocabulary in shad.toml

There is one list, in store.todo_dir(). No item belongs to a project, so every
action works the same from any directory.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from rich.console import Console
from rich.prompt import Confirm
from rich.text import Text

from shad.config.command import resolve_editor, write_value
from shad.shared.config import LABEL_RE, Config, config_path
from shad.shared.errors import ShadError
from shad.shared.render import make_table
from shad.todo import store
from shad.todo.model import STATUSES, Item, check_labels, parse, problems, template
from shad.todo.render import labels_text, status_glyph, status_word, title_text

console = Console()

ACTIONS = ("panel", "add", "list", "status", "edit", "rm", "label")
LABEL_ACTIONS = ("add", "rm", "list")


# ── actions ───────────────────────────────────────────────────────────────


def add_in_editor(directory: Path, labels: list[str], vocabulary: list[str]) -> Item:
    """
    Open the editor on a draft of a new item, create the item from it, and
    return the item.

    The draft is in the temporary directory, not in the item directory, so the
    list and the panel never show an unfinished draft. When store.add rejects
    the draft, the editor opens it again on request. The draft file is kept
    when the user declines.

    The editor and the prompt use the terminal, so a textual caller must
    suspend the app around this call.
    """
    if not sys.stdin.isatty():
        raise ShadError("no title given, and stdin is not a terminal to open an editor in")
    check_labels(labels, vocabulary)

    fd, name = tempfile.mkstemp(prefix="shad-todo-", suffix=".md")
    draft = Path(name)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(template(labels, vocabulary))

    keep = False
    try:
        while True:
            _open_in_editor(draft)
            fields = parse(draft.read_text(encoding="utf-8", errors="replace"), key="")
            if not fields.title and not fields.body.strip():
                raise ShadError("empty title and body; no todo created")
            try:
                return store.add(
                    directory,
                    fields.title,
                    list(fields.labels),
                    vocabulary,
                    status=fields.status,
                    body=fields.body,
                    extra=fields.extra,
                )
            except ShadError as exc:
                console.print(Text(f"  ✗ {exc}", style="bold red"))
                if Confirm.ask("  Edit again?", default=True):
                    continue
                keep = True
                raise ShadError(f"no todo created; the draft is kept in {draft}") from None
    finally:
        if not keep:
            draft.unlink(missing_ok=True)


def _report_added(directory: Path, item: Item) -> None:
    console.print(
        Text("  ✓ ", style="bold green")
        + Text(item.key, style="bright_white")
        + Text(f"  {store.item_path(directory, item.key)}", style="dim")
    )


def _list(cfg: Config, directory: Path, *, keys_only: bool) -> None:
    if keys_only:
        for key in store.keys(directory):
            print(key)
        return

    items = store.list_items(directory)
    table = make_table("todo")
    for _ in range(5):
        table.add_column(no_wrap=True, overflow="ellipsis")
    if not items:
        table.add_row(Text("no todos", style="dim"), "", "", "", "")
        console.print(table)
        return

    for item in items:
        title = title_text(item)
        wrong = problems(item, cfg.todo_labels)
        if wrong:
            title.append(f"  ! {'; '.join(wrong)}", style="red")
        table.add_row(
            status_glyph(item.status),
            Text(item.key, style="bright_white"),
            status_word(item.status),
            labels_text(item.labels, cfg.todo_labels),
            title,
        )
    console.print(table)


def _status(directory: Path, token: str, status: str) -> None:
    key = store.resolve_key(directory, token)
    item = store.set_status(directory, key, status)
    console.print(
        Text("  ✓ ", style="bold green")
        + Text(item.key, style="bright_white")
        + Text("  ", style="")
        + status_word(item.status)
    )


def _edit(cfg: Config, directory: Path, token: str) -> None:
    key = store.resolve_key(directory, token)
    _open_in_editor(store.item_path(directory, key))
    _report_problems(store.read_item(directory, key), cfg)


def _open_in_editor(path: Path) -> None:
    editor = resolve_editor()
    result = subprocess.run([*editor.split(), str(path)], check=False)
    if result.returncode != 0:
        raise ShadError(f"editor exited with status {result.returncode}")


def _remove(directory: Path, token: str) -> None:
    key = store.resolve_key(directory, token)
    path = store.remove(directory, key)
    console.print(
        Text("  ✓ ", style="bold green")
        + Text(f"removed {key}", style="bright_white")
        + Text(f"  {path}", style="dim")
    )


def _report_problems(item: Item, cfg: Config) -> None:
    for problem in problems(item, cfg.todo_labels):
        console.print(Text("  ! ", style="bold yellow") + Text(f"{item.key}: {problem}"))


def _label(cfg: Config, args: argparse.Namespace, path: Path) -> None:
    action = getattr(args, "label_action", None)
    if action is None:
        raise ShadError(f"no label action given; available: {', '.join(LABEL_ACTIONS)}")

    if action == "list":
        for label in cfg.todo_labels:
            print(label)
        return

    name: str = args.name.strip()
    if not LABEL_RE.match(name):
        raise ShadError(f"invalid label {name!r}; use lowercase letters, digits and hyphens")

    if action == "add":
        if name in cfg.todo_labels:
            raise ShadError(f"label '{name}' is already configured")
        write_value(path, "todo.labels", [*cfg.todo_labels, name])
        console.print(Text("  ✓ ", style="bold green") + Text(f"added label {name}"))
        return

    if action == "rm":
        if name not in cfg.todo_labels:
            known = ", ".join(cfg.todo_labels) if cfg.todo_labels else "none"
            raise ShadError(f"label '{name}' is not configured; configured labels: {known}")
        usage = store.label_usage(store.todo_dir(cfg), name)
        if usage and not getattr(args, "force", False):
            raise ShadError(
                f"label '{name}' is still used by {usage} item(s)\n"
                f"       remove it from those items first, or pass --force"
            )
        write_value(path, "todo.labels", [label for label in cfg.todo_labels if label != name])
        console.print(Text("  ✓ ", style="bold green") + Text(f"removed label {name}"))
        return

    raise ShadError(f"unknown label action '{action}'; available: {', '.join(LABEL_ACTIONS)}")


def open_panel(directory: Path, labels: list[str]) -> None:
    # Imported here, not at module scope: textual costs roughly 100ms to
    # import, and `shad todo add` from a script must not pay it.
    from shad.todo.panel import run_panel

    run_panel(directory, labels)


# ── dispatch ──────────────────────────────────────────────────────────────


def cmd_todo(cfg: Config, args: argparse.Namespace, path: Path | None = None) -> None:
    action = getattr(args, "todo_action", None)
    if action is None:
        raise ShadError(f"no todo action given; available: {', '.join(ACTIONS)}")
    if action not in ACTIONS:
        raise ShadError(f"unknown todo action '{action}'; available: {', '.join(ACTIONS)}")

    if action == "label":
        _label(cfg, args, path or config_path())
        return

    directory = store.todo_dir(cfg)

    if action == "panel":
        open_panel(directory, cfg.todo_labels)
    elif action == "add":
        labels = list(args.label or [])
        if args.title is None:
            item = add_in_editor(directory, labels, cfg.todo_labels)
        else:
            item = store.add(directory, args.title, labels, cfg.todo_labels)
        _report_added(directory, item)
    elif action == "list":
        _list(cfg, directory, keys_only=getattr(args, "keys", False))
    elif action == "status":
        if args.status not in STATUSES:
            raise ShadError(
                f"unknown status '{args.status}'; must be one of: {', '.join(STATUSES)}"
            )
        _status(directory, args.key, args.status)
    elif action == "edit":
        _edit(cfg, directory, args.key)
    elif action == "rm":
        _remove(directory, args.key)
