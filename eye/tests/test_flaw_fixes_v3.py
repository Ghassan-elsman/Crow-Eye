"""
Regression tests for flaw-hunt #3 (database / history / map-reduce / evidence-seal):
  F1 - REPLACE() scalar function is allowed; REPLACE INTO / writes still rejected.
  F2 - history summarization does not drop a message appended during the LLM call.
  F3 - _summarize_chunk seals its model call (chain of custody).
  F4 - map-reduce chunk budget accounts for the system-prompt overhead.
"""

import logging
import unittest
from unittest.mock import MagicMock

from eye.services.history_manager import HistoryManager
from eye.services.map_reduce_service import MapReduceService
from eye.services.token_counter import TokenCounter
from eye.services.database_service import ForensicDatabaseService


# ---------------------------------------------------------------------------
# F1 — read-only validation
# ---------------------------------------------------------------------------
class TestReadOnlyValidation(unittest.TestCase):
    def setUp(self):
        # Bypass DatabaseManager init — _is_readonly_query only needs class attrs + logger.
        self.svc = ForensicDatabaseService.__new__(ForensicDatabaseService)
        self.svc.logger = logging.getLogger("t")

    def test_replace_function_allowed(self):
        self.assertTrue(self.svc._is_readonly_query(
            "SELECT REPLACE(file_path, '\\', '/') AS p FROM mft"))

    def test_replace_into_blocked(self):
        self.assertFalse(self.svc._is_readonly_query("REPLACE INTO t (a) VALUES (1)"))

    def test_plain_select_allowed(self):
        self.assertTrue(self.svc._is_readonly_query("SELECT * FROM prefetch_data LIMIT 10"))

    def test_writes_still_blocked(self):
        for q in ("UPDATE t SET a=1", "DELETE FROM t", "INSERT INTO t VALUES(1)",
                  "DROP TABLE t", "ATTACH DATABASE 'x' AS y"):
            self.assertFalse(self.svc._is_readonly_query(q), q)

    def test_like_literal_not_a_false_positive(self):
        # 'UPDATE' inside a string literal must not trip the filter.
        self.assertTrue(self.svc._is_readonly_query(
            "SELECT * FROM logs WHERE msg LIKE '%UPDATE%'"))


# ---------------------------------------------------------------------------
# F2 / F3 — history summarization
# ---------------------------------------------------------------------------
class TestHistorySummarization(unittest.TestCase):
    def _cm(self, usable=10):
        cm = MagicMock()
        cm.token_counter = TokenCounter(backend="gpt-4")
        cm.usable_context_tokens.return_value = usable
        cm.truncation_auditor = None
        cm.evidence_seal = MagicMock()
        cm.model_router.config = {"model_name": "m"}
        cm.model_router.generate.return_value = {"content": "concise summary"}
        cm.max_total_tokens = 8192
        cm.truncation_count = 0
        return cm

    def _msg(self, i, **md):
        return {"id": f"m{i}", "role": "user", "content": f"message {i}",
                "token_count": 100, "metadata": md}

    def test_no_lost_update_when_message_appended_during_summarize(self):
        cm = self._cm(usable=10)  # tiny budget → summarization triggers
        hm = HistoryManager(cm)
        hm.history = [self._msg(i) for i in range(8)]  # len>6 so mid block exists

        # Simulate a message appended DURING the (now lock-free) LLM call.
        def fake_summary(messages):
            hm.history.append(self._msg(99))  # concurrent append
            return "SUMMARY OF PREVIOUS ACTIVITY: x"
        hm._summarize_chunk = fake_summary

        hm.manage_history()

        ids = [m["id"] for m in hm.history]
        self.assertIn("m99", ids, "message appended during summarization was lost")
        self.assertTrue(any(m.get("metadata", {}).get("is_summary") for m in hm.history))

    def test_summarize_chunk_is_sealed(self):
        cm = self._cm(usable=100000)
        hm = HistoryManager(cm)
        hm._summarize_chunk([self._msg(1), self._msg(2)])
        cm.evidence_seal.seal.assert_called_once()
        kwargs = cm.evidence_seal.seal.call_args.kwargs
        self.assertEqual(kwargs.get("phase"), "history_summarize")

    def test_preserved_messages_survive_summarization(self):
        cm = self._cm(usable=10)
        hm = HistoryManager(cm)
        hm.history = [self._msg(0)] + [self._msg(1, preserve_evidence=True)] + \
                     [self._msg(i) for i in range(2, 8)]
        hm._summarize_chunk = lambda msgs: "SUMMARY OF PREVIOUS ACTIVITY: x"
        hm.manage_history()
        self.assertIn("m1", [m["id"] for m in hm.history])  # preserved kept


# ---------------------------------------------------------------------------
# F4 — map-reduce effective chunk budget
# ---------------------------------------------------------------------------
class TestMapReduceBudget(unittest.TestCase):
    def _cm(self, max_tokens, sysp):
        cm = MagicMock()
        cm.token_counter = TokenCounter(backend="gpt-4")
        cm.max_total_tokens = max_tokens
        cm._build_system_prompt.return_value = sysp
        cm.model_router.config = {"model_name": "m"}
        cm.model_router.generate.return_value = {"content": "No anomalies in this batch."}
        cm.evidence_seal = MagicMock()
        return cm

    def test_all_rows_covered_on_large_window(self):
        cm = self._cm(200000, "SYS")
        cm.database_service.execute_query.return_value = {
            "success": True, "data": [{"a": i} for i in range(25)]}
        out = MapReduceService(cm).analyze("db", "SELECT *", "find x", chunk_token_budget=3000)
        self.assertTrue(out["success"])
        self.assertEqual(out["rows_analyzed"], 25)

    def test_row_refused_when_sysp_eats_the_window(self):
        # Tiny window + large system prompt => effective budget shrinks, so a row
        # that would fit the RAW 3000 budget is correctly refused.
        cm = self._cm(2000, "word " * 4000)
        cm.database_service.execute_query.return_value = {
            "success": True, "data": [{"a": "x" * 4000}]}
        out = MapReduceService(cm).analyze("db", "SELECT *", "find x", chunk_token_budget=3000)
        self.assertFalse(out["success"])
        self.assertIn("per-chunk budget", out["error"])


if __name__ == "__main__":
    unittest.main()
