# shad

A small CLI to attach or create project-specific tmux sessions from the current terminal.

- No new windows, no launchers — works inside your current terminal tab.
- Session is created with a configurable layout on first use (harness, bash, git panel, todo panel); subsequent calls just attach.

## Requirements

- Python 3.11+
- tmux
- git 2.36+ (for `shad git sync` and `shad git panel`)

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

### Where the config lives

Every command resolves the config file the same way. Highest precedence first:

| Source | Notes |
|---|---|
| `--config PATH` | Must come before the subcommand: `shad --config ./scratch.toml git sync` |
| `$SHAD_CONFIG` | A full path to a file. `~` is expanded. |
| The per-OS default | See below |

The per-OS default:

| OS | Path |
|---|---|
| Linux, BSD | `$XDG_CONFIG_HOME/shad/shad.toml`, or `~/.config/shad/shad.toml` |
| macOS | `~/Library/Application Support/shad/shad.toml` |
| Windows | `%APPDATA%\shad\shad.toml` |

`XDG_CONFIG_HOME` is used only when it is an absolute path, as the XDG spec
requires.

If the per-OS default does not exist but `~/.config/shad/shad.toml` does, that
file is used instead. This only ever applies on macOS and Windows, and keeps an
existing config from being shadowed when the default moved. A fresh install
always writes to the per-OS default.

Run `shad config path` to print the file the current environment resolves to.

### Rules

Two projects must not name the same directory. Paths are compared after
expanding `~` and resolving symlinks and `..`, so the collision cannot be
hidden by spelling the path differently. `shad config set` and `shad init`
validate the result before writing, so the file can never be left in that
state.

Two projects on *different* directories that happen to be one repository —
worktrees — are legal. See
[One repository, two projects](#one-repository-two-projects).

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

`shad config` reads and edits the resolved config file without opening an editor.

| Command | Description |
|---|---|
| `shad config` / `shad config show` | Print a rendered summary of defaults and projects |
| `shad config show --raw` | Print the file contents as-is |
| `shad config path` | Print the resolved config file path |
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
defaults.git_panel            true | false
defaults.todo_panel           true | false
defaults.todo_percent         integer 1-99
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

# How much of the bundle the git panel takes (%). Bash gets the rest.
# When bundle is horizontal (oc_position top/bottom): the panel is on the right.
# When bundle is vertical   (oc_position left):       the panel is on the bottom.
# split_percent = 20

# Set to false to leave out the git panel or the todo pane.
# git_panel = true
# todo_panel = true

# How much of the window width the todo column takes (%). The todo column runs
# down the right edge. With oc_position top or bottom, the git panel sits under
# the todo pane in that column, and split_percent is ignored.
# todo_percent = 20

# The labels `shad todo add --label` accepts. Managed by `shad todo label`.
# [todo]
# labels = ["chore", "documentation", "investigation", "poc"]
# The directory that holds the todo files. Omit to use the per-OS data dir.
# path = "~/notes/todo"


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
| `[defaults] split_percent` | no | `20` | % of the bundle that the git panel takes (bash gets the rest) |
| `[defaults] git_panel` | no | `true` | `false` leaves the git panel out of new sessions |
| `[defaults] todo_panel` | no | `true` | `false` leaves the todo pane out of new sessions |
| `[defaults] todo_percent` | no | `20` | % of the window width the todo column takes. With `oc_position` `top` or `bottom` the git panel shares that column, so `split_percent` is ignored |
| `[todo] labels` | no | `[]` | The labels `shad todo add --label` accepts; managed by `shad todo label` |
| `[todo] path` | no | `<data dir>/todo` | Directory that holds the todo files. Absolute, or starts with `~`. See [Files](#files) |
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

# Open with a different harness, just this once
shad projects kb --harness claude
shad projects alvr db --harness opencode

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
shad git sync --switch            # also check out the default branch
shad git sync --dry-run           # preview; deletes nothing
shad git sync --yes               # skip the confirmation prompt

# Read-only repository view (the git pane runs this)
shad git panel                    # the repository in the current directory
shad git panel tin shad           # a configured project
shad git panel --no-fetch         # skip the fetch on open

# The todo list: one list, not tied to a project
shad todo add                     # write the item in $EDITOR from a template
shad todo add "Fix panel resize" --label chore
shad todo list                    # --keys prints just the keys
shad todo status fix in-progress  # keys accept a unique prefix
shad todo edit fix                # open the item in $EDITOR
shad todo rm fix
shad todo label add investigation # the label vocabulary lives in shad.toml
shad todo panel                   # the todo pane runs this

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
| `shad git sync --switch` | Also check out the default branch in each project |
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

### Checking out the default branch

By default `shad git sync` never touches a working tree. It advances the
default branch ref underneath you; if you are on `feat/x`, you stay on
`feat/x`.

Pass `--switch` to also check out the default branch in each project's main
worktree. It runs after the fast-forward, so the checkout lands directly on
the new tip.

A project is skipped, with the reason, when it cannot be switched safely:

- The working tree has uncommitted changes. Nothing is stashed or discarded.
- `HEAD` is detached.
- The default branch is checked out in another worktree.
- There is no local copy of the default branch. It is never created.

Switching also **un-pins the branch it leaves behind**. A branch is normally
kept because the main worktree has it checked out; once you are on the default
branch, that branch is a deletion candidate like any other, and can be removed
in the same run if it qualifies. It still appears in the confirmation table
first, and the deletion rules do not change.

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
- A branch checked out in a worktree that is staying. With `--switch`, the
  branch you were on stops counting as checked out.
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

### One repository, two projects

Two configured projects can be one repository — a linked worktree shares its
ref store, object store and branch list with the main worktree:

```toml
[projects.myproj]
path = "~/src/myproj"          # main worktree

[projects.login]
path = "~/src/myproj-login"    # git worktree add, on feat/login
```

Both are valid projects and both get their own tmux session. `shad git sync`
syncs the repository once and reports the other:

```
  ● login  same repository as myproj
```

Identity is `git rev-parse --git-common-dir`, so two *clones* of the same
remote are correctly treated as two repositories and both are synced — they
have separate local branches. The project configured at the repository root is
preferred over one configured at a linked worktree.

Two projects pointing at the *same directory* are a config error, rejected at
load time by every command.

`--dry-run` still fetches — that is how the report is accurate — but it does
not prune, so a preview never consumes the evidence the real run needs.

Requires git 2.36 or newer.

## Git panel

`shad git panel` is a read-only view of one repository. It is what shad runs in
the git pane of every project session, unless `git_panel = false`.

```
 main  ·  ↓2  ·  shad  ·  git 2.55.0
 branches   5  │ branch                            upstream
 worktrees  1  │   chore/dependabot                origin
 stashes    0  │ ● main                         =  origin
```

| Command | Description |
|---|---|
| `shad git panel` | The repository in the current directory |
| `shad git panel <name>` | A configured top-level project |
| `shad git panel <group> <name>` | A configured grouped project |
| `shad git panel --no-fetch` | Skip the fetch on open; show local state only |

Unlike `sync`, no name means the current directory rather than every configured
project, because the panel shows one repository. A name matching more than one
project is an error.

The header carries the active branch, how far it is ahead of and behind its
upstream, the repository name, and the git version — in that order, because a
narrow pane truncates the tail and the branch matters most. A branch with no upstream says so rather
than reporting itself up to date.

Three sections sit behind the left nav:

- **branches** — name, tracking symbol (`=` `↑` `↓` `↕`), and upstream. A `●`
  marks a branch some worktree has checked out. An upstream with the same name
  as its branch shows just the remote.
- **worktrees** — directory, branch, and any locked, prunable or bare flag.
- **stashes** — ref, the branch it was made on, message, and age.

| Key | Action |
|---|---|
| `↑` `↓` or `k` `j` | Move the row cursor |
| `tab` | Move focus between the section list and the table |
| `r` | Fetch and reload |
| `q` | Quit |

The panel fetches on open so the counts are accurate, and the fetch runs off the
UI thread — the sections appear immediately and fill in when it returns. A fetch
that fails is reported in the header and the local sections still populate, so
the panel is usable offline.

Nothing in the panel changes the repository. The fetch never passes `--prune`:
pruning a remote-tracking ref takes its reflog with it, and `shad git sync`
needs those last-known OIDs to prove a gone-upstream branch was fully pushed.

## Todo panel

`shad todo` keeps one small todo list that is not tied to a project: one text
file per item, meant to be edited by hand as much as through the CLI. The
panel runs in the todo pane of every project session, unless
`todo_panel = false`, and every session shows the same list.

```
 todo  ·  2 open  ·  1 done
 ◐ Fix panel resize            chore
 ○ Write docs                  documentation
 ● Bump textual                chore
 ──────────────────────────────────────────
 Fix panel resize
 in-progress  chore
 created 2026-10-07T10:12:00+02:00  ·  updated 3h

 The resize handler fires twice on tmux zoom.
```

### Files

```
<todo dir>/<item key>.md
```

The todo dir is `[todo] path` when it is set:

```sh
shad config set todo.path ~/notes/todo   # the directory must exist; --force skips the check
shad config get todo.path                # prints the todo dir in use, set or default
```

Without `[todo] path`, the todo dir is `~/.local/share/shad/todo`. That
directory follows `$XDG_DATA_HOME` on Linux (`~/Library/Application
Support/shad/todo` on macOS, `%LOCALAPPDATA%\shad\todo` on Windows). The default
is kept apart from the config directory so a dotfiles repository does not pick
the files up.

shad reads only the `.md` files directly in the todo dir, not files in its
subdirectories. shad does not move existing files when the todo dir changes.
Move them with `mv`.

Each item is a header block, a blank line, and the body:

```
title: Fix panel resize
status: in-progress
labels: chore, investigation
created: 2026-10-07T10:12:00+02:00

Free text. Markdown is fine; the panel shows it as text.
```

The file name is the item key: a slug of the title, at most 40 characters. The
CLI accepts any unique prefix of a key. A status change rewrites the headers
and copies the body byte for byte. A header shad does not know is kept. A hand
edit that leaves an unknown status or label is reported in the panel header
and in `shad todo list`, never fatal.

### Commands

| Command | Description |
|---|---|
| `shad todo add [--label L ...]` | Create the item from a template opened in the editor |
| `shad todo add "title" [--label L ...]` | Create the item; prints its key and path |
| `shad todo list [--keys]` | Print the items, or just their keys one per line |
| `shad todo status <key> <status>` | `todo`, `in-progress`, `done`, or `wont-do` |
| `shad todo edit <key>` | Open the file in `$VISUAL`, `$EDITOR`, or the first editor found |
| `shad todo rm <key>` | Delete the file |
| `shad todo label add\|rm\|list [name]` | Manage `[todo] labels` in `shad.toml` |
| `shad todo panel` | The pane |

Every command acts on the same list from any directory, so an agent in the
harness pane can use the same commands.

`add` without a title opens a template in `$VISUAL`, `$EDITOR`, or the first
editor found. The template is the item file format with an empty title. `--label`
fills in the `labels` header. Lines that start with `#` above the first blank
line are help, and shad does not write them to the item. To cancel, save the
template with an empty title and an empty body. When shad cannot create the item
from the saved text, it shows the error and asks to open the editor again. If you
decline, shad keeps the draft in the temporary directory and prints its path.
`add` with a title does not open an editor, so a script or an agent can add an
item without a terminal.

`label rm` refuses while an item still carries the label, and says which
projects do; `--force` removes it anyway and the items then show the label in
red.

### Keys

| Key | Action |
|---|---|
| `↑` `↓` or `k` `j` | Move the row cursor; the detail follows |
| `1` `2` `3` `4` | Set the status: todo, in-progress, done, wont-do |
| `a` | Add an item in the editor, as `shad todo add` without a title does. The cursor moves to the new item |
| `d` then `y` | Delete the item (`n` or `esc` cancels) |
| `e` | Open the item in `$EDITOR`; the panel reloads on return |
| `r` | Reload |
| `q` | Quit |

Rows sort in-progress first, then todo, done, and wont-do. In-progress rows are
bold yellow, done rows dim green, and wont-do rows struck through. Label
colours follow the label's position in `[todo] labels`.

The panel polls the directory once a second, so an item added from the CLI, or
a file saved in another pane, appears without a keypress. Nothing in the panel
touches a file other than the one item a key acts on.

## Shell completion

`shad` supports tab completion for bash.

```sh
echo 'source <(shad completion bash)' >> ~/.bashrc && source ~/.bashrc
```

Source the script; do not append its text to a startup file. A pasted copy is
a snapshot. It keeps offering the command surface that existed when it was
written, so after an upgrade it offers removed options and hides new
subcommands. Sourcing regenerates it from the installed `shad` on every shell
start.

Completion covers subcommands, project and group names, actions, config keys,
and config values. It reads project names from `shad config keys`, honouring
`--config PATH` when that option precedes the subcommand.

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

Created once per tmux session on first open, never rebuilt on subsequent attaches. `git_panel` and `todo_panel` choose the panes; `oc_position` chooses where the harness sits.

**Defaults: both panels on, `oc_position = "top"`**
```
┌─────────────────────┬───────────┐
│  opencode           │ todo      │  100 - panel_percent
├─────────────────────┼───────────┤
│  bash               │ git panel │  panel_percent
└─────────────────────┴───────────┘
   100 - todo_percent  todo_percent
```

The todo column runs down the right edge: the harness over bash on the left,
the todo panel over the git panel on the right, with the columns aligned.
`bottom` mirrors it vertically. `split_percent` is ignored, because the git
panel's width is the column's.

**Both panels on, `oc_position = "left"`**
```
┌──────────┬────────────┬─────────┐
│          │  bash      │         │
│opencode  ├────────────┤ todo    │
│          │  git panel │         │  split_percent of the bundle
└──────────┴────────────┴─────────┘
```

The bundle takes `panel_percent` of the width left of the todo column.

With `git_panel = false`, the todo pane fills the todo column (`top`, `bottom`)
and bash fills the bundle (`left`).

**`todo_panel = false`, `oc_position = "top"`**
```
┌─────────────────────────────────┐
│  opencode                       │  ~65% height
├─────────────────────┬───────────┤
│  bash         (~80%)│ git panel │  ~35% height
└─────────────────────┴───────────┘
```

**`todo_panel = false`, `oc_position = "bottom"`**
```
┌─────────────────────┬───────────┐
│  bash         (~80%)│ git panel │  ~35% height
├─────────────────────┴───────────┤
│  opencode                       │  ~65% height
└─────────────────────────────────┘
```

**`todo_panel = false`, `oc_position = "left"`**
```
┌──────────┬──────────────────────┐
│          │  bash                │  ~80% of bundle height
│opencode  ├──────────────────────┤
│          │  git panel           │  ~20% of bundle height
└──────────┴──────────────────────┘
```

`panel_percent` controls how much of the window the git+bash bundle takes; `split_percent` controls the panel/bash split within it. With `git_panel = false` as well, bash takes the whole bundle.

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
- `opencode` by downloading the latest Linux x64 release into `/usr/local/bin/opencode`

Run it with `sudo`:

```sh
sudo shad init --install-deps
```

### Python packages

`shad` needs `rich` and `textual`. Both install with the package:

```sh
pip install -e .
```

No other binary is required for the git pane. Earlier versions ran
[gitui](https://github.com/gitui-org/gitui) there; `shad git panel` replaces
it, so `gitui` can be uninstalled if nothing else uses it.

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
        ├── shared/
        │   ├── config.py
        │   ├── errors.py
        │   ├── render.py
        │   └── tmux.py
        └── todo/
            ├── command.py
            ├── model.py
            ├── panel.py
            ├── render.py
            └── store.py
```
