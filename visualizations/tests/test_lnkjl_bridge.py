"""LnkJlBridge — the LNK + Jump Lists ("opened files") dashboard data layer.

Proves the bridge unifies the two on-disk schemas into one record shape:
  * OLD: `JLCE` (LNK + Automatic split by an `Artifact` column) + `Custom_JLCE`
  * NEW: `LNK_Files` / `Automatic_JumpLists` / `Custom_JumpLists`
and computes bounds, the per-source timeline, overview (apps / volumes / insights),
the day drill-down, and a target's profile (referenced by more than one source).
"""
import os
import sys
import json
import sqlite3
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from visualizations.lnkjl_bridge import LnkJlBridge


def _make_old(dirpath):
    con = sqlite3.connect(os.path.join(dirpath, "LnkDB.db"))
    con.execute("""CREATE TABLE JLCE (Source_Name TEXT, Local_Path TEXT, Time_Access TEXT, Time_Creation TEXT,
        Time_Modification TEXT, AppID TEXT, AppType TEXT, Artifact TEXT, Drive_Type TEXT, Volume_Label TEXT,
        Drive_SN TEXT, Network_Share_Name TEXT)""")
    rows = [
        # report.docx: referenced by an LNK and an Automatic jump list (Word)
        ("report.lnk", r"C:\Users\a\report.docx", "2026-02-15 10:00:00", "2026-02-10 08:00:00", "2026-02-14 09:00:00", "", "Unknown", "lnk", "DRIVE_FIXED", "OS", "AAA111", ""),
        ("word.autoDest", r"C:\Users\a\report.docx", "2026-02-15 09:00:00", "2026-02-10 08:00:00", "2026-02-14 09:00:00", "word.exe", "Microsoft Word", "Automatic JumpList", "DRIVE_FIXED", "OS", "AAA111", ""),
        # a removable-media open (external device history)
        ("img.lnk", r"E:\photos\img.jpg", "2026-02-14 12:00:00", "", "", "", "Unknown", "lnk", "DRIVE_REMOVABLE", "HIKVISION", "DD366F", ""),
        # a Temp target
        ("x.lnk", r"C:\Users\a\AppData\Local\Temp\x.tmp", "2026-02-13 07:00:00", "", "", "", "Unknown", "lnk", "DRIVE_FIXED", "OS", "AAA111", ""),
    ]
    con.executemany("INSERT INTO JLCE VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.execute("CREATE TABLE Custom_JLCE (Source_Name TEXT, Time_Access TEXT, Artifact TEXT)")
    con.execute("INSERT INTO Custom_JLCE VALUES ('abc.customDestinations-ms', '2026-02-15 08:00:00', 'Custom JumpList')")
    con.commit(); con.close()


def _make_new(dirpath):
    con = sqlite3.connect(os.path.join(dirpath, "LnkDB.db"))
    con.execute("CREATE TABLE LNK_Files (Source_Name TEXT, Local_Path TEXT, Time_Access TEXT, Volume_Type TEXT, Volume_Label TEXT, Volume_Serial TEXT, MFT_Entry_Number TEXT)")
    con.execute("INSERT INTO LNK_Files VALUES ('report.lnk', 'C:\\Users\\a\\report.docx', '2026-02-15 10:00:00', 'DRIVE_FIXED', 'OS', 'AAA111', '84213')")
    con.execute("CREATE TABLE Automatic_JumpLists (Source_Name TEXT, Local_Path TEXT, Time_Access TEXT, AppID TEXT, AppType TEXT, AppDesc TEXT, Volume_Label TEXT)")
    con.execute("INSERT INTO Automatic_JumpLists VALUES ('word.autoDest', 'C:\\Users\\a\\report.docx', '2026-02-15 09:00:00', 'word.exe', 'Application', 'Microsoft Word', 'OS')")
    con.execute("CREATE TABLE Custom_JumpLists (Source_Name TEXT, Local_Path TEXT, Time_Access TEXT, AppID TEXT)")
    con.execute("INSERT INTO Custom_JumpLists VALUES ('abc.custom', 'C:\\Users\\a\\pinned.pdf', '2026-02-15 08:00:00', 'app')")
    con.commit(); con.close()


class TestLnkJlOldSchema(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(); _make_old(cls.tmp); cls.b = LnkJlBridge(cls.tmp)

    def test_bounds(self):
        r = json.loads(self.b.getLnkBounds())
        self.assertTrue(r["hasData"])
        self.assertEqual(r["counts"], {"lnk": 3, "auto": 1, "custom": 1})
        self.assertIn("HIKVISION", r["volumes"])

    def test_timeline(self):
        r = json.loads(self.b.getLnkTimeline(json.dumps({})))
        self.assertEqual(sum(d["value"] for d in r["sources"]["lnk"]["days"]), 3)
        self.assertEqual(sum(d["value"] for d in r["sources"]["auto"]["days"]), 1)

    def test_overview(self):
        r = json.loads(self.b.getLnkOverview(json.dumps({})))
        self.assertEqual(r["totals"]["lnk"], 3)
        self.assertEqual(r["totals"]["targets"], 3)   # report.docx (shared), img.jpg, x.tmp
        apps = {a["app"] for a in r["byApp"]}
        self.assertIn("Microsoft Word", apps)
        self.assertEqual(r["insights"]["removable"]["count"], 1)
        self.assertEqual(len(r["insights"]["removable"]["subjects"]), 1,
                         "the insight states a number it cannot back up")
        self.assertEqual(r["insights"]["tempDownloads"]["count"], 1)
        self.assertEqual(len(r["insights"]["tempDownloads"]["subjects"]), 1,
                         "the insight states a number it cannot back up")
        self.assertGreaterEqual(r["insights"]["externalVolumes"]["count"], 1)
        self.assertTrue(any(v["label"] == "HIKVISION" and "REMOV" in v["driveType"].upper() for v in r["volumes"]))

    def test_target_detail_multi_source(self):
        r = json.loads(self.b.getLnkTargetDetail(json.dumps({"target": r"C:\Users\a\report.docx"})))
        self.assertEqual(sorted(r["sources"]), ["auto", "lnk"])
        self.assertEqual(len(r["refs"]), 2)


class TestLnkJlNewSchema(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(); _make_new(cls.tmp); cls.b = LnkJlBridge(cls.tmp)

    def test_bounds_counts(self):
        r = json.loads(self.b.getLnkBounds())
        self.assertEqual(r["counts"], {"lnk": 1, "auto": 1, "custom": 1})

    def test_unified_target_and_app(self):
        ov = json.loads(self.b.getLnkOverview(json.dumps({})))
        self.assertIn("Microsoft Word", {a["app"] for a in ov["byApp"]})
        td = json.loads(self.b.getLnkTargetDetail(json.dumps({"target": r"C:\Users\a\report.docx"})))
        self.assertEqual(sorted(td["sources"]), ["auto", "lnk"])
        self.assertEqual(td["mftEntry"], "84213")


if __name__ == "__main__":
    unittest.main()
