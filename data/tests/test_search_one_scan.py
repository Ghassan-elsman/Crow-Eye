"""A table's search is one scan and finds what it found before.

search_table used to run COUNT(*) and then the SELECT, each an OR of
LOWER(col) LIKE LOWER(?) over every column: two full scans with two function
calls per value (6.6 s over 690,000 USN rows on a real case). Now the page is
read with one row more, the total counted only when that row exists, and the
LIKE is plain: SQLite's LIKE folds ASCII case exactly as LOWER() did.
"""
import os
import sqlite3
import tempfile
import unittest

from data.base_loader import BaseDataLoader


def _db(rows):
    path = os.path.join(tempfile.mkdtemp(), "t.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE ev (name TEXT, path TEXT, n INTEGER)")
    conn.executemany("INSERT INTO ev VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()
    return path


ROWS = [("Chrome.exe", r"C:\Program Files\Google\CHROME", 1),
        ("notepad.exe", r"C:\Windows\chromeless", 2),
        ("cHrOmE_proxy", None, 3),
        ("Ünïcode-chrome", "x", 4),
        ("firefox.exe", "y", 5),
        ("100%_chrome", "z", 6),
        ("plain", "chrome_1", 7)]


class TestTheSameMatches(unittest.TestCase):

    def setUp(self):
        self.path = _db(ROWS * 3)
        self.loader = BaseDataLoader(self.path)
        self.assertTrue(self.loader.connect())

    def tearDown(self):
        self.loader.disconnect()

    def _old(self, term):
        conn = sqlite3.connect(self.path)
        cols = ["name", "path", "n"]
        where = " OR ".join("LOWER(%s) LIKE LOWER(?) ESCAPE '\\'" % c for c in cols)
        try:
            return sorted(r[0] for r in conn.execute(
                "SELECT rowid FROM ev WHERE " + where, ["%" + term + "%"] * len(cols)))
        finally:
            conn.close()

    def test_plain_like_finds_what_lower_like_found(self):
        for term in ("chrome", "CHROME", "ChRoMe", "exe", "Ü", "1"):
            got = self.loader.search_table("ev", term, page_size=1000)
            self.assertEqual(self._old(term), sorted(r["_rowid_"] for r in got["data"]), term)
            self.assertEqual(len(got["data"]), got["total_count"], term)

    def test_the_total_past_the_page_is_still_exact(self):
        want = len(self._old("chrome"))
        got = self.loader.search_table("ev", "chrome", page_size=4)
        self.assertEqual((4, want), (len(got["data"]), got["total_count"]))
        self.assertTrue(got["has_next"])
        # exactly a page: no row past it, and the total is the page
        exact = self.loader.search_table("ev", "chrome", page_size=want)
        self.assertEqual((want, want, False), (len(exact["data"]), exact["total_count"],
                                               exact["has_next"]))

    def test_one_scan_when_the_matches_fit(self):
        seen = []
        self.loader.connection.set_trace_callback(seen.append)
        self.loader.search_table("ev", "firefox", page_size=1000)
        self.loader.connection.set_trace_callback(None)
        self.assertFalse([q for q in seen if "COUNT(*)" in q.upper()], seen)


class TestLazyPreviews(unittest.TestCase):

    def test_built_when_read_and_once(self):
        from ui.database_search_dialog import UISearchResult
        calls = []
        r = UISearchResult("db", "t", 1, ["name"], {"name": "x"}, None, None,
                           preview_fn=lambda: calls.append(1) or "name: x")
        self.assertEqual([], calls)
        self.assertEqual("name: x", r.match_preview)
        self.assertEqual("name: x", r.match_preview)
        self.assertEqual([1], calls)
        r.match_preview = "set"
        self.assertEqual("set", r.match_preview)


if __name__ == "__main__":
    unittest.main()
