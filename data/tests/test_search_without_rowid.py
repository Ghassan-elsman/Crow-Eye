"""Database Search reads a WITHOUT ROWID table, and not an index's internals.

Every read selected `rowid as _rowid_`, so a WITHOUT ROWID table errored with
"no such column: rowid" and the search reported it as no matches: its rows
were never searchable. The shadow tables SQLite keeps behind a virtual table
(correlation_results.db's matches_fts_idx and matches_fts_config) errored the
same way, and are index internals, never evidence. What a careless fix gets
wrong:

- the WITHOUT ROWID table is skipped instead of read;
- a table whose own text merely mentions WITHOUT ROWID (a column default) is
  taken for one and loses its rowid;
- the shadow tables are searched once they stop erroring, so a term matches
  index bytes and reads as evidence;
- the virtual table itself (the FTS table) is dropped with its shadows.
"""
import os
import sqlite3
import tempfile
import unittest

from data.base_loader import BaseDataLoader
from data.unified_search_engine import UnifiedDatabaseSearchEngine


def _case():
    root = tempfile.mkdtemp(prefix="norowid_")
    ta = os.path.join(root, "Target_Artifacts")
    os.makedirs(ta)
    conn = sqlite3.connect(os.path.join(ta, "kv_custom.db"))
    conn.execute("CREATE TABLE kv (k TEXT PRIMARY KEY, v TEXT) WITHOUT ROWID")
    conn.executemany("INSERT INTO kv VALUES (?, ?)", [("k%d" % i, "chrome %d" % i) for i in range(5)])
    conn.execute("CREATE TABLE note (body TEXT DEFAULT 'kept WITHOUT ROWID text')")
    conn.execute("INSERT INTO note VALUES ('chrome note')")
    conn.execute("CREATE VIRTUAL TABLE docs USING fts5(body)")
    conn.executemany("INSERT INTO docs VALUES (?)", [("chrome in the index",), ("other",)])
    conn.commit()
    conn.close()
    return root


class WithoutRowid(unittest.TestCase):

    def setUp(self):
        self.root = _case()
        self.path = os.path.join(self.root, "Target_Artifacts", "kv_custom.db")

    def test_a_without_rowid_table_is_read_with_no_rowid(self):
        loader = BaseDataLoader(self.path)
        self.assertTrue(loader.connect())
        try:
            got = loader.search_table("kv", "chrome", page_size=100)
            self.assertEqual(5, len(got["data"]))
            self.assertTrue(all(r["_rowid_"] is None for r in got["data"]))
            note = loader.search_table("note", "chrome", page_size=100)
            self.assertEqual([1], [r["_rowid_"] for r in note["data"]])
        finally:
            loader.disconnect()

    def test_the_search_finds_it_and_skips_the_index_internals(self):
        out = UnifiedDatabaseSearchEngine(self.root).search(
            search_term="chrome", max_results_per_table=1000, timeout_seconds=60)
        tables = sorted({h.table_name for r in out if r.database_name.endswith("kv_custom.db")
                         for h in r.get_all_results()})
        self.assertEqual(["docs", "kv", "note"], tables)
        shadow = UnifiedDatabaseSearchEngine._shadow_tables(self.path)
        self.assertEqual({"docs_data", "docs_idx", "docs_content", "docs_docsize",
                          "docs_config"}, shadow)


if __name__ == "__main__":
    unittest.main()
