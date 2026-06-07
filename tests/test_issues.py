"""Tests for issue reference parsing and loading (no network)."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.issues import parse_issue_reference, load_issue_file, Issue  # noqa: E402

# A realistic `gh issue view --json ...` payload, used to exercise the offline
# loader without depending on the network or a committed sample.
_GH_ISSUE_JSON = {
    "number": 1550,
    "title": "[Bug]: UUID validation fails for uppercase UUIDs",
    "url": "https://github.com/go-playground/validator/issues/1550",
    "body": "The `uuid` tag incorrectly rejects valid UUIDs in uppercase format.",
    "labels": [{"name": "bug"}],
    "comments": [
        {"author": {"login": "maintainer"}, "body": "Agreed, the regex should accept A-F."}
    ],
}


class TestParseReference(unittest.TestCase):
    def test_full_url(self):
        repo, num = parse_issue_reference("https://github.com/spf13/cobra/issues/2137")
        self.assertEqual(repo, "spf13/cobra")
        self.assertEqual(num, 2137)

    def test_bare_number_with_repo(self):
        repo, num = parse_issue_reference("42", repo="gin-gonic/gin")
        self.assertEqual((repo, num), ("gin-gonic/gin", 42))

    def test_bare_number_without_repo_errors(self):
        with self.assertRaises(ValueError):
            parse_issue_reference("42")

    def test_garbage_errors(self):
        with self.assertRaises(ValueError):
            parse_issue_reference("not-an-issue")


class TestLoadIssueFile(unittest.TestCase):
    def test_loads_gh_shaped_json(self):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            json.dump(_GH_ISSUE_JSON, fh)
            path = fh.name
        try:
            issue = load_issue_file(path, repo="go-playground/validator")
        finally:
            os.unlink(path)
        self.assertIsInstance(issue, Issue)
        self.assertEqual(issue.number, 1550)
        self.assertEqual(issue.repo, "go-playground/validator")
        self.assertIn("UUID", issue.title)
        self.assertIn("bug", issue.labels)
        # Comment author given as {"login": ...} is normalized.
        self.assertIn("maintainer:", "\n".join(issue.comments))
        # Prompt rendering includes title and body.
        rendered = issue.as_prompt()
        self.assertIn("uppercase", rendered)
        self.assertIn("Issue body", rendered)


if __name__ == "__main__":
    unittest.main()
