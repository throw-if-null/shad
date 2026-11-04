# AGENTS.md

## Project overview

`shad` is a Python CLI tool that manages project-specific tmux sessions. It creates a tmux layout per project — opencode and bash, plus a git panel and a todo pane that are on by default and can each be turned off — and handles session lifecycle: open and status per project, and save, restore and stop across projects. Configuration lives in `~/.config/shad/shad.toml`; todo files live in `[todo] path`, or in the per-OS data directory when it is not set.

Entry point: `shad.cli:main` (registered as the `shad` console script).

## Coral

Load `CORAL-CONTRACT.md` before you change code. It holds every `[auto]` and `[review]` Coral
rule that applies to this project, plus the project's accepted exceptions and extensions. It is
generated. Do not edit it.

Load https://coral.appsandtools.work/guides/deciding-and-escalating before you change code. It is
the protocol for which decisions are yours, which you verify first, and which a human makes. It
defines no rule.

Load the behavioral verification protocol,
<https://coral.appsandtools.work/guides/behavioral-verification>, before you write or change a
test. It states how an acceptance criterion is written and how expected behavior changes. It
defines no rule.

Load the haddock `doc-maintenance` skill,
<https://raw.githubusercontent.com/throw-if-null/haddock/v0.5.0/skills/doc-maintenance/SKILL.md>,
before you change code or documentation. It is the procedure for code comments and
documentation. It defines no rule.

When you change code, follow the contract and the two protocols above where they differ from this
file, from your global instructions, or from the patterns in the existing code.

## Architecture

The codebase follows a **vertical slice** layout — each CLI subcommand owns its own package under `src/shad/`:

```
src/shad/
├── cli.py                      # arg parsing, dispatch, top-level error handling; main(argv) -> exit code
├── __main__.py                 # `python -m shad`
├── testing.py                  # test support: run() calls main in-process; TmuxCase, Pane drive an isolated tmux server
├── shared/                     # cross-cutting utilities
│   ├── config.py               # TOML config loading, Project/Defaults, target resolution, data dir
│   ├── errors.py               # ShadError exception
│   ├── editor.py               # resolve_editor(): $VISUAL, $EDITOR, then the first installed fallback
│   ├── render.py               # make_table() and relative_age() — shared presentation
│   ├── picker.py               # the arrow-key pickers: pure key loops, and the /dev/tty wrapper
│   ├── terminal.py             # the terminal shad runs in; opens kitty tabs through kitten @
│   └── tmux.py                 # low-level tmux subprocess wrappers
├── projects/
│   ├── open/                   # "shad projects <name>" — session picker + layout
│   │   ├── command.py          # open_project() orchestration
│   │   ├── sessions.py         # OC session picker (SQLite query + TUI)
│   │   ├── layout.py           # tmux layout creation: harness, bash, and the enabled panels
│   │   └── banner.py           # ASCII art banner
│   └── status/command.py       # "shad projects <name> status" — reads git via the git slice
├── config/                     # "shad config <action>": one package per action, crosscuts at the root
│   ├── schema.py               # settable key namespace and value validation
│   ├── toml_edit.py            # comment-preserving TOML text editor
│   ├── store.py                # the file as text: the raw reads, and the validated atomic write
│   ├── render.py               # how `show` and `get` print a value
│   ├── show/command.py         # "shad config show"
│   ├── path/command.py         # "shad config path"
│   ├── keys/command.py         # "shad config keys"; the completion script parses it
│   ├── get/command.py          # "shad config get": the file, else the value shad uses
│   ├── set/command.py          # "shad config set"
│   ├── unset/command.py        # "shad config unset"
│   ├── edit/command.py         # "shad config edit": $EDITOR, then validate
│   └── validate/command.py     # "shad config validate"
├── git/                        # "shad git sync" and "shad git panel"
│   ├── run.py                  # the git subprocess contract; no domain knowledge
│   ├── model.py                # dataclasses: one repository, and one sync run
│   ├── refs.py                 # queries: refs, worktrees, remotes, default branch
│   ├── discover.py             # configured path -> repository; per-worktree state
│   ├── plan.py                 # what is safe to delete (the safety boundary)
│   ├── apply.py                # the commands that change a repository
│   ├── report.py               # rich rendering for sync
│   ├── snapshot.py             # one read-only reading of a repository, for the panel
│   ├── panel.py                # the textual app "shad git panel" runs
│   └── command.py              # target resolution, parallel inspect, gate, apply
├── todo/                       # "shad todo <action>": one package per action, crosscuts at the root
│   ├── model.py                # Item, Status, the header format, slug keys; no I/O
│   ├── store.py                # the directory layout and every read and write
│   ├── render.py               # rich styling shared by `list` and the panel
│   ├── add/command.py          # "shad todo add"; add_in_editor, which the panel's `a` key also runs
│   ├── list/command.py         # "shad todo list"
│   ├── status/command.py       # "shad todo status"
│   ├── edit/command.py         # "shad todo edit"
│   ├── rm/command.py           # "shad todo rm"
│   ├── label/command.py        # "shad todo label add|rm|list": the vocabulary in shad.toml
│   └── panel/
│       ├── command.py          # "shad todo panel": the lazy import of the app
│       └── app.py              # the textual app
├── sessions/                   # "shad sessions <action>": one package per action, crosscuts at the root
│   ├── model.py                # Entry and Snapshot, and the JSON format; no I/O
│   ├── store.py                # the snapshot file in the data dir
│   ├── harness.py              # what each harness provides; Claude Code implemented, OpenCode not
│   ├── live.py                 # tmux and the harness records -> one Running per live session
│   ├── render.py               # the rows, the state column, the tables, and the picker frame
│   ├── pick.py                 # the multi-select picker over live sessions
│   ├── save/command.py         # "shad sessions save": the picker, then the snapshot write
│   ├── restore/
│   │   ├── plan.py             # entries -> steps; decides, never creates
│   │   └── command.py          # applies the steps, prints, opens the tabs, attaches
│   ├── stop/command.py         # "shad sessions stop": the picker, then kill-session
│   └── show/command.py         # "shad sessions show"
├── init/command.py             # "shad init" interactive wizard
├── cheat/command.py            # "shad cheat" tmux cheat sheet
└── completion/command.py       # "shad completion bash"
```

Key data flow for the main `open` command:
1. `cli.py` resolves project name (supports prefix matching)
2. `sessions.py` queries the opencode SQLite DB for recent sessions, shows a TUI picker
3. `command.py` resolves the tmux session name, creates or reattaches
4. `layout.py` builds the tmux layout: opencode, bash, and whichever of the git panel and the todo pane are enabled

## Conventions

- **Python 3.11+** with `from __future__ import annotations` in every module.
- **No external deps** beyond `rich` (printed output) and `textual` (the git panel, the one
  full-screen app). `textual` depends on `rich`; it does not replace it, and the commands that
  print and exit stay on `rich`. tmux interaction is via subprocess calls.
- Tests live **next to the code** they test (e.g. `command.py` + `test_command.py` in the same directory).
- Test framework: `unittest` (stdlib), run via `pytest`.
- Linting: `ruff check src/`
- Type checking: `mypy src/`
- All three checks run in CI and can be run locally via `make check`.

## Testing

```sh
make test       # pytest
make lint       # ruff
make typecheck  # mypy
make check      # all three
```

Tests use `unittest.TestCase` with `unittest.mock.patch` for isolating subprocess/IO calls. No conftest files. Shared test support is `src/shad/testing.py` and a slice's `testing.py`; no command imports either.

`shad.testing.run(argv, env=...)` calls `cli.main` in this process and returns the exit code, stdout and stderr. `shad.testing.TmuxCase` gives a test a tmux server on a private socket under `/tmp` (`-S` on its own calls, `TMUX_TMPDIR` for the processes it starts, `TMUX` unset, `-f /dev/null`), a temporary home, config and data directory, and `pane(*args)`, which runs `python -m shad` in a window of that server under a real pseudo-terminal: `send`, `type`, `wait_for`, `screen`, `wait_exit`. A command that drives tmux or needs a terminal is tested there, never against the user's server. The server itself runs in that environment, so the panes a shad layout creates inherit it, and a `shad` shim on `PATH` runs this checkout in them. `run_detached(*args)` runs shad as a process with no controlling terminal, which is how the no-terminal paths are tested. `shell_with_client()` opens a `shell` session with a real nested tmux client attached; a command typed into it with `type_into_shell` runs as a user runs it, and `wait_for_client_on` watches which session the client lands on, which is how attach and `switch-client` are tested. `fake_harness("claude")` puts a sleeping `claude` on `PATH` whose pane reports `claude` as its foreground command. CI installs tmux for this.

## Common pitfalls

- **tmux session naming**: bare project session name (e.g. `tin-shad`) is for new/default sessions. Scoped names use the pattern `<base>--<prefix>-<session-id>`, where the prefix is `oc` for opencode and `cc` for Claude Code. `shared/tmux.py` owns the table (`SESSION_PREFIXES`), builds the name (`project_session_name()`), and splits it again (`split_session_name()`); `shad sessions` depends on the round trip.
- **Picker returns**: `pick_opencode_target()` and `pick_claude_target()` return `None` for cancel, `OpencodeTarget(fresh=True)` for "New session", or `OpencodeTarget(session_key=...)` for an existing session. The `fresh` flag signals that any existing tmux session with the same name should be killed and recreated.
- **A picker must resolve a real session id**: the tmux session name is derived from `session_key`, so a picker that returns a constant key maps every resumed conversation onto one tmux session, and a second `shad projects <name>` attaches a second client to it. tmux mirrors one session across its clients, so both terminals then drive the same harness process. This is why `pick_claude_target()` reads `~/.claude/projects/<slug>/*.jsonl` itself and runs `claude --resume <id>` instead of handing the choice to `claude --resume`. A new Claude Code conversation gets a uuid shad chooses, passed as `claude --session-id <uuid>`, so its tmux name identifies the conversation too; the `fresh-<epoch>` key survives only for opencode, which has no such flag. Claude Code derives `<slug>` from the project path by replacing every character outside `[A-Za-z0-9]` with a hyphen. Each row shows the session's name, then its first prompt. The prompt is the first user entry that is neither `isMeta` nor a command wrapper; a transcript with no such entry is an empty session and is not offered. The name is the last `custom-title` entry (`/rename`), else the last `ai-title`. Claude Code appends both anywhere in the transcript, so `_claude_session_name` reads the whole file, and it matches the entry type as bytes before it parses a line, because a transcript can be tens of megabytes.
- **Inside vs outside tmux**: `_attach()` uses `switch-client` when already inside tmux, `attach-session` otherwise.
- **`shad sessions` reads Claude Code's process record, not the tmux name**: Claude Code 2.1 writes `~/.claude/sessions/<pid>.json` for each running process, with the current `sessionId`, the session's `name`, a `status` of busy or idle with `statusUpdatedAt`, and a `tmux` field of the form `<session>:@<window>.%<pane>`. `/clear` and `/resume` move a process to another conversation while the tmux name keeps the id the pane was opened with, so the record is the truth and the name is the fallback (only when its key is a uuid). A record whose pid is dead is ignored: a killed process leaves its file behind. The file is undocumented; `harness.py::_claude_process_record` is the one place that reads it. The first prompt comes from the transcript through `claude_session_title`, which reads only its first lines.
- **Harness support in `shad sessions` is a registry**: `sessions/harness.py::SUPPORTED` maps a harness name to an object with `live_conversation`, `can_resume`, `resume_command`, `fresh_command` and `new_session_id`. `live_conversation` returns a `Conversation` (id, and optional name, title, status, status age). Only Claude Code is registered. `save` lists a session of an unregistered harness with the reason and does not write it, `restore` skips its entries, and `stop` kills it like any other, because killing needs no harness. To add OpenCode, implement the same methods (the live id of a fresh session would come from the opencode SQLite DB, by project path and creation time) and register it; nothing else in the slice names a harness.
- **One package per action, with crosscuts at the slice root**: in `projects/`, `config/`, `sessions/` and `todo/`, each action is a package with its own `command.py` and tests, and `cli.py` dispatches to them (`cmd_projects`, `cmd_config`, `cmd_sessions`, `cmd_todo`). The modules at a slice's root are what several actions need and must not diverge on. For `sessions/`: the snapshot format and file (`model.py`, `store.py`), which harness holds which conversation (`harness.py`, `live.py`), how rows and states are drawn (`render.py`), and the picker over live rows (`pick.py`). For `todo/`: the item format (`model.py`), the files (`store.py`), and the styling `list` and the panel share (`render.py`). For `config/`: the raw reads and the validated write (`store.py`), and how `show` and `get` print a value (`render.py`); `edit` runs `validate` through its public name, as the todo panel runs `add_in_editor`. A new action is a new package; it reaches these through their public names and never another action's internals. Small duplication between actions, such as the five lines that run `$EDITOR` in `todo/add` and `todo/edit`, is left alone rather than extracted. Shared test fixtures live in the slice's `testing.py`, which no command imports.
- **The picker core is `shared/picker.py`**: `select_one` and `select_many` are pure loops over an iterator of keys with a draw callback, so their tests feed a scripted key sequence. `pick_one` and `pick_many` wrap them in /dev/tty. They raise `NoTerminal` instead of returning None when there is no terminal, so a caller can tell that apart from a cancel: the session picker in `projects/open` treats it as a cancel, `sessions save` turns it into an error that points at `--all`.
- **The picker uses cbreak mode and redraws by moving up, not raw mode and cursor save/restore**: `tty.setraw` also clears OPOST, so a newline is a bare line feed; a panel line that fills the pane then puts the next line at the wrap column and tmux moves it down a row, so every line costs two. `tty.setcbreak` keeps output processing. A saved cursor position (`ESC[s`) is a screen row, so once a frame scrolls the screen, restoring it draws the next frame below the old one. `_Terminal.draw` instead counts the frame's rows and emits `erase(rows)`: carriage return, cursor up that many rows, clear to end of screen. That only holds while the frame is shorter than the terminal, which is why `sessions/render.py::window` cuts the list to the terminal height with "N more" indicators.
- **`sessions stop` and the live state**: the session the command runs in is left out of the list, through `shared.tmux.current_session()` (`$TMUX`, then `display-message -p '#S'`), because killing it detaches the client mid-command. Whether a harness is still running is read from `pane_current_command` across every pane of the session, matched against the harness name, because the index of the harness pane depends on `oc_position`. `kill_session` passes `=<name>` so tmux never matches a prefix: `tin-shad` is a prefix of `tin-shad--cc-<uuid>`.
- **`sessions/restore/plan.py` decides, `restore/command.py` creates**: `plan()` classifies every entry as resume, new, running or skipped and runs no tmux write; the one write is `_create_session` in `restore/command.py`, for the steps that create. Keep it that way for the same reason `git/plan.py` is kept pure. A saved id with no transcript is kept: the harness starts the new conversation under it, so the tmux name is stable across restores.
- **"Running" is decided by conversation id, not by tmux name**: `plan()` takes what `live.collect` found and treats an entry as running when any live session holds its id. The name restore would create often does not exist while the conversation is live: the live session was opened as `fresh-<epoch>`, or its id was superseded by `/clear` or `/resume`. A `session_exists` check on the computed name alone would start a second `claude --resume` process on a live conversation. `session_exists` is the second check, for a name that exists without a readable record.
- **`restore` opens kitty tabs through `shared/terminal.py`**: `plan.tab_targets` picks every session that was attached at save except the one the current terminal takes, and leaves out any that has a client now, because tmux mirrors one session across its clients. `terminal.current()` is `KITTY_WINDOW_ID` plus `kitten` on PATH; `open_tab` runs `kitten @ launch --type=tab --keep-focus`. Without a socket (`listen_on` in kitty.conf), `kitten @` writes a DCS sequence to the tty and waits for the reply; inside tmux the reply never comes, and kitten ignores SIGTERM, so `open_tab` passes a timeout and lets `subprocess.run` kill it. `_open_tabs` stops at the first failure, or every tab would wait out the timeout, and prints the `tmux attach-session` command for each session without a tab.
- **`shad git sync` layering**: the slice is a DAG — `run` and `model` are leaves, `refs` reads, `discover` resolves, `plan` decides, `apply` mutates, `command` orchestrates. `plan.py` is the safety boundary: it runs no git mutations, it only classifies. Keep it that way — a deletion rule that can also delete is much harder to test.
- **`shad git sync` ordering**: two orderings in `git/command.py` are load-bearing. Fast-forward must run *before* branches are classified, or branches merged upstream are silently under-reported — and no test that fakes git output can catch it. Worktrees must be removed *before* branches are deleted, because `git branch -d` refuses a branch a worktree has checked out.
- **`shad git sync --switch`**: the only step in the command that writes to a working tree, which is why it is opt-in. It runs *after* the fast-forward (so the checkout lands on the new tip in one update) and *before* branches are classified (so the branch it leaves behind is no longer pinned and can be deleted in the same run). `fetch_and_plan` re-reads `worktree list` when a switch happens — HEAD moved, so the earlier read is stale. Every blocking condition skips with a reason; nothing stashes, discards, or detaches.
- **`shad git sync` gating**: fetch, prune, and fast-forward are applied immediately and are **not** undone when the user declines the prompt. Only deletions are gated. The report renders them in the past tense above the prompt for that reason.
- **Deleting a gone-upstream branch**: safe only when that upstream ref was pruned *in this run*, because pruning a ref deletes its reflog and its last-known OID with it. That OID is the proof the branch was fully pushed. This is why `--dry-run` fetches but never prunes, and why `plan.stale_upstreams()` has a separate dry-run path that asks the remote via `ls-remote` instead. Both of its paths filter on the `refs/remotes/<remote>/` prefix: the ref snapshots cover every remote, so without it a second remote's refs all read as stale.
- **`shad git panel` is read-only**: the only git write it performs is the fetch in `snapshot.collect`, and that fetch passes `prune=False` deliberately. Pruning a remote-tracking ref deletes its reflog and its last-known OID, which is the evidence `plan.stale_upstreams()` needs to prove a gone-upstream branch was fully pushed. A viewer that pruned would silently consume what the sync command depends on. `git/test_real_git.py::SnapshotTests::test_the_panel_fetch_does_not_prune` guards this.
- **`stash list` is not `for-each-ref`**: it belongs to the log pretty-format family, which does *not* interpret the `%00` escape the rest of the slice uses — it emits three literal characters. Use `LOG_SEP` (`%x00`) there and `FMT_SEP` (`%00`) everywhere else. `-z` then terminates each record with the same NUL that separates fields, so the output is one flat field stream and records are recovered by counting fields, not by splitting on a record separator. The date is `%ct`, not `%cr`, because the relative form is gettext-translated; `panel._age` formats the timestamp instead.
- **`run._is_read_only` special cases**: `worktree` and `stash` are both verbs whose `list` subcommand is a read while the rest mutate. A bare `args[0] in _READ_ONLY` would hand `GIT_OPTIONAL_LOCKS=0` to `stash drop`. Add new multi-verb commands the same way.
- **textual is imported lazily**: `git/command.py::open_panel` imports `shad.git.panel` inside the function, not at module scope. `textual.app` costs roughly 100ms to import and every `shad projects <name>` and `shad git sync` would otherwise pay it. Keep every `textual` import inside `panel.py`.
- **Panel tests**: `git/test_panel.py` uses stdlib `unittest.IsolatedAsyncioTestCase` with textual's `App.run_test()`, so the suite needs no `pytest-asyncio`. The logic worth testing lives in `snapshot.py`, which is synchronous — keep it that way and keep the panel a thin view, or the testable surface moves into the async layer.
- **Panel sizing**: the pane is about 17 rows by 40 to 50 columns at the default `panel_percent`/`todo_percent`, because in the default layout the git panel shares the todo column. That is why the header is one line rather than a table, the nav column is a fixed 16 (12-char label + 2 padding + 1 border, or the labels wrap), and the stash age is `5m` rather than `5 minutes ago`.
- **All git goes through `shad.git.run.git`**: `projects/status/command.py` used to shell out with `subprocess.run(..., cwd=path)`. That path inherits `GIT_DIR`, so `shad projects <name> status` reported whichever repository invoked shad — a git hook, or a tmux pane started by one — instead of the project, and it had no timeout. It now uses `discover.head_branch`, `discover.is_clean`, `refs.latest_tag` and `refs.recent_commits`. `_capture` survives only for the non-git version probes (`python3 --version` and friends); do not route git through it again. `projects/status/test_command.py` asserts no `["git"` literal remains in the module.
- **The status dirty count changed with that migration**: `is_clean(untracked=True)` counts every untracked file, where `status --short` collapsed an untracked directory into one entry. An untracked directory holding two files now reads as two, which is what the "file(s)" label claims.
- **git output parsing**: always use plumbing with explicit formats, and decide from exit codes. Git messages are gettext-translated, `fetch.output = compact` rewrites ref names, and `git branch` layout depends on terminal width. A real NUL byte cannot be passed in argv, so the separator is an escape git expands — and the spelling depends on the command family: ref-filter (`for-each-ref`, `branch`, `tag`) takes `%00` (`FMT_SEP`), the pretty-format family (`log`, `show`, `stash list`, `reflog`) takes `%x00` (`LOG_SEP`). Neither accepts the other's, and neither reports the mismatch — `run._check_format_dialect` raises on it instead.
- **Completion input**: the completion script parses `shad config keys`, not `shad projects`. The latter prints ●/◆ bullets for humans. The script is generated from a template in `completion/command.py` with the `config/schema.py` enum values interpolated, and is installed by *sourcing* `shad completion bash`, never by pasting its text into a startup file — a pasted copy silently keeps completing an older command surface. `completion/test_command.py` drives the script in a real bash process against a fixture config, so a new subcommand that the script does not know about fails the suite.
- **Project identity**: a project is a *directory plus a tmux session*, not a repository — projects need not be git repos at all. Two projects on the same directory are rejected by `_reject_duplicate_paths` in `shared/config.py`, which is safe to fail hard on because it is a property of the config text alone. Two projects on different directories that resolve to one repository (linked worktrees) are legal, and `git/command.py::_resolve` deduplicates them on `--git-common-dir` before any fetch runs. Do not conflate the two: two *clones* of one remote have different common dirs and different local branches, so both must be synced.
- **Config path resolution**: never hard-code `~/.config/shad/shad.toml`. Call `shared.config.config_path()`, which applies `$SHAD_CONFIG`, then the per-OS default from `default_config_dir()`, then an existing legacy `~/.config/shad` file. `cli.main()` passes a `--config` override down to `load()`, `cmd_config()` and `cmd_init()`; readers and writers must resolve identically or `shad init` will write to a file nothing reads. `default_config_dir()` branches on `sys.platform`, not `os.name`, because pathlib dispatches on `os.name` and a test that patched it could not construct a path at all.
- **Config writes**: the stdlib has no TOML writer and shad adds no dependencies, so `config/toml_edit.py` edits the file as text to keep comments. It handles scalar values and single-line arrays of scalars, and rejects multi-line values. Every write is parsed with `tomllib` and loaded with `shared.config.load()` in a temporary file first, then `os.replace`d into position. `config/store.py::write_value` is the entry point for a key outside the `set` schema; `shad todo label` uses it for the `[todo] labels` array.
- **Todo files are the source of truth**: `shad todo` keeps one file per item at `store.todo_dir(cfg)/<item key>.md` — a header block, a blank line, the body. `todo/model.py::parse` never raises: a hand edit that leaves an unknown status or label is surfaced by `problems()`, and a header shad does not define rides along in `Item.extra`. `serialize(parse(text))` must round-trip the body byte for byte, because a status change from the panel rewrites the file. `store.add` creates with `O_EXCL`, so two adds of one key cannot both win; every other write touches one file through a temp file and `os.replace`. There is no lock, and nothing may be added that reads one file to write another.
- **`shad todo add` without a title**: `todo/add/command.py::add_in_editor` writes `model.template()` to a file in the temporary directory, not the data directory, so the list and the panel never show an unfinished draft. The template's help lines start with `#`. `parse()` skips them only because `_HEADER` requires a header name to start with a letter, so do not loosen that pattern. A draft that `store.add` rejects is reopened on request and kept on decline. The command refuses to open an editor when stdin is not a terminal, because an editor reading a pipe blocks the caller.
- **The panel's `a` key and `App.suspend()`**: `todo/panel/app.py::action_add` calls `add_in_editor` inside `self.suspend()`, because the editor and the "Edit again?" prompt use the terminal. In textual 8.2, `suspend()` resumes the app only when its block exits normally. An exception that leaves the block leaves the panel suspended, and it stops reading keys. `action_add` therefore catches `ShadError`, `KeyboardInterrupt` and `EOFError` inside the block. `todo/panel/test_app.py` replaces `suspend` with a recorder that has the same behavior, and asserts that the app resumed.
- **Data dir is not config dir**: todo files resolve through `todo/store.py::todo_dir(cfg)`, which returns `[todo] path` when it is set and `shared.config.default_data_dir() / "todo"` otherwise (`$XDG_DATA_HOME/shad/todo` on Linux). The default never goes through `config_path()`: a config directory is often a dotfiles repository, and todo files must not be dragged into one by default. `[todo] path` must be absolute after `~` expansion; `shared.config.load()` rejects a relative path because it would resolve against each pane's cwd. Tests patch `shad.todo.store.default_data_dir`, set `XDG_DATA_HOME`, or set `Config.todo_path`.
- **`shad todo` has one list, not one per project**: no action reads cwd or takes a project, and the layout sends a bare `shad todo panel` to every project session, so every session shows the same files. `store._item_files` lists only the `.md` files directly in the todo dir; files in a subdirectory are not read.
- **The todo layouts address panes by id**: with `todo_panel` on, `layout.py::_layout_with_todo` captures `#{pane_id}` from each `split-window -P -F` and never uses `session:0.N`, because a fourth split makes every later index depend on the order of the earlier ones. The layouts without a todo pane still use `session:0.N`; when `git_panel` is off they skip the git split, which shifts the index of the harness pane under `bottom`.
- **Panel switches are TOML booleans**: `shared.config.load()` rejects a `git_panel` or `todo_panel` that is not `true` or `false`, because a quoted `"false"` is truthy. `todo_percent` is 1-99; `todo_panel = false` is the only way to turn the todo pane off.
- **textual is imported lazily, again**: `todo/panel/command.py::open_todo_panel` imports `shad.todo.panel.app` inside the function. `todo/panel/test_command.py` reads the module source and asserts the import is indented. Keep every `textual` import inside `todo/panel/app.py`.
- **A textual `App` subclass must not set `self._name`**: `DOMNode.__init__` owns that attribute and `App.name` reads it. mypy catches the collision only when the value type differs.
- **Todo panel polling**: the panel calls `store.signature()` once a second and reloads on any change — name, mtime, or size of any item file. `load()` is synchronous because the directory is tens of files; do not move it to a worker. The panel's tests call `app.poll()` directly rather than waiting out the interval.
- **Completion input for todo**: the script parses `shad todo list --keys` and `shad todo label list`, both one plain word per line. The keys call carries `--config` from the command line, so the keys come from the `[todo] path` of the config the command will read. `shad todo list` without `--keys` is a rich table for humans and is not safe to parse.
- **Pane sizes are `-l N%`, never `-p N`**: tmux 3.4 (Ubuntu 24.04) rejects `split-window -p` with "size missing", so `shad projects` could not build a layout there. `layout.py::_size` spells the size as `-l N%`, which every tmux since 3.1 accepts. The behavior tests run the layout on CI's tmux; the layout unit tests assert the spelling.
