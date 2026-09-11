# AGENTS.md

## Project overview

`shad` is a Python CLI tool that manages project-specific tmux sessions. It creates a 3-pane tmux layout (opencode, bash, gitui) per project and handles session lifecycle (open, status, stop). Configuration lives in `~/.config/shad/shad.toml`.

Entry point: `shad.cli:main` (registered as the `shad` console script).

## Architecture

The codebase follows a **vertical slice** layout — each CLI subcommand owns its own package under `src/shad/`:

```
src/shad/
├── cli.py                      # arg parsing, dispatch, top-level error handling
├── shared/                     # cross-cutting utilities
│   ├── config.py               # TOML config loading, Project/Defaults, target resolution
│   ├── errors.py               # ShadError exception
│   ├── render.py               # make_table() — the shared rich table style
│   └── tmux.py                 # low-level tmux subprocess wrappers
├── projects/
│   ├── open/                   # "shad projects <name>" — session picker + layout
│   │   ├── command.py          # open_project() orchestration
│   │   ├── sessions.py         # OC session picker (SQLite query + TUI)
│   │   ├── layout.py           # tmux 3-pane layout creation
│   │   └── banner.py           # ASCII art banner
│   ├── status/command.py       # "shad projects <name> status"
│   └── stop/command.py         # "shad projects <name> stop"
├── config/                     # "shad config" — inspect and edit shad.toml
│   ├── command.py              # action dispatch (show/path/keys/get/set/unset/edit/validate)
│   ├── schema.py               # settable key namespace and value validation
│   └── toml_edit.py            # comment-preserving TOML text editor
├── git/                        # "shad git sync" — fetch, prune branches and worktrees
│   ├── run.py                  # the git subprocess contract; no domain knowledge
│   ├── model.py                # dataclasses: one repository, and one sync run
│   ├── refs.py                 # queries: refs, worktrees, remotes, default branch
│   ├── discover.py             # configured path -> repository; per-worktree state
│   ├── plan.py                 # what is safe to delete (the safety boundary)
│   ├── apply.py                # the commands that change a repository
│   ├── report.py               # rich rendering
│   └── command.py              # target resolution, parallel inspect, gate, apply
├── init/command.py             # "shad init" interactive wizard
├── cheat/command.py            # "shad cheat" tmux cheat sheet
└── completion/command.py       # "shad completion bash"
```

Key data flow for the main `open` command:
1. `cli.py` resolves project name (supports prefix matching)
2. `sessions.py` queries the opencode SQLite DB for recent sessions, shows a TUI picker
3. `command.py` resolves the tmux session name, creates or reattaches
4. `layout.py` builds the 3-pane tmux layout with opencode, bash, and gitui

## Conventions

- **Python 3.11+** with `from __future__ import annotations` in every module.
- **No external deps** beyond `rich` (for TUI rendering). tmux interaction is via subprocess calls.
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
- **`shad git sync` gating**: fetch, prune, and fast-forward are applied immediately and are **not** undone when the user declines the prompt. Only deletions are gated. The report renders them in the past tense above the prompt for that reason.
- **Deleting a gone-upstream branch**: safe only when that upstream ref was pruned *in this run*, because pruning a ref deletes its reflog and its last-known OID with it. That OID is the proof the branch was fully pushed. This is why `--dry-run` fetches but never prunes, and why `_pruned_oids` has a separate dry-run path that asks the remote via `ls-remote` instead.
- **git output parsing**: always use plumbing with explicit formats, and decide from exit codes. Git messages are gettext-translated, `fetch.output = compact` rewrites ref names, and `git branch` layout depends on terminal width. `%00` in a `--format` is git's own separator escape — a real NUL byte cannot be passed in argv.
- **Completion input**: the completion scripts parse `shad config keys`, not `shad projects`. The latter prints ●/◆ bullets for humans.
- **Config writes**: the stdlib has no TOML writer and shad adds no dependencies, so `config/toml_edit.py` edits the file as text to keep comments. It handles scalar values only and rejects multi-line values. Every write is parsed with `tomllib` and loaded with `shared.config.load()` in a temporary file first, then `os.replace`d into position.
