"""
Tests for TOON large-result compression (audit Pass 3):
- query_database compresses only above the 200-row threshold.
- the toon_compression_docs are injected into the system prompt.
"""

import logging
import unittest
from unittest.mock import MagicMock

from eye.services.forensic_handlers import ForensicHandlers
from eye.services.context_manager import ContextManager
from eye.services.token_counter import TokenCounter


class TestQueryDatabaseCompressionThreshold(unittest.TestCase):
    def _handlers(self, row_count):
        rows = [{"i": i} for i in range(row_count)]
        cm = MagicMock()
        cm.database_service.execute_query.return_value = {
            "success": True, "data": rows, "columns": ["i"], "row_count": row_count,
        }
        fh = ForensicHandlers.__new__(ForensicHandlers)
        fh.cm = cm
        fh.logger = logging.getLogger("test-fh")
        return fh

    def test_below_threshold_returns_full(self):
        fh = self._handlers(150)
        res = fh.handle_query_database({"database_name": "x.db", "sql_query": "SELECT *"})
        self.assertNotIn("compressed", res)
        self.assertEqual(len(res["data"]), 150)

    def test_above_threshold_compresses_to_sample(self):
        fh = self._handlers(250)
        res = fh.handle_query_database({"database_name": "x.db", "sql_query": "SELECT *"})
        self.assertTrue(res.get("compressed"))
        self.assertEqual(res["row_count"], 250)
        self.assertEqual(len(res["rows"]), 20)          # first 10 + last 10
        self.assertEqual(len(res["full_rows"]), 250)    # full data preserved for UI/report
        self.assertIn("analyze_large_dataset", res["toon_summary"])

    def test_exactly_threshold_not_compressed(self):
        fh = self._handlers(200)
        res = fh.handle_query_database({"database_name": "x.db", "sql_query": "SELECT *"})
        self.assertNotIn("compressed", res)


class TestToonDocsInjected(unittest.TestCase):
    def test_docs_appear_in_system_prompt(self):
        cm = ContextManager.__new__(ContextManager)
        cm.logger = logging.getLogger("test-cm")
        cm.token_counter = TokenCounter(backend="gpt-4")
        cm.max_total_tokens = 200_000
        cm.token_budget = {"system_prompt": 100_000}
        cm.case_context_manager = None
        cm.report_engine = None
        cm.database_service = None
        cm._db_manifest_cache = None
        cm.llm_config = {
            "system_prompt_template": ["# EYE"],
            "tools": [],
            "toon_compression_docs": ["## TOON_SENTINEL_BLOCK", "sample-not-full guidance"],
        }
        prompt = cm._build_system_prompt("", [])
        self.assertIn("TOON_SENTINEL_BLOCK", prompt)


if __name__ == "__main__":
    unittest.main()
