"""
Config loading for shad.

Schema (shad.toml):

  [defaults]
  top_command    = "opencode -c"
  bottom_percent = 35
  right_percent  = 30

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

import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "shad" / "shad.toml"


@dataclass
class Defaults:
    top_command: str = "opencode -c"
    bottom_percent: int = 35
    right_percent: int = 30


@dataclass
class Project:
    key: str           # e.g. "kb" or "db"
    group: str | None  # e.g. None or "alvr"
    path: Path
    session: str       # resolved session name

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


def _parse_project(key: str, data: dict, group: str | None = None) -> Project:
    if "path" not in data:
        raise ValueError(
            f"Project [{('projects.' + group + '.' if group else 'projects.') + key}] "
            f"is missing required field 'path'"
        )
    default_session = f"{group}-{key}" if group else key
    return Project(
        key=key,
        group=group,
        path=Path(data["path"]),
        session=data.get("session", default_session),
    )


def load(path: Path = CONFIG_PATH) -> Config:
    if not path.exists():
        print(
            f"error: config file not found: {path}\n"
            f"       create it or copy shad.example.toml to get started.",
            file=sys.stderr,
        )
        sys.exit(1)

    with path.open("rb") as fh:
        raw = tomllib.load(fh)

    # --- defaults ---
    d = raw.get("defaults", {})
    defaults = Defaults(
        top_command=d.get("top_command", "opencode -c"),
        bottom_percent=int(d.get("bottom_percent", 35)),
        right_percent=int(d.get("right_percent", 30)),
    )

    # --- projects ---
    projects: dict[str, Project] = {}
    groups: dict[str, dict[str, Project]] = {}

    for key, value in raw.get("projects", {}).items():
        if not isinstance(value, dict):
            print(f"error: [projects.{key}] must be a TOML table", file=sys.stderr)
            sys.exit(1)

        if "path" in value:
            # top-level project
            projects[key] = _parse_project(key, value, group=None)
        else:
            # group: value is a dict of sub-projects
            group_projects: dict[str, Project] = {}
            for sub_key, sub_value in value.items():
                if not isinstance(sub_value, dict):
                    print(
                        f"error: [projects.{key}.{sub_key}] must be a TOML table",
                        file=sys.stderr,
                    )
                    sys.exit(1)
                group_projects[sub_key] = _parse_project(sub_key, sub_value, group=key)
            groups[key] = group_projects

    return Config(defaults=defaults, projects=projects, groups=groups)


def resolve_prefix(candidates: list[str], token: str) -> str | None:
    """
    Resolve *token* against *candidates* using exact-then-prefix matching.

    Returns the matched candidate name, or raises SystemExit with a message.
    """
    if token in candidates:
        return token

    matches = [c for c in candidates if c.startswith(token)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        print(
            f"error: '{token}' is ambiguous; matches: {', '.join(sorted(matches))}",
            file=sys.stderr,
        )
        sys.exit(1)
    return None  # caller decides how to handle "not found"
