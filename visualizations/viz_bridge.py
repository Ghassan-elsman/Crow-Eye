"""QWebChannel bridge for the visualization frontend.

Exposes the parsed SRUM data to the React chart app as JSON over QWebChannel.
Every method is a read-only `@pyqtSlot(... result=str)` returning a JSON string;
the React side calls them as `window.bridge.method(argsJson)`.

Modelled on `timeline/timeline_bridge.py` (the `_get_db_path` / `_query_db`
helpers are the same shape), scoped to what the SRUM contribution chart needs.
All metrics are read from the stored `timestamp` (event time) and every query is
parameterised - search terms are never concatenated into SQL.
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
from typing import List, Dict, Optional, Tuple

from PyQt5.QtCore import QObject, pyqtSlot

logger = logging.getLogger(__name__)

# provider key -> (database, table). One database, five provider tables.
SRUM_DB = "srum_data.db"
SRUM_TABLES = {
    "application_usage": "srum_application_usage",
    "network_data": "srum_network_data_usage",
    "network_connectivity": "srum_network_connectivity",
    "energy": "srum_energy_usage",
    "app_timeline": "srum_app_timeline",
}
# Columns a free-text search matches against, per table (only ones that exist on
# every provider table).
SEARCH_FIELDS = ("app_name", "app_path", "user_name", "user_sid")



def _bytes(n) -> str:
    """A byte count for an insight note. The exact figure is on the card."""
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024
    return "%.1f GB" % n


try:
    from visualizations.async_bridge import AsyncBridge
except ImportError:                                  # run from its own folder
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    from visualizations.async_bridge import AsyncBridge

from visualizations.async_bridge import cached_slot


def _srum_db(bridge):
    return [bridge._get_db_path(SRUM_DB)]


# AsyncBridge (a QObject): the page calls its slots through callAsync, off
# the GUI thread, so the window keeps painting while a query runs.
class VizBridge(AsyncBridge):
    """Read-only data source for the SRUM contribution chart."""

    def __init__(self, case_directory: str, parent=None):
        super().__init__(parent)
        self.case_dir = case_directory or ""
        logger.info(f"VizBridge initialized with case dir: {case_directory}")

    # ---- low-level db helpers (same shape as TimelineBridge) --------------
    def _get_db_path(self, db_name: str) -> Optional[str]:
        path = os.path.join(self.case_dir, db_name)
        return path if os.path.exists(path) else None

    def _query_db(self, db_name: str, sql: str, params: tuple = ()) -> List[Dict]:
        db_path = self._get_db_path(db_name)
        if not db_path:
            logger.warning(f"Database not found: {db_name}")
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
                    time.sleep(delay)
                    delay *= 2
                    continue
                logger.error(f"Query error on {db_name}: {e}")
                return []
            except Exception as e:
                logger.error(f"Critical query failure on {db_name}: {e}")
                return []
        return []

    def _table_exists(self, table: str) -> bool:
        rows = self._query_db(
            SRUM_DB,
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,))
        return len(rows) > 0

    def _table_columns(self, table: str) -> set:
        rows = self._query_db(SRUM_DB, f"PRAGMA table_info({table})")
        return {r["name"] for r in rows}

    # ---- search + range filters -------------------------------------------
    def _search_clause(self, table: str, terms: List[str], mode: str) -> Tuple[str, list]:
        """Build a parameterised search clause over the searchable columns.

        Each term must (AND) or may (OR) appear in any of the table's searchable
        columns. Empty terms produce no clause.
        """
        terms = [t.strip() for t in (terms or []) if t and t.strip()]
        if not terms:
            return "", []
        cols = [c for c in SEARCH_FIELDS if c in self._table_columns(table)]
        if not cols:
            return "", []
        per_term = []
        params: list = []
        for term in terms:
            ors = " OR ".join(f"{c} LIKE ?" for c in cols)
            per_term.append("(" + ors + ")")
            params.extend([f"%{term}%"] * len(cols))
        joiner = " AND " if (mode or "or").lower() == "and" else " OR "
        return "(" + joiner.join(per_term) + ")", params

    def _range_clause(self, start: str, end: str) -> Tuple[str, list]:
        """A range on the raw `timestamp` text, so its index is used.

        `date(timestamp) >= date(?)` wrapped the column in a function and
        hid it from idx_*_timestamp: the planner walked every row of a 457k-row
        table for one day's top apps (8.9 s). The stored text is
        'YYYY-MM-DD HH:MM:SS', which sorts like the time it names.
        """
        clause, params = [], []
        if start:
            clause.append("timestamp >= date(?)")
            params.append(start)
        if end:
            clause.append("timestamp < date(?, '+1 day')")
            params.append(end)
        return (" AND ".join(clause), params)

    def _where(self, table: str, args: dict) -> Tuple[str, list]:
        """Combine the range and search filters into a WHERE fragment."""
        parts, params = [], []
        rc, rp = self._range_clause(args.get("start", ""), args.get("end", ""))
        if rc:
            parts.append(rc)
            params.extend(rp)
        sc, sp = self._search_clause(table, args.get("terms", []), args.get("mode", "or"))
        if sc:
            parts.append(sc)
            params.extend(sp)
        return ((" WHERE " + " AND ".join(parts)) if parts else "", params)

    # ---- slots -------------------------------------------------------------
    @pyqtSlot(result=str)
    def getSrumBounds(self) -> str:
        """Date range and which providers hold data, to size the calendar."""
        if not self._get_db_path(SRUM_DB):
            return json.dumps({"hasData": False, "reason": "no_srum_db"})
        providers = {}
        gmin = gmax = None
        for key, table in SRUM_TABLES.items():
            if not self._table_exists(table):
                providers[key] = 0
                continue
            row = self._query_db(
                SRUM_DB,
                # date(MIN(...)), not MIN(date(...)): the bare column lets the
                # timestamp index answer the minimum and maximum.
                f"SELECT COUNT(*) c, date(MIN(timestamp)) lo, date(MAX(timestamp)) hi FROM {table}")
            row = row[0] if row else {}
            providers[key] = row.get("c", 0) or 0
            lo, hi = row.get("lo"), row.get("hi")
            if lo and (gmin is None or lo < gmin):
                gmin = lo
            if hi and (gmax is None or hi > gmax):
                gmax = hi
        return json.dumps({
            "hasData": bool(gmin),
            "minDate": gmin, "maxDate": gmax,
            "providers": providers,
        })

    @pyqtSlot(str, result=str)
    @cached_slot("getSrumHeatmaps", _srum_db)
    def getSrumHeatmaps(self, args_json: str) -> str:
        """Per-provider daily activity for the five heat-maps.

        `args_json`: {start, end, terms[], mode}. Each provider's day value is its
        record count (how much that provider recorded that day), self-normalised.
        Returns {providers: {key: {days:[{day,value}], max}}, combined:[{day,value}]}.
        `combined` sums all providers per day and drives the default selected day.
        """
        try:
            args = json.loads(args_json or "{}")
        except Exception:
            args = {}
        combined: Dict[str, int] = {}
        per_raw: Dict[str, Dict[str, int]] = {}
        for key, table in SRUM_TABLES.items():
            raw: Dict[str, int] = {}
            if self._table_exists(table):
                where, params = self._where(table, args)
                for r in self._query_db(SRUM_DB,
                        f"SELECT date(timestamp) d, COUNT(*) c FROM {table}{where} GROUP BY d",
                        tuple(params)):
                    if not r["d"]:
                        continue
                    v = r["c"] or 0
                    raw[r["d"]] = raw.get(r["d"], 0) + v
                    combined[r["d"]] = combined.get(r["d"], 0) + v
            per_raw[key] = raw
        # Only days that HAD activity come out of a GROUP BY, which turns the
        # strip into an ordinal list of active days rather than a time axis -
        # a quiet stretch closes up and vanishes. Fill every day in the range.
        # A cell is always one day; a range too long to fit scrolls instead of
        # changing what a cell means. See timeseries.py.
        start, end = _axis_range(args, combined)
        providers = _densify_series(per_raw, start, end)
        combined_list = _densify(combined, start, end)
        return json.dumps({"providers": providers, "combined": combined_list})

    @pyqtSlot(str, result=str)
    @cached_slot("getSrumDayDetail", _srum_db)
    def getSrumDayDetail(self, args_json: str) -> str:
        """Drill-down for one day: hourly execution, top apps, per-provider
        counts and a presence summary. `args_json`: {day, terms[], mode}."""
        try:
            args = json.loads(args_json or "{}")
        except Exception:
            args = {}
        day = args.get("day", "")
        if not day:
            return json.dumps({"day": "", "hourly": [0] * 24, "topApps": [],
                               "perProvider": {}, "presence": {}})
        # scope filters to this day
        # scope filters to this day
        day_args = dict(args)
        day_args["start"] = day_args["end"] = day

        t = SRUM_TABLES["application_usage"]
        hourly = [0] * 24
        top_apps = []
        if self._table_exists(t):
            where, params = self._where(t, day_args)
            for r in self._query_db(SRUM_DB,
                    f"SELECT CAST(strftime('%H', timestamp) AS INTEGER) h, COUNT(*) c "
                    f"FROM {t}{where} GROUP BY h", tuple(params)):
                if r["h"] is not None and 0 <= r["h"] < 24:
                    hourly[r["h"]] = r["c"] or 0
            for r in self._query_db(SRUM_DB,
                    f"SELECT app_name, COUNT(*) windows, "
                    f"SUM(COALESCE(foreground_cycle_time,0)+COALESCE(background_cycle_time,0)) cycles "
                    f"FROM {t}{where} GROUP BY app_name ORDER BY windows DESC LIMIT 15",
                    tuple(params)):
                top_apps.append({"app": r["app_name"] or "(unknown)",
                                 "windows": r["windows"] or 0,
                                 "cycles": r["cycles"] or 0})

        per_provider = {}
        for key, table in SRUM_TABLES.items():
            if not self._table_exists(table):
                continue
            where, params = self._where(table, day_args)
            row = self._query_db(SRUM_DB, f"SELECT COUNT(*) c FROM {table}{where}", tuple(params))
            per_provider[key] = (row[0]["c"] if row else 0) or 0

        presence = {"keyboard": 0, "mouse": 0, "focus": 0}
        t = SRUM_TABLES["app_timeline"]
        if self._table_exists(t):
            cols = self._table_columns(t)
            sel = ", ".join(
                f"SUM(COALESCE({c},0)) {n}" for n, c in
                (("keyboard", "keyboard_input_s"), ("mouse", "mouse_input_s"), ("focus", "in_focus_s"))
                if c in cols)
            if sel:
                where, params = self._where(t, day_args)
                row = self._query_db(SRUM_DB, f"SELECT {sel} FROM {t}{where}", tuple(params))
                if row:
                    for k in presence:
                        presence[k] = row[0].get(k, 0) or 0

        # Per-provider hourly records (for the stacked hour chart) and per-app
        # per-provider record counts (for the stacked top-apps chart).
        hourly_by_provider = {}
        app_counts = {}   # app -> {provider_key: count}
        for key, table in SRUM_TABLES.items():
            if not self._table_exists(table):
                continue
            where, params = self._where(table, day_args)
            hp = [0] * 24
            for r in self._query_db(SRUM_DB,
                    f"SELECT CAST(strftime('%H', timestamp) AS INTEGER) h, COUNT(*) c "
                    f"FROM {table}{where} GROUP BY h", tuple(params)):
                if r["h"] is not None and 0 <= r["h"] < 24:
                    hp[r["h"]] = r["c"] or 0
            hourly_by_provider[key] = hp
            for r in self._query_db(SRUM_DB,
                    f"SELECT app_name, COUNT(*) c FROM {table}{where} GROUP BY app_name", tuple(params)):
                a = app_counts.setdefault(r["app_name"] or "(unknown)", {})
                a[key] = r["c"] or 0
        top_by = sorted(app_counts.items(), key=lambda kv: sum(kv[1].values()), reverse=True)[:15]
        top_apps_by_provider = [{"app": a, "total": sum(c.values()), "counts": c} for a, c in top_by]

        return json.dumps({"day": day, "hourly": hourly, "topApps": top_apps,
                           "perProvider": per_provider, "presence": presence,
                           "hourlyByProvider": hourly_by_provider,
                           "topAppsByProvider": top_apps_by_provider})

    # ---- activity explorer -------------------------------------------------
    HOUR = "strftime('%Y-%m-%dT%H:00', timestamp)"

    def _merge_activity(self, args: dict, app: str = None, grain: str = "day"):
        """Join every provider on (app, user, bucket) into app-time records.

        `grain` is 'day' (date(timestamp)) for the overview - one bucket per day
        keeps the bubble chart light - or 'hour' for the per-app detail panel.
        Returns {key -> record} where record has app, user, hour (the bucket) and
        every metric. `app` scopes to a single application when given.
        """
        bucket = "date(timestamp)" if grain == "day" else self.HOUR
        records = {}

        def rec(row):
            app_name = row.get("app_name") or "(unknown)"
            sid = row.get("user_sid") or ""
            hour = row.get("hour")
            key = (app_name, sid, hour)
            r = records.get(key)
            if r is None:
                r = records[key] = {
                    "app": app_name, "user": row.get("user_name") or sid or "(unknown)",
                    "userSid": sid, "hour": hour,
                    "bytesSent": 0, "bytesReceived": 0, "cpu": 0, "disk": 0,
                    "battery": 0, "focusS": 0, "keyboardS": 0}
            return r

        def where_for(table):
            a = dict(args)
            if app is not None:
                a = dict(a)  # copy; add app filter below via extra clause
            w, p = self._where(table, a)
            if app is not None:
                clause = f"app_name = ?"
                w = (w + " AND " + clause) if w else (" WHERE " + clause)
                p = list(p) + [app]
            return w, tuple(p)

        t = SRUM_TABLES["application_usage"]
        if self._table_exists(t):
            cols = self._table_columns(t)
            cpu = "+".join(f"COALESCE({c},0)" for c in ("foreground_cycle_time", "background_cycle_time") if c in cols) or "0"
            disk = "+".join(f"COALESCE({c},0)" for c in
                            ("foreground_bytes_read", "foreground_bytes_written",
                             "background_bytes_read", "background_bytes_written") if c in cols) or "0"
            w, p = where_for(t)
            for row in self._query_db(SRUM_DB,
                    f"SELECT app_name, user_name, user_sid, {bucket} hour, "
                    f"SUM({cpu}) cpu, SUM({disk}) disk, COUNT(*) windows FROM {t}{w} "
                    f"GROUP BY app_name, user_sid, hour", p):
                r = rec(row); r["cpu"] += row["cpu"] or 0; r["disk"] += row["disk"] or 0

        t = SRUM_TABLES["network_data"]
        if self._table_exists(t):
            w, p = where_for(t)
            for row in self._query_db(SRUM_DB,
                    f"SELECT app_name, user_name, user_sid, {bucket} hour, "
                    f"SUM(COALESCE(bytes_sent,0)) sent, SUM(COALESCE(bytes_received,0)) recv "
                    f"FROM {t}{w} GROUP BY app_name, user_sid, hour", p):
                r = rec(row); r["bytesSent"] += row["sent"] or 0; r["bytesReceived"] += row["recv"] or 0

        t = SRUM_TABLES["energy"]
        if self._table_exists(t) and "charge_level" in self._table_columns(t):
            w, p = where_for(t)
            for row in self._query_db(SRUM_DB,
                    f"SELECT app_name, user_name, user_sid, {bucket} hour, "
                    f"AVG(COALESCE(charge_level,0)) battery FROM {t}{w} "
                    f"GROUP BY app_name, user_sid, hour", p):
                r = rec(row); r["battery"] = round(row["battery"] or 0, 1)

        t = SRUM_TABLES["app_timeline"]
        if self._table_exists(t):
            cols = self._table_columns(t)
            focus = "SUM(COALESCE(in_focus_s,0))" if "in_focus_s" in cols else "0"
            kbd = "SUM(COALESCE(keyboard_input_s,0))" if "keyboard_input_s" in cols else "0"
            w, p = where_for(t)
            for row in self._query_db(SRUM_DB,
                    f"SELECT app_name, user_name, user_sid, {bucket} hour, "
                    f"{focus} focus, {kbd} kbd FROM {t}{w} GROUP BY app_name, user_sid, hour", p):
                r = rec(row); r["focusS"] += row["focus"] or 0; r["keyboardS"] += row["kbd"] or 0

        return records

    @pyqtSlot(str, result=str)
    @cached_slot("getSrumDayActivity", _srum_db)
    def getSrumDayActivity(self, args_json: str) -> str:
        """App x hour points for ONE selected day - the lower dashboard section.

        `args_json`: {day, terms[], mode, topN}. Every point carries `h` (hour
        0-23) so the chart's X axis is the hours of that day. Capped to the day's
        top-N busiest apps. {day, apps[], users[], points[], ranges{app:{min,max}}}.
        """
        try:
            args = json.loads(args_json or "{}")
        except Exception:
            args = {}
        day = args.get("day", "")
        if not day:
            return json.dumps({"day": "", "apps": [], "users": [], "points": [], "ranges": {}})
        top_n = int(args.get("topN", 20) or 20)

        # scope filters to this day
        day_args = dict(args)
        day_args["start"] = day_args["end"] = day
        records = self._merge_activity(day_args, grain="hour")

        per_app = {}
        for r in records.values():
            a = per_app.setdefault(r["app"], {"hours": 0, "weight": 0})
            a["hours"] += 1
            a["weight"] += (r["bytesSent"] + r["bytesReceived"]) + r["cpu"]
        top_apps = [a for a, _ in sorted(
            per_app.items(), key=lambda kv: (kv[1]["hours"], kv[1]["weight"]), reverse=True)][:top_n]
        top_set = set(top_apps)

        points = []
        for r in records.values():
            if r["app"] not in top_set:
                continue
            try:
                r["h"] = int(str(r["hour"])[11:13])   # 'YYYY-MM-DDTHH:00' -> HH
            except Exception:
                r["h"] = 0
            points.append(r)
        users = sorted({r["user"] for r in points})
        ranges = {}
        for r in points:
            rng = ranges.setdefault(r["app"], {"min": r["h"], "max": r["h"]})
            rng["min"] = min(rng["min"], r["h"])
            rng["max"] = max(rng["max"], r["h"])
        return json.dumps({"day": day, "apps": top_apps, "users": users,
                           "points": points, "ranges": ranges})

    @pyqtSlot(str, result=str)
    @cached_slot("getSrumOverview", _srum_db)
    def getSrumOverview(self, args_json: str) -> str:
        """Range-wide overview for the right panel: totals, top apps, per-user
        split and per-provider record counts. {totals, topApps[], byUser[],
        providerTotals{}}."""
        try:
            args = json.loads(args_json or "{}")
        except Exception:
            args = {}

        records = self._merge_activity(args, grain="day")
        totals = {"bytesSent": 0, "bytesReceived": 0, "cpu": 0, "disk": 0,
                  "presenceSecs": 0, "apps": 0, "activeDays": 0}
        per_app, per_user, days = {}, {}, set()
        # `a["days"]` counts app-user-day rows, not distinct days, and it is what
        # orders topApps - so the insights keep their own day sets rather than
        # changing what that ordering means.
        app_days: Dict[str, set] = {}
        app_focus: Dict[str, float] = {}
        net_by_day = {}   # day -> {sent, received} for the Network-activity time chart
        for r in records.values():
            totals["bytesSent"] += r["bytesSent"]; totals["bytesReceived"] += r["bytesReceived"]
            totals["cpu"] += r["cpu"]; totals["disk"] += r["disk"]; totals["presenceSecs"] += r["focusS"]
            days.add(r["hour"])   # day bucket
            a = per_app.setdefault(r["app"], {"app": r["app"], "days": 0, "cpu": 0, "bytes": 0,
                                              "sent": 0, "received": 0})
            a["days"] += 1; a["cpu"] += r["cpu"]; a["bytes"] += r["bytesSent"] + r["bytesReceived"]
            a["sent"] += r["bytesSent"]; a["received"] += r["bytesReceived"]
            app_days.setdefault(r["app"], set()).add(r["hour"])
            app_focus[r["app"]] = app_focus.get(r["app"], 0) + r["focusS"]
            u = per_user.setdefault(r["user"], {"user": r["user"], "days": 0, "cpu": 0, "bytes": 0})
            u["days"] += 1; u["cpu"] += r["cpu"]; u["bytes"] += r["bytesSent"] + r["bytesReceived"]
            nb = net_by_day.setdefault(r["hour"], {"day": r["hour"], "sent": 0, "received": 0})
            nb["sent"] += r["bytesSent"]; nb["received"] += r["bytesReceived"]
        totals["apps"] = len(per_app)
        totals["activeDays"] = len(days)
        # SRUM records foreground time for only a fraction of the applications it
        # records at all - 26 of 890 on the case this was measured against - so
        # the card states the coverage instead of letting a missing focus time
        # read as "this ran in the background".
        totals["appsWithFocus"] = sum(1 for v in app_focus.values() if v > 0)

        top_apps = sorted(per_app.values(), key=lambda a: (a["days"], a["bytes"] + a["cpu"]), reverse=True)[:12]
        by_user = sorted(per_user.values(), key=lambda u: u["bytes"] + u["cpu"], reverse=True)[:8]

        # Network activity: per-day sent/received over the range, and the top network apps.
        network_by_day = sorted(net_by_day.values(), key=lambda d: d["day"])
        top_network_apps = sorted(
            ({"app": a["app"], "sent": a["sent"], "received": a["received"]} for a in per_app.values()),
            key=lambda a: a["sent"] + a["received"], reverse=True)[:6]

        # Per-provider record counts, overall + grouped by app and by user, so the
        # overview bars can stack by provider (provider = colour everywhere).
        provider_totals = {}
        app_counts, user_counts = {}, {}
        for key, table in SRUM_TABLES.items():
            if not self._table_exists(table):
                provider_totals[key] = 0
                continue
            where, params = self._where(table, args)
            row = self._query_db(SRUM_DB, f"SELECT COUNT(*) c FROM {table}{where}", tuple(params))
            provider_totals[key] = (row[0]["c"] if row else 0) or 0
            for r in self._query_db(SRUM_DB,
                    f"SELECT app_name a, COUNT(*) c FROM {table}{where} GROUP BY app_name", tuple(params)):
                app_counts.setdefault(r["a"] or "(unknown)", {})[key] = r["c"] or 0
            for r in self._query_db(SRUM_DB,
                    f"SELECT user_name u, COUNT(*) c FROM {table}{where} GROUP BY user_name", tuple(params)):
                user_counts.setdefault(r["u"] or "(unknown)", {})[key] = r["c"] or 0
        for a in top_apps:
            a["counts"] = app_counts.get(a["app"], {})
        for u in by_user:
            u["counts"] = user_counts.get(u["user"], {})

        return json.dumps({"totals": totals, "topApps": top_apps,
                           "byUser": by_user, "providerTotals": provider_totals,
                           "networkByDay": network_by_day, "topNetworkApps": top_network_apps,
                           "insights": self._srum_insights(per_app, app_days, per_user)})

    # The insight thresholds. A ratio alone flags a one-packet process, so the
    # floor is what keeps the skew list to things that actually moved data: 10
    # applications on the case this was measured against, out of 295 that used
    # the network at all.
    SKEW_RATIO = 4
    SKEW_FLOOR = 1 << 20          # 1 MiB sent

    def _srum_insights(self, per_app, app_days, per_user) -> dict:
        """The Insights card.

        SRUM is a resource ledger, so its insights are about volume and
        recurrence rather than location - there is no path column to judge.

        One shape that was planned and dropped: *network traffic with no
        foreground time*. SRUM's foreground time comes from one provider that
        covers a small slice of what the others record - 26 applications of 890
        on the case this was written against - so the rule flagged 285 of the
        295 network applications, including Chrome. A tile that flags almost
        everything is not an insight, and `totals.appsWithFocus` states that
        coverage directly instead.
        """
        skew = []
        for a in sorted(per_app.values(), key=lambda x: x["sent"], reverse=True):
            if a["sent"] >= self.SKEW_FLOOR and a["sent"] > self.SKEW_RATIO * max(a["received"], 1):
                skew.append(_subject(
                    a["app"], a["app"],
                    "sent %s, received %s" % (_bytes(a["sent"]), _bytes(a["received"]))))

        once = []
        for app, dayset in sorted(app_days.items()):
            if len(dayset) == 1:
                once.append(_subject(app, app, "only on " + next(iter(dayset))))

        busiest = max(app_days.items(), key=lambda kv: len(kv[1]), default=(None, ()))
        return {
            "netSkew": _insight(len(skew), skew),
            "oneDay": _insight(len(once), once),
            # Measurements, with no record set behind them.
            "busiestApp": _plain(len(busiest[1])),
            "users": _plain(len(per_user)),
        }

    @pyqtSlot(str, result=str)
    @cached_slot("getSrumAppDetail", _srum_db)
    def getSrumAppDetail(self, args_json: str) -> str:
        """Everything about one clicked app: per-hour series, per-user split,
        totals and a share-of-total resource radar. {app, hourly[], byUser[],
        totals{}, radar{}}."""
        try:
            args = json.loads(args_json or "{}")
        except Exception:
            args = {}
        app = args.get("app", "")
        if not app:
            return json.dumps({"app": "", "hourly": [], "byUser": [], "totals": {}, "radar": {}})

        records = self._merge_activity(args, app=app, grain="hour")
        hourly = sorted(records.values(), key=lambda r: r["hour"])

        totals = {"bytesSent": 0, "bytesReceived": 0, "cpu": 0, "disk": 0,
                  "focusS": 0, "keyboardS": 0, "hours": len(hourly)}
        by_user = {}
        for r in hourly:
            for k in ("bytesSent", "bytesReceived", "cpu", "disk", "focusS", "keyboardS"):
                totals[k] += r[k]
            u = by_user.setdefault(r["user"], {"user": r["user"], "hours": 0, "cpu": 0, "bytes": 0})
            u["hours"] += 1
            u["cpu"] += r["cpu"]
            u["bytes"] += r["bytesSent"] + r["bytesReceived"]
        totals["first"] = hourly[0]["hour"] if hourly else None
        totals["last"] = hourly[-1]["hour"] if hourly else None
        by_user = sorted(by_user.values(), key=lambda u: u["bytes"] + u["cpu"], reverse=True)

        # radar = this app's share of the total across all apps (0..100 per axis)
        allrec = self._merge_activity(args)
        gtot = {"cpu": 0, "disk": 0, "netOut": 0, "netIn": 0, "presence": 0}
        for r in allrec.values():
            gtot["cpu"] += r["cpu"]; gtot["disk"] += r["disk"]
            gtot["netOut"] += r["bytesSent"]; gtot["netIn"] += r["bytesReceived"]
            gtot["presence"] += r["focusS"]
        atot = {"cpu": totals["cpu"], "disk": totals["disk"],
                "netOut": totals["bytesSent"], "netIn": totals["bytesReceived"],
                "presence": totals["focusS"]}
        radar = {k: round(100 * atot[k] / gtot[k], 1) if gtot[k] else 0 for k in gtot}

        return json.dumps({"app": app, "hourly": hourly, "byUser": by_user,
                           "totals": totals, "radar": radar,
                           "records": self._app_source_records(app, args)})

    def _app_source_records(self, app: str, args: dict) -> dict:
        """Every SRUM row this app's profile was built from.

        There is no single source row: an application is whatever the five
        providers recorded about it, joined on (app, user, hour). So the panel
        shows the rows themselves, newest first, capped - a busy app can have
        thousands and the point is to let an analyst check the reading, not to
        push the table through the QWebChannel.
        """
        rows, total = [], 0
        for key, table in SRUM_TABLES.items():
            if not self._table_exists(table):
                continue
            where, params = self._where(table, args)
            glue = " AND " if where else " WHERE "
            scoped = f"FROM {table}{where}{glue}app_name=?"
            p = tuple(params) + (app,)
            # The real total, counted rather than inferred from what was
            # fetched - "showing 40 of 600" where 600 was itself a LIMIT is
            # still a wrong number on screen.
            n = self._query_db(SRUM_DB, f"SELECT COUNT(*) c {scoped}", p)
            total += (n[0]["c"] if n else 0) or 0
            for r in self._query_db(
                    SRUM_DB, f"SELECT * {scoped} ORDER BY timestamp DESC LIMIT 60", p):
                rows.append((table, dict(r)))
        rows.sort(key=lambda tr: str(tr[1].get("timestamp") or ""), reverse=True)
        return _source_records(rows, label_of=lambda it: it[0], total=total)
