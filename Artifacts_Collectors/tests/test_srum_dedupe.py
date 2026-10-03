"""SRUM parser exact-duplicate prevention.

The SRUM parser used to write byte-for-byte identical rows - worst in the energy
table, where a minute-truncated timestamp and a NULL event_timestamp collapse
distinct events into identical tuples (44% of one real case's energy rows). The
save step now drops exact-duplicate tuples via `dedupe_exact`. These tests pin
that behaviour: identical rows collapse (including NULL-bearing ones, which a SQL
UNIQUE index would miss), and rows differing in any column are all kept.
"""
import os
import sys
import sqlite3
import tempfile
import datetime
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from Artifacts_Collectors import SRUM_Claw
from Artifacts_Collectors.SRUM_Claw import dedupe_exact, SRUMEnergyRecord


class TestDedupeExact(unittest.TestCase):
    def test_collapses_identical(self):
        rows = [(1, "a", None), (1, "a", None), (1, "a", None)]
        out, removed = dedupe_exact(rows)
        self.assertEqual(out, [(1, "a", None)])
        self.assertEqual(removed, 2)

    def test_none_bearing_rows_collapse(self):
        # The energy case: event_timestamp is None on every row. A Python set
        # treats None == None, so these are recognised as duplicates.
        rows = [("System", "2026-03-05T18:28:00", None, 259, "89.50 Wh")] * 12
        out, removed = dedupe_exact(rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(removed, 11)

    def test_distinct_rows_all_kept_in_order(self):
        rows = [(1, "a"), (1, "b"), (2, "a"), (1, "a")]  # last is a dup of first
        out, removed = dedupe_exact(rows)
        self.assertEqual(out, [(1, "a"), (1, "b"), (2, "a")])
        self.assertEqual(removed, 1)

    def test_empty(self):
        self.assertEqual(dedupe_exact([]), ([], 0))


@unittest.skipUnless(sys.platform == "win32", "SRUM_Claw ESE path is Windows-only")
class TestSaveDedupes(unittest.TestCase):
    def setUp(self):
        # The constructor only gates on the Windows ESE API; the save path is
        # pure sqlite, so force the flag and use throwaway paths.
        self._orig = getattr(SRUM_Claw, "ESENT_AVAILABLE", False)
        SRUM_Claw.ESENT_AVAILABLE = True
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "srum_data.db")
        # The constructor only checks the SRUDB path exists (never read here).
        dummy = os.path.join(self.tmp, "SRUDB.dat")
        with open(dummy, "wb") as fh:
            fh.write(b"\x00")
        self.parser = SRUM_Claw.SRUMParser(dummy, self.db)
        self.parser.create_database_schema()

    def tearDown(self):
        SRUM_Claw.ESENT_AVAILABLE = self._orig

    def test_energy_exact_duplicates_removed(self):
        ts = datetime.datetime(2026, 3, 5, 18, 28, tzinfo=datetime.timezone.utc)
        dup = SRUMEnergyRecord(timestamp=ts, app_name="System", user_sid="S-1-5-18",
                               user_name="SYSTEM", event_timestamp=None,
                               state_transition=259, charge_level="89.50 Wh", cycle_count=0)
        # 5 identical + 1 that differs only in charge_level
        distinct = SRUMEnergyRecord(timestamp=ts, app_name="System", user_sid="S-1-5-18",
                                    user_name="SYSTEM", event_timestamp=None,
                                    state_transition=259, charge_level="90.00 Wh", cycle_count=0)
        records = [dup, dup, dup, dup, dup, distinct]
        self.parser.save_to_database({"energy_usage": records})

        con = sqlite3.connect(self.db)
        n = con.execute("SELECT COUNT(*) FROM srum_energy_usage").fetchone()[0]
        # exact-duplicate groups (all data columns)
        dups = con.execute(
            "SELECT COUNT(*) FROM (SELECT app_name,user_sid,timestamp,event_timestamp,"
            "state_transition,charge_level,cycle_count, COUNT(*) c FROM srum_energy_usage "
            "GROUP BY app_name,user_sid,timestamp,event_timestamp,state_transition,charge_level,cycle_count "
            "HAVING c>1)").fetchone()[0]
        con.close()
        self.assertEqual(n, 2, "the 5 identical rows collapse to 1, the distinct row stays")
        self.assertEqual(dups, 0, "no exact-duplicate rows remain")


if __name__ == "__main__":
    unittest.main()
