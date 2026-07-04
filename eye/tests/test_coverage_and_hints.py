"""
Tests for coverage signals (Workstream E) and NL→SQL value hints (Workstream D).
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from eye.services.query_processor import QueryProcessor
from eye.services.context_manager import ContextManager


class TestCoverage(unittest.TestCase):
    def _qp(self, case_dir, available):
        cm = MagicMock()
        cm.case_directory = case_dir
        cm.database_service.discover_databases.return_value = [
            {"name": n, "accessible": True, "exists": True} for n in available
        ]
        qp = QueryProcessor(cm)
        return qp, cm

    def test_coverage_lists_consulted_and_gaps(self):
        case = Path(tempfile.mkdtemp())
        qp, cm = self._qp(case, ["prefetch.db", "amcache.db", "srum.db"])
        steps = []
        coverage = qp._emit_coverage({"prefetch.db", "amcache.db"}, True, "q", lambda *a, **k: steps.append(a))

        self.assertEqual(coverage["consulted"], ["amcache.db", "prefetch.db"])
        self.assertEqual(coverage["not_consulted"], ["srum.db"])
        self.assertTrue(coverage["sampled"])
        # A coverage step was emitted...
        self.assertTrue(any("coverage" in (a[0] if a else "") for a in steps))
        # ...and persisted.
        log = os.path.join(case, "EYE_Logs", "eye_coverage_log.jsonl")
        self.assertTrue(os.path.exists(log))
        with open(log, encoding="utf-8") as f:
            rec = json.loads(f.readline())
        self.assertEqual(rec["not_consulted"], ["srum.db"])

    def test_coverage_handles_no_databases(self):
        case = Path(tempfile.mkdtemp())
        qp, cm = self._qp(case, [])
        coverage = qp._emit_coverage(set(), False, "q", lambda *a, **k: None)
        self.assertEqual(coverage["consulted"], [])
        self.assertFalse(coverage["sampled"])


class TestValueHints(unittest.TestCase):
    def _cm(self):
        # Bare instance — _value_hints_for_table only uses the class-level column map.
        return ContextManager.__new__(ContextManager)

    def test_hint_from_enumerable_column(self):
        cm = self._cm()
        cols = ["rowid", "path", "type", "event_id"]
        sample = [
            {"path": "C:/a.exe", "type": "execute", "event_id": 4688},
            {"path": "C:/b.exe", "type": "load", "event_id": 4688},
        ]
        hint = cm._value_hints_for_table(cols, sample)
        self.assertIn("type=", hint)
        self.assertIn("execute", hint)
        self.assertIn("event_id=", hint)

    def test_no_hint_without_enumerable_columns(self):
        cm = self._cm()
        self.assertEqual(cm._value_hints_for_table(["path", "size"], [{"path": "x", "size": 1}]), "")

    def test_no_hint_without_samples(self):
        cm = self._cm()
        self.assertEqual(cm._value_hints_for_table(["type"], None), "")
        self.assertEqual(cm._value_hints_for_table(["type"], "not-a-list"), "")


if __name__ == "__main__":
    unittest.main()
