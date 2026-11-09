"""A timeline event can be opened in its own table in the main window.

- A lane query that reads one table by `rowid AS id` stamps each row with its
  database, table and rowid; a query that joins, unions or names no rowid
  stamps nothing (a wrong row is worse than no button).
- The event's detail offers "Show in table" only when the main window has a
  tab for that table, hands the right three values to the Database Search
  navigation, and never shows the stamp as a field.
"""
import json
import os
import sqlite3
import tempfile
import unittest

from timeline.timeline_bridge import TimelineBridge, SOURCE_KEYS, _single_source_table


class SourceTableParse(unittest.TestCase):
    def test_one_table_by_rowid(self):
        self.assertEqual(_single_source_table(
            "SELECT rowid as id, Source_Name FROM LNK_Files WHERE x > ?"), "LNK_Files")
        self.assertEqual(_single_source_table(
            "SELECT rowid AS id, a FROM [mft_usn_correlated] WHERE rowid IN (1,2)"),
            "mft_usn_correlated")

    def test_anything_else_names_no_table(self):
        for sql in ("SELECT a FROM t",                                   # no rowid
                    "SELECT rowid as id FROM a JOIN b ON a.x = b.x",      # joined
                    "SELECT rowid as id FROM a UNION ALL SELECT rowid as id FROM b",
                    "SELECT myrowid as identity FROM t",                  # not the word
                    "SELECT rowid as id FROM (SELECT * FROM t)"):         # subquery
            self.assertIsNone(_single_source_table(sql), sql)


class QueryStamp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        conn = sqlite3.connect(os.path.join(self.dir, "LnkDB.db"))
        conn.execute("CREATE TABLE LNK_Files (Source_Name TEXT)")
        conn.executemany("INSERT INTO LNK_Files VALUES (?)", [("a.lnk",), ("b.lnk",)])
        conn.execute("CREATE TABLE other (Source_Name TEXT)")
        conn.commit()
        conn.close()
        self.bridge = TimelineBridge(self.dir)

    def test_rows_carry_their_source(self):
        rows = self.bridge._query_db(
            "LnkDB.db", "SELECT rowid as id, Source_Name FROM LNK_Files ORDER BY rowid")
        self.assertEqual([(r["_src_db"], r["_src_table"], r["_src_rowid"]) for r in rows],
                         [("LnkDB.db", "LNK_Files", 1), ("LnkDB.db", "LNK_Files", 2)])

    def test_a_query_without_a_rowid_is_not_stamped(self):
        rows = self.bridge._query_db("LnkDB.db", "SELECT Source_Name FROM LNK_Files")
        self.assertTrue(rows)
        self.assertFalse(any(k in r for r in rows for k in SOURCE_KEYS))


try:
    from timeline.timeline_dialog import TimelineDialog
except Exception:                         # QtWebEngine after a QApplication
    TimelineDialog = None


class _Nav:
    """InvestigatorTools as far as the Timeline uses it."""

    def __init__(self, mapped):
        self.mapped = {t.lower() for t in mapped}
        self.calls = []

    def table_view_for(self, table):
        return object() if str(table).lower() in self.mapped else None

    def show_row(self, db, table, row_id):
        self.calls.append((db, table, row_id))
        return True, ""


class _Win:
    def __init__(self, nav):
        self.ui = type("UI", (), {"investigator_tools": nav})()
        self.raised = 0

    def isMinimized(self):
        return False

    def raise_(self):
        self.raised += 1

    def activateWindow(self):
        pass


@unittest.skipIf(TimelineDialog is None, "QtWebEngine could not be imported here")
class ShowInTable(unittest.TestCase):
    def _fake(self, mapped=("LNK_Files",)):
        nav = _Nav(mapped)
        fake = type("D", (), {"_tools": TimelineDialog._tools})()
        fake.main_window = _Win(nav)
        return fake, nav

    def test_only_a_table_with_a_tab_gets_the_button(self):
        fake, _nav = self._fake()
        self.assertTrue(TimelineDialog.has_table_tab(fake, "lnk_files"))
        self.assertFalse(TimelineDialog.has_table_tab(fake, "ai_agent_steps"))

    def test_the_jump_hands_over_the_row_and_raises_the_main_window(self):
        fake, nav = self._fake()
        self.assertTrue(TimelineDialog.show_in_table(fake, "LnkDB.db", "LNK_Files", 7))
        self.assertEqual(nav.calls, [("LnkDB.db", "LNK_Files", 7)])
        self.assertEqual(fake.main_window.raised, 1)

    def test_the_stamp_is_not_shown_as_a_field(self):
        from PyQt5 import QtWidgets
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["t"])  # noqa
        _f, nav = self._fake()
        fake = QtWidgets.QWidget()              # the detail dialog's parent
        fake.main_window = _f.main_window
        fake.bridge = None
        fake._tools = lambda: TimelineDialog._tools(fake)
        fake.show_in_table = lambda *a: None
        fake.has_table_tab = lambda t: TimelineDialog.has_table_tab(fake, t)
        ev = {"name": "a.lnk", "type": "lnk", "_src_db": "LnkDB.db",
              "_src_table": "LNK_Files", "_src_rowid": 3}
        TimelineDialog._open_event_detail_dialog(fake, json.dumps(ev))
        dlg = fake.current_detail_dialog
        try:
            self.assertFalse(any(k in dlg.row_data for k in SOURCE_KEYS))
            labels = [b.text() for b in dlg.findChildren(QtWidgets.QPushButton)]
            self.assertIn("Show in table", labels)
        finally:
            dlg.close()


if __name__ == "__main__":
    unittest.main()
