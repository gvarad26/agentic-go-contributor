"""Tests for pipeline helpers (no network/model)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.logging_util import RunLog  # noqa: E402
from agent.pipeline import _analysis_from_text  # noqa: E402


class _FakeProvider:
    """Records whether the repair path (complete_json) was invoked."""

    def __init__(self, repaired=None, raise_on_repair=False):
        self._repaired = repaired or {}
        self._raise = raise_on_repair
        self.repair_calls = 0

    def complete_json(self, system, user, *, purpose=""):
        self.repair_calls += 1
        if self._raise:
            raise RuntimeError("model unavailable")
        return self._repaired


class TestAnalysisFromText(unittest.TestCase):
    def setUp(self):
        self.log = RunLog(verbose=False)

    def test_valid_json_no_repair(self):
        provider = _FakeProvider()
        out = _analysis_from_text(
            provider, '{"summary": "ok", "plan": ["step"]}', self.log
        )
        self.assertEqual(out["summary"], "ok")
        self.assertEqual(provider.repair_calls, 0)  # happy path never repairs

    def test_prose_triggers_repair(self):
        repaired = {"summary": "fixed", "relevant_files": [{"path": "regexes.go"}], "plan": ["x"]}
        provider = _FakeProvider(repaired=repaired)
        out = _analysis_from_text(
            provider, "I think the bug is in regexes.go because ...", self.log
        )
        self.assertEqual(provider.repair_calls, 1)  # repair was attempted
        self.assertEqual(out, repaired)

    def test_repair_failure_falls_back_to_minimal_plan(self):
        provider = _FakeProvider(raise_on_repair=True)
        prose = "some prose that is not json"
        out = _analysis_from_text(provider, prose, self.log)
        self.assertEqual(provider.repair_calls, 1)
        self.assertIn(prose[:20], out["summary"])
        self.assertEqual(out["relevant_files"], [])
        self.assertEqual(out["plan"], [])


if __name__ == "__main__":
    unittest.main()
