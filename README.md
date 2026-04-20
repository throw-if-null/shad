# shad

A small CLI to attach or create project-specific tmux sessions from the current terminal.

- No new windows, no launchers — works inside your current terminal tab.
- Session is created with a standard 3-pane layout on first use; subsequent calls just attach.

## Requirements

- Python 3.11+
- tmux

## Install

### From GitHub (recommended for other machines)

Install directly from the GitHub repository — no cloning required:

```sh
pip install git+https://github.com/throw-if-null/shad.git
```

Or with `pipx` (keeps the CLI isolated in its own environment):

```sh
pipx install git+https://github.com/throw-if-null/shad.git
```

To install a specific version or commit:

```sh
pip install git+https://github.com/throw-if-null/shad.git@v0.1.0
pip install git+https://github.com/throw-if-null/shad.git@abc1234
```

### From a local clone

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

# Show a tmux cheat sheet popup
shad cheat
```

## tmux cheat sheet

`shad cheat` opens a floating tmux popup with a key-binding reference.
Dismiss it with `q`.

Add this line to `~/.tmux.conf` to trigger it with `prefix + F12`:

```
bind-key F12 run-shell "shad cheat"
```

Then reload your config (`prefix + r` if you have a reload binding, or):

```sh
tmux source-file ~/.tmux.conf
```

## tmux layout

Created once on first open, never rebuilt on subsequent attaches:

```
┌─────────────────────────────────┐
│  top pane  (top_command)        │  ~65% height
├─────────────────────┬───────────┤
│  bottom-left  (70%) │  gitui    │  ~35% height
└─────────────────────┴───────────┘
```

If `shad` is run from **inside** an existing tmux session it uses `switch-client`; outside tmux it uses `attach-session`.

### Navigating panes

- `Ctrl+b` `h/j/k/l` — move left/down/up/right (vim-style, if configured)
- `Ctrl+b` `o` — cycle through panes
- `Ctrl+b` `q` — show pane numbers, press number to jump

## Dependencies

### gitui

The bottom-right pane runs [gitui](https://github.com/gitui-org/gitui). Install the binary:

```sh
mkdir -p ~/.local/bin
curl -sL https://github.com/gitui-org/gitui/releases/download/v0.28.1/gitui-linux-x86_64.tar.gz \
  | tar -xz -C ~/.local/bin
```

Make sure `~/.local/bin` is on your `$PATH`.

### gitui theme (optional)

To match the catppuccin frappe color scheme used in tmux:

```sh
mkdir -p ~/.config/gitui
curl -sL https://raw.githubusercontent.com/catppuccin/gitui/main/themes/catppuccin-frappe.ron \
  -o ~/.config/gitui/theme.ron
```

Other available flavors: `catppuccin-latte`, `catppuccin-macchiato`, `catppuccin-mocha`.

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
