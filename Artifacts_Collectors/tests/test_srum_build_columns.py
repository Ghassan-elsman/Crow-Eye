"""The build a SRUM timeline AppId names: pe_link_time and pe_checksum.

The two tokens after the executable in a '!' AppId were proven against this
machine's own files (146 of 146 System32 and venv executables): the time is
the PE TimeDateStamp and the hex is the PE CheckSum, not the file size. These
tests pin the split, the executable it is taken from (a Store PRAID ending in
'.Exe' named the wrong program), and the re-parse contract: the build is not
part of a row's identity, so a case parsed before the columns existed gains
no second copy of any row and has its NULLs filled instead.
"""
import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from Artifacts_Collectors import SRUM_Claw
from Artifacts_Collectors.SRUM_Claw import (APP_TIMELINE_INSERT, insert_srum_rows,
                                            parse_srum_app_id)
from utils.dedupe_insert import Tally


class TheSplit(unittest.TestCase):

    def test_service_host_form(self):
        p = parse_srum_app_id("!!svchost.exe!2054/02/06:15:19:25!1642e![netsvcs] [Winmgmt]")
        self.assertEqual(("svchost.exe", "[netsvcs] [Winmgmt]"), (p["app_name"], p["hosted_services"]))
        self.assertEqual("2054-02-06 15:19:25", p["pe_link_time"])
        self.assertEqual("0x0001642E", p["pe_checksum"])

    def test_store_form_takes_the_program_not_the_praid(self):
        p = parse_srum_app_id("PythonSoftwareFoundation.PythonManager_25.2.240.0_x64__3847v3x7pw1km"
                              "!Py.Manager.Exe!py-manager.exe!2025/12/05:19:28:48!51354!")
        self.assertEqual("py-manager.exe", p["app_name"])
        self.assertEqual("2025-12-05 19:28:48", p["pe_link_time"])
        self.assertEqual("0x00051354", p["pe_checksum"])

    def test_a_zero_checksum_is_kept(self):
        self.assertEqual("0x00000000", parse_srum_app_id("!!python.exe!2026/02/03:16:10:18!0!")["pe_checksum"])

    def test_no_build_is_empty_never_a_guess(self):
        for raw in (r"\Device\HarddiskVolume3\Windows\System32\svchost.exe [LocalService]",
                    "{0d1e2f}!x!", "!!a.exe!garbage!zz!", "!!a.exe!2026/02/03:16:10:18!"):
            p = parse_srum_app_id(raw)
            self.assertEqual(("", ""), (p["pe_link_time"], p["pe_checksum"]), raw)


def _row(app_name, link, checksum, cycles=5):
    n = APP_TIMELINE_INSERT.count("?")
    row = ["2026-11-01 10:00:00", app_name, "", "", "S-1-5-18", "SYSTEM"] + [None] + [cycles] * (n - 9)
    return tuple(row + [link, checksum])


class TheReparse(unittest.TestCase):

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        cols = SRUM_Claw._INSERT_RE.search(APP_TIMELINE_INSERT).group(2)
        names = [c.strip() for c in cols.split(",") if c.strip()]
        self.conn.execute("CREATE TABLE srum_app_timeline (id INTEGER PRIMARY KEY, %s)"
                          % ", ".join(names))

    def parse(self, rows):
        insert_srum_rows(self.conn, APP_TIMELINE_INSERT, rows, Tally(), {})

    def test_an_old_case_is_filled_not_doubled(self):
        self.parse([_row("python.exe", None, None), _row("svchost.exe", None, None, cycles=9)])
        self.parse([_row("python.exe", "2025-02-04 15:29:44", "0x0004931B"),
                    _row("svchost.exe", "2054-02-06 15:19:25", "0x0001642E", cycles=9)])
        got = self.conn.execute("SELECT app_name, pe_link_time, pe_checksum FROM srum_app_timeline"
                                " ORDER BY app_name").fetchall()
        self.assertEqual([("python.exe", "2025-02-04 15:29:44", "0x0004931B"),
                          ("svchost.exe", "2054-02-06 15:19:25", "0x0001642E")], got)

    def test_a_value_is_never_overwritten(self):
        self.parse([_row("python.exe", "2025-02-04 15:29:44", "0x0004931B")])
        self.parse([_row("python.exe", "1999-01-01 00:00:00", "0x00000001")])
        self.assertEqual([("2025-02-04 15:29:44",)],
                         self.conn.execute("SELECT pe_link_time FROM srum_app_timeline").fetchall())


if __name__ == "__main__":
    unittest.main()
