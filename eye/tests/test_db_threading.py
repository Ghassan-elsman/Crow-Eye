"""
Tests for thread-safe DB access (the root cause of the "internal threading
error"): get_schema / execute_query must work when called from a different
thread than where the service was created, and schemas are cached.
"""

import logging
import os
import shutil
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from eye.services.database_service import ForensicDatabaseService


def _make_service(case_dir):
    svc = ForensicDatabaseService.__new__(ForensicDatabaseService)
    svc.case_directory = Path(case_dir)
    svc.logger = logging.getLogger("test-db")
    svc._schema_cache = {}
    svc.db_manager = None  # path resolves via case_directory; db_manager unused
    return svc


class TestThreadSafeDbAccess(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = os.path.join(self.dir, "amcache_data.db")
        conn = sqlite3.connect(self.db)
        conn.execute("CREATE TABLE InventoryApplication (name TEXT, publisher TEXT)")
        conn.executemany("INSERT INTO InventoryApplication VALUES (?, ?)",
                         [("Steam", "Valve"), ("Notepad", "MS")])
        conn.execute("CREATE TABLE InventoryApplicationFile (file TEXT)")
        conn.commit()
        conn.close()
        self.svc = _make_service(self.dir)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _call_in_thread(self, fn):
        box = {}
        def run():
            try:
                box["result"] = fn()
            except Exception as e:  # pragma: no cover
                box["error"] = e
        t = threading.Thread(target=run)
        t.start(); t.join()
        if "error" in box:
            self.fail(f"cross-thread call raised: {box['error']}")
        return box["result"]

    def test_get_schema_cross_thread(self):
        res = self._call_in_thread(lambda: self.svc.get_schema("amcache_data.db"))
        self.assertTrue(res.get("success"))
        # Multi-table awareness: BOTH tables surfaced.
        self.assertEqual(set(res["all_tables"]),
                         {"InventoryApplication", "InventoryApplicationFile"})
        self.assertIn("name", res["schema"]["InventoryApplication"])
        self.assertEqual(res["row_counts"]["InventoryApplication"], 2)

    def test_execute_query_cross_thread(self):
        res = self._call_in_thread(
            lambda: self.svc.execute_query("amcache_data.db", "SELECT name FROM InventoryApplication"))
        self.assertTrue(res.get("success"))
        self.assertEqual(res["row_count"], 2)
        self.assertEqual(res["columns"], ["name"])
        self.assertEqual({r["name"] for r in res["data"]}, {"Steam", "Notepad"})

    def test_readonly_enforced(self):
        res = self.svc.execute_query("amcache_data.db", "DROP TABLE InventoryApplication")
        self.assertFalse(res.get("success"))

    def test_schema_cache_serves_on_later_failure(self):
        ok = self.svc.get_schema("amcache_data.db")
        self.assertTrue(ok.get("success"))
        # Remove the file so a live fetch would fail; cache must serve it.
        os.remove(self.db)
        served = self.svc.get_schema("amcache_data.db")
        self.assertTrue(served.get("success"))
        self.assertTrue(served.get("from_cache"))
        self.assertEqual(set(served["all_tables"]),
                         {"InventoryApplication", "InventoryApplicationFile"})


if __name__ == "__main__":
    unittest.main()
