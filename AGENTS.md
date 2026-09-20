# AGENTS.md

## Project overview

`shad` is a Python CLI tool that manages project-specific tmux sessions. It creates a 3-pane tmux layout (opencode, bash, git panel) per project and handles session lifecycle (open, status, stop). Configuration lives in `~/.config/shad/shad.toml`.

Entry point: `shad.cli:main` (registered as the `shad` console script).

## Architecture

The codebase follows a **vertical slice** layout — each CLI subcommand owns its own package under `src/shad/`:

```
src/shad/
├── cli.py                      # arg parsing, dispatch, top-level error handling
├── shared/                     # cross-cutting utilities
│   ├── config.py               # TOML config loading, Project/Defaults, target resolution
│   ├── errors.py               # ShadError exception
│   ├── render.py               # make_table() and relative_age() — shared presentation
│   └── tmux.py                 # low-level tmux subprocess wrappers
├── projects/
│   ├── open/                   # "shad projects <name>" — session picker + layout
│   │   ├── command.py          # open_project() orchestration
│   │   ├── sessions.py         # OC session picker (SQLite query + TUI)
│   │   ├── layout.py           # tmux 3-pane layout creation
│   │   └── banner.py           # ASCII art banner
│   ├── status/command.py       # "shad projects <name> status" — reads git via the git slice
│   └── stop/command.py         # "shad projects <name> stop"
├── config/                     # "shad config" — inspect and edit shad.toml
│   ├── command.py              # action dispatch (show/path/keys/get/set/unset/edit/validate)
│   ├── schema.py               # settable key namespace and value validation
│   └── toml_edit.py            # comment-preserving TOML text editor
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
├── init/command.py             # "shad init" interactive wizard
├── cheat/command.py            # "shad cheat" tmux cheat sheet
└── completion/command.py       # "shad completion bash"
```

Key data flow for the main `open` command:
1. `cli.py` resolves project name (supports prefix matching)
2. `sessions.py` queries the opencode SQLite DB for recent sessions, shows a TUI picker
3. `command.py` resolves the tmux session name, creates or reattaches
4. `layout.py` builds the 3-pane tmux layout with opencode, bash, and the git panel

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

Tests use `unittest.TestCase` with `unittest.mock.patch` for isolating subprocess/IO calls. No fixtures or conftest files — each test file is self-contained.

## Common pitfalls

- **tmux session naming**: bare project session name (e.g. `tin-shad`) is for new/default sessions. Scoped names use the pattern `<base>--oc-<session-id>` for existing opencode sessions. The `project_session_name()` function in `shared/tmux.py` handles this.
- **Picker returns**: `pick_opencode_target()` returns `None` for cancel, `OpencodeTarget(fresh=True)` for "New session", or `OpencodeTarget(session_key=...)` for an existing session. The `fresh` flag signals that any existing tmux session with the same name should be killed and recreated.
- **Inside vs outside tmux**: `_attach()` uses `switch-client` when already inside tmux, `attach-session` otherwise.
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
- **Panel sizing**: the pane is about 70x17 at the default `panel_percent`/`split_percent`. That is why the header is one line rather than a table, the nav column is a fixed 16 (12-char label + 2 padding + 1 border, or the labels wrap), and the stash age is `5m` rather than `5 minutes ago`.
- **All git goes through `shad.git.run.git`**: `projects/status/command.py` used to shell out with `subprocess.run(..., cwd=path)`. That path inherits `GIT_DIR`, so `shad projects <name> status` reported whichever repository invoked shad — a git hook, or a tmux pane started by one — instead of the project, and it had no timeout. It now uses `discover.head_branch`, `discover.is_clean`, `refs.latest_tag` and `refs.recent_commits`. `_capture` survives only for the non-git version probes (`python3 --version` and friends); do not route git through it again. `projects/status/test_command.py` asserts no `["git"` literal remains in the module.
- **The status dirty count changed with that migration**: `is_clean(untracked=True)` counts every untracked file, where `status --short` collapsed an untracked directory into one entry. An untracked directory holding two files now reads as two, which is what the "file(s)" label claims.
- **git output parsing**: always use plumbing with explicit formats, and decide from exit codes. Git messages are gettext-translated, `fetch.output = compact` rewrites ref names, and `git branch` layout depends on terminal width. A real NUL byte cannot be passed in argv, so the separator is an escape git expands — and the spelling depends on the command family: ref-filter (`for-each-ref`, `branch`, `tag`) takes `%00` (`FMT_SEP`), the pretty-format family (`log`, `show`, `stash list`, `reflog`) takes `%x00` (`LOG_SEP`). Neither accepts the other's, and neither reports the mismatch — `run._check_format_dialect` raises on it instead.
- **Completion input**: the completion script parses `shad config keys`, not `shad projects`. The latter prints ●/◆ bullets for humans. The script is generated from a template in `completion/command.py` with the `config/schema.py` enum values interpolated, and is installed by *sourcing* `shad completion bash`, never by pasting its text into a startup file — a pasted copy silently keeps completing an older command surface. `completion/test_command.py` drives the script in a real bash process against a fixture config, so a new subcommand that the script does not know about fails the suite.
- **Project identity**: a project is a *directory plus a tmux session*, not a repository — projects need not be git repos at all. Two projects on the same directory are rejected by `_reject_duplicate_paths` in `shared/config.py`, which is safe to fail hard on because it is a property of the config text alone. Two projects on different directories that resolve to one repository (linked worktrees) are legal, and `git/command.py::_resolve` deduplicates them on `--git-common-dir` before any fetch runs. Do not conflate the two: two *clones* of one remote have different common dirs and different local branches, so both must be synced.
- **Config path resolution**: never hard-code `~/.config/shad/shad.toml`. Call `shared.config.config_path()`, which applies `$SHAD_CONFIG`, then the per-OS default from `default_config_dir()`, then an existing legacy `~/.config/shad` file. `cli.main()` passes a `--config` override down to `load()`, `cmd_config()` and `cmd_init()`; readers and writers must resolve identically or `shad init` will write to a file nothing reads. `default_config_dir()` branches on `sys.platform`, not `os.name`, because pathlib dispatches on `os.name` and a test that patched it could not construct a path at all.
- **Config writes**: the stdlib has no TOML writer and shad adds no dependencies, so `config/toml_edit.py` edits the file as text to keep comments. It handles scalar values only and rejects multi-line values. Every write is parsed with `tomllib` and loaded with `shared.config.load()` in a temporary file first, then `os.replace`d into position.
