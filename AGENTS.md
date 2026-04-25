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
│   ├── config.py               # TOML config loading, Project/Defaults dataclasses
│   ├── errors.py               # ShadError exception
│   └── tmux.py                 # low-level tmux subprocess wrappers
├── projects/
│   ├── open/                   # "shad projects <name>" — session picker + layout
│   │   ├── command.py          # open_project() orchestration
│   │   ├── sessions.py         # OC session picker (SQLite query + TUI)
│   │   ├── layout.py           # tmux 3-pane layout creation
│   │   └── banner.py           # ASCII art banner
│   ├── status/command.py       # "shad projects <name> status"
│   └── stop/command.py         # "shad projects <name> stop"
├── init/command.py             # "shad init" interactive wizard
├── cheat/command.py            # "shad cheat" tmux cheat sheet
└── completion/command.py       # "shad completion bash|zsh"
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
