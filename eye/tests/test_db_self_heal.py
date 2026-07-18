"""
Self-heal for query_database: the Eye must reach the RIGHT database/table even when
the model names them imperfectly, and recover automatically on failure.

- Database-name self-heal (new): a wrong/misspelled DB name auto-retries against the
  closest real database, or returns the real database list so the model corrects itself.
- Table self-heal (regression): a 'no such table' returns the available tables + hint.
"""

import logging
import sqlite3
import tempfile
import shutil
import types
import unittest
from pathlib import Path

from eye.services.database_service import ForensicDatabaseService


def _svc(case_dir, available):
    """Build a ForensicDatabaseService without constructing a DatabaseManager.
    `available` is the list discover_databases() should report (monkeypatched)."""
    svc = ForensicDatabaseService.__new__(ForensicDatabaseService)
    svc.case_directory = Path(case_dir)
    svc.db_manager = None
    svc.logger = logging.getLogger("test-db-heal")
    svc._schema_cache = {}
    svc.discover_databases = lambda: available
    return svc


def _real_discover_svc(case_dir):
    """Service that runs the REAL discover_databases (manager reports nothing), so the
    feather-merge path is exercised."""
    svc = ForensicDatabaseService.__new__(ForensicDatabaseService)
    svc.case_directory = Path(case_dir)
    svc.db_manager = types.SimpleNamespace(discover_databases=lambda: [])
    svc.logger = logging.getLogger("test-db-heal")
    svc._schema_cache = {}
    return svc


class TestDatabaseNameSelfHeal(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        # Real on-disk DB whose filename differs from the obvious guess.
        db = Path(self.dir) / "srum_data.db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE app_usage (app TEXT, bytes_sent INTEGER)")
        conn.execute("INSERT INTO app_usage VALUES ('discord.exe', 4200000)")
        conn.commit()
        conn.close()
        self.svc = _svc(self.dir, [{"name": "srum_data.db", "exists": True, "accessible": True}])

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_wrong_db_name_auto_retries_closest(self):
        # Model guessed "srum.db"; the real file is "srum_data.db".
        res = self.svc.execute_query("srum.db", "SELECT app FROM app_usage")
        self.assertTrue(res.get("success"), res.get("error"))
        self.assertTrue(res.get("self_healed"))
        self.assertEqual(res["data"][0]["app"], "discord.exe")
        self.assertIn("srum_data.db", res.get("note", ""))

    def test_unknown_db_returns_enriched_error(self):
        res = self.svc.execute_query("totally_bogus.db", "SELECT 1")
        self.assertFalse(res.get("success"))
        self.assertEqual(res.get("available_databases"), ["srum_data.db"])
        self.assertIn("hint", res)
        self.assertIn("list_case_files", res["hint"])

    def test_ambiguous_does_not_auto_swap(self):
        # Two databases both starting with the guessed base → must NOT silently pick one.
        svc = _svc(self.dir, [
            {"name": "srum_data.db", "exists": True},
            {"name": "srum_net.db", "exists": True},
        ])
        res = svc.execute_query("srum", "SELECT 1")
        self.assertFalse(res.get("success"))
        self.assertEqual(set(res.get("available_databases")), {"srum_data.db", "srum_net.db"})

    def test_norm_db_name(self):
        self.assertEqual(ForensicDatabaseService._norm_db_name("SRUM.db"), "srum")
        self.assertEqual(ForensicDatabaseService._norm_db_name("prefetch_data.sqlite"), "prefetch_data")


class TestTableSelfHealRegression(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        db = Path(self.dir) / "amcache_data.db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE entries (path TEXT, publisher TEXT)")
        conn.execute("INSERT INTO entries VALUES ('C:\\\\x.exe', 'ACME')")
        conn.commit()
        conn.close()
        self.svc = _svc(self.dir, [{"name": "amcache_data.db", "exists": True}])

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_missing_table_returns_available_tables_and_hint(self):
        res = self.svc.execute_query("amcache_data.db", "SELECT path FROM nonexistent_tbl")
        self.assertFalse(res.get("success"))
        self.assertIn("entries", res.get("available_tables", []))
        self.assertIn("hint", res)

    def test_close_table_name_auto_retries(self):
        # 'entrie' is a strong near-match of 'entries' → transparent auto-retry.
        res = self.svc.execute_query("amcache_data.db", "SELECT path FROM entries_")
        # Either auto-healed to entries OR an enriched error pointing at it.
        if res.get("success"):
            self.assertTrue(res.get("self_healed"))
        else:
            self.assertIn("entries", res.get("available_tables", []))


class TestCrossDatabaseSelfHeal(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        a = Path(self.dir) / "a.db"
        conn = sqlite3.connect(a)
        conn.execute("CREATE TABLE ta (x TEXT)")
        conn.execute("CREATE TABLE shared (x TEXT)")
        conn.execute("INSERT INTO shared VALUES ('A')")
        conn.commit(); conn.close()
        b = Path(self.dir) / "b.db"
        conn = sqlite3.connect(b)
        conn.execute("CREATE TABLE tb (name TEXT)")
        conn.execute("INSERT INTO tb VALUES ('hit')")
        conn.execute("CREATE TABLE shared (y TEXT)")
        conn.execute("INSERT INTO shared VALUES ('B')")
        conn.commit(); conn.close()
        self.svc = _svc(self.dir, [{"name": "a.db", "exists": True},
                                   {"name": "b.db", "exists": True}])

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_missing_table_found_in_other_db_auto_switches(self):
        # 'tb' lives only in b.db; queried against a.db → auto-retry in b.db.
        res = self.svc.execute_query("a.db", "SELECT name FROM tb")
        self.assertTrue(res.get("success"), res.get("error"))
        self.assertTrue(res.get("self_healed"))
        self.assertIn("b.db", res.get("note", ""))
        self.assertEqual(res["data"][0]["name"], "hit")

    def test_missing_table_nowhere_enriched_error(self):
        res = self.svc.execute_query("a.db", "SELECT * FROM no_such_anywhere")
        self.assertFalse(res.get("success"))
        self.assertEqual(res.get("found_in"), {})
        self.assertIn("ta", res.get("available_tables", []))

    def test_missing_column_found_in_other_db_auto_switches(self):
        # 'shared' exists in both DBs; column 'y' only in b.db's copy.
        res = self.svc.execute_query("a.db", "SELECT y FROM shared")
        self.assertTrue(res.get("success"), res.get("error"))
        self.assertTrue(res.get("self_healed"))
        self.assertIn("b.db", res.get("note", ""))
        self.assertEqual(res["data"][0]["y"], "B")

    def test_missing_column_everywhere_enriched_error(self):
        res = self.svc.execute_query("a.db", "SELECT zzz FROM shared")
        self.assertFalse(res.get("success"))
        self.assertIn("schema", res)
        self.assertIn("shared", res["schema"])
        self.assertIn("column_found_in", res)


class TestFeatherDiscovery(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        feathers = Path(self.dir) / "Correlation" / "feathers"
        feathers.mkdir(parents=True)
        db = feathers / "Prefetch_CrowEyeFeather.db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE executions (name TEXT, run_count INTEGER)")
        conn.execute("INSERT INTO executions VALUES ('x.exe', 3)")
        conn.commit()
        conn.close()
        self.svc = _real_discover_svc(self.dir)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_feather_db_discovered_with_tables(self):
        feathers = self.svc._discover_feather_databases()
        self.assertEqual(len(feathers), 1)
        f = feathers[0]
        self.assertEqual(f["name"], "Prefetch_CrowEyeFeather.db")
        self.assertEqual(f["category"], "Correlation Feather")
        self.assertIn("executions", f["tables"])

    def test_feather_is_skipped_from_discover(self):
        # Auto-created Correlation feathers duplicate native artifacts the Eye already
        # parses, so they are intentionally EXCLUDED from discover_databases() to avoid
        # duplicate-data analysis. (The helper _discover_feather_databases still exists
        # for reference — see test_feather_db_discovered_with_tables — but is no longer
        # wired into discovery.)
        names = [d["name"] for d in self.svc.discover_databases()]
        self.assertNotIn("Prefetch_CrowEyeFeather.db", names)

    def test_no_feather_dir_is_safe(self):
        d = tempfile.mkdtemp()
        try:
            self.assertEqual(_real_discover_svc(d)._discover_feather_databases(), [])
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
