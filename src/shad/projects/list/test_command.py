from __future__ import annotations

import json

from shad.projects.testing import ProjectsCase


class ListTests(ProjectsCase):
    """
    Feature:    projects/list
    Boundary:   command. `shad projects [<group>] [--json]`, through
                main(argv) with SHAD_CONFIG set. Contract: exit code +
                stdout + stderr.
    """

    def test_list_prints_every_project_and_group(self) -> None:
        """
        Criterion:  list-prints-every-project-and-group
          Given:    the projects kb, kc, tin shad and tin coral.
          When:     `shad projects`.
          Then:     exit 0, stderr empty, stdout names each project and the
                    group.
        """
        result = self.run_shad("projects")
        self.assertEqual((result.code, result.err), (0, ""), result.out)
        for text in ("kb", "kc", "tin", "tin shad", "tin coral"):
            self.assertIn(text, result.out)

    def test_list_of_a_group_prints_its_projects(self) -> None:
        """
        Criterion:  list-of-a-group-prints-its-projects
          When:     `shad projects tin`.
          Then:     exit 0, stderr empty, stdout names tin shad and tin
                    coral and no top-level project.
        """
        result = self.run_shad("projects", "tin")
        self.assertEqual((result.code, result.err), (0, ""), result.out)
        self.assertIn("tin shad", result.out)
        self.assertIn("tin coral", result.out)
        self.assertNotIn("kb", result.out)

    def test_list_with_no_projects_says_so(self) -> None:
        """
        Criterion:  list-with-no-projects-says-so
          Given:    the config names no project.
          When:     `shad projects`.
          Then:     exit 0, stderr empty, stdout says none is configured.
        """
        self.write_config("[defaults]\n")
        result = self.run_shad("projects")
        self.assertEqual((result.code, result.err), (0, ""), result.out)
        self.assertIn("no projects configured", result.out)

    def test_list_json_names_every_project(self) -> None:
        """
        Criterion:  list-json-names-every-project
          Given:    the projects kb, kc, tin shad and tin coral.
          When:     `shad projects --json`, and `shad --json projects`.
          Then:     each exits 0 with stderr empty, and stdout is one JSON
                    object whose `group` is null and whose `projects` is a
                    list of objects each carrying string `key`, nullable
                    string `group`, string `path`, string `session` and
                    string `harness`; the keys are kb, kc, shad and coral.
        """
        for argv in (("projects", "--json"), ("--json", "projects")):
            with self.subTest(argv=argv):
                result = self.run_shad(*argv)
                self.assertEqual((result.code, result.err), (0, ""), result.out)
                document = json.loads(result.out)
                self.assertIsNone(document["group"])
                rows = document["projects"]
                self.assertEqual([row["key"] for row in rows], ["kb", "kc", "coral", "shad"])
                self.assertEqual([row["group"] for row in rows], [None, None, "tin", "tin"])
                for row in rows:
                    self.assertEqual(
                        {name: type(row[name]) for name in ("path", "session", "harness")},
                        {"path": str, "session": str, "harness": str},
                    )
                self.assertEqual(rows[3]["session"], "tin-shad")

    def test_list_json_of_a_group_names_the_group(self) -> None:
        """
        Criterion:  list-json-of-a-group-names-the-group
          When:     `shad projects tin --json`.
          Then:     exit 0, stdout is one JSON object with `group` "tin" and
                    the two projects of the group.
        """
        result = self.run_shad("projects", "tin", "--json")
        self.assertEqual((result.code, result.err), (0, ""), result.out)
        document = json.loads(result.out)
        self.assertEqual(document["group"], "tin")
        self.assertEqual([row["key"] for row in document["projects"]], ["coral", "shad"])

    def test_json_on_an_open_is_a_usage_error(self) -> None:
        """
        Criterion:  json-on-an-open-is-a-usage-error
          When:     `shad projects kb --json`.
          Then:     exit 2, stdout empty, stderr is one line
                    `no_json: <non-empty>`, and no kb session exists.
        """
        result = self.run_shad("projects", "kb", "--json")
        self.assertEqual((result.code, result.out), (2, ""), result.err)
        self.assertRegex(result.err, r"^no_json: .+\n$")
        self.assertEqual(self.sessions_of("kb"), [])
