"""Tests for the tool executors against a temporary repo (no network/model)."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.config import Config  # noqa: E402
from agent.repository import RepoContext  # noqa: E402
from agent.tools import build_tools  # noqa: E402


class TestTools(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "pkg"))
        with open(os.path.join(self.tmp, "pkg", "a.go"), "w") as fh:
            fh.write("package pkg\n\nfunc Add(a, b int) int { return a + b }\n")
        self.ctx = RepoContext(
            repo="x/y", path=self.tmp, branch="b", base_ref="ref"
        )
        self.config = Config()

    def _execs(self, allow_write):
        _, execs = build_tools(self.ctx, self.config, allow_write=allow_write)
        return execs

    def test_read_and_list(self):
        execs = self._execs(False)
        listing = execs["list_directory"]({"path": ""})
        self.assertIn("pkg/", listing)
        content = execs["read_file"]({"path": "pkg/a.go"})
        self.assertIn("func Add", content)

    def test_find_files(self):
        execs = self._execs(False)
        out = execs["find_files"]({"pattern": "*.go"})
        self.assertIn("a.go", out)

    def test_search_code(self):
        execs = self._execs(False)
        out = execs["search_code"]({"pattern": "func Add"})
        self.assertIn("a.go", out)

    def test_path_escape_blocked(self):
        execs = self._execs(False)
        out = execs["read_file"]({"path": "../../etc/passwd"})
        self.assertIn("escapes the repository", out)

    def test_write_only_in_write_phase(self):
        self.assertNotIn("write_file", self._execs(False))
        self.assertIn("write_file", self._execs(True))

    def test_edit_file(self):
        execs = self._execs(True)
        res = execs["edit_file"]({
            "path": "pkg/a.go",
            "old_string": "a + b",
            "new_string": "a + b + 0",
        })
        self.assertIn("edited", res)
        self.assertIn("a + b + 0", execs["read_file"]({"path": "pkg/a.go"}))

    def test_edit_requires_unique(self):
        execs = self._execs(True)
        execs["write_file"]({"path": "pkg/dup.go", "content": "x\nx\n"})
        res = execs["edit_file"]({"path": "pkg/dup.go", "old_string": "x", "new_string": "y"})
        self.assertIn("must be unique", res)

    def test_missing_go_is_graceful(self):
        # go may or may not be installed; either way run_tests returns a string
        # and never raises.
        execs = self._execs(True)
        out = execs["run_tests"]({"package": "./..."})
        self.assertIsInstance(out, str)


if __name__ == "__main__":
    unittest.main()
