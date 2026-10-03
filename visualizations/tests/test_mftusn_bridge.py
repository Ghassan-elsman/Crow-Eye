"""MftUsnBridge — the MFT/USN correlated dashboard's data layer.

Builds a tiny fixture (a *subset* of the correlated columns, to prove the bridge
tolerates schema drift) plus a USN gap row, and checks each slot: bounds,
the two timelines, the window drill-down, the overview + anomalies, and one
file's lifecycle.
"""
import os
import sys
import json
import sqlite3
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from visualizations.mftusn_bridge import MftUsnBridge, reason_cats


# Only a subset of the full schema — no volume_letter / file_size / has_ads.
CORR_COLS = [
    "mft_record_number", "fn_filename", "reconstructed_path", "is_directory", "is_deleted",
    "si_creation_time", "si_modification_time", "si_access_time", "si_mft_entry_change_time",
    "fn_creation_time", "fn_modification_time", "fn_access_time", "fn_mft_entry_change_time",
    "fn_real_size",
    "usn_timestamp", "usn_reason", "has_mft_record", "has_usn_event",
]


def _row(rec, path, fn, reason=None, usn_t=None, si_c="2026-02-16T05:00:00.100000+00:00",
         si_m="2026-02-16T05:00:00.100000+00:00", size=100, is_dir=0, is_del=0, fn_c=None):
    fn_c = fn_c or si_c
    return {
        "mft_record_number": rec, "fn_filename": fn, "reconstructed_path": path,
        "is_directory": is_dir, "is_deleted": is_del,
        "si_creation_time": si_c, "si_modification_time": si_m,
        "si_access_time": si_m, "si_mft_entry_change_time": si_m,
        "fn_creation_time": fn_c, "fn_modification_time": si_m,
        "fn_access_time": si_m, "fn_mft_entry_change_time": si_m, "fn_real_size": size,
        "usn_timestamp": usn_t, "usn_reason": reason,
        "has_mft_record": 1, "has_usn_event": 1 if reason else 0,
    }


class TestMftUsnBridge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        corr = os.path.join(cls.tmp, "mft_usn_correlated_analysis.db")
        con = sqlite3.connect(corr)
        con.execute("CREATE TABLE mft_usn_correlated (%s)" % ", ".join(f"{c}" for c in CORR_COLS))
        rows = [
            _row(10, "./Users/a/new.txt", "new.txt", "DATA_EXTEND | FILE_CREATE | CLOSE", "2026-02-16T05:10:00+00:00"),
            _row(11, "./Users/a/old.txt", "old.txt", "RENAME_NEW_NAME | CLOSE", "2026-02-16T05:20:00+00:00"),
            _row(12, "./Windows/x.dll", "x.dll", "DATA_OVERWRITE | CLOSE", "2026-02-16T05:30:00+00:00"),
            _row(13, "./Windows/y.dll", "y.dll", "SECURITY_CHANGE | CLOSE", "2026-02-16T05:40:00+00:00"),
            _row(14, "./tmp/z.tmp", "z.tmp", "FILE_DELETE | CLOSE", "2026-02-16T05:50:00+00:00", is_del=1),
            # timestomp candidate: SI creation NEWER than FN creation (forward-dated)
            _row(15, "./t/stomp.exe", "stomp.exe", None, None,
                 si_c="2026-02-16T10:00:00.500000+00:00",
                 fn_c="2026-02-15T09:00:00.200000+00:00"),
            # an old MFT-only file (long MFT history), SI == FN — must NOT be flagged
            _row(16, "./old/legacy.sys", "legacy.sys", None, None,
                 si_c="2020-05-01T00:00:00.300000+00:00", si_m="2020-05-02T00:00:00.300000+00:00"),
        ]
        con.executemany(
            "INSERT INTO mft_usn_correlated (%s) VALUES (%s)" % (", ".join(CORR_COLS), ", ".join("?" * len(CORR_COLS))),
            [tuple(r[c] for c in CORR_COLS) for r in rows])
        con.commit(); con.close()

        usn = os.path.join(cls.tmp, "USN_journal.db")
        u = sqlite3.connect(usn)
        u.execute("CREATE TABLE deleted_entries (volume_letter TEXT, gap_start_usn INTEGER, gap_end_usn INTEGER)")
        u.execute("INSERT INTO deleted_entries VALUES ('C:', 1000, 2000)")
        u.commit(); u.close()

        cls.b = MftUsnBridge(cls.tmp)

    def test_reason_cats(self):
        self.assertEqual(reason_cats("DATA_EXTEND | FILE_CREATE | CLOSE"), {"create", "data"})
        self.assertEqual(reason_cats("RENAME_NEW_NAME | CLOSE"), {"rename"})
        self.assertEqual(reason_cats("SECURITY_CHANGE | CLOSE"), {"meta"})
        self.assertEqual(reason_cats(None), set())

    def test_bounds(self):
        r = json.loads(self.b.getMftUsnBounds())
        self.assertTrue(r["hasData"])
        self.assertEqual(r["usnMin"], "2026-02-16")
        self.assertEqual(r["usnMax"], "2026-02-16")
        self.assertEqual(r["mftMin"], "2020-05-01")
        self.assertFalse(r["hasVolume"])   # drift: no volume_letter column

    def test_timelines(self):
        r = json.loads(self.b.getMftUsnTimelines(json.dumps({})))
        # One cell is one day on every strip; this slot used to narrow to hours
        # on a short window and report which it had chosen.
        self.assertNotIn("bucket", r)
        self.assertEqual([c["key"] for c in r["combined"]], ["2026-02-16"])
        cats = {c: sum(b["value"] for b in r["usnEvents"][c]["buckets"]) for c in r["usnEvents"]}
        self.assertEqual(cats["create"], 1)
        self.assertEqual(cats["rename"], 1)
        self.assertEqual(cats["data"], 2)
        self.assertEqual(cats["meta"], 1)
        self.assertEqual(cats["delete"], 1)
        # MFT history has the 2020 and 2026 creation days
        days = {d["day"] for d in r["mftHistory"]}
        self.assertIn("2020-05-01", days)

    def test_overview_and_anomalies(self):
        r = json.loads(self.b.getMftUsnOverview(json.dumps({})))
        t = r["totals"]
        self.assertEqual(t["withEvents"], 5)
        self.assertEqual(t["created"], 1)
        self.assertEqual(t["renamed"], 1)
        self.assertEqual(t["dataChanged"], 2)
        self.assertEqual(t["deletedEvents"], 1)
        self.assertEqual(t["files"], 7)
        a = r["anomalies"]
        self.assertGreaterEqual(a["timestompCandidates"]["count"], 1)   # rec 15
        self.assertTrue(a["timestompCandidates"]["subjects"],
                        "the anomaly states a number it cannot back up")
        # The subject carries the MFT record number the file modal opens on.
        self.assertIn("open", a["timestompCandidates"]["subjects"][0])
        self.assertEqual(a["usnGaps"]["count"], 1)                      # deleted_entries row
        self.assertEqual(len(a["usnGaps"]["subjects"]), 1,
                         "the anomaly states a number it cannot back up")

    def test_window_detail(self):
        r = json.loads(self.b.getMftUsnWindowDetail(json.dumps({"bucket": "2026-02-16T05:00", "gran": "hour"})))
        self.assertEqual(len(r["events"]), 5)
        self.assertEqual(r["byHour"]["create"][5], 1)
        self.assertEqual(r["byHour"]["delete"][5], 1)
        dirs = {d["dir"] for d in r["topDirs"]}
        self.assertTrue(any("Windows" in d for d in dirs))

    def test_file_detail(self):
        r = json.loads(self.b.getMftUsnFileDetail(json.dumps({"rec": 10})))
        self.assertEqual(r["filename"], "new.txt")
        self.assertEqual(len(r["events"]), 1)
        self.assertEqual(sorted(r["events"][0]["cats"]), ["create", "data"])

    def test_file_detail_timestomp_flag(self):
        r = json.loads(self.b.getMftUsnFileDetail(json.dumps({"rec": 15})))
        self.assertTrue(any("newer than file-name creation" in f.lower() for f in r["flags"]))

    def test_clean_file_not_flagged(self):
        # rec 16 has SI == FN (sub-second) — must carry no timestomp flag.
        r = json.loads(self.b.getMftUsnFileDetail(json.dumps({"rec": 16})))
        self.assertEqual(r["flags"], [])


if __name__ == "__main__":
    unittest.main()
