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

### Managing config from the CLI

`shad config` reads and edits `~/.config/shad/shad.toml` without opening an editor.

| Command | Description |
|---|---|
| `shad config` / `shad config show` | Print a rendered summary of defaults and projects |
| `shad config show --raw` | Print the file contents as-is |
| `shad config path` | Print the config file path |
| `shad config keys` | Print every settable key, one per line |
| `shad config get <key>` | Print one value; a table is expanded into dotted lines |
| `shad config set <key> <value>` | Set one value |
| `shad config unset <key>` | Remove a key, or a whole project table |
| `shad config edit` | Open the file in `$EDITOR`, then validate it |
| `shad config validate` | Check that the file parses and loads |

`get` prints the effective value: a key that is absent from the file falls back to what `shad` actually uses (for example `defaults.oc_position` or a project's derived `session`). `show` marks which defaults are set in the file and which are built in.

Keys are dotted TOML paths:

```
defaults.oc_position          top | bottom | left
defaults.panel_percent        integer 1-99
defaults.split_percent        integer 1-99
defaults.harness              opencode | claude
projects.<key>.path           directory path
projects.<key>.session        string
projects.<key>.harness        opencode | claude
projects.<group>.<key>.path   directory path
```

Behaviour of `set` and `unset`:

- Values are validated against the field before they are written.
- Comments, ordering, and alignment in the file are preserved.
- `~` in path values is expanded.
- A new project table is created when the key does not exist yet. Set its `path` first.
- The result is parsed and loaded in a temporary file before it replaces the config, so a rejected edit never damages a working config.
- Unknown keys are rejected. `--force` writes them anyway.
- A path that does not exist is rejected. `--force` writes it anyway.
- `unset projects.<key>.path` is rejected because it would drop the project silently. Use `shad config unset projects.<key>` to remove the project, or `--force`.

```sh
shad config set defaults.oc_position left
shad config set projects.alvr.db.session alvr-db
shad config unset projects.alvr.db
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

# Git maintenance across projects
shad git sync                     # every configured project
shad git sync tin                 # every project in the tin group
shad git sync tin shad            # one project
shad git sync --dry-run           # preview; deletes nothing
shad git sync --yes               # skip the confirmation prompt

# Show a tmux cheat sheet popup
shad cheat

# Inspect and edit the config file
shad config
shad config path
shad config keys
shad config get defaults.harness
shad config set defaults.panel_percent 40
shad config set projects.kb.path ~/gh/kb
shad config unset projects.kb
shad config edit
```

## Git maintenance

`shad git sync` brings repositories up to date and clears out branches and
worktrees that are finished with. It runs over every configured project by
default, or over the projects you name.

| Command | Description |
|---|---|
| `shad git sync` | Sync every configured project |
| `shad git sync <name>` | Sync one top-level project, or a whole group |
| `shad git sync <group> <name>` | Sync one grouped project |
| `shad git sync --dry-run` | Report what would change; delete nothing |
| `shad git sync --yes` | Apply the deletions without the prompt |

Prefix matching works at each level, exactly as it does for `shad projects`.

### What it does

For each project, in order:

1. `git fetch --prune`.
2. Fast-forward the default branch. The branch is detected from
   `origin/HEAD`, falling back to asking the remote, then to `main`/`master`.
3. Delete local branches that are finished.
4. Prune worktree records whose directory is gone, and remove clean worktrees
   whose branch is being deleted.

Steps 1 and 2 are applied immediately. Steps 3 and 4 are listed first and ask
for one confirmation covering the whole run.

**Declining the prompt does not undo the fetch or the fast-forward.** Only the
deletions are gated.

### What it never does

A branch is deleted only when losing work is impossible — either its commits
are already on the default branch, or its upstream was deleted on the server
during this run after every commit had been pushed. That second rule is what
makes squash-merged pull request branches removable; `git branch -d` refuses
them, because by commit ancestry a squashed branch really is unmerged.

These are never deleted:

- The default branch.
- A branch checked out in a worktree that is staying.
- A branch with commits that are not on its upstream.
- A branch that never had an upstream.
- A branch whose upstream disappeared before this run, because whether its
  commits reached the server can no longer be proven.
- Anything at all in a shallow clone, where ancestry is truncated.

These worktrees are never touched:

- The main worktree.
- A locked worktree — its directory being absent is expected.
- A worktree with local changes, including untracked files.
- A worktree containing submodules, or one with a rebase or merge in progress.

Every deleted branch is reported with the commit it pointed at and the command
to restore it. Deleting a branch also deletes its reflog, so that line is the
recovery path until the next `git gc`.

A repository is skipped, with the reason, when it is not a git repository, is
bare, is a path inside a repository rather than its root, or has an operation
in progress. One project failing never stops the others.

`--dry-run` still fetches — that is how the report is accurate — but it does
not prune, so a preview never consumes the evidence the real run needs.

Requires git 2.36 or newer.

## Shell completion

`shad` supports tab completion for bash.

```sh
shad completion bash >> ~/.bashrc && source ~/.bashrc
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
├── AGENTS.md
├── Makefile
├── pyproject.toml
├── shad.example.toml
└── src/
    └── shad/
        ├── __init__.py
        ├── cli.py
        ├── cheat/
        │   └── command.py
        ├── completion/
        │   └── command.py
        ├── config/
        │   ├── command.py
        │   ├── schema.py
        │   └── toml_edit.py
        ├── git/
        │   ├── apply.py
        │   ├── command.py
        │   ├── discover.py
        │   ├── model.py
        │   ├── plan.py
        │   ├── refs.py
        │   ├── report.py
        │   └── run.py
        ├── init/
        │   └── command.py
        ├── projects/
        │   ├── open/
        │   │   ├── banner.py
        │   │   ├── command.py
        │   │   ├── layout.py
        │   │   └── sessions.py
        │   ├── status/
        │   │   └── command.py
        │   └── stop/
        │       └── command.py
        └── shared/
            ├── config.py
            ├── errors.py
            ├── render.py
            └── tmux.py
```
