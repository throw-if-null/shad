"""
Config loading for shad.

Schema (shad.toml):

  [defaults]
  oc_position   = "top"   # top | bottom | left
  panel_percent = 35      # % of window the git+bash bundle takes
  split_percent = 35      # % of the bundle that gitui takes (bash gets the rest)

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
from dataclasses import dataclass, field
from pathlib import Path

from shad.shared.errors import ShadError

# ── where the config lives ────────────────────────────────────────────────

APP_NAME = "shad"
CONFIG_NAME = "shad.toml"

# Full path to a config file. Overrides the per-OS default entirely, including
# the directory, so a scratch config need not live in a config directory.
CONFIG_ENV = "SHAD_CONFIG"



def legacy_config_dir() -> Path:
    """
    The pre-1.0 location, used on every OS.

    Kept as a fallback so an existing install is not silently orphaned when the
    per-OS default moves out from under it. Resolved at call time, like every
    other path here, so HOME is read from the running process.
    """
    return Path.home() / ".config" / APP_NAME


def default_config_dir() -> Path:
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
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return base / APP_NAME

    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg and Path(xdg).is_absolute() else Path.home() / ".config"
    return base / APP_NAME


def config_path() -> Path:
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
    override = os.environ.get(CONFIG_ENV)
    if override:
        return Path(override).expanduser()

    preferred = default_config_dir() / CONFIG_NAME
    if preferred.exists():
        return preferred

    if sys.platform in ("darwin", "win32"):
        # Only these platforms moved away from ~/.config, so only here can an
        # existing install be stranded. On an XDG platform ~/.config *is* the
        # default, which makes the fallback either redundant (XDG_CONFIG_HOME
        # unset, so it is already `preferred`) or wrong — silently ignoring a
        # directory the user explicitly chose.
        legacy = legacy_config_dir() / CONFIG_NAME
        if legacy.exists():
            return legacy

    return preferred


OC_POSITIONS = ("top", "bottom", "left")
HARNESSES = ("opencode", "claude")


@dataclass
class Defaults:
    oc_position: str = "top"
    panel_percent: int = 35
    split_percent: int = 35
    harness: str = "opencode"


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


def _parse_project(
    key: str, data: dict, group: str | None = None, default_harness: str = "opencode"
) -> Project:
    if "path" not in data:
        raise ShadError(
            f"Project [{('projects.' + group + '.' if group else 'projects.') + key}] "
            f"is missing required field 'path'"
        )
    harness = data.get("harness", default_harness)
    if harness not in HARNESSES:
        raise ShadError(
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


def load(path: Path | None = None) -> Config:
    if path is None:
        path = config_path()
    if not path.exists():
        raise ShadError(
            f"config file not found: {path}\n"
            f"       create it or copy shad.example.toml to get started."
        )

    with path.open("rb") as fh:
        raw = tomllib.load(fh)

    # --- defaults ---
    d = raw.get("defaults", {})
    oc_position = d.get("oc_position", "top")
    if oc_position not in OC_POSITIONS:
        raise ShadError(
            f"invalid oc_position '{oc_position}'; must be one of: {', '.join(OC_POSITIONS)}"
        )
    harness = d.get("harness", "opencode")
    if harness not in HARNESSES:
        raise ShadError(
            f"invalid harness '{harness}' in [defaults]; must be one of: {', '.join(HARNESSES)}"
        )

    def _int_setting(name: str, default: int) -> int:
        raw_val = d.get(name, default)
        try:
            return int(raw_val)
        except (TypeError, ValueError):
            raise ShadError(
                f"invalid value for '{name}' in [defaults]: expected an integer, got {raw_val!r}"
            )

    defaults = Defaults(
        oc_position=oc_position,
        panel_percent=_int_setting("panel_percent", 35),
        split_percent=_int_setting("split_percent", 35),
        harness=harness,
    )

    # --- projects ---
    projects: dict[str, Project] = {}
    groups: dict[str, dict[str, Project]] = {}

    for key, value in raw.get("projects", {}).items():
        if not isinstance(value, dict):
            raise ShadError(f"[projects.{key}] must be a TOML table")

        if "path" in value:
            # top-level project
            projects[key] = _parse_project(key, value, group=None, default_harness=harness)
        else:
            # group: value is a dict of sub-projects
            group_projects: dict[str, Project] = {}
            for sub_key, sub_value in value.items():
                if not isinstance(sub_value, dict):
                    raise ShadError(
                        f"[projects.{key}.{sub_key}] must be a TOML table"
                    )
                group_projects[sub_key] = _parse_project(
                    sub_key, sub_value, group=key, default_harness=harness
                )
            groups[key] = group_projects

    cfg = Config(defaults=defaults, projects=projects, groups=groups)
    _reject_duplicate_paths(cfg)
    return cfg


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
            raise ShadError(
                f"'{first}' and '{project.display_name}' both point at {resolved}\n"
                f"       two projects must not name the same directory"
            )
        seen[resolved] = project.display_name


def resolve_prefix(candidates: list[str], token: str) -> str | None:
    """
    Resolve *token* against *candidates* using exact-then-prefix matching.

    Returns the matched candidate name, or raises ShadError with a message.
    """
    if token in candidates:
        return token

    matches = [c for c in candidates if c.startswith(token)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ShadError(
            f"'{token}' is ambiguous; matches: {', '.join(sorted(matches))}"
        )
    return None  # caller decides how to handle "not found"


@dataclass
class Target:
    """The projects named by 0-2 CLI tokens."""

    projects: list[Project]


def all_projects(cfg: Config) -> list[Project]:
    """Every configured project: top-level by key, then grouped by group then key."""
    result = [cfg.projects[key] for key in sorted(cfg.projects)]
    for group in sorted(cfg.groups):
        result.extend(cfg.groups[group][key] for key in sorted(cfg.groups[group]))
    return result


def resolve_target(
    cfg: Config, tokens: list[str], *, usage: str = "shad projects"
) -> Target:
    """
    Resolve 0-2 CLI tokens to the projects they name.

      []             -> every configured project
      [name]         -> one top-level project, or every project in a group
      [group, name]  -> one project inside a group

    Prefix matching applies at each level. Raises ShadError when a token is
    unknown, ambiguous, or when there are too many tokens.
    """
    if not tokens:
        return Target(projects=all_projects(cfg))

    if len(tokens) == 1:
        token = tokens[0]
        match = resolve_prefix(list(cfg.projects) + list(cfg.groups), token)
        if match is None:
            raise ShadError(f"no project or group matching '{token}'")
        if match in cfg.projects:
            return Target(projects=[cfg.projects[match]])
        group = cfg.groups[match]
        return Target(projects=[group[key] for key in sorted(group)])

    if len(tokens) == 2:
        group_token, proj_token = tokens

        group_match = resolve_prefix(list(cfg.groups), group_token)
        if group_match is None:
            if group_token in cfg.projects or any(
                k.startswith(group_token) for k in cfg.projects
            ):
                raise ShadError(
                    f"'{group_token}' resolves to a top-level project, not a group; "
                    f"did you mean: {usage} {group_token}?"
                )
            raise ShadError(f"no group matching '{group_token}'")

        group_projects = cfg.groups[group_match]
        proj_match = resolve_prefix(list(group_projects), proj_token)
        if proj_match is None:
            raise ShadError(
                f"no project matching '{proj_token}' in group '{group_match}'; "
                f"available: {', '.join(sorted(group_projects))}"
            )

        return Target(projects=[group_projects[proj_match]])

    raise ShadError(
        f"too many arguments ({len(tokens)}); usage: {usage} [<group>] [<name>]"
    )
