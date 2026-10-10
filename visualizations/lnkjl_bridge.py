"""QWebChannel bridge for the LNK + Jump Lists ("opened files") dashboard.

Combines three shell-activity artifacts - LNK shortcuts, Automatic jump lists,
Custom jump lists - into one unified "a user opened this file/app" record set,
read from the case's LnkDB.db. Same shape as the SRUM / MFT-USN bridges.

Two schemas are unified (drift): OLD case DBs use `JLCE` (LNK + Automatic split by
an `Artifact` column) + `Custom_JLCE`; the CURRENT parser writes `LNK_Files` /
`Automatic_JumpLists` / `Custom_JumpLists`. The data is small, so every slot fetches
the unified records once and aggregates in Python; `SELECT *` + `.get()` keeps it
tolerant of whichever columns a build wrote.
"""

import os
import json

from visualizations.timeseries import (axis_range as _axis_range,
                                       densify as _densify,
                                       densify_series as _densify_series)

from visualizations.insights import (insight as _insight,
                                       plain as _plain,
                                       subject as _subject)
from visualizations.raw_record import source_records as _source_records
import time
import sqlite3
import logging
from typing import List, Dict, Optional

from PyQt5.QtCore import QObject, pyqtSlot

logger = logging.getLogger(__name__)

LNK_DB = "LnkDB.db"
SOURCES = ("lnk", "auto", "custom")


def _base(path: str) -> str:
    p = str(path or "").replace("/", "\\").rstrip("\\")
    return p[p.rfind("\\") + 1:] if "\\" in p else p


def _dir(path: str) -> str:
    p = str(path or "").replace("/", "\\").rstrip("\\")
    return p[:p.rfind("\\")] if "\\" in p else ""


def _ext(path: str) -> str:
    name = _base(path)
    if "." not in name or name.startswith("."):
        return ""
    return name.rsplit(".", 1)[-1].lower()[:12]


def _real_time(t: str) -> bool:
    return bool(t) and t >= "2000-01-01"


try:
    from visualizations.async_bridge import AsyncBridge
except ImportError:                                  # run from its own folder
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    from visualizations.async_bridge import AsyncBridge


# AsyncBridge (a QObject): the page calls its slots through callAsync, off
# the GUI thread, so the window keeps painting while a query runs.
class LnkJlBridge(AsyncBridge):
    """Read-only data source for the LNK/Jump-List dashboard."""

    def __init__(self, case_directory: str, parent=None):
        super().__init__(parent)
        self.case_dir = case_directory or ""
        self._records_cache = None
        logger.info(f"LnkJlBridge initialized with case dir: {case_directory}")

    # ---- db helpers -------------------------------------------------------
    def _db_path(self) -> Optional[str]:
        p = os.path.join(self.case_dir, LNK_DB)
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
                logger.error(f"LnkDB query error: {e}")
                return []
            except Exception as e:
                logger.error(f"LnkDB query failure: {e}")
                return []
        return []

    def _tables(self) -> set:
        return {r["name"] for r in self._query("SELECT name FROM sqlite_master WHERE type='table'")}

    # ---- the unifier ------------------------------------------------------
    def _unify(self, r: dict, source: str, table: str = "") -> dict:
        target = r.get("Local_Path") or ""
        app = r.get("AppDesc") or r.get("AppType") or r.get("AppID") or ""
        return {
            # The row behind this one, for the panel's Source records section.
            # A target is reached through several artifacts at once, so there is
            # no single row to show and no honest way to pick one.
            "_row": dict(r), "_table": table,
            "source": source,
            "target": target,
            "name": _base(target) if target else (r.get("Source_Name") or ""),
            "dir": _dir(target),
            "ext": _ext(target),
            "app": app if app and app != "Unknown" else "",
            "appType": r.get("AppType") or "",
            "appId": r.get("AppID") or "",
            "tAccess": r.get("Time_Access") or "",
            "tCreation": r.get("Time_Creation") or "",
            "tModification": r.get("Time_Modification") or "",
            "driveType": (r.get("Drive_Type") or r.get("Volume_Type") or "").strip(),
            "volumeLabel": (r.get("Volume_Label") or "").strip(),
            "volumeSerial": (r.get("Volume_Serial") or r.get("Drive_SN") or "").strip(),
            "netShare": (r.get("Network_Share_Name") or "").strip(),
            "sourceName": r.get("Source_Name") or "",
            "sourcePath": r.get("Source_Path") or "",
            "mftEntry": r.get("MFT_Entry_Number") or "",
            "tracker": r.get("Tracker_MAC") or "",
            "knownFolder": r.get("Known_Folder_GUID") or "",
            "args": r.get("Command_Line_Arguments") or "",
        }

    def _all_records(self) -> List[dict]:
        if self._records_cache is not None:
            return self._records_cache
        tabs = self._tables()
        out = []
        # NEW schema
        if "LNK_Files" in tabs:
            out += [self._unify(r, "lnk", "LNK_Files") for r in self._query("SELECT * FROM LNK_Files")]
        if "Automatic_JumpLists" in tabs:
            out += [self._unify(r, "auto", "Automatic_JumpLists") for r in self._query("SELECT * FROM Automatic_JumpLists")]
        if "Custom_JumpLists" in tabs:
            out += [self._unify(r, "custom", "Custom_JumpLists") for r in self._query("SELECT * FROM Custom_JumpLists")]
        # OLD schema (only if the new tables are absent)
        if "LNK_Files" not in tabs and "JLCE" in tabs:
            for r in self._query("SELECT * FROM JLCE"):
                art = (r.get("Artifact") or "").lower()
                out.append(self._unify(r, "lnk" if art == "lnk" else "auto", "JLCE"))
        if "Custom_JumpLists" not in tabs and "Custom_JLCE" in tabs:
            out += [self._unify(r, "custom", "Custom_JLCE") for r in self._query("SELECT * FROM Custom_JLCE")]
        self._records_cache = out
        return out

    def _filtered(self, args: dict) -> List[dict]:
        recs = self._all_records()
        start, end = args.get("start", ""), args.get("end", "")
        src = args.get("source", "")
        vol = args.get("volume", "")
        terms = [t.strip().lower() for t in (args.get("terms") or []) if t and t.strip()]
        mode = (args.get("mode", "or") or "or").lower()
        out = []
        for x in recs:
            d = x["tAccess"][:10]
            if start and (not d or d < start):
                continue
            if end and (not d or d > end):
                continue
            if src and x["source"] != src:
                continue
            if vol and x["volumeLabel"] != vol:
                continue
            if terms:
                hay = (x["target"] + " " + x["app"] + " " + x["volumeLabel"] + " " + x["name"]).lower()
                hit = [t in hay for t in terms]
                if (all(hit) if mode == "and" else any(hit)) is False:
                    continue
            out.append(x)
        return out

    def _has_data(self) -> bool:
        return bool(self._tables() & {"JLCE", "Custom_JLCE", "LNK_Files", "Automatic_JumpLists", "Custom_JumpLists"})

    # ---- slots ------------------------------------------------------------
    @pyqtSlot(result=str)
    def getLnkBounds(self) -> str:
        if not self._has_data():
            return json.dumps({"hasData": False})
        recs = self._all_records()
        days = [x["tAccess"][:10] for x in recs if _real_time(x["tAccess"])]
        counts = {s: sum(1 for x in recs if x["source"] == s) for s in SOURCES}
        vols = sorted({x["volumeLabel"] for x in recs if x["volumeLabel"]})
        return json.dumps({
            "hasData": True,
            "minDate": min(days) if days else None,
            "maxDate": max(days) if days else None,
            "counts": counts, "volumes": vols,
            "hasApp": any(x["app"] for x in recs),
        })

    @pyqtSlot(str, result=str)
    def getLnkTimeline(self, args_json: str) -> str:
        args = _loads(args_json)
        recs = self._filtered(args)
        per = {s: {} for s in SOURCES}
        combined = {}
        for x in recs:
            if not _real_time(x["tAccess"]):
                continue
            d = x["tAccess"][:10]
            per[x["source"]][d] = per[x["source"]].get(d, 0) + 1
            combined[d] = combined.get(d, 0) + 1
        # Only days that HAD activity come out of a GROUP BY, which turns the
        # strip into an ordinal list of active days rather than a time axis -
        # a quiet stretch closes up and vanishes. Fill every day in the range.
        # A cell is always one day; a range too long to fit scrolls instead of
        # changing what a cell means. See timeseries.py.
        start, end = _axis_range(args, combined)
        sources = _densify_series(per, start, end)
        combined_rows = _densify(combined, start, end)
        return json.dumps({"sources": sources, "combined": combined_rows})

    @pyqtSlot(str, result=str)
    def getLnkOverview(self, args_json: str) -> str:
        args = _loads(args_json)
        recs = self._filtered(args)
        by_source = {s: sum(1 for x in recs if x["source"] == s) for s in SOURCES}
        apps, dirs, exts = {}, {}, {}
        vols = {}
        removable = network = temp_dl = 0
        # Who matched, not just how many - see visualizations/insights.py.
        removable_subj, network_subj, temp_subj = [], [], []
        targets = set()
        for x in recs:
            if x["target"]:
                targets.add(x["target"].lower())
            if x["app"]:   # only jump-list records carry an app; LNK files do not
                apps[x["app"]] = apps.get(x["app"], 0) + 1
            if x["dir"]:
                dirs[x["dir"]] = dirs.get(x["dir"], 0) + 1
            e = x["ext"] or "(none)"
            exts[e] = exts.get(e, 0) + 1
            key = (x["driveType"] or "unknown", x["volumeLabel"], x["volumeSerial"])
            vols[key] = vols.get(key, 0) + 1
            dt = x["driveType"].upper()
            if "REMOV" in dt:
                removable += 1
                removable_subj.append(_subject(
                    x["target"] or x["name"], x["target"],
                    x["volumeLabel"] or "unnamed volume"))
            if "REMOTE" in dt or "NETWORK" in dt or x["netShare"]:
                network += 1
                network_subj.append(_subject(
                    x["target"] or x["name"], x["target"],
                    x["netShare"] or dt.lower() or "network"))
            tl = x["target"].lower()
            if "\\temp\\" in tl or "\\downloads\\" in tl or "\\appdata\\" in tl:
                temp_dl += 1
                temp_subj.append(_subject(
                    x["target"], x["target"], x["app"] or x["source"]))
        top = lambda d, kn: sorted(({kn: k, "n": v} for k, v in d.items()), key=lambda z: z["n"], reverse=True)
        volumes = sorted(({"driveType": k[0], "label": k[1], "serial": k[2], "n": v} for k, v in vols.items()),
                         key=lambda z: z["n"], reverse=True)[:12]
        # external volumes = anything that isn't the system 'OS' fixed disk / blank
        external = sum(1 for v in volumes if v["label"] and v["label"].upper() != "OS")
        return json.dumps({
            "totals": {"records": len(recs), "targets": len(targets),
                       "lnk": by_source["lnk"], "auto": by_source["auto"], "custom": by_source["custom"]},
            "byApp": top(apps, "app")[:12],
            "topDirs": top(dirs, "dir")[:12],
            "topExts": top(exts, "ext")[:12],
            "volumes": volumes,
            "insights": {
                "removable": _insight(removable, removable_subj),
                "network": _insight(network, network_subj),
                "tempDownloads": _insight(temp_dl, temp_subj),
                # A count of distinct volumes, not of records.
                "externalVolumes": _plain(external),
            },
        })

    @pyqtSlot(str, result=str)
    def getLnkDayDetail(self, args_json: str) -> str:
        args = _loads(args_json)
        day = args.get("day")
        if not day:
            return json.dumps({"events": [], "byHour": {}, "byApp": [], "topDirs": [], "topExts": []})
        recs = [x for x in self._filtered(args) if x["tAccess"][:10] == day[:10]]
        by_hour = {s: [0] * 24 for s in SOURCES}
        apps, dirs, exts = {}, {}, {}
        events = []
        for x in sorted(recs, key=lambda z: z["tAccess"]):
            t = x["tAccess"]
            hh = int(t[11:13]) if len(t) >= 13 and t[11:13].isdigit() else 0
            by_hour[x["source"]][hh] += 1
            if x["app"]:
                apps[x["app"]] = apps.get(x["app"], 0) + 1
            if x["dir"]:
                dirs[x["dir"]] = dirs.get(x["dir"], 0) + 1
            e = x["ext"] or "(none)"; exts[e] = exts.get(e, 0) + 1
            events.append({"source": x["source"], "app": x["app"], "target": x["target"],
                           "name": x["name"], "t": t, "hour": hh,
                           "volume": x["volumeLabel"], "driveType": x["driveType"]})
        top = lambda d, kn: sorted(({kn: k, "n": v} for k, v in d.items()), key=lambda z: z["n"], reverse=True)
        return json.dumps({"events": events, "byHour": by_hour,
                           "byApp": top(apps, "app")[:8], "topDirs": top(dirs, "dir")[:8], "topExts": top(exts, "ext")[:8]})

    @pyqtSlot(str, result=str)
    def getLnkTargetDetail(self, args_json: str) -> str:
        args = _loads(args_json)
        target = (args.get("target") or "").lower()
        if not target:
            return json.dumps({})
        recs = [x for x in self._all_records() if x["target"].lower() == target]
        if not recs:
            return json.dumps({})
        head = recs[0]
        refs = [{"source": x["source"], "app": x["app"], "sourceName": x["sourceName"],
                 "tAccess": x["tAccess"], "tCreation": x["tCreation"], "tModification": x["tModification"],
                 "volume": x["volumeLabel"], "driveType": x["driveType"], "serial": x["volumeSerial"]}
                for x in recs]
        return json.dumps({
            "target": head["target"], "name": head["name"], "ext": head["ext"], "dir": head["dir"],
            "sources": sorted({x["source"] for x in recs}),
            "mace": {"accessed": head["tAccess"], "created": head["tCreation"], "modified": head["tModification"]},
            "volume": {"type": head["driveType"], "label": head["volumeLabel"], "serial": head["volumeSerial"]},
            "mftEntry": head["mftEntry"], "tracker": head["tracker"], "knownFolder": head["knownFolder"],
            "args": head["args"], "refs": refs,
            # Every row this target was reached through, verbatim. There is no
            # single source row - LNK_Files, Automatic_JumpLists,
            # Custom_JumpLists and JLCE can all carry the same target - so the
            # panel shows all of them rather than picking one.
            "records": _source_records(
                [(x.get("_table") or "", x.get("_row") or {}) for x in recs],
                label_of=lambda it: it[0]),
        })


def _loads(s):
    try:
        return json.loads(s or "{}")
    except Exception:
        return {}
