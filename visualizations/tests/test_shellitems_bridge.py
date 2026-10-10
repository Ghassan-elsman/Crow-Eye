"""ShellItemsBridge — the Shell Items ("user navigation & MRU") dashboard data layer.

Fixture registry_data with all seven source tables, each its own column set,
spanning the sources / item types / volumes: a System shellbag, a network-share
shellbag, a removable-volume shellbag whose embedded FAT time disagrees with the
registry write (the timestomp/mismatch signal), a RecentDocs entry (plus a
MRUListEx metadata row that must be skipped), an OpenSave file on D:, a
LastVisited app+folder, a TypedPath, a RunMRU command and a WordWheelQuery term.
Proves the differing-column unification, classification, and the five slots.
"""
import os
import sys
import json
import sqlite3
import tempfile
import shutil
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from visualizations.shellitems_bridge import ShellItemsBridge

SHELLBAGS_COLS = ["file_name", "short_name", "shell_item_type", "mru_position", "created_date",
                  "modified_date", "accessed_date", "attributes", "file_size", "special_folder",
                  "network_share", "server_name", "share_name", "drive_letter", "mft_record_number",
                  "registry_path", "parent_path", "last_written", "time_basis", "node_slot",
                  "bag_views", "parsed_at", "user_name"]
TABLES = {
    "Shellbags": SHELLBAGS_COLS,
    "RecentDocs": ["subkey", "name", "row_data", "type", "user_name", "mru_position", "key_last_write"],
    "OpenSaveMRU": ["subkey", "name", "type", "file_path", "file_name", "extension", "drive_letter",
                    "access_date", "key_last_write", "row_data", "user_name"],
    "LastSaveMRU": ["mru_number", "type", "application", "folder_path", "folder_name", "drive_letter",
                    "access_date", "key_last_write", "row_data", "user_name"],
    "TypedPaths": ["name", "row_data", "type", "user_name", "mru_position", "key_last_write"],
    "RunMRU": ["command", "mru_position", "access_date", "key_last_write", "user_name"],
    "WordWheelQuery": ["search_term", "search_type", "mru_position", "access_date", "key_last_write", "user_name"],
}


def _row(cols, **vals):
    return tuple(vals.get(c, "") for c in cols)


class TestShellItemsBridge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        con = sqlite3.connect(os.path.join(cls.tmp, "registry_data.db"))
        for t, cols in TABLES.items():
            con.execute('CREATE TABLE "%s" (%s)' % (t, ", ".join(cols)))

        def ins(t, **vals):
            cols = TABLES[t]
            con.execute('INSERT INTO "%s" VALUES (%s)' % (t, ",".join("?" * len(cols))),
                        _row(cols, **vals))

        # --- Shellbags: system / network / removable(with FAT-vs-write mismatch)
        ins("Shellbags", file_name="Windows", shell_item_type="filesystem", drive_letter="C:",
            parent_path="C:\\", created_date="2026-02-10 08:00:00", modified_date="2026-02-14 10:00:00",
            accessed_date="2026-02-14 10:00:00", last_written="2026-02-14 10:05:00",
            mft_record_number="1000", registry_path="Software\\...\\BagMRU\\0", user_name="ann")
        ins("Shellbags", file_name="loot", shell_item_type="network", server_name="NAS", share_name="share",
            network_share="\\\\NAS\\share", modified_date="2026-02-15 09:00:00",
            last_written="2026-02-15 09:00:00", registry_path="Software\\...\\BagMRU\\1", user_name="ann")
        ins("Shellbags", file_name="tools", shell_item_type="filesystem", drive_letter="D:",
            parent_path="D:\\", modified_date="2026-02-16 11:00:00", last_written="2026-02-20 00:00:00",
            file_size="4096", mft_record_number="55", registry_path="Software\\...\\BagMRU\\2", user_name="ann")

        # --- RecentDocs: one real entry + an MRUListEx metadata row (must be skipped)
        ins("RecentDocs", subkey="main", name="MRUListEx", row_data="", type="REG_BINARY")
        ins("RecentDocs", subkey="main", name="1", row_data="report.docx", type="REG_BINARY",
            mru_position=0, key_last_write="2026-02-16 12:00:00", user_name="ann")

        # --- OpenSave file on D:, LastVisited folder, TypedPath, RunMRU, Search
        ins("OpenSaveMRU", name="0", file_path="D:\\secret.xlsx", file_name="secret.xlsx",
            extension="xlsx", drive_letter="D:", access_date="2026-02-16 13:00:00")
        ins("LastSaveMRU", mru_number=0, application="excel.exe", folder_path="C:\\Users\\ann\\Documents",
            folder_name="Documents", drive_letter="C:", access_date="2026-02-15 14:00:00")
        ins("TypedPaths", name="url1", row_data="C:\\Users\\ann\\Downloads",
            mru_position=0, key_last_write="2026-02-15 15:00:00")
        ins("RunMRU", command="cmd.exe", mru_position=0, access_date="2026-02-14 16:00:00")
        ins("WordWheelQuery", search_term="passwords", mru_position=0, access_date="2026-02-13 17:00:00")

        con.commit(); con.close()
        cls.b = ShellItemsBridge(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        # Remove the temp case dir. The fixture writes a real "registry_data.db",
        # and some registry guard tests (test_registry_coverage_gaps,
        # test_registry_user_column_is_meaningful) discover the newest
        # registry_data.db under TEMP - leaving this synthetic one behind makes
        # them fail on fixture data rather than a real parse.
        shutil.rmtree(getattr(cls, "tmp", ""), ignore_errors=True)

    def test_bounds(self):
        r = json.loads(self.b.getShellItemsBounds())
        self.assertTrue(r["hasData"])
        self.assertEqual(r["counts"], {"shellbags": 3, "recentdocs": 1, "opensave": 1,
                                       "lastvisited": 1, "typedpaths": 1, "runmru": 1, "search": 1,
                                       "dialogapps": 0, "taskband": 0, "mountpoints": 0,
                                       "office": 0, "typedurls": 0, "rdp": 0, "recentapps": 0,
                                       "appmru": 0, "regedit": 0, "userassist": 0, "bam": 0,
                                       "dam": 0, "muicache": 0, "shellfolders": 0, "shellext": 0,
                                       "featureusage": 0, "compat": 0, "fileexts": 0,
                                       "programscache": 0, "apppermissions": 0})
        self.assertIn("C:", r["volumes"])
        self.assertIn("D:", r["volumes"])
        self.assertIn("\\\\NAS\\share", r["volumes"])
        # The removable-drive shellbag is dated by its registry write (02-20),
        # not its folder's FAT modified time (02-16).
        self.assertEqual(r["maxDate"], "2026-02-20")

    def test_timeline(self):
        r = json.loads(self.b.getShellItemsTimeline(json.dumps({})))
        self.assertEqual(sum(d["value"] for d in r["sources"]["shellbags"]["days"]), 3)
        self.assertEqual(sum(d["value"] for d in r["sources"]["opensave"]["days"]), 1)

    def test_overview(self):
        r = json.loads(self.b.getShellItemsOverview(json.dumps({})))
        self.assertEqual(r["totals"]["items"], 9)                 # MRUListEx row skipped
        self.assertEqual(r["insights"]["network"]["count"], 1)            # the NAS share
        self.assertEqual(len(r["insights"]["network"]["subjects"]), 1,
                         "the insight states a number it cannot back up")
        self.assertEqual(r["insights"]["removable"]["count"], 2)         # D: shellbag + D: opensave
        self.assertEqual(len(r["insights"]["removable"]["subjects"]), 2,
                         "the insight states a number it cannot back up")
        self.assertEqual(r["insights"]["macMismatch"]["count"], 1)      # tools: FAT 02-16 vs write 02-20
        self.assertEqual(len(r["insights"]["macMismatch"]["subjects"]), 1,
                         "the insight states a number it cannot back up")
        self.assertEqual(r["insights"]["users"]["count"], 1)            # ann
        srcs = {s["source"]: s["n"] for s in r["bySource"]}
        self.assertEqual(srcs["shellbags"], 3)
        self.assertTrue(any(f["file"] == "secret.xlsx" for f in r["topFiles"]))
        self.assertTrue(any(v["type"] == "network" for v in r["volumes"]))

    def test_day_detail(self):
        r = json.loads(self.b.getShellItemsDayDetail(json.dumps({"day": "2026-02-16"})))
        targets = {e["target"] for e in r["events"]}
        self.assertIn("report.docx", targets)                    # recentdocs
        self.assertIn("secret.xlsx", targets)                    # opensave
        # A shellbag is dated by when Explorer recorded it (the registry
        # write, 02-20), not by its folder's own FAT modified time (02-16):
        # dating by the folder time put this week's browsing on years-old days.
        self.assertNotIn("tools", targets)
        self.assertNotIn("MRUListEx", targets)
        r20 = json.loads(self.b.getShellItemsDayDetail(json.dumps({"day": "2026-02-20"})))
        self.assertIn("tools", {e["target"] for e in r20["events"]})

    def test_day_activity(self):
        r = json.loads(self.b.getShellItemsDayActivity(json.dumps({"day": "2026-02-16"})))
        self.assertEqual(r["day"], "2026-02-16")
        self.assertTrue(r["items"])
        self.assertTrue(r["points"])
        # every point carries the bubble axes + colour key
        p = r["points"][0]
        for k in ("item", "hour", "value", "source"):
            self.assertIn(k, p)
        # a bubble's item has a min/max hour range for the span bar
        self.assertIn(r["items"][0], r["ranges"])

    def test_item_detail_mac_mismatch(self):
        bag = next(x for x in self.b._all() if x["target"] == "tools")
        r = json.loads(self.b.getShellItemsItemDetail(json.dumps({"id": bag["id"]})))
        self.assertEqual(r["source"], "shellbags")
        self.assertEqual(r["location"], "removable")
        self.assertTrue(r["macMismatch"])
        self.assertEqual(r["mftRecord"], "55")
        self.assertEqual(r["times"]["modified"], "2026-02-16 11:00:00")

    def test_network_item(self):
        share = next(x for x in self.b._all() if x["target"] == "loot")
        r = json.loads(self.b.getShellItemsItemDetail(json.dumps({"id": share["id"]})))
        self.assertEqual(r["location"], "network")
        self.assertEqual(r["itemType"], "network")

    def test_all_items_lists_every_item_across_days(self):
        """The full list: every record, not one day's worth. 3 shellbags +
        RecentDocs (MRUListEx row excluded) + OpenSave + LastVisited +
        TypedPaths + RunMRU + Search = 9."""
        r = json.loads(self.b.getShellItemsAll(json.dumps({})))
        self.assertEqual(r["total"], 9)
        self.assertEqual(len(r["rows"]), 9)
        self.assertGreater(r["days"], 1)
        times = [x["t"] for x in r["rows"]]
        self.assertEqual(times, sorted(times, reverse=True))      # newest first
        for k in ("id", "t", "source", "target", "path", "user"):
            self.assertIn(k, r["rows"][0])

    def test_all_items_pages_and_orders(self):
        first = json.loads(self.b.getShellItemsAll(json.dumps({"limit": 4})))
        rest = json.loads(self.b.getShellItemsAll(json.dumps({"limit": 4, "offset": 4})))
        ids = [x["id"] for x in first["rows"]] + [x["id"] for x in rest["rows"]]
        self.assertEqual(len(ids), 8)
        self.assertEqual(len(set(ids)), 8)                        # no overlap
        asc = json.loads(self.b.getShellItemsAll(json.dumps({"order": "asc"})))
        times = [x["t"] for x in asc["rows"]]
        self.assertEqual(times, sorted(times))

    def test_empty_source_says_why(self):
        """A source with nothing in it carries an explanation, not just a 0 -
        here CIDSizeMRU, whose table this fixture does not have."""
        r = json.loads(self.b.getShellItemsBounds())
        self.assertIn("dialogapps", r["emptyNotes"])
        self.assertIn("Not in this case", r["emptyNotes"]["dialogapps"])
        self.assertEqual(r["sourceErrors"], {})


MORE_TABLES = {
    "system_configuration": ["setting", "value_raw", "value_decoded", "area", "meaning",
                             "key_path", "last_written", "time_basis", "parsed_at"],
    "MountPoints2": ["user_name", "mount_id", "mount_type", "key_path", "last_written",
                     "time_basis", "parsed_at"],
    "OfficeDocuments": ["user_name", "application", "version", "kind", "document", "raw",
                        "key_path", "last_written", "time_basis", "parsed_at"],
    "BrowserHistory": ["browser", "url", "title", "visit_count", "last_visit", "parsed_at",
                       "user_name"],
    "RDPClientMRU": ["user_name", "entry_type", "server", "username_hint", "key_path",
                     "last_written", "time_basis", "parsed_at"],
    "RecentApps": ["user_name", "app_id", "app_path", "launch_count", "last_accessed",
                   "key_path", "last_written", "time_basis", "parsed_at"],
    "ApplicationArtifacts": ["user_name", "application", "artifact", "name", "value",
                             "key_path", "last_written", "time_basis", "parsed_at"],
    "regedit_lastkey": ["user_name", "name", "value", "key_path", "last_written",
                        "time_basis", "parsed_at"],
}
TASKBAND = "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Taskband"


class TestEveryParsedMruIsShown(unittest.TestCase):
    """The registry parse records more user navigation than the original seven
    tables: taskbar pins, mount points, Office MRUs, TypedURLs, RDP servers,
    RecentApps, per-app MRUs and Regedit's last key. Every one is a source."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        con = sqlite3.connect(os.path.join(cls.tmp, "registry_data.db"))
        for t, cols in MORE_TABLES.items():
            con.execute('CREATE TABLE "%s" (%s)' % (t, ", ".join(cols)))

        def ins(t, **vals):
            cols = MORE_TABLES[t]
            con.execute('INSERT INTO "%s" VALUES (%s)' % (t, ",".join("?" * len(cols))),
                        _row(cols, **vals))

        kw = dict(last_written="2026-03-01 10:00:00", time_basis="key upper bound")
        ins("system_configuration", setting="Favorites", area="taskbar", key_path=TASKBAND,
            value_decoded="2 pinned: Brave.lnk, File Explorer.lnk; 3 by app id (no shortcut)", **kw)
        # Another Taskband value and an unrelated row: neither is a pin.
        ins("system_configuration", setting="FavoritesVersion", area="taskbar", key_path=TASKBAND, **kw)
        ins("system_configuration", setting="HiberbootEnabled", area="power", key_path="SYSTEM\\Power", **kw)
        ins("MountPoints2", user_name="ann", mount_id="##fileserver#finance", mount_type="network share", **kw)
        ins("MountPoints2", user_name="ann", mount_id="{0b2fe29c-e310-47f3-a7d6-1cedcc010000}",
            mount_type="volume GUID", **kw)
        ins("OfficeDocuments", user_name="ann", application="Excel", kind="MRU",
            document="[F00000000][T01DC9F6D04C58F20][O00000000]*C:\\Users\\ann\\Downloads\\budget.xlsx",
            raw="[F00000000][T01DC9F6D04C58F20][O00000000]*C:\\Users\\ann\\Downloads\\budget.xlsx", **kw)
        ins("OfficeDocuments", user_name="ann", application="Word", kind="Place MRU",
            document="C:\\Users\\ann\\Documents\\", raw="C:\\Users\\ann\\Documents\\", **kw)
        ins("BrowserHistory", browser="Internet Explorer", url="http://intranet/hr", user_name="ann")
        ins("RDPClientMRU", user_name="ann", entry_type="MRU", server="10.0.0.5", username_hint="CORP\\ann", **kw)
        ins("RecentApps", user_name="ann", app_id="{6D809377}\\cmd.exe",
            app_path="C:\\Windows\\System32\\cmd.exe", launch_count=4,
            last_accessed="2026-02-20 09:00:00", **kw)
        ins("ApplicationArtifacts", user_name="ann", application="7-Zip", artifact="ArcHistory",
            name="0", value="C:\\Users\\ann\\Desktop\\loot.7z", **kw)
        ins("regedit_lastkey", user_name="ann", name="LastKey",
            value="Computer\\HKEY_LOCAL_MACHINE\\SYSTEM\\CurrentControlSet\\Services", **kw)
        con.commit(); con.close()
        cls.b = ShellItemsBridge(cls.tmp)
        cls.all = json.loads(cls.b.getShellItemsAll(json.dumps({"limit": 500})))["rows"]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(getattr(cls, "tmp", ""), ignore_errors=True)

    def _of(self, source):
        return [r for r in self.all if r["source"] == source]

    def _detail(self, row):
        return json.loads(self.b.getShellItemsItemDetail(json.dumps({"id": row["id"]})))

    def test_taskband_row_becomes_one_record_per_pin(self):
        pins = self._of("taskband")
        self.assertEqual(sorted(r["target"] for r in pins),
                         sorted(["Brave.lnk", "File Explorer.lnk",
                                 "3 Store app(s) pinned by app id (no shortcut)"]))
        self.assertEqual({r["t"] for r in pins}, {"2026-03-01 10:00:00"})
        self.assertIn("Taskband key's write", self._detail(pins[0])["note"])

    def test_a_network_mount_point_is_a_unc_path_on_the_network(self):
        net = [r for r in self._of("mountpoints") if r["path"].startswith("\\\\")]
        self.assertEqual(len(net), 1)
        self.assertEqual(net[0]["path"], "\\\\fileserver\\finance")
        self.assertEqual(self._detail(net[0])["location"], "network")
        self.assertEqual(len(self._of("mountpoints")), 2)

    def test_office_uses_the_items_own_filetime(self):
        xl = [r for r in self._of("office") if r["target"] == "budget.xlsx"]
        self.assertEqual(len(xl), 1)
        self.assertEqual(xl[0]["t"], "2026-02-16 17:52:29")         # [T..], not the key write
        self.assertEqual(xl[0]["path"], "C:\\Users\\ann\\Downloads\\budget.xlsx")
        folder = [r for r in self._of("office") if r["target"] == "Documents"]
        self.assertEqual(folder[0]["t"], "2026-03-01 10:00:00")    # no [T..]: the key write

    def test_the_other_mrus(self):
        self.assertEqual([r["target"] for r in self._of("typedurls")], ["http://intranet/hr"])
        rdp = self._of("rdp")
        self.assertEqual([r["target"] for r in rdp], ["10.0.0.5"])
        self.assertEqual(self._detail(rdp[0])["location"], "network")
        apps = self._of("recentapps")
        self.assertEqual(apps[0]["target"], "cmd.exe")
        self.assertEqual(apps[0]["t"], "2026-02-20 09:00:00")
        self.assertEqual([r["target"] for r in self._of("appmru")], ["loot.7z"])
        self.assertIn("Services", self._of("regedit")[0]["target"])

    def test_every_source_is_counted_and_listed(self):
        b = json.loads(self.b.getShellItemsBounds())
        for src in ("taskband", "mountpoints", "office", "typedurls", "rdp",
                    "recentapps", "appmru", "regedit"):
            self.assertGreater(b["counts"][src], 0, src)
        self.assertEqual(b["total"], len(self.all))
        self.assertEqual(sum(b["counts"].values()), len(self.all))


SHELL_COLS = ["hive", "key_path", "name", "data", "data_decoded", "type", "user_name", "parsed_at"]
UNDATED_TABLES = {
    "MUICache": ["app_path", "app_name", "company", "file_extension", "parsed_at", "user_name"],
    "user_shell_folders": SHELL_COLS,
    "shell_open_command": SHELL_COLS,
    "shell_icon_overlay_identifiers": SHELL_COLS,
    "shell_service_object_delay_load": SHELL_COLS,
    # One dated row so a date range has something to exclude.
    "RDPClientMRU": MORE_TABLES["RDPClientMRU"],
}


class TestUndatedSources(unittest.TestCase):
    """MUICache, User Shell Folders and the shell-extension tables carry no
    time at all. They must still be listed and counted when a date range is
    set - the dashboard always sets one - instead of being filtered away."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        con = sqlite3.connect(os.path.join(cls.tmp, "registry_data.db"))
        for t, cols in UNDATED_TABLES.items():
            con.execute('CREATE TABLE "%s" (%s)' % (t, ", ".join(cols)))

        def ins(t, **vals):
            cols = UNDATED_TABLES[t]
            con.execute('INSERT INTO "%s" VALUES (%s)' % (t, ",".join("?" * len(cols))),
                        _row(cols, **vals))

        ins("MUICache", app_path="C:\\Tools\\procexp64.exe", app_name="Process Explorer",
            company="Sysinternals - www.sysinternals.com", user_name="ann")
        ins("user_shell_folders", hive="NTUSER", name="Desktop", data="%USERPROFILE%\\Desktop",
            data_decoded="C:\\Users\\ann\\OneDrive\\Desktop", user_name="ann")
        ins("shell_open_command", hive="NTUSER", name="ms-settings",
            data_decoded="C:\\Users\\ann\\AppData\\Local\\Temp\\x.exe", user_name="ann")
        ins("shell_icon_overlay_identifiers", hive="SOFTWARE", name=" OneDrive1",
            data_decoded="{BBACC218-34EA-4666-9D7A-C78F2274A524}")
        ins("shell_service_object_delay_load", hive="SOFTWARE", name="WebCheck",
            data_decoded="{E6FB5E20-DE35-11CF-9C87-00AA005127ED}")
        ins("RDPClientMRU", user_name="ann", entry_type="MRU", server="10.0.0.5",
            last_written="2026-03-01 10:00:00")
        con.commit(); con.close()
        cls.b = ShellItemsBridge(cls.tmp, focus_source="muicache")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(getattr(cls, "tmp", ""), ignore_errors=True)

    def _all(self, **args):
        args.setdefault("limit", 500)
        return json.loads(self.b.getShellItemsAll(json.dumps(args)))["rows"]

    def test_undated_rows_survive_a_date_range(self):
        rows = self._all(start="2020-01-01", end="2020-12-31")   # excludes the RDP row
        by = {}
        for r in rows:
            by.setdefault(r["source"], []).append(r)
        self.assertNotIn("rdp", by)
        self.assertEqual([r["target"] for r in by["muicache"]], ["Process Explorer"])
        self.assertEqual(by["muicache"][0]["path"], "C:\\Tools\\procexp64.exe")
        self.assertEqual(by["shellfolders"][0]["target"], "Desktop")
        self.assertEqual(by["shellfolders"][0]["path"], "C:\\Users\\ann\\OneDrive\\Desktop")
        self.assertEqual(len(by["shellext"]), 3)
        self.assertTrue(all(not r["t"] for r in rows))

    def test_shell_extension_note_names_its_table(self):
        ext = [r for r in self._all() if r["source"] == "shellext"]
        notes = [json.loads(self.b.getShellItemsItemDetail(json.dumps({"id": r["id"]})))["note"]
                 for r in ext]
        self.assertTrue(any("icon overlay" in n for n in notes), notes)
        self.assertTrue(any("delay-load" in n for n in notes), notes)
        self.assertTrue(any("open command" in n for n in notes), notes)

    def test_counts_include_undated_sources(self):
        b = json.loads(self.b.getShellItemsBounds())
        self.assertEqual((b["counts"]["muicache"], b["counts"]["shellfolders"],
                          b["counts"]["shellext"], b["counts"]["rdp"]), (1, 1, 3, 1))

    def test_focus_source(self):
        self.assertEqual(json.loads(self.b.getShellItemsFocus()), {"source": "muicache"})
        other = ShellItemsBridge(self.tmp, focus_source="not-a-source")
        self.assertEqual(json.loads(other.getShellItemsFocus()), {"source": ""})


# The registry tables that record what a user RAN or SET, as the parser
# writes them (Regclaw / offline_RegClaw).
EXEC_TABLES = {
    "UserAssist": ["program_path", "run_count", "last_execution", "focus_count", "focus_time",
                   "user_sid", "parsed_at"],
    "BAM": ["subkey", "name", "row_data", "type", "app_name", "process_path", "sid",
            "last_execution", "decoded", "name_kind", "name_kind_raw", "trailing_value",
            "last_written", "time_basis", "parsed_at"],
    "DAM": ["subkey", "name", "row_data", "type", "app_name", "process_path", "sid",
            "last_execution", "execution_count", "decoded", "name_kind", "name_kind_raw",
            "trailing_value", "last_written", "time_basis", "parsed_at"],
    "FeatureUsage": ["user_name", "usage_type", "program", "count", "key_path", "last_written",
                     "time_basis", "parsed_at"],
    "CompatibilityAssistant": ["user_name", "program_path", "blob_size", "key_path",
                               "last_written", "time_basis", "parsed_at"],
    "file_exts": ["user_name", "extension", "choice_type", "progid", "key_path", "last_written",
                  "time_basis", "parsed_at"],
    "programs_cache": ["user_name", "value_name", "blob_size", "key_path", "last_written",
                       "time_basis", "parsed_at"],
    "app_permissions": ["capability", "app", "packaged", "permission", "last_used_start",
                        "last_used_stop", "key_path", "last_written", "time_basis", "parsed_at"],
}


class TestRegistryExecutionSources(unittest.TestCase):
    """UserAssist, BAM, DAM, FeatureUsage, the PCA store, FileExts and the
    ProgramsCache had no dashboard: they are sources of this one now. The ones
    with a time per entry are dated; the ones with only a key write time (one
    upper bound for every entry under it) are listed undated, never piled on
    that one day."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        con = sqlite3.connect(os.path.join(cls.tmp, "registry_data.db"))
        for t, cols in EXEC_TABLES.items():
            con.execute('CREATE TABLE "%s" (%s)' % (t, ", ".join(cols)))

        def ins(t, **vals):
            cols = EXEC_TABLES[t]
            con.execute('INSERT INTO "%s" VALUES (%s)' % (t, ",".join("?" * len(cols))),
                        _row(cols, **vals))

        sid = "S-1-5-21-1-2-3-1001 (HOST\\ann)"
        ins("UserAssist", program_path="UEME_CTLSESSION", user_sid=sid)          # counters: skipped
        ins("UserAssist", program_path="C:\\Tools\\procexp64.exe", run_count="4",
            focus_count="2", focus_time="65000", last_execution="2026-03-02 09:00:00", user_sid=sid)
        ins("BAM", subkey="S-1-5-21-1-2-3-1001", name="Version", sid=sid)        # metadata: skipped
        ins("BAM", process_path="\\Device\\HarddiskVolume3\\Windows\\System32\\cmd.exe",
            app_name="cmd.exe", sid=sid, last_execution="2026-03-03 10:00:00",
            last_written="2026-03-05 00:00:00")
        ins("DAM", process_path="\\Device\\HarddiskVolume3\\x\\y.exe", sid=sid,
            last_execution="2026-03-04 11:00:00", execution_count="3")
        for prog in ("Brave", "Outlook", "Teams"):
            ins("FeatureUsage", user_name="HOST\\ann", usage_type="AppSwitched", program=prog,
                count="7", last_written="2026-03-05 00:00:00")
        ins("CompatibilityAssistant", user_name="HOST\\ann",
            program_path="C:\\Users\\ann\\Downloads\\setup.exe", last_written="2026-03-05 00:00:00")
        ins("file_exts", user_name="HOST\\ann", extension=".001", choice_type="OpenWithList",
            progid="FTK Imager.exe", last_written="2026-03-05 00:00:00")
        ins("programs_cache", user_name="HOST\\ann", value_name="ProgramsCache", blob_size="4096")
        ins("app_permissions", capability="webcam", app="C:#Program Files#Zoom#bin#Zoom.exe",
            packaged=0, permission="Allow", last_used_start="2026-03-06 14:00:00",
            last_used_stop="2026-03-06 14:45:00", last_written="2026-03-07 00:00:00")
        con.commit(); con.close()
        cls.b = ShellItemsBridge(cls.tmp, focus_source="bam")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(getattr(cls, "tmp", ""), ignore_errors=True)

    def _rows(self, **args):
        args.setdefault("limit", 500)
        return json.loads(self.b.getShellItemsAll(json.dumps(args)))["rows"]

    def test_counts_skip_counters_and_metadata(self):
        c = json.loads(self.b.getShellItemsBounds())["counts"]
        self.assertEqual((c["userassist"], c["bam"], c["dam"], c["featureusage"], c["compat"],
                          c["fileexts"], c["programscache"]), (1, 1, 1, 3, 1, 1, 1))

    def test_executions_are_dated_by_their_own_time(self):
        by = {r["source"]: r for r in self._rows()}
        self.assertEqual(by["userassist"]["t"], "2026-03-02 09:00:00")
        self.assertEqual(by["bam"]["t"], "2026-03-03 10:00:00")       # not the key's write time
        self.assertEqual(by["bam"]["target"], "cmd.exe")
        self.assertEqual(by["bam"]["user"], "HOST\\ann")
        self.assertEqual(by["userassist"]["itemType"], "executed")

    def test_key_time_only_sources_are_undated(self):
        rows = [r for r in self._rows() if r["source"] in ("featureusage", "compat", "fileexts",
                                                            "programscache")]
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(not r["t"] for r in rows), rows)
        detail = json.loads(self.b.getShellItemsItemDetail(json.dumps({"id": rows[0]["id"]})))
        self.assertIn("upper bound", detail["note"])

    def test_userassist_note_carries_counts(self):
        ua = [r for r in self._rows() if r["source"] == "userassist"][0]
        note = json.loads(self.b.getShellItemsItemDetail(json.dumps({"id": ua["id"]})))["note"]
        self.assertIn("run 4 time(s)", note)
        self.assertIn("65s", note)

    def test_file_association_is_a_setting(self):
        fe = [r for r in self._rows() if r["source"] == "fileexts"][0]
        self.assertEqual((fe["target"], fe["itemType"]), (".001", "configured"))

    def test_device_use_is_dated_by_its_own_start(self):
        cam = [r for r in self._rows() if r["source"] == "apppermissions"]
        self.assertEqual(len(cam), 1)
        self.assertEqual(cam[0]["t"], "2026-03-06 14:00:00")          # not the key's write time
        self.assertEqual(cam[0]["itemType"], "device access")
        note = json.loads(self.b.getShellItemsItemDetail(json.dumps({"id": cam[0]["id"]})))["note"]
        self.assertIn("webcam", note)
        self.assertIn("until 2026-03-06 14:45:00", note)

    def test_focus_source(self):
        self.assertEqual(json.loads(self.b.getShellItemsFocus()), {"source": "bam"})


class TestFrontEndKnowsEverySource(unittest.TestCase):
    """A source the bridge emits but format.js has no entry or colour ramp for
    throws during render and blanks the whole dashboard."""

    def test_every_bridge_source_has_a_label_and_a_ramp(self):
        import re
        from visualizations.shellitems_bridge import SOURCES
        fmt = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "react-shellitems", "src", "format.js")
        with open(fmt, encoding="utf-8") as fh:
            src = fh.read()
        keys = set(re.findall(r"\{ key: '([a-z]+)'", src.split("export const SOURCES")[1].split("]")[0]))
        ramps = src.split("export const SOURCE_RAMPS")[1].split("}")[0]
        for s in SOURCES:
            self.assertIn(s, keys, "%s has no SOURCES entry in format.js" % s)
            self.assertRegex(ramps, r"\n  %s: \[" % s, "%s has no SOURCE_RAMPS entry" % s)


if __name__ == "__main__":
    unittest.main()
