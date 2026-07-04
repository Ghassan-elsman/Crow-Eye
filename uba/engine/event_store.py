"""
Derived in-memory SQLite store of BehaviorEvents.

The evidence databases are never touched after analysis: all interactive
queries (filters, pagination, summaries) hit this store, which is ours to
index freely. Timeless events (ts_start IS NULL) are kept and served by a
dedicated flag so the UI can render its "activity without exact time" strip.
"""

import json
import sqlite3
from typing import Iterable, Optional

from uba.engine.models import BehaviorEvent

_SCHEMA = """
CREATE TABLE events (
    event_id TEXT PRIMARY KEY,
    rule_id TEXT NOT NULL,
    behavior_class TEXT NOT NULL,
    activity TEXT NOT NULL,
    ts_start TEXT,
    ts_end TEXT,
    actor_type TEXT NOT NULL,
    actor_name TEXT NOT NULL,
    actor_basis TEXT NOT NULL,
    description TEXT NOT NULL,
    severity TEXT NOT NULL,
    confidence TEXT NOT NULL,
    session_context TEXT,
    caveat TEXT,
    session_user TEXT,
    app_name TEXT,
    aggregate_count INTEGER NOT NULL DEFAULT 1,
    details_json TEXT,
    evidence_json TEXT
);
CREATE INDEX idx_events_ts ON events(ts_start);
CREATE INDEX idx_events_actor ON events(actor_name);
CREATE INDEX idx_events_session_user ON events(session_user);
CREATE INDEX idx_events_app ON events(app_name);
CREATE INDEX idx_events_class ON events(behavior_class);
CREATE INDEX idx_events_severity ON events(severity);
CREATE INDEX idx_events_activity ON events(activity);
"""

_COLUMNS = [
    "event_id", "rule_id", "behavior_class", "activity", "ts_start", "ts_end",
    "actor_type", "actor_name", "actor_basis", "description", "severity",
    "confidence", "session_context", "caveat", "session_user", "app_name",
    "aggregate_count", "details_json", "evidence_json",
]


class UBAEventStore:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)

    # ------------------------------------------------------------------ #
    def add_events(self, events: Iterable[BehaviorEvent]) -> int:
        rows = [ev.to_row() for ev in events]
        if not rows:
            return 0
        placeholders = ",".join("?" for _ in _COLUMNS)
        self.conn.executemany(
            "INSERT OR IGNORE INTO events ({}) VALUES ({})".format(
                ",".join(_COLUMNS), placeholders),
            [[r[c] for c in _COLUMNS] for r in rows],
        )
        self.conn.commit()
        return len(rows)

    # ------------------------------------------------------------------ #
    def query_events(self, filters: Optional[dict] = None,
                     cursor: Optional[str] = None,
                     page_size: int = 200) -> dict:
        """Keyset-paginated event query, newest first.

        cursor is "<ts_start>|<event_id>" of the last row of the previous
        page. Timeless events are excluded unless filters['timeless'] is
        truthy, in which case ONLY timeless events are returned.
        """
        filters = filters or {}
        where, params = self._build_where(filters)

        timeless = bool(filters.get("timeless"))
        if timeless:
            where.append("ts_start IS NULL")
        else:
            where.append("ts_start IS NOT NULL")
            if cursor and "|" in cursor:
                ts, eid = cursor.split("|", 1)
                where.append("(ts_start < ? OR (ts_start = ? AND event_id < ?))")
                params.extend([ts, ts, eid])

        where_sql = " AND ".join(where) if where else "1=1"
        order = "ORDER BY actor_name, activity" if timeless else \
                "ORDER BY ts_start DESC, event_id DESC"
        sql = "SELECT * FROM events WHERE {} {} LIMIT ?".format(where_sql, order)
        rows = self.conn.execute(sql, params + [page_size]).fetchall()

        total = self.conn.execute(
            "SELECT COUNT(*) FROM events WHERE {}".format(where_sql), params
        ).fetchone()[0]

        events = [self._row_to_dict(r) for r in rows]
        next_cursor = None
        if not timeless and len(rows) == page_size:
            last = rows[-1]
            next_cursor = "{}|{}".format(last["ts_start"], last["event_id"])
        return {"events": events, "next_cursor": next_cursor, "total": total}

    def get_event(self, event_id: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM events WHERE event_id = ?", (event_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    # ------------------------------------------------------------------ #
    def summary(self, filters: Optional[dict] = None) -> dict:
        """Aggregates for stat tiles + hour-of-day × day heatmap."""
        filters = filters or {}
        where, params = self._build_where(filters)
        where_sql = " AND ".join(where) if where else "1=1"

        def _group(expr, label):
            sql = ("SELECT {} AS k, COUNT(*) AS n, SUM(aggregate_count) AS total "
                   "FROM events WHERE {} GROUP BY k ORDER BY n DESC").format(expr, where_sql)
            return [{label: r["k"], "events": r["n"], "records": r["total"] or 0}
                    for r in self.conn.execute(sql, params)]

        heatmap = [
            {"day": r["d"], "hour": r["h"], "events": r["n"],
             "max_severity": r["max_sev"]}
            for r in self.conn.execute(
                "SELECT substr(ts_start, 1, 10) AS d, "
                "CAST(substr(ts_start, 12, 2) AS INTEGER) AS h, COUNT(*) AS n, "
                "MAX(CASE severity WHEN 'critical' THEN 4 WHEN 'suspicious' THEN 3 "
                "WHEN 'notable' THEN 2 ELSE 1 END) AS max_sev "
                "FROM events WHERE ts_start IS NOT NULL AND {} "
                "GROUP BY d, h".format(where_sql), params)
        ]
        span = self.conn.execute(
            "SELECT MIN(ts_start), MAX(ts_end) FROM events "
            "WHERE ts_start IS NOT NULL AND {}".format(where_sql), params).fetchone()

        return {
            "by_class": _group("behavior_class", "behavior_class"),
            "by_severity": _group("severity", "severity"),
            "by_activity": _group("activity", "activity"),
            "by_actor": _group("actor_name", "actor_name"),
            "heatmap": heatmap,
            "time_span": {"start": span[0], "end": span[1]},
            "timeless_count": self.conn.execute(
                "SELECT COUNT(*) FROM events WHERE ts_start IS NULL AND {}".format(
                    where_sql), params).fetchone()[0],
        }

    # ------------------------------------------------------------------ #
    @staticmethod
    def _build_where(filters: dict):
        where, params = [], []

        def _in(column, values):
            values = [v for v in (values or []) if v is not None]
            if values:
                where.append("{} IN ({})".format(
                    column, ",".join("?" for _ in values)))
                params.extend(values)

        _in("behavior_class", filters.get("classes"))
        _in("severity", filters.get("severities"))
        _in("activity", filters.get("activities"))
        _in("confidence", filters.get("confidences"))
        _in("app_name", filters.get("apps"))

        actors = filters.get("actors")
        if actors:
            # "" is a legal filter value meaning "unattributed".
            # When include_session_user is set, also match events where the
            # named person was the logged-in user (labelled, not attributed) —
            # lets a manager pull "everything while X was signed in".
            marks = ",".join("?" for _ in actors)
            if filters.get("include_session_user"):
                where.append("(actor_name IN ({m}) OR session_user IN ({m}))".format(m=marks))
                params.extend(actors)
                params.extend(actors)
            else:
                where.append("actor_name IN ({})".format(marks))
                params.extend(actors)
        if filters.get("start"):
            where.append("(ts_start IS NULL OR ts_end >= ?)")
            params.append(filters["start"])
        if filters.get("end"):
            where.append("(ts_start IS NULL OR ts_start <= ?)")
            params.append(filters["end"])
        if filters.get("search"):
            where.append("(description LIKE ? OR actor_name LIKE ? OR details_json LIKE ?)")
            needle = "%{}%".format(filters["search"])
            params.extend([needle, needle, needle])
        return where, params

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        d["details"] = json.loads(d.pop("details_json") or "{}")
        evidence = json.loads(d.pop("evidence_json") or "[]")
        d["evidence_count"] = sum(e.get("count", 0) or len(e.get("rowids", []))
                                  for e in evidence) or len(evidence)
        d["evidence"] = evidence
        return d
