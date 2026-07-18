"""
Tests for two fixes:

* `search_artifacts` (ForensicSearchService) now searches across ALL discovered case
  databases (previously it was handed the case directory where a per-DB BaseDataLoader
  was expected, so it silently returned nothing).
* The Correlation Engine's RESULTS database (correlation_results.db) is surfaced as a
  queryable database ("Correlation Results") so the Eye has full query_database/get_schema
  access to the correlated data — while the raw Correlation feathers stay excluded.
"""

import os
import sqlite3
import tempfile
import unittest

from eye.services.database_service import ForensicDatabaseService
from eye.services.search_service import ForensicSearchService, SearchConfig


def _mk(path, table, cols_sql, rows):
    conn = sqlite3.connect(path)
    conn.execute(f"CREATE TABLE {table}({cols_sql})")
    if rows:
        conn.executemany(
            f"INSERT INTO {table} VALUES ({','.join('?' for _ in rows[0])})", rows)
    conn.commit()
    conn.close()


class TestCrossDatabaseSearch(unittest.TestCase):
    def setUp(self):
        self.case = tempfile.mkdtemp(prefix="xsrch_")
        self.art = os.path.join(self.case, "Target_Artifacts")
        os.makedirs(self.art)
        _mk(os.path.join(self.art, "prefetch_data.db"), "prefetch_data",
            "executable_name TEXT, filename TEXT",
            [("cmd.exe", r"C:\cmd.exe")])
        _mk(os.path.join(self.art, "amcache_data.db"), "InventoryApplicationFile",
            "name TEXT, path TEXT",
            [("cmd.exe", r"C:\Windows\cmd.exe"), ("notepad.exe", r"C:\notepad.exe")])

    def test_term_found_across_two_databases(self):
        res = ForensicSearchService(self.art).search(SearchConfig(search_term="cmd.exe"))
        self.assertGreaterEqual(res.total_matches, 2)
        dbs = {getattr(sr, "database", None)
               for rows in res.results.values() for sr in rows}
        self.assertIn("prefetch_data.db", dbs)
        self.assertIn("amcache_data.db", dbs)

    def test_term_absent_returns_nothing(self):
        res = ForensicSearchService(self.art).search(SearchConfig(search_term="zzz_not_here"))
        self.assertEqual(res.total_matches, 0)


class TestCorrelationResultsAccess(unittest.TestCase):
    def setUp(self):
        self.case = tempfile.mkdtemp(prefix="cacc_")
        self.art = os.path.join(self.case, "Target_Artifacts")
        os.makedirs(self.art)
        _mk(os.path.join(self.art, "prefetch_data.db"), "prefetch_data",
            "a TEXT", [("x",)])
        outp = os.path.join(self.case, "Correlation", "output")
        os.makedirs(outp)
        _mk(os.path.join(outp, "correlation_results.db"), "matches",
            "match_id INTEGER, match_score REAL", [(1, 0.9)])
        # A feather that must stay excluded even when correlation output exists.
        fdir = os.path.join(self.case, "Correlation", "feathers")
        os.makedirs(fdir)
        _mk(os.path.join(fdir, "prefetch.db"), "t", "a TEXT", [("y",)])
        self.ds = ForensicDatabaseService(self.art)

    def _accessible(self):
        return [d for d in self.ds.discover_databases() if d.get("accessible")]

    def test_correlation_results_surfaced(self):
        d = next((d for d in self._accessible() if d["name"] == "correlation_results.db"), None)
        self.assertIsNotNone(d)
        self.assertEqual(d["category"], "Correlation Results")
        self.assertIn("matches", d["tables"])

    def test_correlation_results_queryable(self):
        res = self.ds.execute_query("correlation_results.db",
                                    "SELECT match_id, match_score FROM matches")
        self.assertTrue(res.get("success"), res.get("error"))
        self.assertEqual(res["data"][0]["match_id"], 1)
        sch = self.ds.get_schema("correlation_results.db")
        self.assertTrue(sch.get("success"))
        self.assertIn("matches", sch.get("schema") or {})

    def test_feather_still_excluded(self):
        names = {d["name"] for d in self.ds.discover_databases()}
        self.assertNotIn("prefetch.db", names)


class TestNoCorrelationDir(unittest.TestCase):
    def test_noop_without_correlation_dir(self):
        case = tempfile.mkdtemp(prefix="nocorr_")
        art = os.path.join(case, "Target_Artifacts")
        os.makedirs(art)
        _mk(os.path.join(art, "prefetch_data.db"), "prefetch_data", "a TEXT", [("x",)])
        ds = ForensicDatabaseService(art)
        cats = [d["category"] for d in ds.discover_databases()]
        self.assertNotIn("Correlation Results", cats)


if __name__ == "__main__":
    unittest.main()
