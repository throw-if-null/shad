from __future__ import annotations

import unittest
from pathlib import Path

from shad.addressing import resolve_prefix, resolve_target
from shad.config.load import Config, Defaults, Project
from shad.errors import ShadError


def _project(key: str, group: str | None = None) -> Project:
    return Project(
        key=key,
        group=group,
        path=Path("/tmp") / key,
        session=f"{group}-{key}" if group else key,
    )


def _config() -> Config:
    return Config(
        defaults=Defaults(),
        projects={"kb": _project("kb"), "orfe": _project("orfe")},
        groups={
            "tin": {"shad": _project("shad", "tin"), "coral": _project("coral", "tin")},
            "cv": {"sol": _project("sol", "cv")},
        },
    )

# ---------------------------------------------------------------------------
# resolve_prefix
# ---------------------------------------------------------------------------

class ResolvePrefixTests(unittest.TestCase):
    def test_exact_match_returned_directly(self) -> None:
        result = resolve_prefix(["shad", "shell"], "shad")
        self.assertEqual(result, "shad")

    def test_unique_prefix_returns_candidate(self) -> None:
        result = resolve_prefix(["shad", "shell"], "sha")
        self.assertEqual(result, "shad")

    def test_ambiguous_prefix_raises_shad_error(self) -> None:
        with self.assertRaises(ShadError) as ctx:
            resolve_prefix(["shad", "shell", "sheep"], "sh")
        self.assertIn("ambiguous", str(ctx.exception))
        self.assertIn("shad", str(ctx.exception))
        self.assertIn("sheep", str(ctx.exception))

    def test_no_match_returns_none(self) -> None:
        result = resolve_prefix(["shad", "shell"], "xyz")
        self.assertIsNone(result)

    def test_empty_candidates_returns_none(self) -> None:
        result = resolve_prefix([], "shad")
        self.assertIsNone(result)


class ResolveTargetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = _config()

    def test_no_tokens_returns_every_project(self) -> None:
        target = resolve_target(self.cfg, [])
        self.assertEqual(len(target.projects), 5)

    def test_one_token_resolves_a_top_level_project(self) -> None:
        target = resolve_target(self.cfg, ["kb"])
        self.assertEqual([p.key for p in target.projects], ["kb"])

    def test_one_token_prefix_resolves_a_top_level_project(self) -> None:
        target = resolve_target(self.cfg, ["or"])
        self.assertEqual([p.key for p in target.projects], ["orfe"])

    def test_one_token_group_expands_to_every_member_sorted(self) -> None:
        target = resolve_target(self.cfg, ["tin"])
        self.assertEqual([p.key for p in target.projects], ["coral", "shad"])

    def test_two_tokens_resolve_one_grouped_project(self) -> None:
        target = resolve_target(self.cfg, ["tin", "shad"])
        self.assertEqual([p.display_name for p in target.projects], ["tin shad"])

    def test_two_tokens_use_prefix_matching_at_each_level(self) -> None:
        target = resolve_target(self.cfg, ["ti", "sh"])
        self.assertEqual([p.display_name for p in target.projects], ["tin shad"])

    def test_unknown_single_token_raises(self) -> None:
        with self.assertRaises(ShadError) as ctx:
            resolve_target(self.cfg, ["nope"])
        self.assertIn("no project or group matching 'nope'", str(ctx.exception))

    def test_ambiguous_single_token_raises(self) -> None:
        cfg = Config(
            defaults=Defaults(),
            projects={"shad": _project("shad"), "shell": _project("shell")},
        )
        with self.assertRaises(ShadError) as ctx:
            resolve_target(cfg, ["sh"])
        self.assertIn("ambiguous", str(ctx.exception))

    def test_unknown_group_raises(self) -> None:
        with self.assertRaises(ShadError) as ctx:
            resolve_target(self.cfg, ["zzz", "shad"])
        self.assertIn("no group matching 'zzz'", str(ctx.exception))

    def test_unknown_project_in_group_lists_available(self) -> None:
        with self.assertRaises(ShadError) as ctx:
            resolve_target(self.cfg, ["tin", "zzz"])
        message = str(ctx.exception)
        self.assertIn("no project matching 'zzz' in group 'tin'", message)
        self.assertIn("coral, shad", message)

    def test_top_level_project_used_as_a_group_hint_uses_the_usage_string(self) -> None:
        with self.assertRaises(ShadError) as ctx:
            resolve_target(self.cfg, ["kb", "shad"], usage="shad git sync")
        self.assertIn("did you mean: shad git sync kb?", str(ctx.exception))

    def test_too_many_tokens_uses_the_usage_string(self) -> None:
        with self.assertRaises(ShadError) as ctx:
            resolve_target(self.cfg, ["a", "b", "c"], usage="shad git sync")
        message = str(ctx.exception)
        self.assertIn("too many arguments (3)", message)
        self.assertIn("shad git sync [<group>] [<name>]", message)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# config path resolution
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    unittest.main()
