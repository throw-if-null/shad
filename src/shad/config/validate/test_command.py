from __future__ import annotations

import json

from shad.config.testing import ConfigCase


class ValidateTests(ConfigCase):
    """
    Feature:    config/validate
    Boundary:   command. `shad config validate [--json]`, through main(argv)
                with SHAD_CONFIG set. Contract: exit code + stdout + stderr.
    """

    def test_validate_json_reports_the_counts(self) -> None:
        """
        Criterion:  validate-json-reports-the-counts
          Given:    shad.toml holds the projects kb and alvr db.
          When:     `shad config validate --json`.
          Then:     exit 0, stderr empty, stdout is one JSON object with
                    `path`, `valid` true, `projects` 2 and `groups` 1.
        """
        self.assertEqual(
            json.loads(self._run("validate", "--json")),
            {"path": str(self.path), "valid": True, "projects": 2, "groups": 1},
        )

    def test_validate_json_of_a_bad_config_is_the_error_line(self) -> None:
        """
        Criterion:  validate-json-of-a-bad-config-is-the-error-line
          Given:    shad.toml sets oc_position = "sideways".
          When:     `shad config validate --json`.
          Then:     exit 1, stdout empty, stderr one line `invalid_config:
                    <non-empty>`: a failure is never JSON.
        """
        self.path.write_text('[defaults]\noc_position = "sideways"\n')
        self._fail("validate", "--json", code="invalid_config")

    def test_validate_accepts_a_good_config(self) -> None:
        """
        Criterion:  validate-accepts-a-good-config
          Given:    shad.toml holds the projects kb and alvr db.
          When:     `shad config validate`.
          Then:     exit 0, stderr empty, stdout says the file is valid with
                    2 projects and 1 group.
        """
        out = self._run("validate")
        self.assertIn("is valid", out)
        self.assertIn("2 project(s), 1 group(s)", out)

    def test_validate_rejects_a_config_that_does_not_load(self) -> None:
        """
        Criterion:  validate-rejects-a-config-that-does-not-load
          Given:    shad.toml sets oc_position = "sideways".
          When:     `shad config validate`.
          Then:     exit 1, stdout empty, stderr one line `invalid_config:
                    <non-empty>` that names `sideways`.
        """
        self.path.write_text('[defaults]\noc_position = "sideways"\n')
        self.assertIn("sideways", self._fail("validate", code="invalid_config"))

    def test_validate_without_a_file_fails(self) -> None:
        """
        Criterion:  validate-without-a-file-fails
          Given:    the config file does not exist.
          When:     `shad config validate`.
          Then:     exit 1, stdout empty, stderr one line `no_config_file:
                    <non-empty>`.
        """
        self.path.unlink()
        self.assertIn("not found", self._fail("validate", code="no_config_file"))
