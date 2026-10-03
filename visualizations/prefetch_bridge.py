"""QWebChannel bridge for the Prefetch ("program executions") dashboard.

Reads the case's prefetch_data.db and exposes program-execution activity to the
react-prefetch app as JSON. Same shape as the SRUM / MFT-USN / LNK bridges.

Each prefetch row is one executable with a run_count, up to 8 run_times (JSON),
the volumes it touched (JSON), the directories and resources (files/DLLs) it
loaded (JSON), and the .pf file's own MAC times. The data is small, so every
slot fetches all rows once, parses the JSON, and aggregates in Python.

Colour language = run LOCATION, derived from the exe's own full path (the entry
in `resources` whose basename == executable_name):
  system / programfiles / usertemp / removable / other
"""

import os
import json

from visualizations.timeseries import (axis_range as _axis_range,
                                       densify as _densify,
                                       densify_series as _densify_series)
from visualizations.raw_record import raw_record as _raw
from visualizations.insights import (insight as _insight,
                                       plain as _plain,
                                       subject as _subject)
import time
import sqlite3
import logging
from typing import List, Dict, Optional

from PyQt5.QtCore import QObject, pyqtSlot

logger = logging.getLogger(__name__)

PREFETCH_DB = "prefetch_data.db"
LOCATIONS = ("system", "programfiles", "usertemp", "removable", "other")


def _loads_json(v, default):
    if v is None:
        return default
    if isinstance(v, (list, dict)):
        return v
    try:
        out = json.loads(v)
        return out if out is not None else default
    except Exception:
        return default


def _base(path: str) -> str:
    p = str(path or "").replace("/", "\\").rstrip("\\")
    return p[p.rfind("\\") + 1:] if "\\" in p else p


def _norm_resources(raw):
    """(exe app_id, [resource path strings]) from either resources format.

    Old format: a list of path strings. New format: a list of dicts, the first
    a {"_meta": {..., "app_id"}} header and the rest {"path","mft",...}.
    """
    meta_app_id, paths = "", []
    for e in raw or []:
        if isinstance(e, dict):
            if "_meta" in e:
                meta_app_id = (e.get("_meta") or {}).get("app_id", "") or ""
            elif e.get("path"):
                paths.append(e["path"])
        elif isinstance(e, str) and e:
            paths.append(e)
    return meta_app_id, paths


def _devpath(app_id: str) -> str:
    r"""A classifiable path from a prefetch app_id.

    app_id is a device path: \DEVICE\HARDDISKVOLUMEn\WINDOWS\... . The volume
    prefix carries no drive letter, so strip it to the volume-relative path
    (\WINDOWS\...), which _classify reads by substring exactly as it would a
    C:\WINDOWS\... path.
    """
    import re
    return re.sub(r"^\\DEVICE\\HARDDISKVOLUME\d+", "", str(app_id or ""), flags=re.IGNORECASE) or str(app_id or "")


def _classify(exe_path: str, removable_drive: bool) -> str:
    p = (exe_path or "").upper()
    if removable_drive:
        return "removable"
    # a non-C: drive letter is another volume
    if len(p) >= 2 and p[1] == ":" and p[0] != "C":
        return "removable"
    if "\\WINDOWS\\" in p or p.endswith("\\WINDOWS"):
        return "system"
    if "\\PROGRAM FILES" in p:
        return "programfiles"
    if "\\USERS\\" in p and ("\\APPDATA\\" in p or "\\TEMP\\" in p or "\\DOWNLOADS\\" in p or "\\DESKTOP\\" in p):
        return "usertemp"
    if "\\TEMP\\" in p or "\\DOWNLOADS\\" in p:
        return "usertemp"
    return "other"


class PrefetchBridge(QObject):
    def __init__(self, case_directory: str, parent=None):
        super().__init__(parent)
        self.case_dir = case_directory or ""
        self._cache = None
        logger.info(f"PrefetchBridge initialized with case dir: {case_directory}")

    def _db_path(self) -> Optional[str]:
        p = os.path.join(self.case_dir, PREFETCH_DB)
        return p if os.path.exists(p) else None

    def _query(self, sql: str, params: tuple = ()) -> List[Dict]:
        p = self._db_path()
        if not p:
            return []
        for attempt in range(3):
            try:
                conn = sqlite3.connect(p)
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute(sql, params)
                rows = [dict(r) for r in cur.fetchall()]
                conn.close()
                return rows
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() and attempt < 2:
                    time.sleep(0.1); continue
                logger.error(f"prefetch query error: {e}")
                return []
            except Exception as e:
                logger.error(f"prefetch query failure: {e}")
                return []
        return []

    def _has_data(self) -> bool:
        return len(self._query("SELECT name FROM sqlite_master WHERE type='table' AND name='prefetch_data'")) > 0

    # ---- unify one prefetch row --------------------------------------------
    def _record(self, r: dict) -> dict:
        exe = r.get("executable_name") or _base(r.get("filename") or "")
        directories = _loads_json(r.get("directories"), [])
        volumes = _loads_json(r.get("volumes"), [])
        run_times = [t for t in _loads_json(r.get("run_times"), []) if t]
        # Two resource formats in the wild: an older list of path STRINGS, and a
        # newer list of {"path","mft",...} dicts whose first element is a
        # {"_meta": {..., "app_id": "\\DEVICE\\HARDDISKVOLUMEn\\..."}} header.
        # Normalise to a list of path strings, and lift the exe's own path from
        # app_id (it is not among the loaded resources in the new format, so
        # without this every program classified as "other").
        meta_app_id, resources = _norm_resources(_loads_json(r.get("resources"), []))
        # exe full path = the resource whose basename matches the executable name,
        # else the app_id header path.
        exe_upper = (exe or "").upper()
        exe_path = ""
        for res in resources:
            if _base(res).upper() == exe_upper:
                exe_path = res
                break
        if not exe_path and meta_app_id:
            exe_path = _devpath(meta_app_id)
        # volume of the exe (match its drive letter), plus removable detection
        vol_label = vol_serial = ""
        removable = False
        drive = (exe_path[:2] if len(exe_path) >= 2 and exe_path[1] == ":" else "")
        for v in volumes:
            dn = (v.get("device_name") or "")
            vid = (v.get("volume_id") or "")
            if not drive or vid.upper().startswith(drive.upper()):
                vol_serial = v.get("serial_number") or vol_serial
                # device_name embeds a label + drive type: (Drive C: 'OS' (Fixed))
                import re
                mlabel = re.search(r"'([^']*)'", dn)
                if mlabel:
                    vol_label = mlabel.group(1)
                if "REMOVABLE" in dn.upper() or "NETWORK" in dn.upper() or "REMOTE" in dn.upper():
                    removable = True
                if drive and vid.upper().startswith(drive.upper()):
                    break
        location = _classify(exe_path or (drive + "\\"), removable)
        return {
            "filename": r.get("filename") or "",
            "exe": exe,
            "exePath": exe_path,
            "hash": r.get("hash") or "",
            "runCount": r.get("run_count") or 0,
            "lastExecuted": r.get("last_executed") or "",
            "runTimes": sorted(run_times),
            "location": location,
            "volumeLabel": vol_label,
            "volumeSerial": vol_serial,
            "removable": removable,
            "resources": resources,
            "directories": directories,
            "pfCreated": r.get("created_on") or "",
            "pfModified": r.get("modified_on") or "",
            "pfAccessed": r.get("accessed_on") or "",
        }

    def _all(self) -> List[dict]:
        if self._cache is None:
            self._cache = [self._record(r) for r in self._query("SELECT * FROM prefetch_data")]
        return self._cache

    def _filtered(self, args: dict) -> List[dict]:
        recs = self._all()
        start, end = args.get("start", ""), args.get("end", "")
        loc = args.get("location", "")
        vol = args.get("volume", "")
        terms = [t.strip().lower() for t in (args.get("terms") or []) if t and t.strip()]
        mode = (args.get("mode", "or") or "or").lower()
        out = []
        for x in recs:
            if loc and x["location"] != loc:
                continue
            if vol and x["volumeLabel"] != vol:
                continue
            if start or end:
                days = [t[:10] for t in x["runTimes"]] or ([x["lastExecuted"][:10]] if x["lastExecuted"] else [])
                if start and not any(d >= start for d in days):
                    continue
                if end and not any(d <= end for d in days):
                    continue
            if terms:
                hay = (x["exe"] + " " + x["exePath"] + " " + x["volumeLabel"]).lower()
                hit = [t in hay for t in terms]
                if (all(hit) if mode == "and" else any(hit)) is False:
                    continue
            out.append(x)
        return out

    # ---- slots -------------------------------------------------------------
    @pyqtSlot(result=str)
    def getPrefetchBounds(self) -> str:
        if not self._has_data():
            return json.dumps({"hasData": False})
        recs = self._all()
        all_days = [t[:10] for x in recs for t in x["runTimes"] if t >= "2000"]
        counts = {loc: sum(1 for x in recs if x["location"] == loc) for loc in LOCATIONS}
        vols = sorted({x["volumeLabel"] for x in recs if x["volumeLabel"]})
        return json.dumps({
            "hasData": True,
            "minDate": min(all_days) if all_days else None,
            "maxDate": max(all_days) if all_days else None,
            "counts": counts, "volumes": vols,
        })

    @pyqtSlot(str, result=str)
    def getPrefetchTimeline(self, args_json: str) -> str:
        recs = self._filtered(_loads(args_json))
        per = {loc: {} for loc in LOCATIONS}
        combined = {}
        for x in recs:
            for t in x["runTimes"]:
                if t < "2000":
                    continue
                d = t[:10]
                per[x["location"]][d] = per[x["location"]].get(d, 0) + 1
                combined[d] = combined.get(d, 0) + 1
        # A GROUP BY over timestamps yields only the days that HAD runs, which
        # turns the strip into an ordinal list of active days rather than a time
        # axis - a quiet week closes up and disappears. Fill the whole range,
        # and widen the bucket when a day can no longer be drawn.
        args = _loads(args_json)
        start, end = _axis_range(args, combined)
        sources = _densify_series(per, start, end)
        combined_rows = _densify(combined, start, end)
        return json.dumps({"sources": sources, "combined": combined_rows})

    @pyqtSlot(str, result=str)
    def getPrefetchOverview(self, args_json: str) -> str:
        recs = self._filtered(_loads(args_json))
        by_loc = {loc: 0 for loc in LOCATIONS}
        vols = {}
        total_runs = 0
        days = set()
        user_temp = removable = single_run = 0
        # Collect WHO matched, not just how many: an insight the analyst cannot
        # open is a number with no next question. See visualizations/insights.py.
        temp_subj, removable_subj, single_subj = [], [], []
        top_programs = []
        for x in recs:
            by_loc[x["location"]] += 1
            total_runs += (x["runCount"] or len(x["runTimes"]))
            for t in x["runTimes"]:
                if t >= "2000":
                    days.add(t[:10])
            key = (x["volumeLabel"], x["volumeSerial"], "removable" if x["removable"] else "fixed")
            vols[key] = vols.get(key, 0) + 1
            runs = x["runCount"] or len(x["runTimes"])
            if x["location"] == "usertemp":
                user_temp += 1
                temp_subj.append(_subject(
                    x["exe"], x["filename"],
                    "ran %d%s - last %s" % (runs, "x", x["lastExecuted"] or "unknown")))
            if x["location"] == "removable":
                removable += 1
                removable_subj.append(_subject(
                    x["exe"], x["filename"],
                    "%s - ran %dx" % (x["volumeLabel"] or "unnamed volume", runs)))
            if (x["runCount"] or 0) <= 1:
                single_run += 1
                single_subj.append(_subject(
                    x["exe"], x["filename"],
                    "%s - %s" % (x["location"], x["lastExecuted"] or "unknown")))
            top_programs.append({"exe": x["exe"], "runCount": x["runCount"] or len(x["runTimes"]),
                                 "location": x["location"], "lastExecuted": x["lastExecuted"],
                                 "filename": x["filename"], "volume": x["volumeLabel"]})
        top_programs.sort(key=lambda z: z["runCount"], reverse=True)
        volumes = sorted(({"label": k[0], "serial": k[1], "type": k[2], "n": v} for k, v in vols.items()),
                         key=lambda z: z["n"], reverse=True)[:12]
        return json.dumps({
            "totals": {"programs": len(recs), "runs": total_runs, "activeDays": len(days),
                       "userTemp": user_temp, "removable": removable, "singleRun": single_run},
            "byLocation": [{"loc": loc, "n": by_loc[loc]} for loc in LOCATIONS],
            "topPrograms": top_programs[:15],
            "volumes": volumes,
            "insights": {
                "userTemp": _insight(user_temp, temp_subj),
                "removable": _insight(removable, removable_subj),
                "singleRun": _insight(single_run, single_subj),
                # A maximum is a measurement, not a set of records.
                "maxRuns": _plain(max((p["runCount"] for p in top_programs), default=0)),
            },
        })

    @pyqtSlot(str, result=str)
    def getPrefetchDayDetail(self, args_json: str) -> str:
        args = _loads(args_json)
        day = args.get("day")
        if not day:
            return json.dumps({"events": [], "byHour": {}, "byProgram": [], "topDirs": []})
        recs = self._filtered(args)
        by_hour = {loc: [0] * 24 for loc in LOCATIONS}
        progs, dirs = {}, {}
        events = []
        for x in recs:
            for t in x["runTimes"]:
                if t[:10] != day[:10]:
                    continue
                hh = int(t[11:13]) if len(t) >= 13 and t[11:13].isdigit() else 0
                by_hour[x["location"]][hh] += 1
                progs[x["exe"]] = progs.get(x["exe"], 0) + 1
                d = _dirof(x["exePath"])
                if d:
                    dirs[d] = dirs.get(d, 0) + 1
                events.append({"exe": x["exe"], "t": t, "hour": hh, "location": x["location"],
                               "runCount": x["runCount"], "volume": x["volumeLabel"],
                               "path": x["exePath"], "filename": x["filename"]})
        events.sort(key=lambda z: z["t"])
        top = lambda d, kn: sorted(({kn: k, "n": v} for k, v in d.items()), key=lambda z: z["n"], reverse=True)
        return json.dumps({"events": events, "byHour": by_hour,
                           "byProgram": top(progs, "exe")[:8], "topDirs": top(dirs, "dir")[:8]})


    def _raw_row(self, table: str, key_col: str, key):
        """The verbatim source row behind a detail panel. See raw_record.py."""
        rows = self._query('SELECT * FROM "%s" WHERE "%s" = ? LIMIT 1' % (table, key_col), (key,))
        return _raw(rows[0], table) if rows else None

    @pyqtSlot(str, result=str)
    def getPrefetchProgramDetail(self, args_json: str) -> str:
        args = _loads(args_json)
        fn = args.get("filename")
        rec = next((x for x in self._all() if x["filename"] == fn), None)
        if not rec:
            return json.dumps({})
        # flag loaded resources outside System / Program Files as "unusual"
        res = []
        for r in rec["resources"]:
            up = r.upper()
            unusual = not ("\\WINDOWS\\" in up or "\\PROGRAM FILES" in up)
            res.append({"path": r, "unusual": unusual})
        return json.dumps({
            "exe": rec["exe"], "exePath": rec["exePath"], "hash": rec["hash"],
            "runCount": rec["runCount"], "location": rec["location"], "runTimes": rec["runTimes"],
            "volume": {"label": rec["volumeLabel"], "serial": rec["volumeSerial"], "removable": rec["removable"]},
            "pf": {"created": rec["pfCreated"], "modified": rec["pfModified"], "accessed": rec["pfAccessed"]},
            "resources": res, "directories": rec["directories"],
            "unusualCount": sum(1 for r in res if r["unusual"]),
            # Everything the parser stored for this program, under the curated
            # reading above - so "the panel does not show it" and "the artifact
            # does not record it" stop looking the same.
            "raw": self._raw_row("prefetch_data", "filename", fn),
        })


def _dirof(path: str) -> str:
    p = str(path or "").replace("/", "\\").rstrip("\\")
    return p[:p.rfind("\\")] if "\\" in p else ""


def _loads(s):
    try:
        return json.loads(s or "{}")
    except Exception:
        return {}
