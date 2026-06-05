"""
Tests for the cross-iteration evidence ledger and synthesis correlation mandate.
"""

import logging
import unittest
from unittest.mock import MagicMock

from eye.services.query_processor import QueryProcessor


def _qp():
    qp = QueryProcessor.__new__(QueryProcessor)
    qp.cm = MagicMock()
    qp.logger = logging.getLogger("test-ql")
    return qp


class TestEvidenceLedger(unittest.TestCase):
    def setUp(self):
        self.qp = _qp()
        self.entries = [
            {"iteration": 1, "tool": "get_schema", "params": {"database_name": "amcache_data.db"},
             "result": {"success": True, "all_tables": ["InventoryApplication", "InventoryApplicationFile"]}},
            {"iteration": 2, "tool": "query_database",
             "params": {"database_name": "amcache_data.db", "sql_query": "SELECT name FROM InventoryApplication WHERE name LIKE '%steam%'"},
             "result": {"success": True, "database_name": "amcache_data.db", "row_count": 0}},
            {"iteration": 3, "tool": "query_database",
             "params": {"database_name": "prefetch_data.db", "sql_query": "SELECT * FROM prefetch_data"},
             "result": {"success": True, "database_name": "prefetch_data.db", "row_count": 4, "compressed": False}},
            {"iteration": 4, "tool": "get_schema", "params": {"database_name": "srum_data.db"},
             "result": {"success": False, "error": "locked database"}},
        ]

    def test_ledger_renders_per_step(self):
        text = self.qp._build_evidence_ledger(self.entries)
        self.assertIn("Evidence Gathered So Far", text)
        self.assertIn("[1] get_schema", text)
        self.assertIn("2 table(s)", text)
        self.assertIn("InventoryApplication", text)
        self.assertIn("[2] query_database", text)
        self.assertIn("/InventoryApplication", text)   # table parsed from SQL
        self.assertIn("0 row(s)", text)
        self.assertIn("[3] query_database", text)
        self.assertIn("4 row(s)", text)
        self.assertIn("[4] get_schema", text)
        self.assertIn("FAILED: locked database", text)

    def test_empty_ledger(self):
        self.assertEqual(self.qp._build_evidence_ledger([]), "")

    def test_synthesis_prompt_includes_ledger_and_correlation(self):
        ledger = self.qp._build_evidence_ledger(self.entries)
        prompt = self.qp._build_synthesis_prompt(
            "does this pc has games", [{"success": True, "data": []}], ledger_text=ledger
        )
        self.assertIn("Evidence Gathered So Far", prompt)
        self.assertIn("CROSS-SOURCE CORRELATION", prompt)
        self.assertIn("CORROBORATE", prompt)


if __name__ == "__main__":
    unittest.main()
