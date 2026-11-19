"""
How a name on the command line finds what it names: exact match first,
then a unique prefix, for projects, groups and todo keys alike.

Pure functions over the loaded configuration; shared-and-safe.
"""

from __future__ import annotations

from dataclasses import dataclass

from shad.config.load import Config, Project, all_projects
from shad.errors import ShadError


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
        raise ShadError.usage(
            "ambiguous_name",
            f"'{token}' is ambiguous; matches: {', '.join(sorted(matches))}"
        )
    return None  # caller decides how to handle "not found"


@dataclass
class Target:
    """The projects named by 0-2 CLI tokens."""

    projects: list[Project]


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
            raise ShadError.not_found("no_such_project", f"no project or group matching '{token}'")
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
                raise ShadError.not_found(
                    "no_such_group",
                    f"'{group_token}' resolves to a top-level project, not a group; "
                    f"did you mean: {usage} {group_token}?"
                )
            raise ShadError.not_found("no_such_group", f"no group matching '{group_token}'")

        group_projects = cfg.groups[group_match]
        proj_match = resolve_prefix(list(group_projects), proj_token)
        if proj_match is None:
            raise ShadError.not_found(
                "no_such_project",
                f"no project matching '{proj_token}' in group '{group_match}'; "
                f"available: {', '.join(sorted(group_projects))}"
            )

        return Target(projects=[group_projects[proj_match]])

    raise ShadError.usage(
        "too_many_arguments",
        f"too many arguments ({len(tokens)}); usage: {usage} [<group>] [<name>]"
    )
