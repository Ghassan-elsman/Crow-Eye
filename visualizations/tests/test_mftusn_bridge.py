"""MftUsnBridge — the MFT/USN correlated dashboard's data layer.

Two fixtures:

* a tiny one with a *subset* of the correlated columns, to prove the bridge
  tolerates schema drift (older correlators lack volume_letter, usn_filename,
  mft_sequence_number, usn_parent_frn...), and
* a full-schema one shaped like the real case it was rebuilt against: an MFT
  record repeated once per USN event, a journal-only file whose MFT entry was
  reused, a folder that exists only in the journal, and an 8.3 File-Name.
"""
import os
import sys
import json
import sqlite3
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from visualizations.mftusn_bridge import (MftUsnBridge, parse_file_id, reason_cats,
                                          reason_flags)


# Only a subset of the full schema — no volume_letter / file_size / has_ads.
CORR_COLS = [
    "mft_record_number", "fn_filename", "reconstructed_path", "is_directory", "is_deleted",
    "si_creation_time", "si_modification_time", "si_access_time", "si_mft_entry_change_time",
    "fn_creation_time", "fn_modification_time", "fn_access_time", "fn_mft_entry_change_time",
    "fn_real_size",
    "usn_timestamp", "usn_reason", "has_mft_record", "has_usn_event",
]


def _row(rec, path, fn, reason=None, usn_t=None, si_c="2026-02-16 05:00:00",
         si_m="2026-02-16 05:00:00", size=100, is_dir=0, is_del=0, fn_c=None):
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


class TestMftUsnBridgeDrift(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        corr = os.path.join(cls.tmp, "mft_usn_correlated_analysis.db")
        con = sqlite3.connect(corr)
        con.execute("CREATE TABLE mft_usn_correlated (%s)" % ", ".join(f"{c}" for c in CORR_COLS))
        rows = [
            _row(10, "./Users/a/new.txt", "new.txt", "DATA_EXTEND | FILE_CREATE | CLOSE", "2026-02-16 05:10:00"),
            _row(11, "./Users/a/old.txt", "old.txt", "RENAME_NEW_NAME | CLOSE", "2026-02-16 05:20:00"),
            _row(12, "./Windows/x.dll", "x.dll", "DATA_OVERWRITE | CLOSE", "2026-02-16 05:30:00"),
            _row(13, "./Windows/y.dll", "y.dll", "SECURITY_CHANGE | CLOSE", "2026-02-16 05:40:00"),
            _row(14, "./tmp/z.tmp", "z.tmp", "FILE_DELETE | CLOSE", "2026-02-16 05:50:00", is_del=1),
            # timestomp candidate: SI creation NEWER than FN creation (forward-dated)
            _row(15, "./t/stomp.exe", "stomp.exe", None, None,
                 si_c="2026-02-16 10:00:00", fn_c="2026-02-15 09:00:00"),
            # an old MFT-only file (long MFT history), SI == FN — must NOT be flagged
            _row(16, "./old/legacy.sys", "legacy.sys", None, None,
                 si_c="2020-05-01 00:00:00", si_m="2020-05-02 00:00:00"),
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

    def test_reason_flags_and_cats(self):
        self.assertEqual(reason_flags("DATA_EXTEND | FILE_CREATE | CLOSE"),
                         ["DATA_EXTEND", "FILE_CREATE", "CLOSE"])
        self.assertEqual(reason_cats("DATA_EXTEND | FILE_CREATE | CLOSE"), {"create", "data"})
        self.assertEqual(reason_cats("RENAME_NEW_NAME | CLOSE"), {"rename"})
        self.assertEqual(reason_cats("SECURITY_CHANGE | CLOSE"), {"meta"})
        # A substring match put NAMED_DATA_EXTEND under "data" as well.
        self.assertEqual(reason_cats("NAMED_DATA_EXTEND"), {"meta"})
        self.assertEqual(reason_cats(None), set())

    def test_bounds_cover_both_sources(self):
        r = json.loads(self.b.getMftUsnBounds())
        self.assertTrue(r["hasData"])
        self.assertEqual((r["usnMin"], r["usnMax"]), ("2026-02-16", "2026-02-16"))
        self.assertEqual(r["mftMin"], "2020-05-01")
        self.assertEqual((r["min"], r["max"]), ("2020-05-01", "2026-02-16"))
        self.assertFalse(r["hasVolume"])   # drift: no volume_letter column

    def test_one_axis_for_mft_and_every_flag(self):
        r = json.loads(self.b.getMftUsnTimelines(json.dumps({})))
        self.assertNotIn("bucket", r)
        keys = [row["key"] for row in r["rows"]]
        self.assertEqual(keys[:2], ["mft_created", "mft_modified"])
        self.assertEqual(set(keys[2:]), {"FILE_CREATE", "FILE_DELETE", "RENAME_NEW_NAME",
                                         "DATA_OVERWRITE", "DATA_EXTEND", "SECURITY_CHANGE", "CLOSE"})
        # Every series shares the same day list: the MFT's 2020 and the journal's 2026.
        days = [c["key"] for c in r["combined"]]
        self.assertEqual((days[0], days[-1]), ("2020-05-01", "2026-02-16"))
        for k in keys:
            self.assertEqual([b["key"] for b in r["series"][k]["buckets"]], days)
        total = lambda k: sum(b["value"] for b in r["series"][k]["buckets"])
        self.assertEqual(total("FILE_CREATE"), 1)
        self.assertEqual(total("CLOSE"), 5)
        self.assertEqual(total("mft_created"), 7)          # 7 distinct files

    def test_window_detail_counts_the_whole_day(self):
        r = json.loads(self.b.getMftUsnWindowDetail(json.dumps({"bucket": "2026-02-16"})))
        self.assertEqual(r["total"], 5)
        self.assertEqual(len(r["events"]), 5)
        self.assertEqual(r["byHour"]["FILE_CREATE"][5], 1)
        self.assertEqual(r["byHourCat"]["delete"][5], 1)
        self.assertEqual(r["byFlag"]["CLOSE"], 5)
        self.assertTrue(any("Windows" in d["dir"] for d in r["topDirs"]))
        self.assertEqual(r["mft"]["created"]["total"], 6)   # all but legacy.sys

    def test_overview_and_anomalies(self):
        r = json.loads(self.b.getMftUsnOverview(json.dumps({})))
        t = r["totals"]
        self.assertEqual(t["usnEvents"], 5)
        self.assertEqual(t["created"], 1)
        self.assertEqual(t["renamed"], 1)
        self.assertEqual(t["dataChanged"], 2)
        self.assertEqual(t["deletedEvents"], 1)
        self.assertEqual(t["files"], 7)
        a = r["anomalies"]
        self.assertEqual(a["timestompCandidates"]["count"], 1)   # rec 15
        self.assertTrue(a["timestompCandidates"]["subjects"],
                        "the anomaly states a number it cannot back up")
        self.assertIn("open", a["timestompCandidates"]["subjects"][0])
        self.assertEqual(a["usnGaps"]["count"], 1)                      # deleted_entries row
        self.assertEqual(len(a["usnGaps"]["subjects"]), 1)

    def test_file_detail(self):
        r = json.loads(self.b.getMftUsnFileDetail(json.dumps({"rec": 10})))
        self.assertEqual(r["filename"], "new.txt")
        self.assertEqual(len(r["events"]), 1)
        self.assertEqual(sorted(r["events"][0]["cats"]), ["create", "data"])

    def test_file_detail_timestomp_flag(self):
        r = json.loads(self.b.getMftUsnFileDetail(json.dumps({"rec": 15})))
        self.assertTrue(any("newer than file-name creation" in f.lower() for f in r["flags"]))

    def test_clean_file_not_flagged(self):
        r = json.loads(self.b.getMftUsnFileDetail(json.dumps({"rec": 16})))
        self.assertEqual(r["flags"], [])

    def test_the_dead_timestomp_rule_is_gone(self):
        """'All four SI times whole seconds while FN keeps sub-seconds' can never
        fire: this parser stores MFT times to the whole second on both sides."""
        src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "mftusn_bridge.py"), encoding="utf-8").read()
        self.assertNotIn("NOT LIKE '%.%'", src)
        self.assertNotIn("timestomp-tool signature", src)


FULL_COLS = ["volume_letter", "mft_record_number", "mft_sequence_number", "fn_filename",
             "reconstructed_path", "is_directory", "is_deleted", "file_size", "has_ads",
             "si_creation_time", "si_modification_time", "si_access_time", "si_mft_entry_change_time",
             "fn_creation_time", "fn_modification_time", "fn_access_time", "fn_mft_entry_change_time",
             "usn_timestamp", "usn_reason", "usn_filename", "usn_frn", "usn_parent_frn",
             "has_mft_record", "has_usn_event"]


def _frn(rec, seq):
    return str((seq << 48) | rec)


def _full(vol, rec, seq, fn, path, *, reason=None, t=None, un=None, parent=None, mft=1,
          is_dir=0, si_c="2026-10-01 10:00:00"):
    return {"volume_letter": vol, "mft_record_number": rec, "mft_sequence_number": seq,
            "fn_filename": fn if mft else None, "reconstructed_path": path if mft else None,
            "is_directory": is_dir, "is_deleted": 0, "file_size": 10, "has_ads": 0,
            "si_creation_time": si_c if mft else None, "si_modification_time": si_c if mft else None,
            "si_access_time": None, "si_mft_entry_change_time": None,
            "fn_creation_time": si_c if mft else None, "fn_modification_time": None,
            "fn_access_time": None, "fn_mft_entry_change_time": None,
            "usn_timestamp": t, "usn_reason": reason, "usn_filename": un,
            "usn_frn": _frn(rec, seq) if reason else None,
            "usn_parent_frn": _frn(*parent) if parent else None,
            "has_mft_record": mft, "has_usn_event": 1 if reason else 0}


class TestMftUsnBridgeRealShape(unittest.TestCase):
    """Shaped like the 7.10.2026 case the dashboard was rebuilt against."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        con = sqlite3.connect(os.path.join(cls.tmp, "mft_usn_correlated_analysis.db"))
        con.execute("CREATE TABLE mft_usn_correlated (%s)" % ", ".join(FULL_COLS))
        rows = [
            # root and a live Temp folder
            _full("C", 5, 5, ".", "./", is_dir=1),
            _full("C", 100, 3, "Temp", "./Users/a/Temp", is_dir=1),
            # one MFT record with an 8.3 File-Name, repeated per USN event (3 rows)
            _full("C", 44, 195, "MIGRAT~1.DAT", "./Users/a/Temp/MIGRAT~1.DAT",
                  reason="DATA_EXTEND | FILE_CREATE", t="2026-10-08 01:00:00",
                  un="migration.dat", parent=(100, 3)),
            _full("C", 44, 195, "MIGRAT~1.DAT", "./Users/a/Temp/MIGRAT~1.DAT",
                  reason="DATA_OVERWRITE", t="2026-10-08 01:05:00",
                  un="migration.dat", parent=(100, 3)),
            _full("C", 44, 195, "MIGRAT~1.DAT", "./Users/a/Temp/MIGRAT~1.DAT",
                  reason="DATA_EXTEND | CLOSE", t="2026-10-08 02:00:00",
                  un="migration.dat", parent=(100, 3)),
            # a scoped folder that exists only in the journal (record 300 reused since)
            _full("C", 300, 7, None, None, reason="FILE_CREATE", t="2026-10-08 00:50:00",
                  un="scoped_dir1", parent=(100, 3), mft=0, is_dir=1),
            # a file inside it, journal-only too
            _full("C", 301, 2, None, None, reason="FILE_CREATE | CLOSE", t="2026-10-08 00:51:00",
                  un="banner.css", parent=(300, 7), mft=0),
            # record 300 now held by an unrelated file (sequence 8): must not name the folder
            _full("C", 300, 8, "other.txt", "./other.txt", reason="BASIC_INFO_CHANGE",
                  t="2026-10-08 03:00:00", un="other.txt", parent=(5, 5)),
            # a file whose parent nobody recorded
            _full("C", 400, 1, None, None, reason="FILE_DELETE | CLOSE", t="2026-10-08 03:30:00",
                  un="lost.tmp", parent=(999, 1), mft=0),
        ]
        con.executemany("INSERT INTO mft_usn_correlated VALUES (%s)" % ",".join("?" * len(FULL_COLS)),
                        [tuple(r[c] for c in FULL_COLS) for r in rows])
        con.commit(); con.close()
        cls.b = MftUsnBridge(cls.tmp)

    def _events(self):
        r = json.loads(self.b.getMftUsnWindowDetail(json.dumps({"bucket": "2026-10-08"})))
        return r, {e["name"]: e for e in r["events"]}

    def test_files_are_counted_once_not_per_event(self):
        r = json.loads(self.b.getMftUsnOverview("{}"))
        self.assertEqual(r["totals"]["files"], 4)          # 5, 100, 44, 300@8
        self.assertEqual(r["totals"]["usnEvents"], 7)
        tl = json.loads(self.b.getMftUsnTimelines("{}"))
        created = sum(b["value"] for b in tl["series"]["mft_created"]["buckets"])
        self.assertEqual(created, 4)

    def test_the_long_name_wins_over_the_8_3_alias(self):
        _r, ev = self._events()
        self.assertIn("migration.dat", ev)
        e = ev["migration.dat"]
        self.assertEqual(e["path"], "Users/a/Temp/migration.dat")
        self.assertEqual(e["shortName"], "MIGRAT~1.DAT")

    def test_journal_only_files_get_their_folder_back(self):
        _r, ev = self._events()
        self.assertEqual(ev["banner.css"]["path"], "Users/a/Temp/scoped_dir1/banner.css")
        self.assertEqual(ev["banner.css"]["pathFrom"], "journal")
        self.assertFalse(ev["banner.css"]["inMft"])

    def test_a_reused_record_does_not_name_someone_elses_folder(self):
        _r, ev = self._events()
        self.assertNotIn("other.txt/banner.css", ev["banner.css"]["path"])

    def test_an_unknown_folder_is_said_not_guessed(self):
        _r, ev = self._events()
        self.assertEqual(ev["lost.tmp"]["path"], "")

    def test_top_directories_count_journal_only_events(self):
        r, _ev = self._events()
        dirs = {d["dir"]: d["n"] for d in r["topDirs"]}
        self.assertEqual(dirs.get("Users/a/Temp"), 4)        # 3 migration.dat + scoped_dir1
        self.assertEqual(dirs.get("Users/a/Temp/scoped_dir1"), 1)

    def test_paging_and_one_hour(self):
        page = json.loads(self.b.getMftUsnDayEvents(json.dumps({"bucket": "2026-10-08", "hour": 1})))
        self.assertEqual(page["total"], 2)
        self.assertTrue(all(e["hour"] == 1 for e in page["events"]))
        self.assertEqual(page["hour"], 1)

    def test_file_detail_by_volume_record_and_sequence(self):
        self.assertEqual(parse_file_id("C:300:7"), ("C", 300, 7))
        old = json.loads(self.b.getMftUsnFileDetail(json.dumps({"id": "C:300:7"})))
        new = json.loads(self.b.getMftUsnFileDetail(json.dumps({"id": "C:300:8"})))
        self.assertEqual(old["filename"], "scoped_dir1")
        self.assertFalse(old["inMft"])
        self.assertEqual(new["filename"], "other.txt")
        self.assertEqual(len(old["events"]), 1)
        self.assertEqual(len(new["events"]), 1)
        mig = json.loads(self.b.getMftUsnFileDetail(json.dumps({"id": "C:44:195"})))
        self.assertEqual(mig["filename"], "migration.dat")
        self.assertEqual(mig["eventsTotal"], 3)


class TestAllFilesWalk(unittest.TestCase):
    """The All-files list with no filter walks idx_corr_si_modified from the
    previous page's last file instead of grouping every file again for each
    page (about 7 s a page on 3.3 M files). Each page must be the one the
    GROUP BY gives: every file once, in the same order, across two volumes,
    shared timestamps and a file repeated once per USN event."""

    N = 1300                                   # three pages of 500

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.db = os.path.join(cls.tmp, "mft_usn_correlated_analysis.db")
        con = sqlite3.connect(cls.db)
        con.execute("CREATE TABLE mft_usn_correlated (%s)" % ", ".join(FULL_COLS))
        rows = []
        for i in range(cls.N):
            vol = "CD"[i % 2]
            si = "2026-10-%02d 10:%02d:00" % (1 + i % 9, i % 7)     # many ties
            for k in range(1 + i % 3):                               # 1-3 rows per file
                rows.append(_full(vol, 1000 + i // 2, 1, "f%d.txt" % i, "./f%d.txt" % i,
                                  reason="DATA_EXTEND", t="2026-10-10 00:00:%02d" % k,
                                  un="f%d.txt" % i, si_c=si))
        con.executemany("INSERT INTO mft_usn_correlated VALUES (%s)" % ",".join("?" * len(FULL_COLS)),
                        [tuple(r[c] for c in FULL_COLS) for r in rows])
        con.execute("CREATE INDEX idx_corr_si_modified ON mft_usn_correlated"
                    "(si_modification_time, volume_letter, mft_record_number) WHERE has_mft_record = 1")
        con.commit()
        cls.con = con

    def _reference(self, order, offset):
        o = order.upper()
        return [(v, r, t) for v, r, t in self.con.execute(
            "SELECT volume_letter vol, mft_record_number rec, si_modification_time t "
            "FROM mft_usn_correlated WHERE has_mft_record=1 GROUP BY vol, rec "
            "ORDER BY t %s, vol %s, rec %s LIMIT 500 OFFSET %d" % (o, o, o, offset))]

    def _page(self, b, order, offset, **extra):
        r = json.loads(b.getMftUsnAll(json.dumps(dict(kind="files", order=order,
                                                      offset=offset, **extra))))
        return r, [parse_file_id(f["id"])[:2] + (f["t"],) for f in r["rows"]]

    def test_load_more_pages_match_the_group_by(self):
        b = MftUsnBridge(self.tmp)
        grouped = []
        b._mft_files = lambda *a, **k: grouped.append(a) or {"total": 0, "files": []}
        for order in ("desc", "asc"):
            seen = set()
            for offset in (0, 500, 1000):
                r, got = self._page(b, order, offset)
                self.assertEqual(got, self._reference(order, offset), (order, offset))
                self.assertEqual(r["total"], self.N)
                seen.update(g[:2] for g in got)
            self.assertEqual(len(seen), self.N)
        self.assertEqual(grouped, [])          # the walk answered every page

    def test_a_date_range_and_a_volume_are_walked_too(self):
        b = MftUsnBridge(self.tmp)
        grouped = []
        real = b._mft_files
        b._mft_files = lambda *a, **k: grouped.append(a) or real(*a, **k)
        for flt, sql in (({"start": "2026-10-03", "end": "2026-10-06"},
                          "si_modification_time >= '2026-10-03' AND "
                          "si_modification_time < date('2026-10-06', '+1 day')"),
                         ({"volume": "D"}, "volume_letter = 'D'"),
                         ({"start": "2026-10-02", "volume": "C"},
                          "si_modification_time >= '2026-10-02' AND volume_letter = 'C'")):
            for order in ("desc", "asc"):
                o = order.upper()
                ref = [(v, r, t) for v, r, t in self.con.execute(
                    "SELECT volume_letter vol, mft_record_number rec, si_modification_time t "
                    "FROM mft_usn_correlated WHERE has_mft_record=1 AND %s GROUP BY vol, rec "
                    "ORDER BY t %s, vol %s, rec %s" % (sql, o, o, o))]
                self.assertGreater(len(ref), 0)
                got, offset = [], 0
                while True:
                    r, page = self._page(b, order, offset, **flt)
                    self.assertEqual(r["total"], len(ref), flt)
                    got += page
                    if len(page) < 500:
                        break
                    offset += 500
                self.assertEqual(got, ref, (flt, order))
        self.assertEqual(grouped, [])

    def test_a_searchs_later_pages_resume_from_the_group_by_page(self):
        # A search's page 0 is the GROUP BY page (sparse matches can make the
        # walk's residual scan cost as much as one grouping), and it plants a
        # cursor: every "load more" after it is walked, applying the same
        # term test to each index entry, instead of grouping every matching
        # file again (~7 s a page on 3.3 M files).
        b = MftUsnBridge(self.tmp)
        ref = MftUsnBridge(self.tmp)               # the plain GROUP BY, for parity
        groupings = []
        real = b._mft_files
        b._mft_files = lambda *a, **k: groupings.append(a) or real(*a, **k)
        args = {"terms": ["f"], "mode": "or"}      # every fixture file matches
        where, params = ref._where(args, extra="has_mft_record=1")
        for order in ("desc", "asc"):
            seen = set()
            for offset in (0, 500, 1000):
                r, got = self._page(b, order, offset, **args)
                want = ref._mft_files(where, params, "si_modification_time",
                                      offset, 500, order.upper())
                self.assertEqual(got, [parse_file_id(f["id"])[:2] + (f["t"],)
                                       for f in want["files"]], (order, offset))
                self.assertEqual(r["total"], self.N)
                seen.update(g[:2] for g in got)
            self.assertEqual(len(seen), self.N)
        # one grouping per order: page 0 only; the later pages were walked
        self.assertEqual(len(groupings), 2)

    def test_a_searchs_walked_page_matches_what_the_term_matches(self):
        # A term most files do NOT match: the walk must skip the gaps and
        # still agree with the GROUP BY, page by page.
        b = MftUsnBridge(self.tmp)
        ref = MftUsnBridge(self.tmp)
        args = {"terms": ["f1"], "mode": "or"}     # f1, f1x, f10xx... a sparse subset
        where, params = ref._where(args, extra="has_mft_record=1")
        total = None
        for order in ("desc", "asc"):
            offset, got_all = 0, []
            while True:
                r, got = self._page(b, order, offset, **args)
                want = ref._mft_files(where, params, "si_modification_time",
                                      offset, 500, order.upper())
                self.assertEqual(got, [parse_file_id(f["id"])[:2] + (f["t"],)
                                       for f in want["files"]], (order, offset))
                total = r["total"]
                got_all += got
                if len(got) < 500:
                    break
                offset += 500
            self.assertEqual(len(got_all), total)
            self.assertTrue(0 < total < self.N)

    def test_a_jump_or_a_filter_is_answered_by_the_group_by(self):
        b = MftUsnBridge(self.tmp)
        r, got = self._page(b, "desc", 700)    # no page ever ends at 700: no cursor
        self.assertEqual(got, self._reference("desc", 700))
        r, got = self._page(b, "desc", 0, terms=["f1"])
        self.assertTrue(got and all(name.startswith("f1") for name in
                                    (f["name"] for f in r["rows"])))

    def test_without_the_index_the_group_by_answers(self):
        tmp = tempfile.mkdtemp()
        con = sqlite3.connect(os.path.join(tmp, "mft_usn_correlated_analysis.db"))
        con.execute("ATTACH ? AS src", (self.db,))
        con.execute("CREATE TABLE mft_usn_correlated AS SELECT * FROM src.mft_usn_correlated")
        con.commit(); con.close()
        b = MftUsnBridge(tmp)
        self.assertIsNone(b._all_files_keyset(0, "DESC"))
        r, got = self._page(b, "asc", 0)
        self.assertEqual(got, self._reference("asc", 0))


if __name__ == "__main__":
    unittest.main()
