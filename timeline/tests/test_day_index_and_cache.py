"""The timeline's speed-ups answer exactly what the slow paths answered.

- day_index: a day's row ids from the map equal the full scan's, and a map
  whose source changed is never read.
- case_cache: a stored answer is used only while every database is unchanged.
- _ts_range: a text range over a column holding both stored shapes
  ('YYYY-MM-DD HH:MM:SS' and 'YYYY-MM-DDTHH:MM:SS') matches what datetime()
  matched, and never the next day's rows (the 'T' range alone took them).
"""
import json
import os
import sqlite3
import tempfile
import time
import unittest

from timeline import case_cache, day_index
from timeline.timeline_bridge import TimelineBridge

COLS = ["a_time", "b_time", "c_time"]


def _case(rows):
    root = tempfile.mkdtemp()
    ta = os.path.join(root, "Target_Artifacts")
    os.makedirs(ta)
    db = os.path.join(ta, "big.db")
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE t (name TEXT, a_time TEXT, b_time TEXT, c_time TEXT)")
    conn.executemany("INSERT INTO t VALUES (?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()
    return ta, db


def _scan(db, lo, hi):
    conn = sqlite3.connect(db)
    where = " OR ".join('("%s" >= ? AND "%s" < ?)' % (c, c) for c in COLS)
    try:
        return sorted(r[0] for r in conn.execute(
            "SELECT rowid FROM t WHERE " + where, [v for _ in COLS for v in (lo, hi)]))
    finally:
        conn.close()


class TestTheDayMap(unittest.TestCase):

    def setUp(self):
        rows = []
        for i in range(3000):
            day = 1 + i % 28
            rows.append(("f%d" % i, "2026-10-%02d 0%d:00:00" % (day, i % 9),
                         None if i % 3 else "2026-09-%02d 12:00:00" % (1 + i % 28),
                         "garbage" if i % 7 == 0 else "2026-10-%02d 23:59:59" % (1 + (i + 5) % 28)))
        self.ta, self.db = _case(rows)

    def test_a_day_from_the_map_is_the_scan(self):
        self.assertTrue(day_index.build(self.ta, self.db, "t", COLS))
        self.assertTrue(day_index.ready(self.ta, self.db, "t", COLS))
        for day in ("2026-10-05", "2026-09-17", "2026-10-28", "2026-11-01"):
            n = day_index.day_number(day)
            got = day_index.rowids(self.ta, "t", n, n)
            self.assertEqual(_scan(self.db, day + " 00:00:00", day + " 23:59:60"), got, day)
        # a two-day window is both days
        a, b = day_index.day_number("2026-10-05"), day_index.day_number("2026-10-06")
        self.assertEqual(_scan(self.db, "2026-10-05 00:00:00", "2026-10-07 00:00:00"),
                         day_index.rowids(self.ta, "t", a, b))

    def test_a_changed_source_is_never_read(self):
        day_index.build(self.ta, self.db, "t", COLS)
        # A mere mtime touch (the case was only read) must NOT invalidate it.
        os.utime(self.db, (time.time() + 5, time.time() + 5))
        self.assertTrue(day_index.ready(self.ta, self.db, "t", COLS))
        # A real re-parse adds rows and GROWS the database - that does.
        conn = sqlite3.connect(self.db)
        conn.execute("INSERT INTO t VALUES (?, '2026-10-05 01:00:00', NULL, NULL)", ('x' * 100000,))
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
        self.assertFalse(day_index.ready(self.ta, self.db, "t", COLS))
        # and other columns asked for are a different map
        day_index.build(self.ta, self.db, "t", COLS)
        self.assertFalse(day_index.ready(self.ta, self.db, "t", COLS[:2]))

    def test_the_map_lives_beside_the_case_not_in_it(self):
        day_index.build(self.ta, self.db, "t", COLS)
        path = day_index.map_path(self.ta)
        self.assertEqual(os.path.dirname(os.path.dirname(path)), os.path.dirname(self.ta))
        self.assertNotIn("Target_Artifacts", path)

    def test_a_small_table_is_left_to_the_scan(self):
        self.assertFalse(day_index.build_in_background(self.ta, self.db, "t", COLS))


class TestTheCaseCache(unittest.TestCase):

    def test_used_while_unchanged_asked_again_after(self):
        ta, db = _case([("x", "2026-10-01 00:00:00", None, None)])
        sig = case_cache.signature(ta)
        case_cache.put(ta, "bounds", "ANSWER", sig=sig)
        self.assertEqual("ANSWER", case_cache.get(ta, "bounds"))
        # A mere mtime touch (the case was only read) must NOT invalidate it.
        os.utime(db, (time.time() + 5, time.time() + 5))
        self.assertEqual("ANSWER", case_cache.get(ta, "bounds"))
        # A re-parse GROWS the database, and that does invalidate it.
        conn = sqlite3.connect(db)
        conn.execute("INSERT INTO t VALUES (?, '2026-10-02 00:00:00', NULL, NULL)", ('x' * 100000,))
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
        self.assertIsNone(case_cache.get(ta, "bounds"))

    def test_the_bridge_answers_from_it(self):
        ta, _db = _case([("x", "2026-10-01 00:00:00", None, None)])
        b = TimelineBridge(ta)
        calls = []
        first = b._cached_answer("k", lambda: calls.append(1) or json.dumps({"v": 1}))
        again = b._cached_answer("k", lambda: calls.append(1) or json.dumps({"v": 2}))
        self.assertEqual((first, again, len(calls)), (json.dumps({"v": 1}),) * 2 + (1,))


class TestBothStoredShapes(unittest.TestCase):

    def test_the_range_is_what_datetime_matched_and_never_the_next_day(self):
        rows = [("sp", "2026-10-30 05:00:00", None, None),
                ("T", "2026-10-30T23:00:00", None, None),
                ("next-sp", "2026-10-31 00:04:00", None, None),   # sorts below '...31T'
                ("next-T", "2026-10-31T00:00:00", None, None),
                ("prev", "2026-10-29T23:59:59", None, None)]
        ta, db = _case(rows)
        b = TimelineBridge(ta)
        where, params = b._ts_range("a_time", "2026-10-30T00:00:00", "2026-10-30T23:59:59")
        conn = sqlite3.connect(db)
        got = sorted(r[0] for r in conn.execute("SELECT name FROM t WHERE " + where, params))
        old = sorted(r[0] for r in conn.execute(
            "SELECT name FROM t WHERE datetime(a_time) BETWEEN datetime(?) AND datetime(?)",
            ("2026-10-30T00:00:00", "2026-10-30T23:59:59")))
        conn.close()
        self.assertEqual(["T", "sp"], got)
        self.assertEqual(old, got)


if __name__ == "__main__":
    unittest.main()
