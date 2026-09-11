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

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from shad.shared.errors import ShadError

CONFIG_PATH = Path.home() / ".config" / "shad" / "shad.toml"

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
        path=Path(data["path"]),
        session=data.get("session", default_session),
        harness=harness,
    )


def load(path: Path = CONFIG_PATH) -> Config:
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

    return Config(defaults=defaults, projects=projects, groups=groups)


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
    """The projects named by 0-2 CLI tokens, plus what those tokens named."""

    projects: list[Project]
    group: str | None = None  # set when the tokens named a whole group


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
        return Target(
            projects=[group[key] for key in sorted(group)],
            group=match,
        )

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
