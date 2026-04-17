# shad

A small CLI to attach or create project-specific tmux sessions from the current terminal.

- No new windows, no launchers — works inside your current terminal tab.
- Session is created with a standard 3-pane layout on first use; subsequent calls just attach.

## Requirements

- Python 3.11+
- tmux

## Install

```sh
pip install -e /path/to/shad
```

Or, if you cloned to `~/gh/tin/shad`:

```sh
pip install -e ~/gh/tin/shad
```

`pip install -e` in a user environment (or inside a venv) is sufficient — no build step needed.

## Config

Copy the example config and edit it:

```sh
mkdir -p ~/.config/shad
cp shad.example.toml ~/.config/shad/shad.toml
```

Config path: `~/.config/shad/shad.toml`

### Schema

```toml
[defaults]
top_command    = "opencode -c"
bottom_percent = 35   # bottom area height as % of window
right_percent  = 30   # right pane width as % of bottom strip

# Top-level project
[projects.kb]
path = "/home/user/gh/kb"
# session = "kb"   ← optional; defaults to project key

# Grouped project  →  shad projects alvr db
[projects.alvr.db]
path = "/home/user/gh/alvr/db"
# session = "alvr-db"  ← optional; defaults to "<group>-<key>"
```

- `path` is **required** for every project.
- `session` is optional; defaults to the project key (top-level) or `<group>-<key>` (grouped).
- Maximum two levels: `[projects.<group>.<key>]`.

## Usage

```
shad --help

# List all configured projects and groups
shad projects

# Open a top-level project (exact or prefix match)
shad projects kb
shad projects k         # prefix: resolves to kb if unambiguous

# List sub-projects in a group
shad projects alvr

# Open a grouped project
shad projects alvr db
shad projects al d      # prefix matching per level
```

## tmux layout

Created once on first open, never rebuilt on subsequent attaches:

```
┌─────────────────────────────────┐
│  top pane  (top_command)        │  ~65% height
├─────────────────────┬───────────┤
│  bottom-left  (70%) │ right 30% │  ~35% height
└─────────────────────┴───────────┘
```

If `shad` is run from **inside** an existing tmux session it uses `switch-client`; outside tmux it uses `attach-session`.

## Project structure

```
shad/
├── README.md
├── pyproject.toml
├── shad.example.toml
└── src/
    └── shad/
        ├── __init__.py
        ├── cli.py
        ├── config.py
        └── tmux.py
```
