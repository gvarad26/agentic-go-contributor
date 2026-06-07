"""Tests for repository helpers that don't need network access."""

import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.repository import build_repo_map, _read_module_path, collect_diff, RepoContext  # noqa: E402


class TestRepoMap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "binding"))
        os.makedirs(os.path.join(self.tmp, "vendor", "junk"))
        open(os.path.join(self.tmp, "go.mod"), "w").write("module example.com/foo\n\ngo 1.21\n")
        open(os.path.join(self.tmp, "binding", "json.go"), "w").write("package binding\n")
        open(os.path.join(self.tmp, "vendor", "junk", "z.go"), "w").write("package junk\n")

    def test_module_path(self):
        self.assertEqual(_read_module_path(self.tmp), "example.com/foo")

    def test_repo_map_includes_and_excludes(self):
        m = build_repo_map(self.tmp)
        self.assertIn("binding/", m)
        self.assertIn("json.go", m)
        self.assertNotIn("vendor", m)  # vendor is skipped


class TestCollectDiff(unittest.TestCase):
    def test_diff_includes_new_file(self):
        tmp = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-q", tmp], check=True)
        subprocess.run(["git", "-C", tmp, "config", "user.email", "t@t"], check=True)
        subprocess.run(["git", "-C", tmp, "config", "user.name", "t"], check=True)
        open(os.path.join(tmp, "a.txt"), "w").write("hello\n")
        subprocess.run(["git", "-C", tmp, "add", "-A"], check=True)
        subprocess.run(["git", "-C", tmp, "commit", "-q", "-m", "init"], check=True)
        # New file should appear in the collected diff.
        open(os.path.join(tmp, "b.txt"), "w").write("world\n")
        ctx = RepoContext(repo="x/y", path=tmp, branch="b", base_ref="ref")
        diff = collect_diff(ctx)
        self.assertIn("b.txt", diff)
        self.assertIn("world", diff)


if __name__ == "__main__":
    unittest.main()
