"""
Tests for the structured result cache (computation reuse within a case) and its
integration with handle_query_database.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from eye.services.result_cache import ResultCache
from eye.services.forensic_handlers import ForensicHandlers


def _result(n):
    return {"success": True, "columns": ["a"],
            "data": [{"a": i} for i in range(n)], "row_count": n}


class TestResultCache(unittest.TestCase):
    def setUp(self):
        self.case = Path(tempfile.mkdtemp())

    def test_normalize_sql(self):
        c = ResultCache(self.case)
        self.assertEqual(c._normalize_sql("SELECT  *   FROM t ;"), "SELECT * FROM t")

    def test_put_get_full_roundtrip(self):
        c = ResultCache(self.case)
        c.put("db1", "SELECT * FROM t", _result(3))
        hit = c.get("db1", "select * from t".replace("select", "SELECT").replace("from", "FROM"))
        # Normalization is whitespace/semicolon only (case preserved); same text hits.
        hit = c.get("db1", "SELECT * FROM t ;")
        self.assertIsNotNone(hit)
        self.assertTrue(hit["full"])
        self.assertEqual(hit["row_count"], 3)
        self.assertEqual(len(hit["data"]), 3)

    def test_large_result_stored_metadata_only(self):
        c = ResultCache(self.case)
        c.put("db1", "SELECT * FROM big", _result(ResultCache.ROW_CAP + 5))
        hit = c.get("db1", "SELECT * FROM big")
        self.assertIsNotNone(hit)
        self.assertFalse(hit["full"])
        self.assertEqual(hit["row_count"], ResultCache.ROW_CAP + 5)
        self.assertLessEqual(len(hit["data"]), 5)  # only a small sample kept

    def test_persistence_round_trip(self):
        c = ResultCache(self.case)
        c.put("db1", "SELECT * FROM t", _result(2))
        c2 = ResultCache(self.case)  # fresh instance loads from disk
        self.assertIsNotNone(c2.get("db1", "SELECT * FROM t"))
        self.assertEqual(len(c2.recent(limit=5)), 1)


class TestHandlerReuse(unittest.TestCase):
    def test_identical_query_served_from_cache(self):
        case = Path(tempfile.mkdtemp())
        cm = MagicMock()
        cm.result_cache = ResultCache(case)
        cm.database_service.execute_query.return_value = _result(3)
        handler = ForensicHandlers(cm)

        params = {"database_name": "db1", "sql_query": "SELECT * FROM t"}
        r1 = handler.handle_query_database(params)
        r2 = handler.handle_query_database(params)

        # The DB was queried exactly once; the second call came from cache.
        self.assertEqual(cm.database_service.execute_query.call_count, 1)
        self.assertTrue(r2.get("cached"))
        self.assertEqual(r2.get("row_count"), 3)
        self.assertFalse(r1.get("cached", False))


if __name__ == "__main__":
    unittest.main()
