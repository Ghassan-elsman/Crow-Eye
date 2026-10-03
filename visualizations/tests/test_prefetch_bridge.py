"""PrefetchBridge — the Prefetch ("program executions") dashboard data layer.

Fixture prefetch_data rows spanning the run-location categories (System,
Program Files, User/Temp, Removable), with JSON run_times / volumes / resources,
proving classification, JSON parsing, exe-path derivation, and the slots.
"""
import os
import sys
import json
import sqlite3
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from visualizations.prefetch_bridge import PrefetchBridge

COLS = ["filename", "executable_name", "hash", "run_count", "last_executed",
        "run_times", "volumes", "directories", "resources",
        "created_on", "modified_on", "accessed_on"]


def _row(fn, exe, run_count, run_times, exe_path, device, resources_extra=None):
    resources = [exe_path] + (resources_extra or ["C:\\Windows\\System32\\ntdll.dll"])
    vols = [{"volume_id": exe_path[:2], "device_name": device, "serial_number": "SER" + fn[:3], "creation_time": "2025-09-08 12:23:45"}]
    return (fn, exe, "H" + fn[:4], run_count, run_times[-1] if run_times else None,
            json.dumps(run_times), json.dumps(vols), json.dumps(["C:\\WINDOWS"]),
            json.dumps(resources), "2026-02-10 08:00:01", "2026-02-16 11:00:01", "2026-02-16 12:00:00")


class TestPrefetchBridge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        con = sqlite3.connect(os.path.join(cls.tmp, "prefetch_data.db"))
        con.execute("CREATE TABLE prefetch_data (%s)" % ", ".join(COLS))
        rows = [
            _row("SVCHOST.EXE-1.pf", "SVCHOST.EXE", 5,
                 ["2026-02-14 10:00:00", "2026-02-15 11:00:00", "2026-02-16 09:00:00"],
                 "C:\\WINDOWS\\SYSTEM32\\SVCHOST.EXE", "\\VOLUME{x} (Drive C: 'OS' (Fixed))"),
            _row("CHROME.EXE-2.pf", "CHROME.EXE", 8,
                 ["2026-02-16 09:30:00", "2026-02-16 12:00:00"],
                 "C:\\PROGRAM FILES\\GOOGLE\\CHROME\\CHROME.EXE", "\\VOLUME{x} (Drive C: 'OS' (Fixed))"),
            _row("MAL.EXE-3.pf", "MAL.EXE", 1,
                 ["2026-02-16 03:00:00"],
                 "C:\\USERS\\A\\APPDATA\\LOCAL\\TEMP\\MAL.EXE", "\\VOLUME{x} (Drive C: 'OS' (Fixed))",
                 resources_extra=["C:\\USERS\\A\\APPDATA\\LOCAL\\TEMP\\INJECT.DLL"]),
            _row("TOOL.EXE-4.pf", "TOOL.EXE", 2,
                 ["2026-02-15 20:00:00", "2026-02-16 20:00:00"],
                 "D:\\TOOLS\\TOOL.EXE", "\\VOLUME{y} (Drive D: 'KINGSTON' (Removable))"),
        ]
        con.executemany("INSERT INTO prefetch_data VALUES (%s)" % ",".join("?" * len(COLS)), rows)
        con.commit(); con.close()
        cls.b = PrefetchBridge(cls.tmp)

    def test_bounds(self):
        r = json.loads(self.b.getPrefetchBounds())
        self.assertTrue(r["hasData"])
        self.assertEqual(r["counts"], {"system": 1, "programfiles": 1, "usertemp": 1, "removable": 1, "other": 0})
        self.assertIn("KINGSTON", r["volumes"])
        self.assertEqual(r["maxDate"], "2026-02-16")

    def test_timeline(self):
        r = json.loads(self.b.getPrefetchTimeline(json.dumps({})))
        self.assertEqual(sum(d["value"] for d in r["sources"]["system"]["days"]), 3)   # 3 run_times
        self.assertEqual(sum(d["value"] for d in r["sources"]["removable"]["days"]), 2)

    def test_overview(self):
        r = json.loads(self.b.getPrefetchOverview(json.dumps({})))
        self.assertEqual(r["totals"]["programs"], 4)
        self.assertEqual(r["totals"]["runs"], 5 + 8 + 1 + 2)
        self.assertEqual(r["insights"]["userTemp"]["count"], 1)
        self.assertEqual(len(r["insights"]["userTemp"]["subjects"]), 1,
                         "the insight states a number it cannot back up")
        self.assertEqual(r["insights"]["removable"]["count"], 1)
        self.assertEqual(len(r["insights"]["removable"]["subjects"]), 1,
                         "the insight states a number it cannot back up")
        self.assertEqual(r["insights"]["singleRun"]["count"], 1)     # MAL ran once
        self.assertEqual(len(r["insights"]["singleRun"]["subjects"]), 1,
                         "the insight states a number it cannot back up")
        self.assertEqual(r["topPrograms"][0]["exe"], "CHROME.EXE")   # run_count 8 is highest
        self.assertTrue(any(v["type"] == "removable" and v["label"] == "KINGSTON" for v in r["volumes"]))

    def test_day_detail(self):
        r = json.loads(self.b.getPrefetchDayDetail(json.dumps({"day": "2026-02-16"})))
        exes = {e["exe"] for e in r["events"]}
        self.assertEqual(exes, {"SVCHOST.EXE", "CHROME.EXE", "MAL.EXE", "TOOL.EXE"})
        self.assertEqual(r["byHour"]["usertemp"][3], 1)   # MAL at 03:00

    def test_program_detail_unusual_resource(self):
        r = json.loads(self.b.getPrefetchProgramDetail(json.dumps({"filename": "MAL.EXE-3.pf"})))
        self.assertEqual(r["location"], "usertemp")
        self.assertEqual(len(r["runTimes"]), 1)
        self.assertGreaterEqual(r["unusualCount"], 1)     # Temp exe + inject.dll load
        self.assertTrue(r["exePath"].upper().endswith("MAL.EXE"))

    def test_new_meta_dict_resources_format(self):
        """The newer resources JSON is a list of dicts with a _meta app_id header;
        the exe path is lifted from app_id and classification must still work
        (regression: every program was landing in 'other')."""
        from visualizations.prefetch_bridge import PrefetchBridge
        row = {
            "filename": "SVC.EXE-9.pf", "executable_name": "SVC.EXE", "hash": "H9",
            "run_count": 3, "last_executed": "2026-09-18 10:00:00",
            "run_times": json.dumps(["2026-09-18 10:00:00"]),
            "volumes": json.dumps([{"volume_id": "C:", "device_name": "\\VOLUME{x} (Drive C: 'OS' (Fixed))", "serial_number": "S9"}]),
            "directories": json.dumps([]),
            "resources": json.dumps([
                {"_meta": {"app_id": "\\DEVICE\\HARDDISKVOLUME3\\WINDOWS\\SYSTEM32\\SVC.EXE"}},
                {"path": "C:\\WINDOWS\\SYSTEM32\\NTDLL.DLL", "mft": "0-0"},
                {"path": "C:\\USERS\\A\\APPDATA\\LOCAL\\TEMP\\HOOK.DLL", "mft": "0-0"},
            ]),
            "created_on": "", "modified_on": "", "accessed_on": "",
        }
        rec = PrefetchBridge("")._record(row)
        self.assertEqual(rec["location"], "system")               # from app_id \WINDOWS\
        self.assertIn("SVC.EXE", rec["exePath"].upper())
        self.assertEqual(rec["resources"], ["C:\\WINDOWS\\SYSTEM32\\NTDLL.DLL",
                                            "C:\\USERS\\A\\APPDATA\\LOCAL\\TEMP\\HOOK.DLL"])


if __name__ == "__main__":
    unittest.main()
