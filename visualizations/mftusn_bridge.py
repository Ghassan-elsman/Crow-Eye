"""QWebChannel bridge for the MFT/USN correlated visualization.

Exposes the MFT <-> USN correlated data to the react-mftusn chart app as JSON
over QWebChannel. Same shape as visualizations/viz_bridge.py (the SRUM one):
read-only `@pyqtSlot(... result=str)` methods returning JSON strings, every
query parameterised.

Two databases in the case's Target_Artifacts:
  * mft_usn_correlated_analysis.db  ->  mft_usn_correlated  (the join)
  * USN_journal.db                  ->  deleted_entries     (USN gaps)

The correlated schema DRIFTS between parser builds - older DBs lack
volume_letter / file_size / file_extension / usn_filename / has_ads. Every
optional column is guarded with a _table_columns() check and derived from what
IS present (reconstructed_path, fn_filename, fn_real_size) when missing.
"""

import os
import json
import time
import sqlite3
import logging
from typing import List, Dict, Optional, Tuple

from PyQt5.QtCore import QObject, pyqtSlot

logger = logging.getLogger(__name__)

from visualizations.raw_record import raw_record as _raw
from visualizations.insights import (SUBJECT_CAP as _CAP,
                                     insight as _insight,
                                     subject as _subject)
from visualizations.timeseries import (axis_range as _axis_range,
                                       densify as _densify,
                                       densify_series as _densify_series,
                                       densify_table as _densify_table,
                                       span as _span)

CORR_DB = "mft_usn_correlated_analysis.db"
USN_DB = "USN_journal.db"
CORR_TABLE = "mft_usn_correlated"

# reason-category -> colour (reason = colour everywhere, mirrors SRUM providers)
REASON_CATS = ("create", "delete", "rename", "data", "meta")

# free-text search targets (only those present are used)
SEARCH_FIELDS = ("reconstructed_path", "fn_filename", "usn_filename", "file_extension")


def reason_cats(reason: str) -> set:
    """Map a USN reason flag string to the categories its flags touch."""
    r = (reason or "").upper()
    cats = set()
    if "FILE_CREATE" in r:
        cats.add("create")
    if "FILE_DELETE" in r:
        cats.add("delete")
    if "RENAME_OLD_NAME" in r or "RENAME_NEW_NAME" in r:
        cats.add("rename")
    if "DATA_OVERWRITE" in r or "DATA_EXTEND" in r or "DATA_TRUNCATION" in r:
        cats.add("data")
    if any(k in r for k in ("BASIC_INFO_CHANGE", "SECURITY_CHANGE", "OBJECT_ID_CHANGE",
                            "EA_CHANGE", "INDEXABLE_CHANGE", "HARD_LINK_CHANGE",
                            "REPARSE_POINT_CHANGE", "NAMED_DATA", "STREAM_CHANGE")):
        cats.add("meta")
    return cats


def _ext(filename: str, path: str) -> str:
    """Derive a lowercase extension from the name (or path) when no column exists."""
    name = filename or (path or "").rsplit("/", 1)[-1]
    if not name or "." not in name.rsplit("/", 1)[-1]:
        return ""
    return name.rsplit(".", 1)[-1].lower()[:12]


def _dirname(path: str) -> str:
    p = (path or "").replace("\\", "/")
    if p.startswith("./"):
        p = p[2:]
    return p.rsplit("/", 1)[0] if "/" in p else "\\"


class MftUsnBridge(QObject):
    """Read-only data source for the MFT/USN correlated dashboard."""

    def __init__(self, case_directory: str, parent=None):
        super().__init__(parent)
        self.case_dir = case_directory or ""
        self._cols_cache = None
        logger.info(f"MftUsnBridge initialized with case dir: {case_directory}")

    # ---- low-level db helpers (same shape as VizBridge) -------------------
    def _get_db_path(self, db_name: str) -> Optional[str]:
        path = os.path.join(self.case_dir, db_name)
        return path if os.path.exists(path) else None

    def _query(self, db_name: str, sql: str, params: tuple = ()) -> List[Dict]:
        db_path = self._get_db_path(db_name)
        if not db_path:
            return []
        retries, delay = 3, 0.1
        for attempt in range(retries):
            try:
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute(sql, params)
                rows = [dict(r) for r in cur.fetchall()]
                conn.close()
                return rows
            except sqlite3.OperationalError as e:
                if ("locked" in str(e).lower() or "busy" in str(e).lower()) and attempt < retries - 1:
                    time.sleep(delay); delay *= 2; continue
                logger.error(f"Query error on {db_name}: {e}")
                return []
            except Exception as e:
                logger.error(f"Critical query failure on {db_name}: {e}")
                return []
        return []

    def _has_table(self, db_name: str, table: str) -> bool:
        return len(self._query(db_name, "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))) > 0

    def _cols(self) -> set:
        if self._cols_cache is None:
            rows = self._query(CORR_DB, f"PRAGMA table_info({CORR_TABLE})")
            self._cols_cache = {r["name"] for r in rows}
        return self._cols_cache

    def _size_expr(self) -> str:
        c = self._cols()
        for col in ("file_size", "fn_real_size", "fn_allocated_size"):
            if col in c:
                return f"COALESCE({col}, 0)"
        return "0"

    # ---- filters ----------------------------------------------------------
    def _where(self, args: dict, extra: str = "") -> Tuple[str, list]:
        cols = self._cols()
        parts, params = [], []
        start, end = args.get("start", ""), args.get("end", "")
        # time filter applies to the USN window by default (activity), unless the
        # caller asks for the MFT-history axis.
        tcol = "usn_timestamp"
        if args.get("axis") == "mft" and "si_modification_time" in cols:
            tcol = "si_modification_time"
        if start:
            parts.append(f"date({tcol}) >= date(?)"); params.append(start)
        if end:
            parts.append(f"date({tcol}) <= date(?)"); params.append(end)
        if args.get("volume") and "volume_letter" in cols:
            parts.append("volume_letter = ?"); params.append(args["volume"])
        terms = [t.strip() for t in (args.get("terms") or []) if t and t.strip()]
        scols = [c for c in SEARCH_FIELDS if c in cols]
        if terms and scols:
            per = []
            for t in terms:
                per.append("(" + " OR ".join(f"{c} LIKE ?" for c in scols) + ")")
                params.extend([f"%{t}%"] * len(scols))
            join = " AND " if (args.get("mode", "or").lower() == "and") else " OR "
            parts.append("(" + join.join(per) + ")")
        if extra:
            parts.append(extra)
        return ((" WHERE " + " AND ".join(parts)) if parts else "", params)

    def _has_data(self) -> bool:
        return self._has_table(CORR_DB, CORR_TABLE)

    # ---- slots ------------------------------------------------------------
    @pyqtSlot(result=str)
    def getMftUsnBounds(self) -> str:
        if not self._has_data():
            return json.dumps({"hasData": False})
        cols = self._cols()
        mft = self._query(CORR_DB,
            f"SELECT MIN(date(si_creation_time)) a, MAX(date(si_modification_time)) b FROM {CORR_TABLE} "
            f"WHERE si_modification_time > '2000-01-01'")
        usn = self._query(CORR_DB,
            f"SELECT MIN(date(usn_timestamp)) a, MAX(date(usn_timestamp)) b FROM {CORR_TABLE} WHERE has_usn_event=1")
        vols = []
        if "volume_letter" in cols:
            vols = [r["v"] for r in self._query(CORR_DB, f"SELECT DISTINCT volume_letter v FROM {CORR_TABLE} WHERE volume_letter IS NOT NULL ORDER BY v")]
        m, u = (mft[0] if mft else {}), (usn[0] if usn else {})
        return json.dumps({
            "hasData": True,
            "mftMin": m.get("a"), "mftMax": m.get("b"),
            "usnMin": u.get("a"), "usnMax": u.get("b"),
            "volumes": vols,
            "hasVolume": "volume_letter" in cols,
            "hasAds": "has_ads" in cols,
        })

    @pyqtSlot(str, result=str)
    def getMftUsnTimelines(self, args_json: str) -> str:
        """Two series, both one cell per calendar day: MFT history
        (Created/Modified, over the machine's own history) and USN events per
        reason-category over the journal window."""
        args = _loads(args_json)
        if not self._has_data():
            return json.dumps({"mftHistory": [], "usnEvents": {}, "combined": []})

        # MFT history — cheap SQL aggregates over all rows.
        created = {r["d"]: r["c"] for r in self._query(CORR_DB,
            f"SELECT date(si_creation_time) d, COUNT(*) c FROM {CORR_TABLE} "
            f"WHERE si_creation_time > '2000-01-01' GROUP BY d")}
        modified = {r["d"]: r["c"] for r in self._query(CORR_DB,
            f"SELECT date(si_modification_time) d, COUNT(*) c FROM {CORR_TABLE} "
            f"WHERE si_modification_time > '2000-01-01' GROUP BY d")}
        # The MFT chart's range is the machine's own history, not the analyst's
        # filter - Standard-Info times run back to the build - so it gets its own
        # axis, independent of the journal window below. Measured on one case:
        # 954 days carry anything across a 9,758-day span, so the empty stretches
        # are most of the chart and are exactly what it is for.
        mft_start, mft_end = _span(created, modified)
        mft_history = _densify_table(
            {"created": created, "modified": modified}, mft_start, mft_end)

        # USN events — fetch the (light) event rows, bucket + categorise in Python.
        where, params = self._where(args, extra="has_usn_event=1")
        rows = self._query(CORR_DB,
            f"SELECT usn_timestamp t, usn_reason r FROM {CORR_TABLE}{where}", tuple(params))
        per_cat = {c: {} for c in REASON_CATS}
        combined = {}
        for x in rows:
            t = x["t"]
            if not t:
                continue
            for c in reason_cats(x["r"]):
                per_cat[c][t] = per_cat[c].get(t, 0) + 1
            combined[t] = combined.get(t, 0) + 1
        # Only days that HAD events came out of this before, which turned the
        # strip into an ordinal list of busy days rather than a time axis - a
        # quiet stretch closed up and vanished. Fill every day in the window.
        # This slot used to narrow to hour cells on a short window; it no longer
        # does, because a cell means one day on every strip in the fleet.
        start, end = _axis_range(args, combined)
        usn = _densify_series(per_cat, start, end, key="key", field="buckets")
        combined_rows = _densify(combined, start, end, key="key")
        return json.dumps({
            "mftHistory": mft_history,
            "usnEvents": usn,
            "combined": combined_rows,
        })

    @pyqtSlot(str, result=str)
    def getMftUsnWindowDetail(self, args_json: str) -> str:
        """Events on the selected USN day: file points, by-hour-by-category,
        top directories, top extensions."""
        args = _loads(args_json)
        bucket = args.get("bucket")     # 'YYYY-MM-DD'
        if not self._has_data() or not bucket:
            return json.dumps({"events": [], "byHour": {}, "topDirs": [], "topExts": []})
        where, params = self._where(args, extra="has_usn_event=1")
        where += " AND date(usn_timestamp)=?"; params.append(bucket[:10])
        size = self._size_expr()
        rows = self._query(CORR_DB,
            f"SELECT mft_record_number rec, reconstructed_path path, fn_filename fn, usn_timestamp t, "
            f"usn_reason r, is_deleted del, {size} sz FROM {CORR_TABLE}{where} "
            f"ORDER BY usn_timestamp LIMIT 6000", tuple(params))
        return self._window_payload(rows)

    def _window_payload(self, rows):
        by_hour = {c: [0] * 24 for c in REASON_CATS}
        dirs, exts = {}, {}
        events = []
        for x in rows:
            t = x["t"] or ""
            hh = int(t[11:13]) if len(t) >= 13 and t[11:13].isdigit() else 0
            cats = reason_cats(x["r"])
            for c in cats:
                by_hour[c][hh] += 1
            d = _dirname(x["path"]); dirs[d] = dirs.get(d, 0) + 1
            e = _ext(x["fn"], x["path"]) or "(none)"; exts[e] = exts.get(e, 0) + 1
            events.append({"rec": x["rec"], "path": x["path"], "fn": x["fn"], "t": t,
                           "hour": hh, "cats": sorted(cats), "size": x["sz"], "deleted": x["del"]})
        top_dirs = sorted(({"dir": k, "n": v} for k, v in dirs.items()), key=lambda z: z["n"], reverse=True)[:12]
        top_exts = sorted(({"ext": k, "n": v} for k, v in exts.items()), key=lambda z: z["n"], reverse=True)[:12]
        return json.dumps({"events": events, "byHour": by_hour, "topDirs": top_dirs, "topExts": top_exts})

    @pyqtSlot(str, result=str)
    def getMftUsnOverview(self, args_json: str) -> str:
        args = _loads(args_json)
        if not self._has_data():
            return json.dumps({"totals": {}, "anomalies": {}, "topDirs": [], "topExts": [], "byCategory": {}})
        cols = self._cols()

        # totals over all rows (cheap)
        base = self._query(CORR_DB,
            f"SELECT COUNT(*) total, SUM(CASE WHEN is_directory=1 THEN 1 ELSE 0 END) dirs, "
            f"SUM(CASE WHEN has_usn_event=1 THEN 1 ELSE 0 END) events, "
            f"SUM(CASE WHEN is_deleted=1 THEN 1 ELSE 0 END) deleted FROM {CORR_TABLE}")
        b = base[0] if base else {}
        ads = 0
        if "has_ads" in cols:
            r = self._query(CORR_DB, f"SELECT SUM(CASE WHEN has_ads=1 THEN 1 ELSE 0 END) a FROM {CORR_TABLE}")
            ads = (r[0]["a"] if r else 0) or 0

        # category counts + top dirs/exts from the USN-event subset (fast, ~activity)
        where, params = self._where(args, extra="has_usn_event=1")
        ev = self._query(CORR_DB,
            f"SELECT reconstructed_path path, fn_filename fn, usn_reason r FROM {CORR_TABLE}{where}", tuple(params))
        by_cat = {c: 0 for c in REASON_CATS}
        dirs, exts = {}, {}
        for x in ev:
            for c in reason_cats(x["r"]):
                by_cat[c] += 1
            d = _dirname(x["path"]); dirs[d] = dirs.get(d, 0) + 1
            e = _ext(x["fn"], x["path"]) or "(none)"; exts[e] = exts.get(e, 0) + 1
        top_dirs = sorted(({"dir": k, "n": v} for k, v in dirs.items()), key=lambda z: z["n"], reverse=True)[:12]
        top_exts = sorted(({"ext": k, "n": v} for k, v in exts.items()), key=lambda z: z["n"], reverse=True)[:12]

        # anomalies — timestomping candidates, tight/low-false-positive:
        #   (a) SI creation set LATER than the kernel-written File-Name creation
        #       (forward-dating; FN is not user-settable), or
        #   (b) all four SI times zeroed to whole seconds while FN keeps sub-second
        #       precision (the classic timestomp-tool signature).
        # The old "SI modified before created" rule is dropped - it is normal for
        # copied/installed files (new creation time, older kept modification time).
        #
        # These used to be SELECT COUNT(*), which meant the rows were never
        # materialised server-side - so an anomaly could state a number and the
        # analyst had no way to ask WHICH files. They now select the records and
        # count them, which is the same work for SQLite and the difference
        # between a figure and a lead. Capped, because "deleted but present" can
        # run to thousands; insight() reports the real total separately and
        # marks the list truncated.
        _TS_WHERE = (
            "(si_creation_time >= '2008-01-01' AND fn_creation_time >= '2008-01-01' "
            " AND si_creation_time > fn_creation_time) "
            "OR (si_creation_time >= '2008-01-01' AND si_creation_time NOT LIKE '%.%' "
            " AND si_modification_time NOT LIKE '%.%' AND si_access_time NOT LIKE '%.%' "
            " AND si_mft_entry_change_time NOT LIKE '%.%' "
            " AND (fn_creation_time LIKE '%.%' OR fn_modification_time LIKE '%.%'))")

        tsomp_n = self._query(CORR_DB, f"SELECT COUNT(*) n FROM {CORR_TABLE} WHERE {_TS_WHERE}")
        timestomp = (tsomp_n[0]["n"] if tsomp_n else 0) or 0
        tsomp_rows = self._query(CORR_DB,
            f"SELECT mft_record_number rec, reconstructed_path path, fn_filename fn, "
            f"si_creation_time sic, fn_creation_time fnc FROM {CORR_TABLE} "
            f"WHERE {_TS_WHERE} ORDER BY si_creation_time DESC LIMIT {_CAP}")
        timestomp_subj = [
            _subject(x["path"] or x["fn"], x["rec"],
                     "SI %s vs FN %s" % (x["sic"] or "-", x["fnc"] or "-"))
            for x in tsomp_rows]

        gaps, gaps_subj = 0, []
        if self._has_table(USN_DB, "deleted_entries"):
            g = self._query(USN_DB, "SELECT COUNT(*) n FROM deleted_entries")
            gaps = (g[0]["n"] if g else 0) or 0
            gaps_subj = self._deleted_entry_subjects()

        del_rows = self._query(CORR_DB,
            f"SELECT mft_record_number rec, reconstructed_path path, fn_filename fn, "
            f"{self._size_expr()} sz FROM {CORR_TABLE} WHERE is_deleted=1 "
            f"ORDER BY mft_record_number LIMIT {_CAP}")
        deleted_subj = [_subject(x["path"] or x["fn"], x["rec"],
                                 "record %s" % x["rec"]) for x in del_rows]

        ads_subj = []
        if "has_ads" in cols:
            ads_rows = self._query(CORR_DB,
                f"SELECT mft_record_number rec, reconstructed_path path, fn_filename fn "
                f"FROM {CORR_TABLE} WHERE has_ads=1 ORDER BY mft_record_number LIMIT {_CAP}")
            ads_subj = [_subject(x["path"] or x["fn"], x["rec"], "alternate data stream")
                        for x in ads_rows]

        totals = {
            "files": (b.get("total") or 0), "directories": (b.get("dirs") or 0),
            "withEvents": (b.get("events") or 0), "deleted": (b.get("deleted") or 0),
            "ads": ads,
            "created": by_cat["create"], "renamed": by_cat["rename"],
            "dataChanged": by_cat["data"], "deletedEvents": by_cat["delete"],
        }
        anomalies = {
            "timestompCandidates": _insight(timestomp, timestomp_subj),
            "usnGaps": _insight(gaps, gaps_subj),
            "deletedButPresent": _insight((b.get("deleted") or 0), deleted_subj),
            "ads": _insight(ads, ads_subj),
        }
        return json.dumps({"totals": totals, "anomalies": anomalies, "byCategory": by_cat,
                           "topDirs": top_dirs, "topExts": top_exts})

    def _deleted_entry_subjects(self):
        """USN journal gaps, as insight subjects.

        Despite the table name, `deleted_entries` holds **gaps in the journal**
        - ranges of USNs that are missing - not deleted files. So these rows
        carry no MFT record number and cannot open the file-detail modal; they
        are handed back without an `open` id, and InsightPanel renders them as
        a plain list. Saying "here are the gaps" is useful; pretending each one
        is a file you can click into would not be.
        """
        # The table's shape varies between parser versions - older cases carry
        # only (volume_letter, gap_start_usn, gap_end_usn) while current ones add
        # gap_size, forensic_significance and potential_activity. Naming a column
        # that is not there fails the whole query and returns nothing, which
        # would show a non-zero count with an empty list, so ask first.
        have = {r["name"] for r in self._query(USN_DB, "PRAGMA table_info(deleted_entries)")}
        if not {"gap_start_usn", "gap_end_usn"} <= have:
            return []
        optional = [c for c in ("gap_size", "forensic_significance", "potential_activity")
                    if c in have]
        select = ["volume_letter vol" if "volume_letter" in have else "'' vol",
                  "gap_start_usn a", "gap_end_usn b"] + optional
        order = "gap_size DESC" if "gap_size" in have else "gap_start_usn"
        rows = self._query(USN_DB,
                           "SELECT %s FROM deleted_entries ORDER BY %s LIMIT %d"
                           % (", ".join(select), order, _CAP))
        out = []
        for x in rows:
            vol = (x["vol"] or "").strip()
            label = "%s USN %s - %s" % (vol if vol else "gap", x["a"], x["b"])
            note = ""
            for col in ("forensic_significance", "potential_activity"):
                if col in optional and x[col]:
                    note = x[col]
                    break
            if not note:
                size = x["gap_size"] if "gap_size" in optional else None
                if size is None:
                    try:
                        size = int(x["b"]) - int(x["a"])
                    except (TypeError, ValueError):
                        size = None
                note = "%s records missing" % size if size is not None else "journal gap"
            out.append(_subject(label, None, note))
        return out

    @pyqtSlot(str, result=str)
    def getMftUsnFileDetail(self, args_json: str) -> str:
        args = _loads(args_json)
        rec = args.get("rec")
        if not self._has_data() or rec is None:
            return json.dumps({})
        cols = self._cols()
        vsel = "volume_letter" if "volume_letter" in cols else "'' volume_letter"
        rows = self._query(CORR_DB,
            f"SELECT {vsel}, mft_record_number rec, reconstructed_path path, fn_filename fn, is_directory dir, "
            f"is_deleted del, si_creation_time sic, si_modification_time sim, si_access_time sia, "
            f"si_mft_entry_change_time sie, fn_creation_time fnc, fn_modification_time fnm, fn_access_time fna, "
            f"fn_mft_entry_change_time fne, {self._size_expr()} sz, usn_timestamp t, usn_reason r "
            f"FROM {CORR_TABLE} WHERE mft_record_number = ? ORDER BY usn_timestamp", (rec,))
        if not rows:
            return json.dumps({})
        head = rows[0]
        # Everything the correlator stored for this record, shown under the
        # curated reading so "the panel does not show it" and "the artifact does
        # not record it" stop looking the same. See raw_record.py.
        _full = self._query(
            CORR_DB, f"SELECT * FROM {CORR_TABLE} WHERE mft_record_number = ? LIMIT 1", (rec,))
        raw = _raw(_full[0], CORR_TABLE) if _full else None
        events = [{"t": x["t"], "cats": sorted(reason_cats(x["r"])), "reason": x["r"]} for x in rows if x["t"]]
        # timestomping flags on the head record (tight / low-false-positive).
        def _real(v): return v and v >= "2008-01-01"
        flags = []
        if _real(head["sic"]) and _real(head["fnc"]) and head["sic"] > head["fnc"]:
            flags.append("Standard-Info creation is newer than File-Name creation (possible forward-dating)")
        si_whole = all(head[k] and "." not in head[k] for k in ("sic", "sim", "sia", "sie"))
        fn_sub = any(head[k] and "." in head[k] for k in ("fnc", "fnm"))
        if _real(head["sic"]) and si_whole and fn_sub:
            flags.append("Standard-Info timestamps zeroed to whole seconds while File-Name keeps sub-seconds (timestomp-tool signature)")
        return json.dumps({
            "rec": head["rec"], "path": head["path"], "filename": head["fn"],
            "isDir": head["dir"], "deleted": head["del"], "size": head["sz"],
            "si": {"created": head["sic"], "modified": head["sim"], "accessed": head["sia"], "mftChanged": head["sie"]},
            "fnTimes": {"created": head["fnc"], "modified": head["fnm"], "accessed": head["fna"], "mftChanged": head["fne"]},
            "events": events, "flags": flags, "raw": raw,
        })


def _loads(s):
    try:
        return json.loads(s or "{}")
    except Exception:
        return {}
