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
optional column is guarded with a _cols() check and derived from what IS
present (reconstructed_path, fn_filename, fn_real_size) when missing.

What the dashboard draws, and what it counts (measured on a real case,
482,779 correlated rows):

* **One strip, one day axis** for both sources: MFT Created / MFT Modified
  rows (distinct FILES per day, Standard-Info times) and one row per USN
  reason flag present in the case (USN records per day). They used to be two
  charts on two axes - an MFT bar chart 2px per day across 26 years and a USN
  strip over the journal window - so the two could not be read against each
  other. The journal of that case covers 5 h 43 min on one day; the MFT runs
  back years. On one axis that is visible at a glance.
* **Aggregates are SQL over every row.** The day drill-down fetched at most
  6,000 events and computed its hour chart and top lists from those: that case
  has 283,585 events on its one journal day, so 98% of them were missing from
  every number shown. Events are now paged; the totals are counted.
* **Files, not rows.** The correlated table repeats an MFT record once per USN
  event, so a COUNT(*) of "files" counted events. File counts are
  COUNT(DISTINCT volume:record).
* **Names and paths.** 87% of that case's USN events (247,224) had no MFT
  row: no File-Name, no reconstructed path - the event list showed them blank.
  Most were not "reused entries" at all: the live MFT parser read only the
  first fragment of a fragmented $MFT, so 97% of those files were simply never
  read (fixed in MFT_Claw). The journal keeps the name (usn_filename) and the
  parent directory's reference (usn_parent_frn); the correlator now writes the
  rebuilt path into reconstructed_path, so search finds them too. A row
  without one (an older case) is still rebuilt here at display time.
* **Renames** come from `filename_changes`: one row per rename, old name ->
  new name and old folder -> new folder, paired from the journal by the
  correlator.
* **Every list is complete.** Day lists are paged with "N of total", and the
  all-records section pages through every event, file or rename that matches
  the filters, across all days.
* **Read-only.** The indexes the dashboard relies on are made by the
  correlator; this bridge does not write to the case.
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
                                       densify_series as _densify_series)

CORR_DB = "mft_usn_correlated_analysis.db"
USN_DB = "USN_journal.db"
CORR_TABLE = "mft_usn_correlated"

# reason-category -> colour, for the summary counts and the event chips
REASON_CATS = ("create", "delete", "rename", "data", "meta")

# Every USN reason flag, in the order the strip lists them. Flags a case does
# not contain get no row; a flag missing here still gets one, after these.
FLAG_ORDER = (
    "FILE_CREATE", "FILE_DELETE", "RENAME_OLD_NAME", "RENAME_NEW_NAME",
    "DATA_OVERWRITE", "DATA_EXTEND", "DATA_TRUNCATION",
    "NAMED_DATA_OVERWRITE", "NAMED_DATA_EXTEND", "NAMED_DATA_TRUNCATION",
    "BASIC_INFO_CHANGE", "SECURITY_CHANGE", "EA_CHANGE", "OBJECT_ID_CHANGE",
    "REPARSE_POINT_CHANGE", "STREAM_CHANGE", "HARD_LINK_CHANGE", "INDEXABLE_CHANGE",
    "INTEGRITY_CHANGE", "COMPRESSION_CHANGE", "ENCRYPTION_CHANGE", "TRANSACTED_CHANGE",
    "DESIRED_STORAGE_CLASS_CHANGE", "CLOSE",
)

# The two MFT rows on the shared strip.
MFT_ROWS = (("mft_created", "Files created (MFT)"), ("mft_modified", "Files modified (MFT)"))

# free-text search targets (only those present are used). The rename summary
# makes a file findable by a name it no longer has.
SEARCH_FIELDS = ("reconstructed_path", "fn_filename", "usn_filename", "file_extension",
                 "filename_change_timeline")

EVENT_PAGE = 500          # events per page in the day drill-down
DAY_FILES = 200           # MFT files per page of a day's list (the totals are counted)
ALL_PAGE = 500            # rows per page of the all-records section
FILE_EVENTS = 2000        # USN events listed in one file's modal (the total is counted)
REC_MASK = 0xFFFFFFFFFFFF  # an NTFS file reference's record-number bits

# The MFT rows of the strip draw Standard-Info times inside this window. A 1980
# date is real (it is what a ZIP without times extracts to); 1601 is a zero
# FILETIME, and years past 2100 are damage. What falls outside is counted and
# said, not silently dropped. (The floor was 2000, which hid 267 real files.)
MFT_TIME_FLOOR, MFT_TIME_CEIL = "1980-01-01", "2100-01-01"
RENAME_TABLE = "filename_changes"


def norm_term(term: str) -> str:
    """A search term as the stored paths spell it.

    Paths are stored relative to the volume root with forward slashes
    ('./Users/a/x.txt'); an examiner pastes 'C:\\Users\\a'. That matched
    nothing, silently.
    """
    t = (term or "").strip().strip('"').replace("\\", "/")
    if len(t) >= 2 and t[1] == ":" and t[0].isalpha():
        t = t[2:]
    if t.startswith("./"):
        t = t[2:]
    return t.lstrip("/") or t


def reason_flags(reason: str) -> List[str]:
    """'DATA_EXTEND | FILE_CREATE | CLOSE' -> ['DATA_EXTEND', 'FILE_CREATE', 'CLOSE']."""
    return [f.strip().upper() for f in (reason or "").split("|") if f.strip()]


def reason_cats(reason: str) -> set:
    """Map a USN reason flag string to the categories its flags touch."""
    flags = set(reason_flags(reason))
    cats = set()
    if "FILE_CREATE" in flags:
        cats.add("create")
    if "FILE_DELETE" in flags:
        cats.add("delete")
    if flags & {"RENAME_OLD_NAME", "RENAME_NEW_NAME"}:
        cats.add("rename")
    if flags & {"DATA_OVERWRITE", "DATA_EXTEND", "DATA_TRUNCATION"}:
        cats.add("data")
    if flags & {"BASIC_INFO_CHANGE", "SECURITY_CHANGE", "OBJECT_ID_CHANGE", "EA_CHANGE",
                "INDEXABLE_CHANGE", "HARD_LINK_CHANGE", "REPARSE_POINT_CHANGE", "STREAM_CHANGE",
                "NAMED_DATA_OVERWRITE", "NAMED_DATA_EXTEND", "NAMED_DATA_TRUNCATION",
                "INTEGRITY_CHANGE", "COMPRESSION_CHANGE", "ENCRYPTION_CHANGE",
                "TRANSACTED_CHANGE", "DESIRED_STORAGE_CLASS_CHANGE"}:
        cats.add("meta")
    return cats


def flag_sort_key(flag: str):
    return (FLAG_ORDER.index(flag) if flag in FLAG_ORDER else len(FLAG_ORDER), flag)


def _ext(filename: str, path: str) -> str:
    """Derive a lowercase extension from the name (or path) when no column exists."""
    name = filename or (path or "").replace("\\", "/").rsplit("/", 1)[-1]
    if not name or "." not in name:
        return ""
    return name.rsplit(".", 1)[-1].lower()[:12]


def _dirname(path: str) -> str:
    p = (path or "").replace("\\", "/")
    if p.startswith("./"):
        p = p[2:]
    return p.rsplit("/", 1)[0] if "/" in p else "\\"


def _clean_path(path: str) -> str:
    """'./Users/a/x.txt' -> 'Users/a/x.txt'; unknown placeholders -> ''."""
    p = (path or "").replace("\\", "/")
    if not p or p.startswith("[Unknown"):
        return ""
    return p[2:] if p.startswith("./") else p


def _is_short(name: str) -> bool:
    """An 8.3 DOS name ('MIGRAT~1.DAT')."""
    n = name or ""
    return "~" in n and len(n) <= 12 and n.upper() == n


def file_id(vol, rec, seq) -> str:
    """The id a file modal opens on: volume, record AND sequence number.

    A record number alone names whichever file holds that MFT entry now; the
    journal's events for an earlier file in the same entry differ in sequence.
    """
    return "%s:%s:%s" % (vol or "", "" if rec is None else rec, "" if seq is None else seq)


def parse_file_id(value):
    """'C:44:195' / 44 / '44' -> (volume or None, record, sequence or None)."""
    if isinstance(value, int):
        return None, value, None
    text = str(value or "")
    parts = text.split(":")
    if len(parts) == 3:
        vol, rec, seq = parts
        try:
            return (vol or None, int(rec), int(seq) if seq != "" else None)
        except ValueError:
            return None, None, None
    try:
        return None, int(text), None
    except ValueError:
        return None, None, None


try:
    from visualizations.async_bridge import AsyncBridge
except ImportError:                                  # run from its own folder
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    from visualizations.async_bridge import AsyncBridge


# AsyncBridge (a QObject): the page calls its slots through callAsync, off
# the GUI thread, so the window keeps painting while a query runs.
class MftUsnBridge(AsyncBridge):
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

    def _vol(self) -> str:
        return "volume_letter" if "volume_letter" in self._cols() else "''"

    def _seq(self) -> str:
        return "mft_sequence_number" if "mft_sequence_number" in self._cols() else "NULL"

    def _file_key(self) -> str:
        """The SQL expression naming one FILE (not one correlated row).

        Volume and record; on a single-volume case the record number alone,
        an integer - DISTINCT over a built string cost about a second more per
        count on a 3.5-million-row case."""
        if "volume_letter" not in self._cols():
            return "mft_record_number"
        if getattr(self, "_one_volume", None) is None:
            rows = self._query(CORR_DB, f"SELECT DISTINCT volume_letter v FROM {CORR_TABLE} "
                                        f"WHERE volume_letter IS NOT NULL LIMIT 2")
            self._one_volume = len(rows) <= 1
        if self._one_volume:
            return "mft_record_number"
        return f"({self._vol()} || ':' || mft_record_number)"

    def _mft_only(self) -> str:
        return "has_mft_record=1" if "has_mft_record" in self._cols() else "1=1"

    def _usn_name(self) -> str:
        return "usn_filename" if "usn_filename" in self._cols() else "NULL"

    def _parent_rec_expr(self) -> Optional[str]:
        """The USN parent directory's MFT record number, from its file reference."""
        if "usn_parent_frn" not in self._cols():
            return None
        return f"(CAST(usn_parent_frn AS INTEGER) & {REC_MASK})"

    def _parent_seq_expr(self) -> str:
        """...and its sequence number: which occupant of that record it means."""
        if "usn_parent_frn" not in self._cols():
            return "NULL"
        return "(CAST(usn_parent_frn AS INTEGER) >> 48)"

    # ---- filters ----------------------------------------------------------
    def _where(self, args: dict, extra: str = "", tcol: str = "usn_timestamp") -> Tuple[str, list]:
        cols = self._cols()
        parts, params = [], []
        start, end = args.get("start", ""), args.get("end", "")
        # Ranges on the stored text ('YYYY-MM-DD HH:MM:SS'), not date(col):
        # date() hides the column from every index.
        if start:
            parts.append(f"{tcol} >= ?"); params.append(str(start)[:10])
        if end:
            parts.append(f"{tcol} < date(?, '+1 day')"); params.append(str(end)[:10])
        if args.get("volume") and "volume_letter" in cols:
            parts.append("volume_letter = ?"); params.append(args["volume"])
        terms = [norm_term(t) for t in (args.get("terms") or []) if t and norm_term(t)]
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

    def _cached(self, name, args_json, compute):
        """A slot's answer, kept for the same filters while the database is
        unchanged: on a complete MFT the strip and the overview are seconds of
        SQL each, and they are asked again every time the view comes back to
        the same filters. A re-correlation changes the file's time and with it
        every key."""
        stamps = []
        for db in (CORR_DB, USN_DB):             # the overview reads both
            path = self._get_db_path(db)
            try:
                stamps.append(os.path.getmtime(path) if path else None)
            except OSError:
                stamps.append(None)
        key = (name, json.dumps(_loads(args_json), sort_keys=True), tuple(stamps))
        # Slots run on worker threads now (AsyncBridge): the cache is read and
        # written under a lock, and the answer is computed outside it.
        with self._cache_lock:
            cache = self.__dict__.setdefault("_result_cache", {})
            hit = cache.get(key)
        if hit is not None:
            return hit
        value = compute(args_json)
        with self._cache_lock:
            if len(cache) >= 64:
                cache.clear()
            cache[key] = value
        return value

    # ---- names and paths ----------------------------------------------------
    def _lookup(self, keys, journal):
        """MFT directories (journal=False) or journal names (journal=True) for
        (volume, record, sequence) keys, in chunks. Sequence must match: a
        record number alone can name a later directory that reused the entry,
        which would print a plausible, wrong path."""
        cols = self._cols()
        has_seq = "mft_sequence_number" in cols
        by_vol = {}
        for vol, rec, seq in keys:
            by_vol.setdefault(vol, set()).add(rec)
        found = {}
        for vol, recs in by_vol.items():
            recs = sorted(recs)
            vol_sql, vparams = ("", [])
            if "volume_letter" in cols:
                vol_sql, vparams = " AND volume_letter = ?", [vol]
            for i in range(0, len(recs), 500):
                chunk = recs[i:i + 500]
                if journal:
                    sql = (f"SELECT mft_record_number rec, {self._seq()} seq, {self._usn_name()} name, "
                           f"{self._parent_rec_expr() or 'NULL'} prec, {self._parent_seq_expr()} pseq "
                           f"FROM {CORR_TABLE} WHERE has_usn_event=1 AND {self._usn_name()} IS NOT NULL "
                           f"AND mft_record_number IN ({','.join('?' * len(chunk))}){vol_sql} "
                           f"GROUP BY mft_record_number, seq")
                else:
                    sql = (f"SELECT mft_record_number rec, {self._seq()} seq, reconstructed_path path "
                           f"FROM {CORR_TABLE} WHERE {self._mft_only()} AND mft_record_number IN "
                           f"({','.join('?' * len(chunk))}){vol_sql} GROUP BY mft_record_number, seq")
                for r in self._query(CORR_DB, sql, tuple(chunk) + tuple(vparams)):
                    exact = (vol, r["rec"], r["seq"] if has_seq else None)
                    if exact in keys:
                        found[exact] = r
                    # A key asked without a sequence (no usn_parent_frn column)
                    # takes whichever occupant there is.
                    loose = (vol, r["rec"], None)
                    if loose in keys:
                        found.setdefault(loose, r)
        return found

    def _parent_paths(self, keys) -> Dict[tuple, Tuple[str, str]]:
        """{(volume, record, sequence): (path, source)} for parent directories.

        A directory still in the MFT gives its reconstructed path ("mft").
        One that is not - a temp folder created and deleted inside the journal
        window - is named from its own journal records, and its parent after
        it, until a directory still in the MFT (or the root) is reached
        ("journal"). Measured on a real case: 491 of the first 500 events of
        the journal's day had a parent directory no longer in the MFT.
        """
        keys = {k for k in keys if k and k[1] is not None}
        if not keys:
            return {}
        mft_paths, names = {}, {}
        frontier = set(keys)
        for _depth in range(48):
            if not frontier:
                break
            for k, r in self._lookup(frontier, journal=False).items():
                p = _clean_path(r["path"])
                if p or k[1] == 5:
                    mft_paths[k] = p
            rest = {k for k in frontier if k not in mft_paths and k[1] != 5}
            nxt = set()
            if rest:
                for k, r in self._lookup(rest, journal=True).items():
                    pkey = (k[0], r["prec"], r["pseq"])
                    names[k] = (r["name"], pkey)
                    if r["prec"] is not None and pkey not in mft_paths and pkey not in names:
                        nxt.add(pkey)
            frontier = nxt
        out = {}
        for key in keys:
            parts, k, prefix, source, seen = [], key, None, "mft", set()
            while k is not None and k not in seen:
                seen.add(k)
                if k in mft_paths:
                    prefix = mft_paths[k]
                    break
                if k[1] == 5:
                    prefix = ""
                    break
                if k in names:
                    parts.append(names[k][0])
                    source = "journal"
                    k = names[k][1]
                    continue
                break
            if prefix is None and not parts:
                continue
            path = "/".join(p for p in [prefix or ""] + list(reversed(parts)) if p)
            if prefix is None:
                path = "?/" + path            # the chain ends in a directory nobody named
            out[key] = (path, source)
        return out

    def _name_and_path(self, row, parents) -> Tuple[str, str, str]:
        """(display name, path, where the path came from) for one event row."""
        fn, un = row.get("fn") or "", row.get("un") or ""
        # The journal's name is the long one; the File-Name attribute can be
        # the 8.3 alias (or absent: the MFT entry was reused since).
        name = un if (un and (not fn or _is_short(fn))) else (fn or un)
        path = _clean_path(row.get("path"))
        if path:
            if name and _is_short(path.rsplit("/", 1)[-1]) and name != path.rsplit("/", 1)[-1]:
                path = (path.rsplit("/", 1)[0] + "/" + name) if "/" in path else name
            return name, path, "mft"
        parent = parents.get((row.get("vol") or "", row.get("prec"), row.get("pseq")))
        if parent is not None:
            ppath, source = parent
            return name, ("%s/%s" % (ppath.rstrip("/"), name) if ppath else name), source
        return name, "", ""

    def _event(self, x, parents, renames=None):
        name, path, source = self._name_and_path(x, parents)
        t = x.get("t") or ""
        hh = int(t[11:13]) if len(t) >= 13 and t[11:13].isdigit() else 0
        rename = (renames or {}).get(x.get("u"))
        return {"id": file_id(x.get("vol"), x.get("rec"), x.get("seq")), "rec": x.get("rec"),
                "name": name, "path": path, "pathFrom": source, "t": t, "hour": hh,
                "flags": reason_flags(x.get("r")), "cats": sorted(reason_cats(x.get("r"))),
                "size": x.get("sz"), "deleted": x.get("del"),
                "inMft": bool(x.get("inmft", 1)), "rename": rename,
                "shortName": x.get("fn") if (x.get("fn") and x.get("fn") != name) else None}

    def _event_select(self) -> str:
        prec = self._parent_rec_expr() or "NULL"
        has_mft = "has_mft_record" if "has_mft_record" in self._cols() else "1"
        return (f"SELECT {self._vol()} vol, mft_record_number rec, {self._seq()} seq, "
                f"reconstructed_path path, fn_filename fn, {self._usn_name()} un, "
                f"usn_timestamp t, usn_reason r, is_deleted del, {self._size_expr()} sz, "
                f"{'usn_event_id' if 'usn_event_id' in self._cols() else 'NULL'} u, "
                f"{prec} prec, {self._parent_seq_expr()} pseq, {has_mft} inmft FROM {CORR_TABLE}")

    def _events_out(self, rows):
        """Event rows -> JSON events, with folders rebuilt where the row has
        none and each rename record showing old -> new."""
        parents = self._parent_paths({(r["vol"] or "", r["prec"], r["pseq"]) for r in rows
                                      if not _clean_path(r["path"])})
        return [self._event(r, parents, self._renames_for_usns([r.get("u") for r in rows]))
                for r in rows]

    # ---- renames (filename_changes: old name -> new name) -----------------
    def _has_renames(self) -> bool:
        return self._has_table(CORR_DB, RENAME_TABLE)

    def _renames_for_usns(self, usns):
        """{usn: {"old", "new", "side"}} for the rename records among `usns`."""
        usns = [u for u in usns if u is not None]
        if not usns or not self._has_renames():
            return {}
        cache = getattr(self, "_rn_cache", None)
        key = tuple(usns)
        if cache and cache[0] == key:
            return cache[1]
        out = {}
        for i in range(0, len(usns), 400):
            chunk = usns[i:i + 400]
            q = ",".join("?" * len(chunk))
            for r in self._query(CORR_DB,
                    f"SELECT usn_old, usn_new, old_name, new_name, is_move, new_parent_path "
                    f"FROM {RENAME_TABLE} WHERE usn_old IN ({q}) OR usn_new IN ({q})",
                    tuple(chunk) + tuple(chunk)):
                info = {"old": r["old_name"], "new": r["new_name"], "move": bool(r["is_move"]),
                        "newDir": _clean_path(r["new_parent_path"])}
                out[r["usn_old"]] = dict(info, side="old")
                out[r["usn_new"]] = dict(info, side="new")
        self._rn_cache = (key, out)
        return out

    def _rename_where(self, args, day=None):
        parts, params = [], []
        if day:
            parts.append("date(rename_time) = ?"); params.append(day)
        else:
            if args.get("start"):
                parts.append("date(rename_time) >= date(?)"); params.append(args["start"])
            if args.get("end"):
                parts.append("date(rename_time) <= date(?)"); params.append(args["end"])
        if args.get("volume"):
            parts.append("volume_letter = ?"); params.append(args["volume"])
        terms = [norm_term(t) for t in (args.get("terms") or []) if t and norm_term(t)]
        if terms:
            per = []
            for t in terms:
                per.append("(old_name LIKE ? OR new_name LIKE ? OR old_parent_path LIKE ? "
                           "OR new_parent_path LIKE ?)")
                params.extend([f"%{t}%"] * 4)
            join = " AND " if (args.get("mode", "or").lower() == "and") else " OR "
            parts.append("(" + join.join(per) + ")")
        return ((" WHERE " + " AND ".join(parts)) if parts else "", params)

    def _renames(self, args, day=None, offset=0, limit=DAY_FILES, order="asc"):
        """{total, rows} of renames matching the filters (one day, or all)."""
        if not self._has_renames():
            return {"total": 0, "rows": [], "available": False}
        where, params = self._rename_where(args, day)
        n = self._query(CORR_DB, f"SELECT COUNT(*) n FROM {RENAME_TABLE}{where}", tuple(params))
        direction = "DESC" if order == "desc" else "ASC"
        rows = self._query(CORR_DB,
            f"SELECT volume_letter vol, mft_record_number rec, mft_sequence_number seq, "
            f"rename_time t, old_name, new_name, old_parent_path, new_parent_path, is_move "
            f"FROM {RENAME_TABLE}{where} ORDER BY rename_time {direction}, usn_old {direction} "
            f"LIMIT {int(limit)} OFFSET {int(offset)}", tuple(params))
        return {"total": (n[0]["n"] if n else 0) or 0, "available": True,
                "rows": [{"id": file_id(r["vol"], r["rec"], r["seq"]), "t": r["t"],
                          "old": r["old_name"], "new": r["new_name"],
                          "oldDir": _clean_path(r["old_parent_path"]),
                          "newDir": _clean_path(r["new_parent_path"]),
                          "move": bool(r["is_move"])} for r in rows]}

    def _top_dirs_and_exts(self, where, params, limit=12):
        """Top directories and file types over EVERY event matching `where`.

        Grouped in SQL by the parent directory's record - which journal-only
        events carry too - then named from the MFT. Grouping on the
        reconstructed path would put every journal-only event under nothing.
        """
        prec = self._parent_rec_expr()
        if prec:
            rows = self._query(CORR_DB,
                f"SELECT {self._vol()} vol, {prec} prec, {self._parent_seq_expr()} pseq, COUNT(*) n "
                f"FROM {CORR_TABLE}{where} GROUP BY vol, prec, pseq ORDER BY n DESC LIMIT {limit}",
                tuple(params))
            names = self._parent_paths({(r["vol"] or "", r["prec"], r["pseq"]) for r in rows})
            dirs = []
            for r in rows:
                hit = names.get((r["vol"] or "", r["prec"], r["pseq"]))
                dirs.append({"dir": (hit[0] or "\\") if hit else
                             "(unnamed folder #%s)" % r["prec"],
                             "fromJournal": bool(hit and hit[1] == "journal"), "n": r["n"]})
        else:
            rows = self._query(CORR_DB,
                f"SELECT rtrim(reconstructed_path, replace(reconstructed_path, '/', '')) d, "
                f"COUNT(*) n FROM {CORR_TABLE}{where} GROUP BY d ORDER BY n DESC LIMIT {limit}",
                tuple(params))
            dirs = [{"dir": _dirname((r["d"] or "") + "x") or "\\", "n": r["n"]} for r in rows]
        name_col = "COALESCE(%s, fn_filename)" % self._usn_name() if self._usn_name() != "NULL" else "fn_filename"
        ext_sql = (f"CASE WHEN instr({name_col}, '.') > 0 THEN lower(replace({name_col}, "
                   f"rtrim({name_col}, replace({name_col}, '.', '')), '')) ELSE '(none)' END")
        ext_rows = self._query(CORR_DB,
            f"SELECT {ext_sql} e, COUNT(*) n FROM {CORR_TABLE}{where} GROUP BY e "
            f"ORDER BY n DESC LIMIT {limit}", tuple(params))
        exts = [{"ext": (r["e"] or "(none)")[:16], "n": r["n"]} for r in ext_rows]
        return dirs, exts

    def _flag_counts(self, where, params):
        """{flag: n} and {category: n} over every event matching `where`."""
        by_flag, by_cat = {}, {c: 0 for c in REASON_CATS}
        for r in self._query(CORR_DB,
                f"SELECT usn_reason r, COUNT(*) n FROM {CORR_TABLE}{where} GROUP BY r",
                tuple(params)):
            for f in reason_flags(r["r"]):
                by_flag[f] = by_flag.get(f, 0) + r["n"]
            for c in reason_cats(r["r"]):
                by_cat[c] += r["n"]
        return by_flag, by_cat

    # ---- slots ------------------------------------------------------------
    @pyqtSlot(result=str)
    def getMftUsnBounds(self) -> str:
        # Cached like the strip and the overview: asked on every open.
        return self._cached("bounds", "{}", lambda _a: self._bounds())

    def _bounds(self) -> str:
        if not self._has_data():
            return json.dumps({"hasData": False})
        cols = self._cols()
        mft = self._query(CORR_DB,
            f"SELECT date(MIN(si_creation_time)) a, date(MAX(si_modification_time)) b FROM {CORR_TABLE} "
            f"WHERE si_creation_time >= '{MFT_TIME_FLOOR}' AND si_modification_time < '{MFT_TIME_CEIL}'")
        usn = self._query(CORR_DB,
            f"SELECT date(MIN(usn_timestamp)) a, date(MAX(usn_timestamp)) b FROM {CORR_TABLE} WHERE has_usn_event=1")
        vols = []
        if "volume_letter" in cols:
            vols = [r["v"] for r in self._query(CORR_DB, f"SELECT DISTINCT volume_letter v FROM {CORR_TABLE} WHERE volume_letter IS NOT NULL ORDER BY v")]
        m, u = (mft[0] if mft else {}), (usn[0] if usn else {})
        ends = [d for d in (m.get("a"), m.get("b"), u.get("a"), u.get("b")) if d]
        return json.dumps({
            "hasData": True,
            "mftMin": m.get("a"), "mftMax": m.get("b"),
            "usnMin": u.get("a"), "usnMax": u.get("b"),
            # The shared axis covers both.
            "min": min(ends) if ends else None, "max": max(ends) if ends else None,
            "volumes": vols,
            "hasVolume": "volume_letter" in cols,
            "hasAds": "has_ads" in cols,
        })

    @pyqtSlot(str, result=str)
    def getMftUsnTimelines(self, args_json: str) -> str:
        return self._cached("timelines", args_json, self._timelines)

    def _timelines(self, args_json: str) -> str:
        """One strip on one day axis: MFT Created / Modified (distinct files per
        day) and one row per USN reason flag (records per day)."""
        args = _loads(args_json)
        if not self._has_data():
            return json.dumps({"rows": [], "series": {}, "combined": [], "totals": {}})

        mft_extra = self._mft_only()
        created, modified, outside = {}, {}, {}
        ranged = bool(args.get("start") or args.get("end"))
        for key, col, out in (("c", "si_creation_time", created), ("m", "si_modification_time", modified)):
            # One pass per column: the in-window days AND the files whose time
            # is outside the drawable window (said, not dropped).
            where, params = self._where(args, extra=f"{mft_extra} AND {col} IS NOT NULL", tcol=col)
            for r in self._query(CORR_DB,
                    f"SELECT CASE WHEN {col} >= '{MFT_TIME_FLOOR}' AND {col} < '{MFT_TIME_CEIL}' "
                    f"THEN date({col}) ELSE '' END d, COUNT(DISTINCT {self._file_key()}) c "
                    f"FROM {CORR_TABLE}{where} GROUP BY d", tuple(params)):
                if r["d"]:
                    out[r["d"]] = r["c"]
                elif not ranged:
                    outside[key] = r["c"]

        # USN: one GROUP BY day and reason string, split into flags here - a
        # day has a few dozen distinct reason strings, not thousands of rows.
        where, params = self._where(args, extra="has_usn_event=1")
        per_flag, usn_day = {}, {}
        for r in self._query(CORR_DB,
                f"SELECT date(usn_timestamp) d, usn_reason r, COUNT(*) n FROM {CORR_TABLE}{where} "
                f"GROUP BY d, r", tuple(params)):
            if not r["d"]:
                continue
            for f in reason_flags(r["r"]):
                per_flag.setdefault(f, {})
                per_flag[f][r["d"]] = per_flag[f].get(r["d"], 0) + r["n"]
            usn_day[r["d"]] = usn_day.get(r["d"], 0) + r["n"]

        combined = {}
        for counts in (created, modified, usn_day):
            for d, n in counts.items():
                combined[d] = combined.get(d, 0) + n
        start, end = _axis_range(args, combined)
        series_in = {"mft_created": created, "mft_modified": modified}
        series_in.update(per_flag)
        series = _densify_series(series_in, start, end, key="key", field="buckets")
        rows = [{"key": k, "label": label, "group": "mft",
                 "total": sum(series_in[k].values())} for k, label in MFT_ROWS]
        rows += [{"key": f, "label": f.replace("_", " ").title().replace("Mft", "MFT"),
                  "group": "usn", "total": sum(per_flag[f].values())}
                 for f in sorted(per_flag, key=flag_sort_key)]
        return json.dumps({
            "rows": rows,
            "series": series,
            "combined": _densify(combined, start, end, key="key"),
            "totals": {"usnEvents": sum(usn_day.values()),
                       "mftCreated": sum(created.values()),
                       "mftModified": sum(modified.values()),
                       "mftOutsideCreated": outside.get("c", 0),
                       "mftOutsideModified": outside.get("m", 0)},
        })

    @pyqtSlot(str, result=str)
    def getMftUsnWindowDetail(self, args_json: str) -> str:
        """One day: USN events by hour and flag, the top directories and types
        (all counted in SQL), one page of the events, and the MFT files
        created / modified that day. `hour` narrows the events to one hour.
        Cached per filters (12 s for one day on a complete MFT)."""
        return self._cached("window", args_json, self._window_detail)

    def _window_detail(self, args_json: str) -> str:
        args = _loads(args_json)
        bucket = str(args.get("bucket") or "")[:10]
        empty = {"events": [], "total": 0, "page": 0, "pageSize": EVENT_PAGE, "byHour": {},
                 "byHourCat": {}, "topDirs": [], "topExts": [], "byFlag": {},
                 "mft": {"created": {"total": 0, "files": []}, "modified": {"total": 0, "files": []}},
                 "renames": {"total": 0, "rows": []}}
        if not self._has_data() or not bucket:
            return json.dumps(empty)
        page = max(0, int(args.get("page") or 0))
        day_args = {k: v for k, v in args.items() if k not in ("start", "end")}
        where, params = self._where(day_args, extra="has_usn_event=1")
        where += " AND usn_timestamp >= ? AND usn_timestamp < date(?, '+1 day')"; params.extend([bucket, bucket])

        by_hour, by_hour_cat = {}, {c: [0] * 24 for c in REASON_CATS}
        for r in self._query(CORR_DB,
                f"SELECT substr(usn_timestamp, 12, 2) h, usn_reason r, COUNT(*) n "
                f"FROM {CORR_TABLE}{where} GROUP BY h, r", tuple(params)):
            try:
                h = int(r["h"])
            except (TypeError, ValueError):
                continue
            if not 0 <= h < 24:
                continue
            for f in reason_flags(r["r"]):
                by_hour.setdefault(f, [0] * 24)[h] += r["n"]
            for c in reason_cats(r["r"]):
                by_hour_cat[c][h] += r["n"]
        by_flag = {f: sum(v) for f, v in by_hour.items()}
        top_dirs, top_exts = self._top_dirs_and_exts(where, params)
        page_data = self._day_events(where, params, args.get("hour"), page)
        renames = self._renames(day_args, day=bucket)
        renames.update({"page": 0, "pageSize": DAY_FILES})
        page_data.update({"byHour": by_hour, "byHourCat": by_hour_cat, "byFlag": by_flag,
                          "topDirs": top_dirs, "topExts": top_exts,
                          "mft": self._mft_day(bucket, args), "renames": renames})
        return json.dumps(page_data)

    @pyqtSlot(str, result=str)
    def getMftUsnDayEvents(self, args_json: str) -> str:
        """One page of a day's events (optionally one hour) - without the day's
        aggregates, which do not change between pages. Recomputing them cost
        ~1.8 s per page on a 283,585-event day."""
        args = _loads(args_json)
        bucket = str(args.get("bucket") or "")[:10]
        if not self._has_data() or not bucket:
            return json.dumps({"events": [], "total": 0, "page": 0, "pageSize": EVENT_PAGE})
        day_args = {k: v for k, v in args.items() if k not in ("start", "end")}
        where, params = self._where(day_args, extra="has_usn_event=1")
        where += " AND usn_timestamp >= ? AND usn_timestamp < date(?, '+1 day')"; params.extend([bucket, bucket])
        return json.dumps(self._day_events(where, params, args.get("hour"),
                                           max(0, int(args.get("page") or 0))))

    def _day_events(self, where, params, hour, page):
        ev_where, ev_params = where, list(params)
        if hour is not None and str(hour).isdigit():
            ev_where += " AND substr(usn_timestamp, 12, 2)=?"; ev_params.append("%02d" % int(hour))
        total = self._query(CORR_DB, f"SELECT COUNT(*) n FROM {CORR_TABLE}{ev_where}", tuple(ev_params))
        total = (total[0]["n"] if total else 0) or 0
        rows = self._query(CORR_DB,
            f"{self._event_select()}{ev_where} ORDER BY usn_timestamp LIMIT {EVENT_PAGE} "
            f"OFFSET {page * EVENT_PAGE}", tuple(ev_params))
        return {"events": self._events_out(rows), "total": total,
                "page": page, "pageSize": EVENT_PAGE,
                "hour": int(hour) if hour is not None and str(hour).isdigit() else None}

    def _mft_files(self, where, params, col, offset, limit, order="ASC"):
        """{total, files} - distinct files (volume + record) matching `where`."""
        n = self._query(CORR_DB, f"SELECT COUNT(DISTINCT {self._file_key()}) n FROM {CORR_TABLE}{where}",
                        tuple(params))
        rows = self._query(CORR_DB,
            f"SELECT {self._vol()} vol, mft_record_number rec, {self._seq()} seq, "
            f"reconstructed_path path, fn_filename fn, {self._usn_name()} un, {col} t, "
            f"is_directory dir, is_deleted del, {self._size_expr()} sz FROM {CORR_TABLE}{where} "
            f"GROUP BY vol, rec ORDER BY t {order}, rec LIMIT {int(limit)} OFFSET {int(offset)}",
            tuple(params))
        files = []
        for r in rows:
            name, path, _src = self._name_and_path(r, {})
            files.append({"id": file_id(r["vol"], r["rec"], r["seq"]), "name": name,
                          "path": path, "t": r["t"], "dir": r["dir"], "size": r["sz"],
                          "deleted": r["del"]})
        return {"total": (n[0]["n"] if n else 0) or 0, "files": files}

    def _mft_day(self, day, args, only=None, page=0):
        """Files created / modified on `day` (Standard-Info): counted, one page
        of DAY_FILES listed. It stopped at the first 200 with no way on: 97
        days of one case had more, and 165k files could not be reached."""
        out = {}
        day_args = {k: v for k, v in args.items() if k not in ("start", "end")}
        for key, col in (("created", "si_creation_time"), ("modified", "si_modification_time")):
            if only and key != only:
                continue
            where, params = self._where(day_args, extra=f"{self._mft_only()} AND {col} >= ? "
                                        f"AND {col} < date(?, '+1 day')", tcol=col)
            params.extend([day, day])
            part = self._mft_files(where, params, col, page * DAY_FILES, DAY_FILES)
            part.update({"page": page, "pageSize": DAY_FILES})
            out[key] = part
        return out

    @pyqtSlot(str, result=str)
    def getMftUsnDayFiles(self, args_json: str) -> str:
        """One page of a day's created or modified files (`kind`)."""
        args = _loads(args_json)
        bucket = str(args.get("bucket") or "")[:10]
        kind = args.get("kind") if args.get("kind") in ("created", "modified") else "created"
        if not self._has_data() or not bucket:
            return json.dumps({"total": 0, "files": [], "page": 0, "pageSize": DAY_FILES})
        page = max(0, int(args.get("page") or 0))
        return json.dumps(self._mft_day(bucket, args, only=kind, page=page)[kind])

    @pyqtSlot(str, result=str)
    def getMftUsnDayRenames(self, args_json: str) -> str:
        """One page of a day's renames (old name -> new name)."""
        args = _loads(args_json)
        bucket = str(args.get("bucket") or "")[:10]
        page = max(0, int(args.get("page") or 0))
        out = self._renames(args, day=bucket, offset=page * DAY_FILES)
        out.update({"page": page, "pageSize": DAY_FILES})
        return json.dumps(out)

    @pyqtSlot(str, result=str)
    def getMftUsnAll(self, args_json: str) -> str:
        """Every USN record, MFT file or rename matching the filters, across
        all days - newest or oldest first, ALL_PAGE at a time. The rest of the
        dashboard is read one day at a time."""
        args = _loads(args_json)
        kind = args.get("kind") if args.get("kind") in ("events", "files", "renames") else "events"
        order = "DESC" if str(args.get("order") or "desc").lower() == "desc" else "ASC"
        offset = max(0, int(args.get("offset") or 0))
        empty = {"kind": kind, "rows": [], "total": 0, "pageSize": ALL_PAGE}
        if not self._has_data():
            return json.dumps(empty)
        if kind == "renames":
            r = self._renames(args, offset=offset, limit=ALL_PAGE, order=order.lower())
            return json.dumps({"kind": kind, "rows": r["rows"], "total": r["total"],
                               "available": r["available"], "pageSize": ALL_PAGE})
        if kind == "files":
            col = "si_modification_time"
            where, params = self._where(args, extra=f"{self._mft_only()}", tcol=col)
            part = self._mft_files(where, params, col, offset, ALL_PAGE, order)
            return json.dumps({"kind": kind, "rows": part["files"], "total": part["total"],
                               "pageSize": ALL_PAGE})
        where, params = self._where(args, extra="has_usn_event=1")
        n = self._query(CORR_DB, f"SELECT COUNT(*) n FROM {CORR_TABLE}{where}", tuple(params))
        rows = self._query(CORR_DB,
            f"{self._event_select()}{where} ORDER BY usn_timestamp {order}, rowid {order} "
            f"LIMIT {ALL_PAGE} OFFSET {offset}", tuple(params))
        return json.dumps({"kind": kind, "rows": self._events_out(rows),
                           "total": (n[0]["n"] if n else 0) or 0, "pageSize": ALL_PAGE})

    @pyqtSlot(str, result=str)
    def getMftUsnOverview(self, args_json: str) -> str:
        return self._cached("overview", args_json, self._overview)

    def _overview(self, args_json: str) -> str:
        """The right-hand panel. Every number honours the same filters: the
        search and the volume apply to all of them, the date range to the
        journal records and the renames (an MFT file has no single date). The
        file tiles used to ignore every filter while the record tiles beside
        them obeyed it, so a search showed "200,314 files" next to 12 events.
        """
        args = _loads(args_json)
        if not self._has_data():
            return json.dumps({"totals": {}, "anomalies": {}, "topDirs": [], "topExts": [],
                               "byCategory": {}, "byFlag": {}})
        cols = self._cols()
        fk = self._file_key()
        nodate = {k: v for k, v in args.items() if k not in ("start", "end")}

        def w(extra=""):
            return self._where(nodate, extra=extra)

        # Files, not rows: the table repeats a record once per USN event.
        bw, bp = w(self._mft_only())
        # One group per file, then counted: the same numbers as four
        # COUNT(DISTINCT)s, in a single pass that the correlator's
        # idx_corr_mft_files serves in record order. The four DISTINCTs each
        # built a temporary B-tree - 7.7 s on a 3.5-million-row case.
        ads_col = "MAX(has_ads=1)" if "has_ads" in cols else "0"
        group = "mft_record_number" + (", volume_letter" if "volume_letter" in cols else "")
        base = self._query(CORR_DB,
            f"SELECT COUNT(*) files, SUM(d) dirs, SUM(dl) deleted, SUM(a) ads FROM ("
            f"SELECT MAX(is_directory=1) d, MAX(is_deleted=1) dl, {ads_col} a "
            f"FROM {CORR_TABLE}{bw} GROUP BY {group})", tuple(bp))
        b = base[0] if base else {}
        ew, ep = self._where(args, extra="has_usn_event=1")
        ev = self._query(CORR_DB,
            f"SELECT COUNT(DISTINCT {fk} || ':' || COALESCE({self._seq()}, '')) evfiles, "
            f"COUNT(*) events FROM {CORR_TABLE}{ew}", tuple(ep))
        e = ev[0] if ev else {}
        ads = (b.get("ads") or 0)

        by_flag, by_cat = self._flag_counts(ew, ep)
        top_dirs, top_exts = self._top_dirs_and_exts(ew, ep)

        # Timestomp candidates: SI creation set LATER than the kernel-written
        # File-Name creation (forward-dating; FN is not user-settable).
        # A second rule - all four SI times whole seconds while FN keeps
        # sub-seconds - was dropped: this parser stores MFT times to the whole
        # second on both sides, so it could never fire; a rule that cannot
        # fire reads as "checked, nothing found". The old "SI modified before
        # created" rule is not used either - it is normal for copied files.
        _TS_WHERE = ("si_creation_time >= '2008-01-01' AND fn_creation_time >= '2008-01-01' "
                     "AND si_creation_time > fn_creation_time")
        # The candidates are counted and ranked from the correlator's partial
        # index (idx_corr_timestomp: only these rows), and only the _CAP shown
        # are read in full. Reading every candidate's row was 3.5 s for 22,891
        # candidates on a complete MFT.
        tw, tp = w(f"{self._mft_only()} AND {_TS_WHERE}")
        keys = self._query(CORR_DB,
            f"SELECT {self._vol()} vol, mft_record_number rec, MAX(si_creation_time) sic "
            f"FROM {CORR_TABLE}{tw} GROUP BY vol, rec", tuple(tp))
        timestomp = len(keys)
        top = sorted(keys, key=lambda x: x["sic"] or "", reverse=True)[:_CAP]
        tsomp_rows = []
        for k in top:
            vol_sql, vparams = ("volume_letter IS ? AND ", [k["vol"]]) if "volume_letter" in cols else ("", [])
            got = self._query(CORR_DB,
                f"SELECT {self._vol()} vol, mft_record_number rec, {self._seq()} seq, "
                f"reconstructed_path path, fn_filename fn, {self._usn_name()} un, "
                f"si_creation_time sic, fn_creation_time fnc FROM {CORR_TABLE} WHERE {vol_sql}"
                f"mft_record_number = ? AND {self._mft_only()} AND {_TS_WHERE} LIMIT 1",
                tuple(vparams) + (k["rec"],))
            tsomp_rows.extend(got)
        timestomp_subj = []
        for x in tsomp_rows:
            name, path, _s = self._name_and_path(x, {})
            timestomp_subj.append(_subject(path or name, file_id(x["vol"], x["rec"], x["seq"]),
                                           "SI %s vs FN %s" % (x["sic"] or "-", x["fnc"] or "-")))

        gaps, gaps_subj = 0, []
        if self._has_table(USN_DB, "deleted_entries"):
            g = self._query(USN_DB, "SELECT COUNT(*) n FROM deleted_entries")
            gaps = (g[0]["n"] if g else 0) or 0
            gaps_subj = self._deleted_entry_subjects()

        dw, dp = w(f"{self._mft_only()} AND is_deleted=1")
        # The first _CAP files, without grouping 1.6 million deleted rows to
        # find them: rows come in record order, a file's repeats are adjacent.
        del_rows = _first_files(self._query(CORR_DB,
            f"SELECT {self._vol()} vol, mft_record_number rec, {self._seq()} seq, "
            f"reconstructed_path path, fn_filename fn, {self._usn_name()} un, "
            f"{self._size_expr()} sz FROM {CORR_TABLE}{dw} LIMIT {_CAP * 50}", tuple(dp)))
        deleted_subj = []
        for x in del_rows:
            name, path, _s = self._name_and_path(x, {})
            deleted_subj.append(_subject(path or name, file_id(x["vol"], x["rec"], x["seq"]),
                                         "record %s" % x["rec"]))

        ads_subj = []
        if "has_ads" in cols:
            aw, ap = w("has_ads=1")
            ads_rows = _first_files(self._query(CORR_DB,
                f"SELECT {self._vol()} vol, mft_record_number rec, {self._seq()} seq, "
                f"reconstructed_path path, fn_filename fn, {self._usn_name()} un "
                f"FROM {CORR_TABLE}{aw} LIMIT {_CAP * 50}", tuple(ap)))
            for x in ads_rows:
                name, path, _s = self._name_and_path(x, {})
                ads_subj.append(_subject(path or name, file_id(x["vol"], x["rec"], x["seq"]),
                                         "alternate data stream"))

        # Renames, old -> new, newest first. A rename record pair in the
        # journal is one rename here, so this is not the RENAME_* record count.
        rn = self._renames(args, limit=_CAP, order="desc")
        rename_subj = [_subject("%s -> %s" % (r["old"] or "?", r["new"] or "?"), r["id"],
                                "%s%s" % (r["t"] or "", " - moved to %s" % (r["newDir"] or "?")
                                          if r["move"] else ""))
                       for r in rn["rows"]]

        totals = {
            "files": (b.get("files") or 0), "directories": (b.get("dirs") or 0),
            "withEvents": (e.get("evfiles") or 0), "usnEvents": (e.get("events") or 0),
            "deleted": (b.get("deleted") or 0), "ads": ads,
            "created": by_cat["create"], "renamed": by_cat["rename"],
            "renames": rn["total"], "renamesAvailable": rn["available"],
            "dataChanged": by_cat["data"], "deletedEvents": by_cat["delete"],
        }
        anomalies = {
            "timestompCandidates": _insight(timestomp, timestomp_subj),
            "usnGaps": _insight(gaps, gaps_subj),
            "deletedButPresent": _insight((b.get("deleted") or 0), deleted_subj),
            "ads": _insight(ads, ads_subj),
            "renames": _insight(rn["total"], rename_subj),
        }
        return json.dumps({"totals": totals, "anomalies": anomalies, "byCategory": by_cat,
                           "byFlag": by_flag, "topDirs": top_dirs, "topExts": top_exts})

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
        """One FILE: volume + record + sequence, so an earlier file that held
        the same MFT entry is not mixed into this one's timeline."""
        args = _loads(args_json)
        vol, rec, seq = parse_file_id(args.get("id", args.get("rec")))
        if not self._has_data() or rec is None:
            return json.dumps({})
        cols = self._cols()
        where, params = ["mft_record_number = ?"], [rec]
        if vol and "volume_letter" in cols:
            where.append("volume_letter = ?"); params.append(vol)
        if seq is not None and "mft_sequence_number" in cols:
            where.append("mft_sequence_number = ?"); params.append(seq)
        w = " WHERE " + " AND ".join(where)
        has_mft = "has_mft_record" if "has_mft_record" in cols else "1"
        prec = self._parent_rec_expr() or "NULL"
        rows = self._query(CORR_DB,
            f"SELECT {self._vol()} vol, mft_record_number rec, {self._seq()} seq, "
            f"{self._parent_seq_expr()} pseq, "
            f"reconstructed_path path, fn_filename fn, {self._usn_name()} un, is_directory dir, "
            f"is_deleted del, si_creation_time sic, si_modification_time sim, si_access_time sia, "
            f"si_mft_entry_change_time sie, fn_creation_time fnc, fn_modification_time fnm, fn_access_time fna, "
            f"fn_mft_entry_change_time fne, {self._size_expr()} sz, usn_timestamp t, usn_reason r, "
            f"{has_mft} inmft, {prec} prec FROM {CORR_TABLE}{w} "
            f"ORDER BY {has_mft} DESC, usn_timestamp", tuple(params))
        if not rows:
            return json.dumps({})
        head = rows[0]
        parents = {}
        if not _clean_path(head["path"]):
            parents = self._parent_paths({(head["vol"] or "", head["prec"], head["pseq"])})
        name, path, source = self._name_and_path(head, parents)
        # Every name the journal recorded for this file - a rename shows here.
        names = []
        for x in rows:
            n = x["un"] or x["fn"]
            if n and n not in names:
                names.append(n)
        # Everything the correlator stored for this record, shown under the
        # curated reading so "the panel does not show it" and "the artifact does
        # not record it" stop looking the same. See raw_record.py.
        _full = self._query(
            CORR_DB, f"SELECT * FROM {CORR_TABLE}{w} ORDER BY {has_mft} DESC LIMIT 1", tuple(params))
        raw = _raw(_full[0], CORR_TABLE) if _full else None
        timed = [x for x in rows if x["t"]]
        # A busy file has thousands (Amcache.hve: 21,689 on one case); the
        # modal lists the first FILE_EVENTS and says how many there are.
        events = [{"t": x["t"], "cats": sorted(reason_cats(x["r"])), "flags": reason_flags(x["r"]),
                   "reason": x["r"], "name": x["un"] or x["fn"]} for x in timed[:FILE_EVENTS]]
        # Timestomping flag on the head record (tight / low-false-positive).
        def _real(v): return v and v >= "2008-01-01"
        flags = []
        if _real(head["sic"]) and _real(head["fnc"]) and head["sic"] > head["fnc"]:
            flags.append("Standard-Info creation is newer than File-Name creation (possible forward-dating)")
        renames = []
        if self._has_renames() and head["seq"] is not None:
            for r in self._query(CORR_DB,
                    f"SELECT rename_time t, old_name, new_name, old_parent_path, new_parent_path, "
                    f"is_move FROM {RENAME_TABLE} WHERE volume_letter IS ? AND mft_record_number = ? "
                    f"AND mft_sequence_number = ? ORDER BY rename_time, usn_old",
                    (head["vol"], head["rec"], head["seq"])):
                renames.append({"t": r["t"], "old": r["old_name"], "new": r["new_name"],
                                "oldDir": _clean_path(r["old_parent_path"]),
                                "newDir": _clean_path(r["new_parent_path"]),
                                "move": bool(r["is_move"])})
        return json.dumps({
            "renames": renames,
            "id": file_id(head["vol"], head["rec"], head["seq"]),
            "rec": head["rec"], "seq": head["seq"], "volume": head["vol"],
            "path": path, "pathFrom": source, "filename": name,
            "shortName": head["fn"] if (head["fn"] and head["fn"] != name) else None,
            "names": names, "inMft": bool(head["inmft"]),
            "isDir": head["dir"], "deleted": head["del"], "size": head["sz"],
            "si": {"created": head["sic"], "modified": head["sim"], "accessed": head["sia"], "mftChanged": head["sie"]},
            "fnTimes": {"created": head["fnc"], "modified": head["fnm"], "accessed": head["fna"], "mftChanged": head["fne"]},
            "events": events, "eventsTotal": len(timed), "flags": flags, "raw": raw,
        })


def _first_files(rows, cap=None):
    """The first `cap` distinct files (volume, record) of `rows`, in order."""
    cap = _CAP if cap is None else cap
    out, seen = [], set()
    for r in rows:
        k = (r.get("vol"), r.get("rec"))
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
        if len(out) >= cap:
            break
    return out


def _loads(s):
    try:
        return json.loads(s or "{}")
    except Exception:
        return {}
