# shad

A small CLI to attach or create project-specific tmux sessions from the current terminal.

- No new windows, no launchers — works inside your current terminal tab.
- Session is created with a configurable 3-pane layout on first use; subsequent calls just attach.

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

Config is read from `~/.config/shad/shad.toml`.

### First time setup

Run the interactive wizard:

```sh
shad init
```

On Fedora you can also ask `shad` to install missing runtime dependencies first:

```sh
sudo shad init --install-deps
```

It will prompt for a project path, key, and optional group, then create `~/.config/shad/shad.toml` with a commented `[defaults]` block and your first project entry. Uncomment and adjust the defaults if you want a different layout.

To add more projects later, run `shad init` again.

### Manual setup

If you prefer to edit the file directly, create it and use the annotated example below as your reference:

```sh
mkdir -p ~/.config/shad
touch ~/.config/shad/shad.toml
```

### Full annotated example

```toml
# ~/.config/shad/shad.toml

[defaults]
# Which side opencode occupies. The git+bash bundle takes the opposite side.
# Allowed values: top | bottom | left
# oc_position = "top"

# How much of the window the git+bash bundle takes (%).
# The opencode panel gets the remaining space.
# panel_percent = 35

# How much of the bundle gitui takes (%). Bash gets the rest.
# When bundle is horizontal (oc_position top/bottom): gitui is on the right.
# When bundle is vertical   (oc_position left):       gitui is on the bottom.
# split_percent = 35


# ── Top-level projects ────────────────────────────────────────────────
# Accessed with:  shad projects <key>

[projects.kb]
path    = "/home/user/gh/kb"       # required — absolute path to the project root
# session = "kb"                   # optional — tmux session name; defaults to the key ("kb")

[projects.orfe]
path    = "/home/user/gh/tin/orfe"


# ── Grouped projects ──────────────────────────────────────────────────
# Accessed with:  shad projects <group> <key>
# Maximum depth: one group level (group → project).

[projects.alvr.db]
path    = "/home/user/gh/alvr/db"
# session = "alvr-db"              # optional; defaults to "<group>-<key>" ("alvr-db")

[projects.alvr.portal]
path    = "/home/user/gh/alvr/portal"
```

### Field reference

| Field | Required | Default | Description |
|---|---|---|---|
| `[defaults] oc_position` | no | `"top"` | Side opencode occupies: `top`, `bottom`, or `left` |
| `[defaults] panel_percent` | no | `35` | % of the window the git+bash bundle takes |
| `[defaults] split_percent` | no | `35` | % of the bundle that gitui takes (bash gets the rest) |
| `path` | **yes** | — | Absolute path to the project root |
| `session` | no | key or `<group>-<key>` | tmux session name; must be unique across all projects |

### How session names are resolved

- Top-level project `[projects.kb]` → session `kb`
- Grouped project `[projects.alvr.db]` → session `alvr-db`
- Override either by setting `session = "my-name"` explicitly.
- If you reopen the same project and choose an existing OpenCode session, `shad` uses a scoped tmux session name like `alvr-db--oc-<session-id>` so multiple OpenCode sessions can stay open side by side.

## Usage

```
shad --help

# Add a new project interactively (creates config if missing)
shad init

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

# Show session status without opening
shad projects kb status
shad projects alvr db status

# Kill a project's tmux sessions
shad projects kb stop
shad projects alvr db stop

# Show a tmux cheat sheet popup
shad cheat
```

## Shell completion

`shad` supports tab completion for bash and zsh.

### bash

```sh
shad completion bash >> ~/.bashrc && source ~/.bashrc
```

### zsh

```sh
shad completion zsh >> ~/.zshrc && source ~/.zshrc
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

Created once per tmux session on first open, never rebuilt on subsequent attaches. The layout depends on `oc_position`:

**`oc_position = "top"` (default)**
```
┌─────────────────────────────────┐
│  opencode                       │  ~65% height
├─────────────────────┬───────────┤
│  bash         (~65%)│  gitui    │  ~35% height
└─────────────────────┴───────────┘
```

**`oc_position = "bottom"`**
```
┌─────────────────────┬───────────┐
│  bash         (~65%)│  gitui    │  ~65% height
├─────────────────────┴───────────┤
│  opencode                       │  ~35% height
└─────────────────────────────────┘
```

**`oc_position = "left"`**
```
┌──────────┬──────────────────────┐
│          │  bash                │  ~65% of bundle height
│opencode  ├──────────────────────┤
│          │  gitui               │  ~35% of bundle height
└──────────┴──────────────────────┘
```

`panel_percent` controls how much of the window the git+bash bundle takes; `split_percent` controls the gitui/bash split within it.

If `shad` is run from **inside** an existing tmux session it uses `switch-client`; outside tmux it uses `attach-session`.

`shad projects <name> status` lists all tmux sessions that belong to the configured project session name, including scoped sessions created for specific OpenCode session ids. `shad projects <name> stop` stops all of them.

### Navigating panes

- `Ctrl+b` `h/j/k/l` — move left/down/up/right (vim-style, if configured)
- `Ctrl+b` `o` — cycle through panes
- `Ctrl+b` `q` — show pane numbers, press number to jump

## Dependencies

### Fedora bootstrap

`shad init --install-deps` is tailored for Fedora and installs missing dependencies before starting the init wizard.

- `tmux` via `dnf`
- `gitui` via `dnf`
- `opencode` by downloading the latest Linux x64 release into `/usr/local/bin/opencode`

Run it with `sudo`:

```sh
sudo shad init --install-deps
```

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
        ├── banner.py
        ├── cheat.py
        ├── cli.py
        ├── completion.py
        ├── config.py
        ├── init.py
        ├── sessions.py
        ├── status.py
        └── tmux.py
```
