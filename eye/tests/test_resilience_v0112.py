"""
Tests for v0.11.2 resilience features:
  - ModelRouter.generate central transient-retry + backoff (Gemini 500 fix).
  - Transparent auto map-reduce for big query results (+ AUTO_MAPREDUCE audit).
  - Overflow auto-recovery via map-reduce instead of a refusal.
"""

import logging
import unittest
from unittest.mock import MagicMock, patch

from eye.services.model_router import ModelRouter, is_transient_model_error
from eye.services.query_processor import QueryProcessor


class TestTransientClassifier(unittest.TestCase):
    def test_transient_vs_permanent(self):
        self.assertTrue(is_transient_model_error(Exception("500 INTERNAL")))
        self.assertTrue(is_transient_model_error(Exception("overloaded_error")))
        self.assertTrue(is_transient_model_error(Exception("503 UNAVAILABLE")))
        self.assertFalse(is_transient_model_error(Exception("401 Unauthorized")))
        self.assertFalse(is_transient_model_error(Exception("429 RESOURCE_EXHAUSTED quota")))


class TestModelRouterRetry(unittest.TestCase):
    def _router(self, attempts=3):
        r = ModelRouter.__new__(ModelRouter)  # skip _initialize_backend
        r.logger = logging.getLogger("test-router")
        r.config = {"backend": "gemini", "model_name": "g",
                    "reasoning": {"model_retry_max_attempts": attempts}}
        r.backend = MagicMock()
        return r

    @patch("time.sleep", return_value=None)
    def test_retries_transient_then_succeeds(self, _s):
        r = self._router(attempts=3)
        calls = {"n": 0}
        def gen(*a, **k):
            calls["n"] += 1
            if calls["n"] < 3:
                raise Exception("500 INTERNAL")
            return {"content": "ok", "tool_calls": []}
        r.backend.generate.side_effect = gen
        retries = []
        out = r.generate("sys", "msg", on_retry=lambda att, exc: retries.append(att))
        self.assertEqual(out["content"], "ok")
        self.assertEqual(r.backend.generate.call_count, 3)
        self.assertEqual(len(retries), 2)  # two retries before the 3rd success

    @patch("time.sleep", return_value=None)
    def test_permanent_error_raises_immediately(self, _s):
        r = self._router(attempts=3)
        r.backend.generate.side_effect = Exception("401 Unauthorized")
        with self.assertRaises(Exception):
            r.generate("sys", "msg")
        self.assertEqual(r.backend.generate.call_count, 1)  # no retry on auth error

    @patch("time.sleep", return_value=None)
    def test_exhausts_attempts_then_raises(self, _s):
        r = self._router(attempts=2)
        r.backend.generate.side_effect = Exception("503 UNAVAILABLE")
        with self.assertRaises(Exception):
            r.generate("sys", "msg")
        self.assertEqual(r.backend.generate.call_count, 2)


_FAKE_MR = MagicMock()


class TestAutoMapReduce(unittest.TestCase):
    def setUp(self):
        self.qp = QueryProcessor(MagicMock())
        self.qp.cm.truncation_auditor = MagicMock()

    def _big_result(self, rows=2000):
        return {
            "tool_name": "query_database", "success": True,
            "result": {
                "row_count": rows,
                "full_rows": [{"a": i} for i in range(rows)],
                "columns": ["a"],
                "database_name": "x.db",
                "sql_query": "SELECT a FROM t",
            },
        }

    def test_big_result_routes_through_map_reduce(self):
        call = {"name": "query_database", "parameters": {"database_name": "x.db", "sql_query": "SELECT a FROM t"}}
        cfg = {"enable_auto_map_reduce": True, "auto_map_reduce_row_threshold": 1500}
        with patch("eye.services.map_reduce_service.MapReduceService") as MR:
            MR.return_value.analyze.return_value = {"success": True, "summary": "ALL ROWS SUMMARY", "chunks_processed": 4}
            out = self.qp._maybe_auto_map_reduce(call, self._big_result(), "find anomalies", cfg, lambda *a, **k: None)
        self.assertTrue(out["result"]["auto_map_reduced"])
        self.assertEqual(out["result"]["summary"], "ALL ROWS SUMMARY")
        self.assertEqual(out["result"]["full_rows"][0], {"a": 0})  # kept for the report
        # AUTO_MAPREDUCE audit event written.
        actions = [c.kwargs.get("action") for c in self.qp.cm.truncation_auditor.log_event.call_args_list]
        self.assertIn("AUTO_MAPREDUCE", actions)

    def test_small_result_unchanged(self):
        call = {"name": "query_database", "parameters": {}}
        cfg = {"enable_auto_map_reduce": True, "auto_map_reduce_row_threshold": 1500}
        small = self._big_result(rows=10)
        out = self.qp._maybe_auto_map_reduce(call, small, "q", cfg, lambda *a, **k: None)
        self.assertIs(out, small)  # untouched

    def test_disabled_unchanged(self):
        call = {"name": "query_database", "parameters": {}}
        cfg = {"enable_auto_map_reduce": False, "auto_map_reduce_row_threshold": 1500}
        big = self._big_result()
        out = self.qp._maybe_auto_map_reduce(call, big, "q", cfg, lambda *a, **k: None)
        self.assertIs(out, big)


class TestOverflowRecovery(unittest.TestCase):
    def setUp(self):
        self.qp = QueryProcessor(MagicMock())
        self.qp.cm.truncation_auditor = MagicMock()
        self.qp.cm.case_directory = None

    def test_recovers_via_map_reduce(self):
        ledger = [{"tool": "query_database", "params": {"database_name": "x.db", "sql_query": "SELECT * FROM big"},
                   "result": {"database_name": "x.db", "sql_query": "SELECT * FROM big"}}]
        cfg = {"enable_auto_map_reduce": True}
        with patch("eye.services.map_reduce_service.MapReduceService") as MR:
            MR.return_value.analyze.return_value = {"success": True, "summary": "RECOVERED", "chunks_processed": 5}
            out = self.qp._overflow_auto_map_reduce(ledger, "q", cfg, lambda *a, **k: None)
        self.assertIsNotNone(out)
        self.assertIn("RECOVERED", out["response"])
        actions = [c.kwargs.get("action") for c in self.qp.cm.truncation_auditor.log_event.call_args_list]
        self.assertIn("AUTO_MAPREDUCE", actions)

    def test_no_candidate_returns_none(self):
        out = self.qp._overflow_auto_map_reduce([], "q", {"enable_auto_map_reduce": True}, lambda *a, **k: None)
        self.assertIsNone(out)


if __name__ == "__main__":
    unittest.main()
