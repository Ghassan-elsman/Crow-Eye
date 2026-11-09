"""A dashboard's kept answers outlive its dialog, and only while the case does.

Each bridge kept its answers on itself, so closing and reopening a dashboard
asked every question again (the MFT/USN overview 10 s and its strip 9 s on a
3.9 M-row case). They are now kept for the session (async_bridge's store) and
the unfiltered MFT/USN opening answers beside the case (utils/case_cache.py).
What a careless version gets wrong:

- an answer kept past a re-parse: a parse in WAL mode writes the -wal file
  and leaves the database's own mtime alone, so a key on the .db alone holds;
- every stored answer thrown away because a reader touched an EMPTY WAL (its
  mtime moves on every open, nothing written);
- two cases' answers mixed, keyed on the question alone.
"""
import json
import os
import sqlite3
import tempfile
import time
import unittest

from PyQt5 import QtWebEngineWidgets  # noqa: F401  (before any QCoreApplication)
from PyQt5 import QtWidgets

from utils import case_cache
from visualizations import async_bridge
from visualizations.async_bridge import AsyncBridge, db_state

# A QApplication, never a bare QCoreApplication: the widget tests after this
# module take whatever instance exists, and widgets need a QApplication.
_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["x"])


class _Bridge(AsyncBridge):
    calls = 0

    def __init__(self, path):
        super().__init__()
        self.path = path

    def answer(self, args_json):
        def compute(_a):
            type(self).calls += 1
            return "computed %d" % type(self).calls
        return self.cached_result("q", args_json, compute, [self.path])


def _db(folder, name="t.db"):
    path = os.path.join(folder, name)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (x)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    conn.close()
    return path


class TheSessionStore(unittest.TestCase):

    def setUp(self):
        AsyncBridge().clear_cache()
        _Bridge.calls = 0
        self.dir = tempfile.mkdtemp(prefix="reopen_")

    def test_a_reopened_dashboard_is_answered_from_the_session(self):
        path = _db(self.dir)
        first = _Bridge(path).answer("{}")
        again = _Bridge(path).answer("{}")          # a new bridge: a reopened dialog
        self.assertEqual((first, again, 1), ("computed 1", "computed 1", _Bridge.calls))
        # another case's database is another key
        other = _db(tempfile.mkdtemp(prefix="reopen_"))
        self.assertEqual("computed 2", _Bridge(other).answer("{}"))

    def test_a_write_to_the_wal_is_a_new_answer(self):
        path = _db(self.dir)
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA wal_autocheckpoint=0")
        before = db_state([path])
        self.assertEqual("computed 1", _Bridge(path).answer("{}"))
        conn.execute("INSERT INTO t VALUES (2)")
        conn.commit()
        try:
            self.assertNotEqual(before, db_state([path]))
            self.assertEqual("computed 2", _Bridge(path).answer("{}"))
        finally:
            conn.close()


class BesideTheCase(unittest.TestCase):

    def test_an_empty_wal_touched_is_not_a_change(self):
        ta = os.path.join(tempfile.mkdtemp(prefix="cc_"), "Target_Artifacts")
        os.makedirs(ta)
        _db(ta, "a.db")
        wal = os.path.join(ta, "a.db-wal")
        open(wal, "wb").close()
        sig = case_cache.signature(ta)
        case_cache.put(ta, "k", "ANSWER", "Charts", "x.json", sig=sig)
        later = time.time() + 5
        os.utime(wal, (later, later))                  # a reader opened it
        self.assertEqual("ANSWER", case_cache.get(ta, "k", "Charts", "x.json"))
        with open(wal, "wb") as handle:                # a WAL that holds pages
            handle.write(b"\0" * 32)
        self.assertIsNone(case_cache.get(ta, "k", "Charts", "x.json"))

    def test_stale_entries_are_dropped_when_one_is_stored(self):
        ta = os.path.join(tempfile.mkdtemp(prefix="cc_"), "Target_Artifacts")
        os.makedirs(ta)
        db = _db(ta, "a.db")
        case_cache.put(ta, "old", 1, "Charts", "y.json")
        conn = sqlite3.connect(db)
        conn.execute("INSERT INTO t VALUES (3)")
        conn.commit()
        conn.close()
        later = time.time() + 5
        os.utime(db, (later, later))
        case_cache.put(ta, "new", 2, "Charts", "y.json")
        with open(case_cache.path_for(ta, "Charts", "y.json"), encoding="utf-8") as h:
            self.assertEqual(["new"], list(json.load(h)))


if __name__ == "__main__":
    unittest.main()
