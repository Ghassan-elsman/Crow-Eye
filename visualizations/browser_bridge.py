"""QWebChannel bridge for the browser-forensics dashboard.

Exposes `browser_analysis.db` to the React chart app as JSON over QWebChannel.
Every method is a read-only `@pyqtSlot(... result=str)` returning a JSON string;
the React side calls them as `window.bridge.method(argsJson)`.

Same shape as `viz_bridge.py` (SRUM) rather than `shellitems_bridge.py`: browser
history, cache and cookies run to tens of thousands of rows, so every slot
aggregates in SQL with a parameterised WHERE instead of reading the tables into
Python first.

Five ACTIVITIES are the colour language of the dashboard - visits, searches,
downloads, cookies, cache - and each is unioned from its Chromium and Gecko
tables so one strip means the same thing whichever engine produced it.

DOMAIN is the pivot, the way the program is for Prefetch: `_domain()` reduces
every URL to a host so visits, cookies, cache, credentials and downloads for one
site line up in the detail panel.

Timestamps are stored by the parser as `'%Y-%m-%d %H:%M:%S'` UTC strings
(`utils.time_utils.format_forensic_timestamp`), which SQLite's `date()` and
`strftime()` read directly - there is no epoch conversion anywhere here.

Secrets are never returned. `password_encrypted_b64`, cookie values and autofill
values stay in the database; the parser deliberately preserves rather than
decrypts, and a chart must not undo that.
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

BROWSER_DB = "browser_analysis.db"

# activity key -> list of (table, time column, url column). Two entries where
# Chromium and Gecko keep the same evidence in differently named tables; the
# bridge unions them so the dashboard shows one "visits" strip, not two.
ACTIVITY_SOURCES: Dict[str, List[Tuple[str, str, str]]] = {
    "visits": [
        ("browser_history", "visit_time", "url"),
        ("browser_gecko_history", "visit_time", "url"),
    ],
    "searches": [
        ("browser_shortcuts", "last_access_time", "url"),
    ],
    "downloads": [
        ("browser_downloads", "start_time", "source_url"),
        ("browser_gecko_downloads", "start_time", "url"),
    ],
    "cookies": [
        ("browser_cookies", "creation_time", "host_key"),
        ("browser_gecko_cookies", "creation_time", "host"),
    ],
    "cache": [
        ("browser_cache", "response_time", "url"),
        ("browser_service_worker", "response_time", "resource_url"),
    ],
}

ACTIVITY_ORDER = ["visits", "searches", "downloads", "cookies", "cache"]

# Columns a free-text search matches against. Not every table has every one -
# `_search_clause` keeps only those that exist on the table being queried.
SEARCH_FIELDS = ("url", "title", "source_url", "host_key", "host", "text",
                 "target_path", "resource_url", "origin_url")

# Columns the day's event list may show as a label, in preference order. Kept
# deliberately short: `browser_cookies.value`, `browser_autofill.value` and
# `browser_credentials.password_encrypted_b64` must never reach a chart, so no
# generic "first text column" rule is used here.
EVENT_LABEL_FIELDS = ("title", "text", "target_path")

# How many individual events one day may send to the front end. A busy day is
# ~1,600 rows; the cap stops a pathological day from freezing the dialog, and
# the UI is told the true total so it can say what it is not showing.
DAY_EVENT_CAP = 2000

# Provenance columns every table carries, used for the browser/profile filters.
PROV_BROWSER = "browser"
PROV_PROFILE = "profile"


try:
    from visualizations.async_bridge import AsyncBridge
except ImportError:                                  # run from its own folder
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    from visualizations.async_bridge import AsyncBridge

from visualizations.async_bridge import cached_slot


def _browser_db(bridge):
    return [bridge._get_db_path(BROWSER_DB)]


# AsyncBridge (a QObject): the page calls its slots through callAsync, off
# the GUI thread, so the window keeps painting while a query runs.
class BrowserBridge(AsyncBridge):
    """Read-only data source for the browser-forensics dashboard."""

    def __init__(self, case_directory: str, parent=None):
        super().__init__(parent)
        self.case_dir = case_directory or ""
        self._col_cache: Dict[str, set] = {}
        self._exists_cache: Dict[str, bool] = {}
        logger.info(f"BrowserBridge initialized with case dir: {case_directory}")

    # ---- low-level db helpers (same shape as VizBridge) --------------------
    def _get_db_path(self, db_name: str) -> Optional[str]:
        path = os.path.join(self.case_dir, db_name)
        return path if os.path.exists(path) else None

    def _query_db(self, sql: str, params: tuple = ()) -> List[Dict]:
        db_path = self._get_db_path(BROWSER_DB)
        if not db_path:
            logger.warning(f"Database not found: {BROWSER_DB}")
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
                logger.error(f"Query error on {BROWSER_DB}: {e}")
                return []
            except Exception as e:
                logger.error(f"Critical query failure on {BROWSER_DB}: {e}")
                return []
        return []

    def _table_exists(self, table: str) -> bool:
        # Cached like _table_columns: every query of every slot asked again,
        # one connection each (91 connections to open the dashboard).
        if table not in self._exists_cache:
            rows = self._query_db(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
            self._exists_cache[table] = len(rows) > 0
        return self._exists_cache[table]

    def _table_columns(self, table: str) -> set:
        """Columns of `table`, cached.

        Every slot asks this repeatedly and the answer cannot change while a
        dialog is open, so the PRAGMA runs once per table per session. This is
        also the drift guard: a case parsed before 2026-09 has no
        `browser_service_worker.http_status` and no `browser_sessions.window_index`,
        so nothing may assume a column exists.
        """
        if table not in self._col_cache:
            rows = self._query_db(f"PRAGMA table_info({table})")
            self._col_cache[table] = {r["name"] for r in rows}
        return self._col_cache[table]

    def _usable(self, table: str, *needed: str) -> bool:
        """True when the table exists and carries every column named."""
        if not self._table_exists(table):
            return False
        cols = self._table_columns(table)
        return all(c in cols for c in needed)

    # ---- search + range + provenance filters -------------------------------
    def _search_clause(self, table: str, terms: List[str], mode: str) -> Tuple[str, list]:
        """Parameterised search over whichever searchable columns this table has.

        Each term must (AND) or may (OR) appear in any of them. Terms are never
        concatenated into SQL.
        """
        terms = [t.strip() for t in (terms or []) if t and t.strip()]
        if not terms:
            return "", []
        cols = [c for c in SEARCH_FIELDS if c in self._table_columns(table)]
        if not cols:
            return "", []
        per_term, params = [], []
        for term in terms:
            ors = " OR ".join(f"{c} LIKE ?" for c in cols)
            per_term.append("(" + ors + ")")
            params.extend([f"%{term}%"] * len(cols))
        joiner = " AND " if (mode or "or").lower() == "and" else " OR "
        return "(" + joiner.join(per_term) + ")", params

    def _range_clause(self, tcol: str, start: str, end: str) -> Tuple[str, list]:
        # On the raw text ('YYYY-MM-DD HH:MM:SS' sorts as time), so an index
        # on the column is usable; date(col) hid it from the planner.
        clause, params = [], []
        if start:
            clause.append(f"{tcol} >= date(?)")
            params.append(start)
        if end:
            clause.append(f"{tcol} < date(?, '+1 day')")
            params.append(end)
        return (" AND ".join(clause), params)

    def _where(self, table: str, tcol: str, args: dict) -> Tuple[str, list]:
        """Range + search + browser/profile, as one WHERE fragment."""
        parts, params = [], []
        # A row with no event time cannot be placed on any chart.
        parts.append(f"{tcol} IS NOT NULL AND {tcol} <> ''")

        rc, rp = self._range_clause(tcol, args.get("start", ""), args.get("end", ""))
        if rc:
            parts.append(rc)
            params.extend(rp)

        sc, sp = self._search_clause(table, args.get("terms", []), args.get("mode", "or"))
        if sc:
            parts.append(sc)
            params.extend(sp)

        cols = self._table_columns(table)
        for key, col in (("browser", PROV_BROWSER), ("profile", PROV_PROFILE)):
            val = (args.get(key) or "").strip()
            if val and col in cols:
                parts.append(f"{col} = ?")
                params.append(val)

        return ((" WHERE " + " AND ".join(parts)) if parts else "", params)

    # ---- domain helper -----------------------------------------------------
    @staticmethod
    def _domain(value: str) -> str:
        """Reduce a URL or cookie host to a comparable host name.

        Cookie hosts arrive as `.example.com`; URLs as `https://example.com/x`.
        Both must land on `example.com` or the detail panel joins nothing. A
        value that is not URL-shaped (a search phrase, a file path) is returned
        cleaned rather than dropped - it is still evidence, just not a host.
        """
        if not value:
            return ""
        text = str(value).strip()
        if "://" in text:
            text = text.split("://", 1)[1]
        text = text.split("/", 1)[0].split("?", 1)[0]
        text = text.lstrip(".")
        if "@" in text:                       # strip any userinfo
            text = text.rsplit("@", 1)[1]
        if text.startswith("["):              # IPv6 literal
            return text.split("]", 1)[0] + "]"
        text = text.split(":", 1)[0]          # drop the port
        return text.lower()[:255]

    # ---- the fan-in ---------------------------------------------------------
    def _activity_rows(self, args: dict, grain: str = "day",
                       activities: Optional[List[str]] = None) -> List[Dict]:
        """Every event from every activity, bucketed, as flat records.

        The browser equivalent of VizBridge._merge_activity: several tables with
        nothing in common but their provenance columns are fanned into one list
        of `{activity, bucket, url, browser, profile, n}` records so the strips,
        the day drill-down and the overview can all be built from one shape.
        """
        bucket = "date(%s)" if grain == "day" else "strftime('%%Y-%%m-%%dT%%H:00', %s)"
        out: List[Dict] = []
        for act in (activities or ACTIVITY_ORDER):
            for table, tcol, ucol in ACTIVITY_SOURCES.get(act, []):
                if not self._usable(table, tcol, ucol):
                    continue
                where, params = self._where(table, tcol, args)
                sql = (f"SELECT {bucket % tcol} AS bucket, {ucol} AS url, "
                       f"{PROV_BROWSER} AS browser, {PROV_PROFILE} AS profile, "
                       f"COUNT(*) AS n "
                       f"FROM {table}{where} "
                       f"GROUP BY bucket, url, browser, profile")
                for r in self._query_db(sql, tuple(params)):
                    if not r.get("bucket"):
                        continue
                    out.append({
                        "activity": act,
                        "bucket": r["bucket"],
                        "url": r.get("url") or "",
                        "domain": self._domain(r.get("url") or ""),
                        "browser": r.get("browser") or "",
                        "profile": r.get("profile") or "",
                        "n": int(r.get("n") or 0),
                    })
        return out

    def _day_events(self, day_args: dict, limit: int) -> List[Dict]:
        """The day's individual events, oldest first, capped at `limit`.

        Every other slot aggregates; this one does not, because an investigator
        reading a day eventually wants the rows themselves. Each table is asked
        for `limit` rows at most, so a single noisy table cannot exhaust the cap
        before the others are read, and the merged list is cut to `limit` after
        sorting. The count the UI displays comes from the hour histogram, not
        from this list, so a capped list still says how much it is hiding.
        """
        out: List[Dict] = []
        for act in ACTIVITY_ORDER:
            for table, tcol, ucol in ACTIVITY_SOURCES.get(act, []):
                if not self._usable(table, tcol, ucol):
                    continue
                cols = self._table_columns(table)
                # A human-readable label where the table has one. Deliberately a
                # short allow-list: no column that could carry a secret (cookie
                # values, autofill values, password blobs) is ever named here.
                label_col = next((c for c in EVENT_LABEL_FIELDS if c in cols), None)
                label_sql = f"{label_col} AS label" if label_col else "'' AS label"
                where, params = self._where(table, tcol, day_args)
                sql = (f"SELECT {tcol} AS t, {ucol} AS url, {label_sql}, "
                       f"{PROV_BROWSER} AS browser, {PROV_PROFILE} AS profile "
                       f"FROM {table}{where} ORDER BY {tcol} LIMIT ?")
                for r in self._query_db(sql, tuple(params) + (limit,)):
                    when = (r.get("t") or "").strip()
                    if not when:
                        continue
                    url = r.get("url") or ""
                    out.append({
                        "t": when,
                        "time": when[11:19] or when,
                        "activity": act,
                        "domain": self._domain(url),
                        "label": (r.get("label") or "").strip(),
                        "url": url,
                        "browser": r.get("browser") or "",
                        "profile": r.get("profile") or "",
                    })
        out.sort(key=lambda e: e["t"])
        return out[:limit]

    # ---- slots -------------------------------------------------------------
    @pyqtSlot(result=str)
    @cached_slot("getBrowserBounds", _browser_db)
    def getBrowserBounds(self) -> str:
        """The date range the data covers, plus what exists to chart."""
        if not self._get_db_path(BROWSER_DB):
            return json.dumps({"hasData": False, "reason": "no_browser_db"})

        counts, gmin, gmax = {}, None, None
        for act in ACTIVITY_ORDER:
            total = 0
            for table, tcol, ucol in ACTIVITY_SOURCES[act]:
                if not self._usable(table, tcol, ucol):
                    continue
                rows = self._query_db(
                    f"SELECT COUNT(*) c, date(MIN({tcol})) lo, date(MAX({tcol})) hi "
                    f"FROM {table} WHERE {tcol} IS NOT NULL AND {tcol} <> ''")
                if not rows:
                    continue
                r = rows[0]
                total += int(r.get("c") or 0)
                lo, hi = r.get("lo"), r.get("hi")
                if lo and (gmin is None or lo < gmin):
                    gmin = lo
                if hi and (gmax is None or hi > gmax):
                    gmax = hi
            counts[act] = total

        return json.dumps({
            "hasData": bool(gmin),
            "minDate": gmin, "maxDate": gmax,
            "sources": counts,
            "browsers": self._distinct(PROV_BROWSER),
            "profiles": self._distinct(PROV_PROFILE),
        })

    def _distinct(self, column: str) -> List[str]:
        """Distinct provenance values across the tables that have any data."""
        seen = set()
        for act in ACTIVITY_ORDER:
            for table, tcol, _ucol in ACTIVITY_SOURCES[act]:
                if not self._usable(table, tcol, column):
                    continue
                for r in self._query_db(
                        f"SELECT DISTINCT {column} v FROM {table} "
                        f"WHERE {column} IS NOT NULL AND {column} <> ''"):
                    if r.get("v"):
                        seen.add(str(r["v"]))
        return sorted(seen)

    @pyqtSlot(str, result=str)
    @cached_slot("getBrowserHeatmaps", _browser_db)
    def getBrowserHeatmaps(self, args_json: str) -> str:
        """One day-count series per activity, plus the combined series."""
        args = _loads(args_json)
        per_raw, combined = {}, {}
        for act in ACTIVITY_ORDER:
            days: Dict[str, int] = {}
            for table, tcol, ucol in ACTIVITY_SOURCES[act]:
                if not self._usable(table, tcol, ucol):
                    continue
                where, params = self._where(table, tcol, args)
                sql = (f"SELECT date({tcol}) d, COUNT(*) c FROM {table}{where} "
                       f"GROUP BY d")
                for r in self._query_db(sql, tuple(params)):
                    if not r.get("d"):
                        continue
                    days[r["d"]] = days.get(r["d"], 0) + int(r.get("c") or 0)
                    combined[r["d"]] = combined.get(r["d"], 0) + int(r.get("c") or 0)
            per_raw[act] = days
        # Only days that HAD activity come out of a GROUP BY, which turns the
        # strip into an ordinal list of active days rather than a time axis -
        # a quiet stretch closes up and vanishes. Fill every day in the range.
        # A cell is always one day; a range too long to fit scrolls instead of
        # changing what a cell means. See timeseries.py.
        start, end = _axis_range(args, combined)
        sources = _densify_series(per_raw, start, end)
        combined_rows = _densify(combined, start, end)
        return json.dumps({"sources": sources, "combined": combined_rows})

    @pyqtSlot(str, result=str)
    @cached_slot("getBrowserOverview", _browser_db)
    def getBrowserOverview(self, args_json: str) -> str:
        """The four cards: domains, intent, downloads, insights."""
        args = _loads(args_json)
        return json.dumps({
            "totals": self._totals(args),
            "topDomains": self._top_domains(args),
            "intent": self._intent(args),
            "downloads": self._downloads(args),
            "insights": self._browser_insights(args),
            "sourceTotals": self._source_totals(args),
        })

    def _source_totals(self, args: dict) -> Dict[str, int]:
        totals = {}
        for act in ACTIVITY_ORDER:
            n = 0
            for table, tcol, ucol in ACTIVITY_SOURCES[act]:
                if not self._usable(table, tcol, ucol):
                    continue
                where, params = self._where(table, tcol, args)
                rows = self._query_db(f"SELECT COUNT(*) c FROM {table}{where}", tuple(params))
                n += int(rows[0]["c"]) if rows else 0
            totals[act] = n
        return totals

    def _totals(self, args: dict) -> Dict[str, int]:
        # The overview and its insights both ask: computed once per filter.
        return self.cached_result("_totals", json.dumps(args, sort_keys=True),
                                  lambda _a: self._compute_totals(args), _browser_db(self))

    def _compute_totals(self, args: dict) -> Dict[str, int]:
        rows = self._activity_rows(args, grain="day")
        return {
            "events": sum(r["n"] for r in rows),
            "domains": len({r["domain"] for r in rows if r["domain"]}),
            "activeDays": len({r["bucket"] for r in rows}),
            "browsers": len({r["browser"] for r in rows if r["browser"]}),
            "profiles": len({r["profile"] for r in rows if r["profile"]}),
        }

    def _top_domains(self, args: dict, limit: int = 12) -> List[Dict]:
        """Most-visited domains, split typed vs clicked.

        The split is the point: a domain reached by typing was chosen, one
        reached by a link may only have been passed through. `typed_count` and
        the `transition` text carry that, and neither exists on the Gecko side
        in the same form, so Gecko rows count as visits without an intent split
        rather than being silently attributed to one.
        """
        agg: Dict[str, Dict] = {}
        for table, tcol, ucol in (("browser_history", "visit_time", "url"),
                                  ("browser_gecko_history", "visit_time", "url")):
            if not self._usable(table, tcol, ucol):
                continue
            cols = self._table_columns(table)
            typed = "typed_count" if "typed_count" in cols else (
                "typed" if "typed" in cols else None)
            where, params = self._where(table, tcol, args)
            sel = [f"{ucol} AS url", "COUNT(*) AS visits"]
            if typed:
                sel.append(f"SUM(CASE WHEN COALESCE({typed},0) > 0 THEN 1 ELSE 0 END) AS typed")
            sql = f"SELECT {', '.join(sel)} FROM {table}{where} GROUP BY {ucol}"
            for r in self._query_db(sql, tuple(params)):
                dom = self._domain(r.get("url") or "")
                if not dom:
                    continue
                cur = agg.setdefault(dom, {"domain": dom, "visits": 0, "typed": 0})
                cur["visits"] += int(r.get("visits") or 0)
                cur["typed"] += int(r.get("typed") or 0)
        out = sorted(agg.values(), key=lambda d: d["visits"], reverse=True)[:limit]
        for d in out:
            d["clicked"] = max(0, d["visits"] - d["typed"])
        return out

    def _intent(self, args: dict, limit: int = 15) -> Dict[str, List[Dict]]:
        """What was actually typed: omnibox text and typed URLs."""
        typed_terms: List[Dict] = []
        if self._usable("browser_shortcuts", "last_access_time", "text"):
            where, params = self._where("browser_shortcuts", "last_access_time", args)
            cols = self._table_columns("browser_shortcuts")
            hits = "number_of_hits" if "number_of_hits" in cols else None
            sel = "text, url" + (f", {hits} AS hits" if hits else ", 0 AS hits")
            for r in self._query_db(
                    f"SELECT {sel} FROM browser_shortcuts{where} "
                    f"ORDER BY hits DESC LIMIT {int(limit)}", tuple(params)):
                if (r.get("text") or "").strip():
                    typed_terms.append({
                        "text": r["text"],
                        "domain": self._domain(r.get("url") or ""),
                        "hits": int(r.get("hits") or 0),
                    })

        typed_urls: List[Dict] = []
        for table, tcol in (("browser_history", "visit_time"),
                            ("browser_gecko_history", "visit_time")):
            if not self._usable(table, tcol, "url"):
                continue
            cols = self._table_columns(table)
            typed = "typed_count" if "typed_count" in cols else (
                "typed" if "typed" in cols else None)
            if not typed:
                continue
            where, params = self._where(table, tcol, args)
            joiner = " AND " if where else " WHERE "
            sql = (f"SELECT url, title, {typed} AS typed FROM {table}{where}"
                   f"{joiner}COALESCE({typed},0) > 0 "
                   f"ORDER BY typed DESC LIMIT {int(limit)}")
            for r in self._query_db(sql, tuple(params)):
                typed_urls.append({
                    "url": r.get("url") or "",
                    "domain": self._domain(r.get("url") or ""),
                    "title": r.get("title") or "",
                    "typed": int(r.get("typed") or 0),
                })
        typed_urls.sort(key=lambda d: d["typed"], reverse=True)
        return {"terms": typed_terms, "typedUrls": typed_urls[:limit]}

    def _downloads(self, args: dict, limit: int = 20) -> List[Dict]:
        """What landed on disk, and whether the browser flagged or opened it."""
        out: List[Dict] = []
        for table, tcol, ucol in (("browser_downloads", "start_time", "source_url"),
                                  ("browser_gecko_downloads", "start_time", "url")):
            if not self._usable(table, tcol, ucol):
                continue
            cols = self._table_columns(table)
            want = ["target_path", "received_bytes", "total_bytes",
                    "danger_type", "opened", "mime_type", "state"]
            sel = [f"{tcol} AS started", f"{ucol} AS src"]
            sel += [c for c in want if c in cols]
            where, params = self._where(table, tcol, args)
            sql = (f"SELECT {', '.join(sel)} FROM {table}{where} "
                   f"ORDER BY {tcol} DESC LIMIT {int(limit)}")
            for r in self._query_db(sql, tuple(params)):
                out.append({
                    "started": r.get("started") or "",
                    "sourceUrl": r.get("src") or "",
                    "domain": self._domain(r.get("src") or ""),
                    "targetPath": r.get("target_path") or "",
                    "bytes": int(r.get("received_bytes") or r.get("total_bytes") or 0),
                    "dangerType": r.get("danger_type"),
                    "opened": r.get("opened"),
                    "mimeType": r.get("mime_type") or "",
                    "state": r.get("state"),
                })
        out.sort(key=lambda d: d["started"], reverse=True)
        return out[:limit]

    def _anti_forensics(self, args: dict, limit: int = 12) -> Dict:
        """Evidence a domain was visited, where the history row is gone.

        Favicons, cache entries, top sites and sessions all outlive a cleared
        history, and cookies outlive it too. A domain present in one of those
        and absent from history is the strongest routine signal that history
        was pruned - so it is listed by name rather than merely counted.
        """
        visited = set()
        for table, tcol in (("browser_history", "visit_time"),
                            ("browser_gecko_history", "visit_time")):
            if not self._usable(table, tcol, "url"):
                continue
            for r in self._query_db(f"SELECT DISTINCT url FROM {table}"):
                d = self._domain(r.get("url") or "")
                if d:
                    visited.add(d)

        survivors: Dict[str, Dict] = {}
        for table, ucol, label in (("browser_favicons", "page_url", "favicon"),
                                   ("browser_cache", "url", "cache"),
                                   ("browser_top_sites", "url", "top site"),
                                   ("browser_sessions", "url", "session"),
                                   ("browser_cookies", "host_key", "cookie"),
                                   ("browser_gecko_cookies", "host", "cookie")):
            if not self._usable(table, ucol):
                continue
            for r in self._query_db(f"SELECT DISTINCT {ucol} v FROM {table}"):
                d = self._domain(r.get("v") or "")
                if not d or d in visited:
                    continue
                cur = survivors.setdefault(d, {"domain": d, "sources": []})
                if label not in cur["sources"]:
                    cur["sources"].append(label)

        # Rank by how many DIFFERENT artifact kinds corroborate the domain. A
        # domain seen only in cache is usually a third-party CDN or tracker the
        # user never chose to visit; one carried by a cookie AND a favicon AND
        # a top-site entry is a site that was used and then pruned. Cache-only
        # domains are counted but never lead the list.
        def rank(entry):
            kinds = set(entry["sources"])
            return (-(len(kinds)), 0 if kinds != {"cache"} else 1, entry["domain"])

        orphans = sorted(survivors.values(), key=rank)
        corroborated = [o for o in orphans if set(o["sources"]) != {"cache"}]

        return {
            "orphanDomains": corroborated[:limit],
            "orphans": corroborated,
            "orphanCount": len(corroborated),
            "visitedDomains": len(visited),
        }

    # Chromium's `danger_type`: 0 is NOT_DANGEROUS and 7 is USER_VALIDATED (the
    # user was warned and chose to keep it). Everything else is a warning the
    # browser raised, which is the thing worth listing.
    SAFE_DANGER_TYPES = {0, 7}

    def _download_rows(self, args: dict) -> List[Dict]:
        """Every download in range, uncapped - the overview card caps at 20."""
        out: List[Dict] = []
        for table, tcol, ucol in (("browser_downloads", "start_time", "source_url"),
                                  ("browser_gecko_downloads", "start_time", "url")):
            if not self._usable(table, tcol, ucol):
                continue
            cols = self._table_columns(table)
            want = ["target_path", "danger_type", "opened", "mime_type"]
            sel = [f"{tcol} AS started", f"{ucol} AS src"]
            sel += [c for c in want if c in cols]
            where, params = self._where(table, tcol, args)
            for r in self._query_db(f"SELECT {', '.join(sel)} FROM {table}{where}", tuple(params)):
                out.append({
                    "started": r.get("started") or "",
                    "domain": self._domain(r.get("src") or ""),
                    "targetPath": r.get("target_path") or "",
                    "dangerType": r.get("danger_type"),
                    "opened": r.get("opened"),
                })
        return out

    # Programs and scripts, as opposed to documents and media. What was fetched
    # and could then be run is the question a download list is read for.
    EXECUTABLE_EXT = {".exe", ".msi", ".ps1", ".bat", ".cmd", ".scr", ".dll",
                      ".vbs", ".js", ".jar", ".hta", ".lnk", ".com", ".cpl"}

    def _browser_insights(self, args: dict) -> Dict:
        """The Insights card: what in this browsing history is worth opening.

        This replaces the Anti-forensics card rather than sitting beside it -
        that card listed orphan domains well but ended in two numbers with
        nothing behind them, and the fleet had already settled on one shape for
        "a count you can open" (`visualizations/insights.py`). Its reasoning did
        not go in the bin: it is the hint text each tile carries, so an analyst
        reads it at the moment it matters.

        Two signals that were measured and rejected, because a tile that counts
        noise is worse than no tile:

        - *Downloads that were opened.* 53 of 160 on the case this was written
          against. Opening what you downloaded is what downloading is for.
        - *Domains appearing only in cache.* `browser_cache.url` does not hold
          one clean URL per row - 273 of 400 sampled rows parse to something
          that is not a host, including concatenated URLs and Permissions-Policy
          header text - so the 233 it counted were mostly parse debris. The
          cache column needs fixing in the parser before anything is built on
          it.
        """
        af = self._anti_forensics(args)
        downloads = self._download_rows(args)

        def dsubject(d, note):
            name = os.path.basename((d["targetPath"] or "").replace("\\", "/")) \
                or d["domain"] or "(unnamed download)"
            return _subject(name, d["domain"] or None,
                            note + ((" · " + d["started"][:10]) if d["started"] else ""))

        flagged, executables = [], []
        for d in downloads:
            dt = d["dangerType"]
            try:
                risky = dt is not None and dt != "" and int(dt) not in self.SAFE_DANGER_TYPES
            except (TypeError, ValueError):
                risky = False
            if risky:
                flagged.append(dsubject(d, "the browser warned about this file"))
            ext = os.path.splitext((d["targetPath"] or "").replace("\\", "/"))[1].lower()
            if ext in self.EXECUTABLE_EXT:
                executables.append(dsubject(d, "fetched from " + (d["domain"] or "an unknown host")))

        # Corroborated by two or more KINDS of artifact. One is too weak to
        # state: a third-party cookie is set on domains the user never chose to
        # visit, and 82 of this case's 106 single-artifact orphans were exactly
        # that. Two independent artifacts agreeing is the shape of a site that
        # was used and then pruned.
        strong = [o for o in af["orphans"] if len(set(o["sources"])) >= 2]
        pruned = [_subject(o["domain"], o["domain"], " · ".join(o["sources"]))
                  for o in strong]

        totals = self._totals(args)
        return {
            "historyPruned": _insight(len(pruned), pruned),
            "flaggedDownloads": _insight(len(flagged), flagged),
            "executableDownloads": _insight(len(executables), executables),
            # Measurements, with no record set behind them.
            "domains": _plain(totals.get("domains", 0)),
            "activeDays": _plain(totals.get("activeDays", 0)),
        }

    @pyqtSlot(str, result=str)
    @cached_slot("getBrowserDayDetail", _browser_db)
    def getBrowserDayDetail(self, args_json: str) -> str:
        """One day: the hour histogram, per-activity split, top domains, events."""
        args = _loads(args_json)
        day = (args.get("day") or "").strip()
        if not day:
            return json.dumps({"day": "", "hourly": [0] * 24, "topDomains": [],
                               "perSource": {}, "hourlyBySource": {},
                               "events": [], "eventsTotal": 0})
        day_args = dict(args, start=day, end=day)

        hourly = [0] * 24
        hourly_by_source: Dict[str, List[int]] = {}
        per_source: Dict[str, int] = {}
        for act in ACTIVITY_ORDER:
            series = [0] * 24
            for table, tcol, ucol in ACTIVITY_SOURCES[act]:
                if not self._usable(table, tcol, ucol):
                    continue
                where, params = self._where(table, tcol, day_args)
                sql = (f"SELECT CAST(strftime('%H', {tcol}) AS INTEGER) h, COUNT(*) c "
                       f"FROM {table}{where} GROUP BY h")
                for r in self._query_db(sql, tuple(params)):
                    h = r.get("h")
                    if h is None or not (0 <= int(h) <= 23):
                        continue
                    series[int(h)] += int(r.get("c") or 0)
            hourly_by_source[act] = series
            per_source[act] = sum(series)
            for i in range(24):
                hourly[i] += series[i]

        rows = self._activity_rows(day_args, grain="day")
        agg: Dict[str, Dict] = {}
        for r in rows:
            if not r["domain"]:
                continue
            cur = agg.setdefault(r["domain"], {"domain": r["domain"], "total": 0, "counts": {}})
            cur["total"] += r["n"]
            cur["counts"][r["activity"]] = cur["counts"].get(r["activity"], 0) + r["n"]
        top = sorted(agg.values(), key=lambda d: d["total"], reverse=True)[:15]

        # The hour histogram already counted every row, so it - not the capped
        # list - is what the UI reports as the day's true total.
        events = self._day_events(day_args, DAY_EVENT_CAP)

        return json.dumps({"day": day, "hourly": hourly, "topDomains": top,
                           "perSource": per_source, "hourlyBySource": hourly_by_source,
                           "events": events, "eventsTotal": sum(hourly)})

    @pyqtSlot(str, result=str)
    @cached_slot("getBrowserDayActivity", _browser_db)
    def getBrowserDayActivity(self, args_json: str) -> str:
        """Bubble/scatter source: domain on Y, hour on X, size = events."""
        args = _loads(args_json)
        day = (args.get("day") or "").strip()
        top_n = int(args.get("topN") or 30)
        if not day:
            return json.dumps({"day": "", "domains": [], "points": [], "ranges": {}})
        day_args = dict(args, start=day, end=day)

        rows = [r for r in self._activity_rows(day_args, grain="hour") if r["domain"]]
        totals: Dict[str, int] = {}
        for r in rows:
            totals[r["domain"]] = totals.get(r["domain"], 0) + r["n"]
        domains = [d for d, _ in sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:top_n]]
        keep = set(domains)

        merged: Dict[Tuple[str, str, int], Dict] = {}
        for r in rows:
            if r["domain"] not in keep:
                continue
            # bucket is 'YYYY-MM-DDTHH:00'; the hour is the X axis, derived here
            # rather than in JS so the chart never re-parses a timestamp.
            try:
                hour = int(str(r["bucket"])[11:13])
            except (ValueError, IndexError):
                continue
            key = (r["domain"], r["activity"], hour)
            cur = merged.setdefault(key, {
                "domain": r["domain"], "activity": r["activity"], "h": hour,
                "hour": r["bucket"], "n": 0, "browser": r["browser"],
            })
            cur["n"] += r["n"]

        points = list(merged.values())
        ranges: Dict[str, Dict[str, int]] = {}
        for p in points:
            cur = ranges.setdefault(p["domain"], {"min": p["h"], "max": p["h"]})
            cur["min"] = min(cur["min"], p["h"])
            cur["max"] = max(cur["max"], p["h"])

        return json.dumps({"day": day, "domains": domains,
                           "points": points, "ranges": ranges})

    @pyqtSlot(str, result=str)
    @cached_slot("getBrowserDomainDetail", _browser_db)
    def getBrowserDomainDetail(self, args_json: str) -> str:
        """Everything known about one domain, across every table.

        This is the browser answer to "what is this site to this machine" -
        visits, what was typed to reach it, cookies it set, what it served from
        cache, whether a login was saved for it, and what was downloaded from
        it. Credentials are reported as counts and usernames' presence only;
        no stored secret is returned.
        """
        args = _loads(args_json)
        domain = (args.get("domain") or "").strip().lower()
        if not domain:
            return json.dumps({"domain": "", "hasData": False})

        like = f"%{domain}%"
        out: Dict = {"domain": domain, "hasData": True}

        visits = []
        for table, tcol in (("browser_history", "visit_time"),
                            ("browser_gecko_history", "visit_time")):
            if not self._usable(table, tcol, "url"):
                continue
            cols = self._table_columns(table)
            extra = [c for c in ("title", "transition", "visit_count", "typed_count",
                                 "typed", "visit_type") if c in cols]
            sel = ", ".join([f"{tcol} AS t", "url"] + extra)
            for r in self._query_db(
                    f"SELECT {sel} FROM {table} WHERE url LIKE ? "
                    f"AND {tcol} IS NOT NULL AND {tcol} <> '' "
                    f"ORDER BY {tcol} DESC LIMIT 200", (like,)):
                if self._domain(r.get("url") or "") != domain:
                    continue
                visits.append({
                    "time": r.get("t") or "", "url": r.get("url") or "",
                    "title": r.get("title") or "",
                    "transition": r.get("transition") or r.get("visit_type") or "",
                    "typed": int(r.get("typed_count") or r.get("typed") or 0),
                })
        visits.sort(key=lambda d: d["time"], reverse=True)
        out["visits"] = visits[:100]
        out["visitCount"] = len(visits)

        out["cookies"] = self._domain_cookies(domain, like)
        out["cache"] = self._domain_cache(domain, like)
        out["credentials"] = self._domain_credentials(domain, like)
        out["downloads"] = self._domain_downloads(domain, like)
        out["records"] = self._domain_source_records(domain, like)
        return json.dumps(out)

    # Every table that can mention a domain, and the column that does.
    DOMAIN_TABLES = (
        ("browser_history", "url"), ("browser_gecko_history", "url"),
        ("browser_downloads", "source_url"), ("browser_gecko_downloads", "url"),
        ("browser_cookies", "host_key"), ("browser_gecko_cookies", "host"),
        ("browser_favicons", "page_url"), ("browser_top_sites", "url"),
        ("browser_sessions", "url"), ("browser_logins", "origin_url"),
        ("browser_autofill_profiles", "email"),
    )

    def _domain_source_records(self, domain: str, like: str) -> dict:
        """Every row in the case that mentions this domain, verbatim.

        A domain is not a record - it is whatever a dozen tables happened to
        store about a host - so there is no single row to show and the panel
        lists them all, capped.

        This is the highest-risk surface in the dashboard: `browser_logins`,
        `browser_cookies` and `browser_autofill_profiles` are exactly where
        stored passwords, cookie values and saved-card fragments live.
        `raw_record`'s withhold list is what keeps them off the screen, by
        exact name and by suffix, and a column it does not know about is
        reported rather than silently dumped only because the suffix rule
        catches the shapes the parser uses.
        """
        rows, total = [], 0
        for table, col in self.DOMAIN_TABLES:
            if not self._usable(table, col):
                continue
            n = self._query_db(f"SELECT COUNT(*) c FROM {table} WHERE {col} LIKE ?", (like,))
            total += (n[0]["c"] if n else 0) or 0
            for r in self._query_db(
                    f"SELECT * FROM {table} WHERE {col} LIKE ? LIMIT 40", (like,)):
                rows.append((table, dict(r)))
        return _source_records(rows, label_of=lambda it: it[0], total=total)

    def _domain_cookies(self, domain: str, like: str) -> List[Dict]:
        out = []
        for table, hcol, ccol in (("browser_cookies", "host_key", "creation_time"),
                                  ("browser_gecko_cookies", "host", "creation_time")):
            if not self._usable(table, hcol):
                continue
            cols = self._table_columns(table)
            extra = [c for c in ("name", "is_secure", "is_httponly", "is_persistent",
                                 "expires_time", "expiry_time", "last_access_time",
                                 "last_accessed") if c in cols]
            tsel = f"{ccol} AS created, " if ccol in cols else ""
            sel = tsel + ", ".join([f"{hcol} AS host"] + extra)
            for r in self._query_db(
                    f"SELECT {sel} FROM {table} WHERE {hcol} LIKE ? LIMIT 100", (like,)):
                if self._domain(r.get("host") or "") != domain:
                    continue
                out.append({
                    "host": r.get("host") or "", "name": r.get("name") or "",
                    "created": r.get("created") or "",
                    "lastAccess": r.get("last_access_time") or r.get("last_accessed") or "",
                    "expires": r.get("expires_time") or r.get("expiry_time") or "",
                    "secure": r.get("is_secure"), "httpOnly": r.get("is_httponly"),
                })
        return out[:60]

    def _domain_cache(self, domain: str, like: str) -> List[Dict]:
        out = []
        for table, ucol, tcol in (("browser_cache", "url", "response_time"),
                                  ("browser_service_worker", "resource_url", "response_time")):
            if not self._usable(table, ucol):
                continue
            cols = self._table_columns(table)
            extra = [c for c in ("http_status", "content_type", "content_length",
                                 "content_encoding", "cache_format") if c in cols]
            tsel = f"{tcol} AS fetched, " if tcol in cols else ""
            sel = tsel + ", ".join([f"{ucol} AS url"] + extra)
            for r in self._query_db(
                    f"SELECT {sel} FROM {table} WHERE {ucol} LIKE ? LIMIT 120", (like,)):
                if self._domain(r.get("url") or "") != domain:
                    continue
                out.append({
                    "url": r.get("url") or "", "fetched": r.get("fetched") or "",
                    "status": r.get("http_status"),
                    "contentType": r.get("content_type") or "",
                    "bytes": int(r.get("content_length") or 0),
                    "encoding": r.get("content_encoding") or "",
                    "format": r.get("cache_format") or "",
                })
        return out[:80]

    def _domain_credentials(self, domain: str, like: str) -> List[Dict]:
        """Saved logins for this domain - metadata only, never a secret."""
        out = []
        for table, ucol in (("browser_credentials", "origin_url"),
                            ("browser_gecko_credentials", "hostname")):
            if not self._usable(table, ucol):
                continue
            cols = self._table_columns(table)
            extra = [c for c in ("date_created", "date_last_used", "times_used",
                                 "time_created", "time_last_used", "blacklisted",
                                 "encryption_version", "username_value") if c in cols]
            sel = ", ".join([f"{ucol} AS origin"] + extra)
            for r in self._query_db(
                    f"SELECT {sel} FROM {table} WHERE {ucol} LIKE ? LIMIT 40", (like,)):
                if self._domain(r.get("origin") or "") != domain:
                    continue
                out.append({
                    "origin": r.get("origin") or "",
                    # Presence, not the value. The parser preserves the
                    # ciphertext on purpose; a chart must not surface it.
                    "hasUsername": bool((r.get("username_value") or "").strip()),
                    "created": r.get("date_created") or r.get("time_created") or "",
                    "lastUsed": r.get("date_last_used") or r.get("time_last_used") or "",
                    "timesUsed": int(r.get("times_used") or 0),
                    "scheme": r.get("encryption_version") or "",
                    "blacklisted": r.get("blacklisted"),
                })
        return out

    def _domain_downloads(self, domain: str, like: str) -> List[Dict]:
        out = []
        for table, ucol, tcol in (("browser_downloads", "source_url", "start_time"),
                                  ("browser_gecko_downloads", "url", "start_time")):
            if not self._usable(table, ucol):
                continue
            cols = self._table_columns(table)
            extra = [c for c in ("target_path", "received_bytes", "total_bytes",
                                 "danger_type", "opened", "mime_type") if c in cols]
            tsel = f"{tcol} AS started, " if tcol in cols else ""
            sel = tsel + ", ".join([f"{ucol} AS src"] + extra)
            for r in self._query_db(
                    f"SELECT {sel} FROM {table} WHERE {ucol} LIKE ? LIMIT 40", (like,)):
                if self._domain(r.get("src") or "") != domain:
                    continue
                out.append({
                    "started": r.get("started") or "",
                    "sourceUrl": r.get("src") or "",
                    "targetPath": r.get("target_path") or "",
                    "bytes": int(r.get("received_bytes") or r.get("total_bytes") or 0),
                    "dangerType": r.get("danger_type"),
                    "opened": r.get("opened"),
                    "mimeType": r.get("mime_type") or "",
                })
        return out


def _loads(args_json: str) -> dict:
    """Parse a slot argument, tolerating empty or malformed input.

    A slot must never raise across the QWebChannel boundary - the React side
    gets `null` and shows its empty state instead of a dead panel.
    """
    try:
        return json.loads(args_json or "{}") or {}
    except (ValueError, TypeError):
        return {}
