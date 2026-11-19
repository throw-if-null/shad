from __future__ import annotations

import json

from shad.todo.testing import TodoCase


class ListTests(TodoCase):
    """
    Feature:    todo/list
    Boundary:   command. `shad todo list [--keys | --json]`, through
                main(argv) with SHAD_CONFIG and XDG_DATA_HOME under the test
                root. Contract: exit code + stdout + stderr. `--keys` is a
                published surface: the completion script parses it as one
                plain key per line.
    """

    def test_list_json_carries_every_item(self) -> None:
        """
        Criterion:  list-json-carries-every-item
          Given:    the item "Good one" with the label poc, hand-edited to
                    the unknown status doing.
          When:     `shad todo list --json`.
          Then:     exit 0, stderr empty, stdout is one JSON object with
                    `labels` (the vocabulary) and `items`: one object with
                    `key` good-one, `title`, `status` doing, `labels`
                    ["poc"], string `created`, integer `updated`, string
                    `body`, and `problems` naming the unknown status.
        """
        self._run("add", "Good one", "--label", "poc")
        path = self._dir() / "good-one.md"
        path.write_text(path.read_text().replace("status: todo", "status: doing"))
        document = json.loads(self._run("list", "--json"))
        self.assertEqual(document["labels"], ["chore", "poc"])
        (item,) = document["items"]
        self.assertEqual(
            (item["key"], item["title"], item["status"], item["labels"]),
            ("good-one", "Good one", "doing", ["poc"]),
        )
        self.assertIsInstance(item["created"], str)
        self.assertIsInstance(item["updated"], int)
        self.assertIsInstance(item["body"], str)
        self.assertEqual(item["problems"], ["unknown status 'doing'"])

    def test_json_carries_no_decoration(self) -> None:
        """
        Criterion:  json-carries-no-decoration
          When:     `shad todo list --json` with one item, in a pane (a
                    terminal, where the text form is colored).
          Then:     exit 0, and the output parses as JSON and contains no
                    escape byte 0x1b.
        """
        self._run("add", "Plain")
        document = json.loads(self._run("list", "--json"))
        self.assertEqual([item["key"] for item in document["items"]], ["plain"])
        self.assertNotIn("\x1b", self._run("list", "--json"))

    def test_list_keys_with_json_is_a_usage_error(self) -> None:
        """
        Criterion:  list-keys-with-json-is-a-usage-error
          When:     `shad todo list --keys --json`.
          Then:     exit 2, stdout empty, stderr is one line
                    `no_json: <non-empty>`.
        """
        result = self._result("list", "--keys", "--json")
        self.assertEqual((result.code, result.out), (2, ""), result.err)
        self.assertRegex(result.err, r"^no_json: .+\n$")

    def test_list_keys_prints_one_key_per_line_in_order(self) -> None:
        """
        Criterion:  list-keys-prints-one-key-per-line-in-order
          Given:    the items Beta and Alpha were added, in that order.
          When:     `shad todo list --keys`.
          Then:     exit 0, stderr empty, stdout is `alpha` and `beta`, one
                    per line, sorted, with no other text.
        """
        self._run("add", "Beta")
        self._run("add", "Alpha")
        self.assertEqual(self._run("list", "--keys"), "alpha\nbeta\n")

    def test_list_renders_every_item_and_flags_problems(self) -> None:
        """
        Criterion:  list-renders-every-item-and-flags-problems
          Given:    an item whose file was hand-edited to an unknown status.
          When:     `shad todo list`.
          Then:     exit 0, stderr empty, stdout shows the item's key and
                    title and names the unknown status.
        """
        self._run("add", "Good one", "--label", "poc")
        path = self._dir() / "good-one.md"
        path.write_text(path.read_text().replace("status: todo", "status: doing"))
        out = self._run("list")
        self.assertIn("good-one", out)
        self.assertIn("Good one", out)
        self.assertIn("unknown status 'doing'", out)

    def test_list_with_nothing_says_so(self) -> None:
        """
        Criterion:  list-with-nothing-says-so
          Given:    no item exists.
          When:     `shad todo list`, and `shad todo list --keys`.
          Then:     both exit 0; the first says there are no todos, the
                    second prints nothing.
        """
        self.assertIn("no todos", self._run("list"))
        self.assertEqual(self._run("list", "--keys"), "")
