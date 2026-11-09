"""Database Search on threads finds exactly what it found table by table.

The whole-case search ran one table after another, 47.6 s on a live parse of
this machine. sqlite3 releases the GIL while a query runs, so the tables are
now searched SEARCH_THREADS at a time (14.4 s on the same case, the same 5,086
hits). Each check names what a careless version gets wrong:

- the hits, per database, equal the table-by-table path's: the same rows, the
  same per-table cap (max(100, max_results // tables in that database)), the
  same cut at max_results per database in table order, the same truncation;
- a column named for an SQL keyword (`exists`, which AmCache has) is searched,
  not a syntax error that reads as "no matches";
- the Timeline's day map (Timeline/day_index.db) is not a database to search.
"""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from data.unified_search_engine import UnifiedDatabaseSearchEngine
from data.base_loader import BaseDataLoader
from data.database_manager import DatabaseManager


def _case():
    root = tempfile.mkdtemp(prefix="srch_")
    ta = os.path.join(root, "Target_Artifacts")
    os.makedirs(ta)
    # one database with many matching rows in several tables, one small one
    big = sqlite3.connect(os.path.join(ta, "big_custom.db"))
    for t in ("alpha", "beta", "gamma"):
        big.execute("CREATE TABLE %s (name TEXT, path TEXT)" % t)
        big.executemany("INSERT INTO %s VALUES (?, ?)" % t,
                        [("chrome %d" % i, "C:/x/%s/%d" % (t, i)) for i in range(400)])
    big.commit()
    big.close()
    small = sqlite3.connect(os.path.join(ta, "small_custom.db"))
    small.execute('CREATE TABLE inv (name TEXT, "exists" TEXT, "value" TEXT)')
    small.executemany("INSERT INTO inv VALUES (?, ?, ?)",
                      [("a", "AdvertisingID_77", "1"), ("chrome", "x", "2"), ("b", "y", "3")])
    small.commit()
    small.close()
    tl = os.path.join(root, "Timeline")
    os.makedirs(tl)
    d = sqlite3.connect(os.path.join(tl, "day_index.db"))
    d.execute("CREATE TABLE days_x (day INTEGER, rid INTEGER, PRIMARY KEY (day, rid)) WITHOUT ROWID")
    d.commit()
    d.close()
    return root


def _hits(results):
    return {(r.database_name, h.table_name, str(h.row_id))
            for r in results for h in r.get_all_results()}


class SearchOnThreads(unittest.TestCase):

    def setUp(self):
        self.root = _case()
        self.eng = UnifiedDatabaseSearchEngine(self.root)

    def test_threads_find_what_table_by_table_found(self):
        for cap in (1000, 300):              # 300: a database is cut at its cap
            threaded = self.eng.search(search_term="chrome", max_results_per_table=cap,
                                       timeout_seconds=60)
            infos = [d for d in self.eng.discover_databases_with_metadata()
                     if getattr(d, "accessible", False) and d.name.endswith("_custom.db")]
            sequential = [self.eng._search_database(
                db_info=d, search_term="chrome", tables=None, case_sensitive=False,
                exact_match=False, max_results=cap, timeout_seconds=60) for d in infos]
            mine = [r for r in threaded if r.database_name.endswith("_custom.db")]
            self.assertEqual(_hits(mine), _hits(sequential), cap)
            by = {r.database_name: (r.total_matches, r.truncated, r.tables_searched)
                  for r in mine}
            ref = {r.database_name: (r.total_matches, r.truncated, r.tables_searched)
                   for r in sequential}
            self.assertEqual(by, ref, cap)
        # the cut really happened at 300 (3 tables x 400 matching rows)
        self.assertEqual(by["big_custom.db"][:2], (300, True))

    def test_a_keyword_column_is_searched(self):
        loader = BaseDataLoader(os.path.join(self.root, "Target_Artifacts", "small_custom.db"))
        loader.connect()
        try:
            hit = loader.search_table("inv", "AdvertisingID", page=1, page_size=10)
            self.assertEqual(hit["total_count"], 1)
            exact = loader.search_table("inv", "advertisingid_77", exact_match=True,
                                        page=1, page_size=10)
            self.assertEqual(exact["total_count"], 1)
        finally:
            loader.disconnect()

    def test_the_timeline_day_map_is_not_searched(self):
        names = [str(d.path) for d in DatabaseManager(Path(self.root)).discover_databases()]
        self.assertFalse(any(n.endswith("day_index.db") for n in names), names)
        self.assertTrue(any(n.endswith("small_custom.db") for n in names), names)


if __name__ == "__main__":
    unittest.main()
