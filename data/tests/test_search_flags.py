"""Database Search honours every box on the dialog, with or without a period.

Found by the 2026-10-07 user-guide audit and fixed 2026-11-05; each check names
what the old code did:

- "Use Regex" reached nothing: it was validated and saved to history, and the
  search ran a LIKE for the pattern's literal text;
- a case-sensitive search escaped the term for LIKE and ran it through GLOB,
  so a term holding a backslash, _, % or [ looked for backslashes and found
  nothing;
- with the Time Period Filter on, the term was matched in Python, by
  substring, over the first max_results * 10 rows of the period: Exact Match
  and Regex were ignored, and a match past those rows was never found;
- each search was written to history twice, once by the engine and once by
  the dialog.
"""
import os
import sqlite3
import tempfile
import unittest
import datetime as dt

from data.unified_search_engine import UnifiedDatabaseSearchEngine
from data.base_loader import BaseDataLoader, escape_glob, value_matcher

ROWS = [("chrome", "C:/a/chrome.exe"), ("Chrome", "C:/b/Chrome.exe"),
        ("xchromex", "C:/c/xchromex.exe"), ("a_b%c[1]", "C:/d/a_b%c[1].txt"),
        ("ab", "C:/e/ab.txt"), ("back\\slash", "C:/f/back\\slash")]


def _case(filler=0):
    root = tempfile.mkdtemp(prefix="srchflags_")
    ta = os.path.join(root, "Target_Artifacts")
    os.makedirs(ta)
    con = sqlite3.connect(os.path.join(ta, "flags_custom.db"))
    con.execute("CREATE TABLE ev (name TEXT, path TEXT, timestamp TEXT)")
    stamp = "2026-10-01 10:%02d:00"
    # Rows of the period that match nothing, before the ones that do: the old
    # time path read only max_results * 10 of them.
    con.executemany("INSERT INTO ev VALUES (?, ?, ?)",
                    [("filler %d" % i, "C:/z/%d" % i, stamp % (i % 60)) for i in range(filler)])
    con.executemany("INSERT INTO ev VALUES (?, ?, ?)",
                    [(n, p, stamp % 30) for n, p in ROWS])
    con.commit()
    con.close()
    return root


def _names(results):
    out = set()
    for r in results:
        for h in r.get_all_results():
            # record_data on the plain path, row_data on the time-filtered one
            data = getattr(h, "record_data", None) or getattr(h, "row_data", None) or {}
            out.add(data.get("name"))
    return out


class TheLoaderAndTheMatcherAgree(unittest.TestCase):

    def setUp(self):
        root = _case()
        self.loader = BaseDataLoader(os.path.join(root, "Target_Artifacts", "flags_custom.db"))
        self.assertTrue(self.loader.connect())
        self.addCleanup(self.loader.disconnect)

    def found(self, term, **kw):
        got = self.loader.search_table("ev", term, columns=["name"], page_size=100, **kw)
        return {row["name"] for row in got["data"]}

    def test_regex_is_a_regex(self):
        self.assertEqual(self.found("^chr.me$", use_regex=True), {"chrome", "Chrome"})
        self.assertEqual(self.found("^chr.me$", use_regex=True, case_sensitive=True), {"chrome"})
        self.assertEqual(self.found("chr.me", use_regex=True, exact_match=True), {"chrome", "Chrome"})
        self.assertEqual(self.found("chr.me", use_regex=True), {"chrome", "Chrome", "xchromex"})
        # and a plain search for the same text finds no regex at all
        self.assertEqual(self.found("^chr.me$"), set())

    def test_case_sensitive_terms_with_wildcard_characters(self):
        self.assertEqual(self.found("a_b%c[1]", case_sensitive=True), {"a_b%c[1]"})
        self.assertEqual(self.found("b%c", case_sensitive=True), {"a_b%c[1]"})
        self.assertEqual(self.found("back\\slash", case_sensitive=True), {"back\\slash"})
        self.assertEqual(self.found("Chrome", case_sensitive=True), {"Chrome"})
        self.assertEqual(self.found("a?b", case_sensitive=True), set())     # ? is literal
        self.assertEqual(escape_glob("a*b?[c]"), "a[*]b[?][[]c]")

    def test_the_python_matcher_says_what_the_sql_says(self):
        values = [n for n, _p in ROWS]
        for kw in ({}, {"case_sensitive": True}, {"exact_match": True},
                   {"exact_match": True, "case_sensitive": True},
                   {"use_regex": True}, {"use_regex": True, "exact_match": True}):
            for term in ("chrome", "Chrome", "b%c", "chr.me"):
                if not kw.get("use_regex") and term == "chr.me":
                    continue
                m = value_matcher(term, **kw)
                self.assertEqual({v for v in values if m(v)}, self.found(term, **kw), (term, kw))


class TheEngine(unittest.TestCase):

    PERIOD = (dt.datetime(2026, 10, 1, 0, 0, 0), dt.datetime(2026, 10, 1, 23, 59, 59))

    def search(self, root, term, period=False, **kw):
        eng = UnifiedDatabaseSearchEngine(root)
        start, end = self.PERIOD if period else (None, None)
        res = eng.search(search_term=term, databases=["flags_custom.db"],
                         max_results_per_table=100, timeout_seconds=60,
                         start_time=start, end_time=end, **kw)
        return eng, res

    def test_every_box_holds_with_and_without_a_period(self):
        root = _case(filler=1500)          # more than 100 * 10 rows in the period
        for period in (False, True):
            _e, res = self.search(root, "xchromex", period)
            self.assertEqual(_names(res), {"xchromex"}, ("found past the cap", period))
            _e, res = self.search(root, "chrome", period, exact_match=True)
            self.assertEqual(_names(res), {"chrome", "Chrome"}, ("exact", period))
            _e, res = self.search(root, "^chr.me$", period, use_regex=True)
            self.assertEqual(_names(res), {"chrome", "Chrome"}, ("regex", period))
            _e, res = self.search(root, "b%c", period, case_sensitive=True)
            self.assertEqual(_names(res), {"a_b%c[1]"}, ("glob", period))

    def test_a_bad_pattern_is_said_not_searched(self):
        with self.assertRaises(ValueError):
            self.search(_case(), "chr(ome", use_regex=True)

    def test_history_is_written_once(self):
        root = _case()
        eng, _res = self.search(root, "chrome")
        before = len(eng.history_manager.load_history() or [])
        eng.search(search_term="chrome2", databases=["flags_custom.db"], record_history=False)
        self.assertEqual(len(eng.history_manager.load_history() or []), before)
        eng.search(search_term="chrome3", databases=["flags_custom.db"])
        self.assertEqual(len(eng.history_manager.load_history() or []), before + 1)


if __name__ == "__main__":
    unittest.main()
