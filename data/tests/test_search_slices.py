"""A large table searched in rowid slices finds exactly what one scan found.

Database Search ran each table as one task, so the largest table bounded the
whole search: the 43-column LIKE over 3.9 M correlated MFT/USN rows, 16.6 s on
a live parse of this machine, while the other threads sat idle. A table of
SLICE_ROWS * 2 rowids or more is now read as up to SEARCH_SLICES slices, each a
task on the pool. What a careless version gets wrong:

- the slices miss rowids: a gap between two, or the rows written after the
  plan read the largest rowid;
- the table's cap is applied per slice, so a table returns cap rows per slice
  instead of cap rows;
- the cap keeps the most relevant rows of every slice instead of the first
  rows in rowid order, which is what one scan keeps;
- a WITHOUT ROWID table cannot be sliced and is skipped instead of read whole;
- the search still counts every match past the page, a second full scan
  nobody reads (DatabaseSearchEngine reads only "any match").
"""
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

import data.unified_search_engine as use
from data.base_loader import BaseDataLoader
from data.search_engine import DatabaseSearchEngine
from data.unified_search_engine import UnifiedDatabaseSearchEngine, rowid_slices


def _case(rows=5000):
    root = tempfile.mkdtemp(prefix="slices_")
    ta = os.path.join(root, "Target_Artifacts")
    os.makedirs(ta)
    conn = sqlite3.connect(os.path.join(ta, "big_custom.db"))
    conn.execute("CREATE TABLE ev (name TEXT, path TEXT, n INTEGER)")
    conn.executemany("INSERT INTO ev VALUES (?, ?, ?)",
                     [("chrome %d" % i if i % 7 == 0 else "other %d" % i,
                       "C:/x/chrome/%d" % i if i % 11 == 0 else "C:/y/%d" % i, i)
                      for i in range(rows)])
    # gaps in the rowids, as deletes leave them
    conn.execute("DELETE FROM ev WHERE rowid % 97 = 0")
    conn.execute("CREATE TABLE kv (k TEXT PRIMARY KEY, v TEXT) WITHOUT ROWID")
    conn.executemany("INSERT INTO kv VALUES (?, ?)", [("k%d" % i, "chrome") for i in range(50)])
    conn.commit()
    conn.close()
    return root


def _hits(results):
    return sorted((r.database_name, h.table_name, h.record_data.get("_rowid_"),
                   h.record_data.get("k"))
                  for r in results for h in r.get_all_results())


class TheSlices(unittest.TestCase):

    def test_they_cover_every_rowid_and_nothing_twice(self):
        self.assertIsNone(rowid_slices(None, None))
        self.assertIsNone(rowid_slices(1, use.SLICE_ROWS * 2 - 1))
        parts = rowid_slices(5, 5 + use.SLICE_ROWS * 7, slice_rows=use.SLICE_ROWS)
        self.assertLessEqual(len(parts), use.SEARCH_SLICES)
        self.assertEqual(parts[0][0], -(2 ** 63))
        self.assertEqual(parts[-1][1], 2 ** 63 - 1)
        for (a, b), (c, d) in zip(parts, parts[1:]):
            self.assertEqual(b + 1, c)
            self.assertLessEqual(a, b)
        many = rowid_slices(1, 10 ** 9)
        self.assertEqual(len(many), use.SEARCH_SLICES)


class SlicedFindsWhatOneScanFound(unittest.TestCase):

    def setUp(self):
        self.root = _case()
        self.eng = UnifiedDatabaseSearchEngine(self.root)

    def _search(self, cap, slice_rows):
        with mock.patch.object(use, "SLICE_ROWS", slice_rows), \
                mock.patch.object(use, "rowid_slices",
                                  lambda lo, hi: rowid_slices(lo, hi, slice_rows=slice_rows)):
            out = self.eng.search(search_term="chrome", max_results_per_table=cap,
                                  timeout_seconds=60)
        return [r for r in out if r.database_name.endswith("_custom.db")]

    def test_the_same_rows_the_same_cut(self):
        for cap in (100, 300, 5000):
            whole = self._search(cap, 10 ** 9)          # never sliced
            sliced = self._search(cap, 400)              # about a dozen slices
            self.assertEqual(_hits(whole), _hits(sliced), cap)
            self.assertEqual([(r.total_matches, r.truncated, r.tables_searched) for r in whole],
                             [(r.total_matches, r.truncated, r.tables_searched) for r in sliced], cap)

    def test_the_cut_keeps_the_first_rows_not_the_best_per_slice(self):
        # two tables in the database: each keeps max(100, 240 // 2) rows
        sliced = self._search(240, 400)
        rowids = sorted(h[2] for h in _hits(sliced) if h[1] == "ev")
        conn = sqlite3.connect(os.path.join(self.root, "Target_Artifacts", "big_custom.db"))
        want = [r[0] for r in conn.execute(
            "SELECT rowid FROM ev WHERE name LIKE '%chrome%' OR path LIKE '%chrome%' "
            "OR n LIKE '%chrome%' ORDER BY rowid LIMIT 120")]
        conn.close()
        self.assertEqual(want, rowids)


class NoSecondCount(unittest.TestCase):

    def test_the_search_engine_never_counts_past_the_page(self):
        root = _case(3000)
        loader = BaseDataLoader(os.path.join(root, "Target_Artifacts", "big_custom.db"))
        self.assertTrue(loader.connect())
        seen = []
        loader.connection.set_trace_callback(seen.append)
        try:
            got = DatabaseSearchEngine(loader, enable_cache=False).search(
                "chrome", tables=["ev"], max_results=100)
        finally:
            loader.connection.set_trace_callback(None)
            loader.disconnect()
        self.assertEqual(100, got.total_matches)
        self.assertFalse([q for q in seen if "COUNT(*)" in q.upper()], seen)

    def test_a_slice_of_the_table_is_only_that_slice(self):
        root = _case(3000)
        loader = BaseDataLoader(os.path.join(root, "Target_Artifacts", "big_custom.db"))
        self.assertTrue(loader.connect())
        try:
            got = loader.search_table("ev", "chrome", page_size=5000, rowid_range=(1000, 1999))
            # the exact total still answers when asked for
            assert got["total_count"] == len(got["data"])
        finally:
            loader.disconnect()
        rowids = [r["_rowid_"] for r in got["data"]]
        self.assertTrue(rowids)
        self.assertTrue(all(1000 <= x <= 1999 for x in rowids))


if __name__ == "__main__":
    unittest.main()
