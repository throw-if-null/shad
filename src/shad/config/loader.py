"""
Loading `shad.toml`: where the file and the data directory are, and the
file parsed and validated against `schema.py` into a Config.

The functions that read the environment take it as an argument; the root
passes its own once per run, and a test passes what it wants. Pure
functions over the file and that mapping; shared-and-safe.

Schema (shad.toml):

  [defaults]
  oc_position   = "top"   # top | bottom | left
  panel_percent = 35      # % of window the git+bash bundle takes
  split_percent = 20      # % of the bundle that the git panel takes (bash gets the rest)
  git_panel     = true    # false = no git panel pane
  todo_panel    = true    # false = no todo pane
  todo_percent  = 20      # % of window width the todo column takes

  [todo]
  labels = ["chore", "documentation"]   # the label vocabulary `shad todo add --label` accepts
  path   = "~/notes/todo"               # optional; defaults to <data dir>/todo

  # top-level project (no group)
  [projects.kb]
  path    = "/home/user/gh/kb"
  session = "kb"          # optional; defaults to project key

  # grouped project  →  `shad projects alvr db`
  [projects.alvr.db]
  path    = "/home/user/gh/alvr/db"
  session = "alvr-db"     # optional; defaults to "<group>-<key>"

A table is treated as a *project* if it contains a "path" key.
A table is treated as a *group* if it contains no "path" key.
Maximum supported depth: group → project  (2 levels).
"""

from __future__ import annotations

import os
import sys
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from shad.config.schema import DEFAULTS_FIELDS, HARNESSES, check, check_labels
from shad.errors import ShadError

# ── where the config lives ────────────────────────────────────────────────

APP_NAME = "shad"
CONFIG_NAME = "shad.toml"

# Full path to a config file. Overrides the per-OS default entirely, including
# the directory, so a scratch config need not live in a config directory.
CONFIG_ENV = "SHAD_CONFIG"



def _env(env: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if env is None else env


def _home(env: Mapping[str, str]) -> Path:
    """HOME as *env* has it, else the account's home directory."""
    home = env.get("HOME")
    return Path(home) if home else Path.home()


def legacy_config_dir(env: Mapping[str, str] | None = None) -> Path:
    """
    The pre-1.0 location, used on every OS.

    Kept as a fallback so an existing install is not silently orphaned when the
    per-OS default moves out from under it.
    """
    return _home(_env(env)) / ".config" / APP_NAME


def default_config_dir(env: Mapping[str, str] | None = None) -> Path:
    """
    The per-OS directory shad stores its config in, before any override.

      Linux/BSD   $XDG_CONFIG_HOME/shad   (default ~/.config/shad)
      macOS       ~/Library/Application Support/shad
      Windows     %APPDATA%\\shad

    XDG_CONFIG_HOME is honoured only when it is absolute, as the spec requires;
    a relative value would resolve against the current directory and put the
    config somewhere different for every invocation.

    The branch keys off sys.platform, not os.name: pathlib dispatches on
    os.name, so a test that patched it could not construct a path at all.
    Cygwin reports "cygwin" and is POSIX-shaped, so it takes the XDG branch.
    """
    env = _env(env)
    if sys.platform == "darwin":
        return _home(env) / "Library" / "Application Support" / APP_NAME
    if sys.platform == "win32":
        appdata = env.get("APPDATA")
        base = Path(appdata) if appdata else _home(env) / "AppData" / "Roaming"
        return base / APP_NAME

    xdg = env.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg and Path(xdg).is_absolute() else _home(env) / ".config"
    return base / APP_NAME


def default_data_dir(env: Mapping[str, str] | None = None) -> Path:
    """
    The per-OS directory shad stores its data in: today, the todo files.

      Linux/BSD   $XDG_DATA_HOME/shad   (default ~/.local/share/shad)
      macOS       ~/Library/Application Support/shad
      Windows     %LOCALAPPDATA%\\shad

    Data is kept apart from config because a config directory is often tracked
    in a dotfiles repository, and todo files should not be dragged into one by
    default. The XDG rule is the same as default_config_dir(): the variable is
    honoured only when it is absolute.
    """
    env = _env(env)
    if sys.platform == "darwin":
        return _home(env) / "Library" / "Application Support" / APP_NAME
    if sys.platform == "win32":
        local = env.get("LOCALAPPDATA")
        base = Path(local) if local else _home(env) / "AppData" / "Local"
        return base / APP_NAME

    xdg = env.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg and Path(xdg).is_absolute() else _home(env) / ".local" / "share"
    return base / APP_NAME


def config_path(env: Mapping[str, str] | None = None) -> Path:
    """
    Resolve the config file to use. Precedence, highest first:

      1. $SHAD_CONFIG          — an explicit file path
      2. the per-OS default    — see default_config_dir()
      3. ~/.config/shad/shad.toml, on macOS and Windows only, when it exists
         and (2) does not

    Rule 3 is restricted to the platforms whose default moved away from
    ~/.config, and only fires when that file is actually there, so it never
    invents a path and never overrides an explicit $XDG_CONFIG_HOME.
    Writers (`shad init`, `shad config set`) get the same answer as readers,
    which is what keeps an existing config from being shadowed by a new empty
    one in the per-OS location.

    Resolved on every call rather than at import, so the environment a process
    actually starts with is the one that decides.
    """
    env = _env(env)
    override = env.get(CONFIG_ENV)
    if override:
        return Path(override).expanduser()

    preferred = default_config_dir(env) / CONFIG_NAME
    if preferred.exists():
        return preferred

    if sys.platform in ("darwin", "win32"):
        # Only these platforms moved away from ~/.config, so only here can an
        # existing install be stranded. On an XDG platform ~/.config *is* the
        # default, which makes the fallback either redundant (XDG_CONFIG_HOME
        # unset, so it is already `preferred`) or wrong — silently ignoring a
        # directory the user explicitly chose.
        legacy = legacy_config_dir(env) / CONFIG_NAME
        if legacy.exists():
            return legacy

    return preferred


@dataclass
class Defaults:
    """The [defaults] settings; the defaults here are the schema's."""

    oc_position: str = "top"
    panel_percent: int = 35
    split_percent: int = 20
    harness: str = "opencode"
    git_panel: bool = True
    todo_panel: bool = True
    todo_percent: int = 20


@dataclass
class Project:
    key: str           # e.g. "kb" or "db"
    group: str | None  # e.g. None or "alvr"
    path: Path
    session: str       # resolved session name
    harness: str = "opencode"

    @property
    def display_name(self) -> str:
        """Human-readable name used in listings."""
        if self.group:
            return f"{self.group} {self.key}"
        return self.key


@dataclass
class Config:
    defaults: Defaults
    # top-level projects keyed by their key
    projects: dict[str, Project] = field(default_factory=dict)
    # grouped projects: groups[group_name][project_key] = Project
    groups: dict[str, dict[str, Project]] = field(default_factory=dict)
    # [todo] labels, in file order; the vocabulary every todo item is checked against
    todo_labels: list[str] = field(default_factory=list)
    # [todo] path, expanded; None means the todo files are under the data dir
    todo_path: Path | None = None
    # The per-OS data directory, resolved by the root; the snapshot and, by
    # default, the todo files live under it
    data_dir: Path = Path(".")

    @property
    def todo_dir(self) -> Path:
        """Where the todo files are: [todo] path, else <data dir>/todo."""
        return self.todo_path if self.todo_path is not None else self.data_dir / "todo"


def _parse_project(
    key: str, data: dict, group: str | None = None, default_harness: str = "opencode"
) -> Project:
    if "path" not in data:
        raise ShadError.validation(
            "invalid_config",
            f"Project [{('projects.' + group + '.' if group else 'projects.') + key}] "
            f"is missing required field 'path'"
        )
    harness = data.get("harness", default_harness)
    if harness not in HARNESSES:
        raise ShadError.validation(
            "invalid_config",
            f"invalid harness '{harness}' in project '{key}'; "
            f"must be one of: {', '.join(HARNESSES)}"
        )
    default_session = f"{group}-{key}" if group else key
    return Project(
        key=key,
        group=group,
        # Expanded here so every consumer agrees what a project path means:
        # `~/src/x` is documented in shad.toml, and `git -C ~/src/x` does not
        # expand it — the shell normally would.
        path=Path(data["path"]).expanduser(),
        session=data.get("session", default_session),
        harness=harness,
    )


def load(path: Path | None = None, *, data_dir: Path | None = None) -> Config:
    """
    The file at *path* (the resolved one when None), validated against the
    schema. *data_dir* is where the snapshot and the default todo files
    live; the root resolves it once, and None resolves it here.
    """
    if path is None:
        path = config_path()
    if data_dir is None:
        data_dir = default_data_dir()
    if not path.exists():
        raise ShadError.not_found(
            "no_config_file",
            f"config file not found: {path}; create it or copy shad.example.toml to get started"
        )

    with path.open("rb") as fh:
        try:
            raw = tomllib.load(fh)
        except tomllib.TOMLDecodeError as exc:
            raise ShadError.validation(
                "invalid_config", f"{path} is not valid TOML: {exc}"
            ) from None

    # --- defaults ---
    d = raw.get("defaults", {})
    if not isinstance(d, dict):
        raise ShadError.validation("invalid_config", "[defaults] must be a TOML table")
    settings: dict[str, object] = {}
    for spec in DEFAULTS_FIELDS:
        if spec.name not in d:
            settings[spec.name] = spec.default
            continue
        try:
            settings[spec.name] = check(spec, d[spec.name], spec.name)
        except ShadError as exc:
            if spec.name != "todo_percent":
                raise
            raise ShadError.validation(
                "invalid_config", f"{exc.message} (set todo_panel = false to hide the todo pane)"
            ) from None
    harness = str(settings["harness"])
    defaults = Defaults(**settings)  # type: ignore[arg-type]

    # --- projects ---
    projects: dict[str, Project] = {}
    groups: dict[str, dict[str, Project]] = {}

    for key, value in raw.get("projects", {}).items():
        if not isinstance(value, dict):
            raise ShadError.validation("invalid_config", f"[projects.{key}] must be a TOML table")

        if "path" in value:
            # top-level project
            projects[key] = _parse_project(key, value, group=None, default_harness=harness)
        else:
            # group: value is a dict of sub-projects
            group_projects: dict[str, Project] = {}
            for sub_key, sub_value in value.items():
                if not isinstance(sub_value, dict):
                    raise ShadError.validation(
                        "invalid_config",
                        f"[projects.{key}.{sub_key}] must be a TOML table"
                    )
                group_projects[sub_key] = _parse_project(
                    sub_key, sub_value, group=key, default_harness=harness
                )
            groups[key] = group_projects

    todo = raw.get("todo", {})
    if not isinstance(todo, dict):
        raise ShadError.validation("invalid_config", "[todo] must be a TOML table")
    cfg = Config(
        defaults=defaults,
        projects=projects,
        groups=groups,
        todo_labels=check_labels(todo.get("labels", []), "[todo] labels"),
        todo_path=_parse_todo_path(todo),
        data_dir=data_dir,
    )
    _reject_duplicate_paths(cfg)
    return cfg


def _parse_todo_path(todo: dict) -> Path | None:
    """
    The [todo] path, with `~` expanded, or None when it is not set.

    A relative path is rejected: it would resolve against the current
    directory, so the pane and a shell in a subdirectory would each read a
    different list.
    """
    value = todo.get("path")
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ShadError.validation("invalid_config", "[todo] path must be a non-empty string")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ShadError.validation(
            "invalid_config", f"[todo] path must be absolute or start with ~; got {value!r}"
        )
    return path


def _reject_duplicate_paths(cfg: Config) -> None:
    """
    Refuse a config where two projects name the same directory.

    A project is a directory plus a session, so two entries on one directory
    are a mistake in the file, not a layout: `shad projects` would offer two
    names for the same place, and `shad git sync` would plan the same
    repository twice and report the second pass as failures.

    Paths are compared after expanduser+resolve, which catches `~`, a relative
    entry, and the `/home` -> `/var/home` symlink. This is a property of the
    config text alone — unlike repository identity, it cannot start being true
    because of something that happened on disk — so failing hard is safe.

    Two *worktrees* or two *clones* of one repository are different
    directories and stay legal. `shad git sync` handles the shared-ref-store
    case by deduplicating on --git-common-dir, not by rejecting the config.
    """
    seen: dict[Path, str] = {}
    for project in all_projects(cfg):
        resolved = project.path.expanduser().resolve()
        first = seen.get(resolved)
        if first is not None:
            raise ShadError.validation(
                "invalid_config",
                f"'{first}' and '{project.display_name}' both point at {resolved}; "
                f"two projects must not name the same directory"
            )
        seen[resolved] = project.display_name


def all_projects(cfg: Config) -> list[Project]:
    """Every configured project: top-level by key, then grouped by group then key."""
    result = [cfg.projects[key] for key in sorted(cfg.projects)]
    for group in sorted(cfg.groups):
        result.extend(cfg.groups[group][key] for key in sorted(cfg.groups[group]))
    return result
