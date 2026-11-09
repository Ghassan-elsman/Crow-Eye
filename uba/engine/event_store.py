"""
Derived in-memory SQLite store of BehaviorEvents.

The evidence databases are never touched after analysis: all interactive
queries (filters, pagination, summaries) hit this store, which is ours to
index freely. Timeless events (ts_start IS NULL) are kept and served by a
dedicated flag so the UI can render its "activity without exact time" strip.
"""

import json
import sqlite3
import threading
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
    actor_sid TEXT NOT NULL DEFAULT '',
    host TEXT NOT NULL DEFAULT '',
    user_rule INTEGER NOT NULL DEFAULT 0,
    aggregate_count INTEGER NOT NULL DEFAULT 1,
    details_json TEXT,
    evidence_json TEXT,
    operator TEXT NOT NULL DEFAULT '',
    operator_kind TEXT NOT NULL DEFAULT '',
    operator_basis TEXT NOT NULL DEFAULT '',
    app_state TEXT NOT NULL DEFAULT '',
    app_state_basis TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_events_operator ON events(operator);
CREATE INDEX idx_events_ts ON events(ts_start);
CREATE INDEX idx_events_rule ON events(rule_id);
CREATE INDEX idx_events_actor ON events(actor_name);
CREATE INDEX idx_events_session_user ON events(session_user);
CREATE INDEX idx_events_app ON events(app_name);
CREATE INDEX idx_events_class ON events(behavior_class);
CREATE INDEX idx_events_severity ON events(severity);
CREATE INDEX idx_events_activity ON events(activity);
CREATE INDEX idx_events_actor_sid ON events(actor_sid);
"""

_COLUMNS = [
    "event_id", "rule_id", "behavior_class", "activity", "ts_start", "ts_end",
    "actor_type", "actor_name", "actor_basis", "description", "severity",
    "confidence", "session_context", "caveat", "session_user", "app_name",
    "actor_sid", "host", "user_rule", "aggregate_count", "details_json", "evidence_json",
    "operator", "operator_kind", "operator_basis", "app_state", "app_state_basis",
]


# Who drove an event, as one key (who_drove.py writes operator / operator_kind):
#   ai_agent  the agent's own session record says it ran it (rule ai_agent_turn),
#             or Crow-Eye Sentinel's signals named it (operator_kind ai_agent)
#   script    automation of any other kind
#   person / remote / program, or unknown when nothing decided it.
# The desktop names an AI agent only from its session record (decision 602:
# the other agent signals are Sentinel's).
DRIVERS = ("person", "remote", "program", "script", "ai_agent", "unknown")
DRIVER_SQL = ("(CASE WHEN rule_id = 'ai_agent_turn' OR operator_kind = 'ai_agent' THEN 'ai_agent' "
              "WHEN operator = 'automation' THEN 'script' "
              "WHEN operator = 'person' THEN 'person' "
              "WHEN operator = 'remote_person' THEN 'remote' "
              "WHEN operator = 'program' THEN 'program' ELSE 'unknown' END)")


class UBAEventStore:
    def __init__(self, create_schema: bool = True):
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        if create_schema:
            self.conn.executescript(_SCHEMA)
            # The two-column index is built here, not in _SCHEMA: the schema
            # readers (Sentinel's extract-schema, test parser_schema) take the
            # comma inside `(ts_start, event_id)` for a column of `events`.
            self.ensure_indexes()
        # create_schema=False is for persisted_store.load(), which copies a
        # stored database (schema, rows and indexes) into this one.
        # One reader at a time: the UBA window runs its heavier reads off the
        # GUI thread (uba_bridge ASYNC_SLOTS), and this one connection is
        # shared with the slots that stay on it.
        self.lock = threading.RLock()

    def ensure_indexes(self):
        """Indexes added after a store was first written. A stored analysis
        is copied in whole (persisted_store.load), so an older one lacks
        them; building one over the copy in memory is cheap."""
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_events_ts_id "
                          "ON events(ts_start, event_id)")
        self.conn.commit()

    # ------------------------------------------------------------------ #
    def add_events(self, events: Iterable[BehaviorEvent]) -> int:
        rows = [ev.to_row() for ev in events]
        if not rows:
            return 0
        placeholders = ",".join("?" for _ in _COLUMNS)
        before = self.conn.total_changes
        self.conn.executemany(
            "INSERT OR IGNORE INTO events ({}) VALUES ({})".format(
                ",".join(_COLUMNS), placeholders),
            [[r[c] for c in _COLUMNS] for r in rows],
        )
        self.conn.commit()
        # What was stored: INSERT OR IGNORE drops duplicates, and len(rows)
        # reported them as added.
        return self.conn.total_changes - before

    # ------------------------------------------------------------------ #
    def events_for_day(self, day: str, limit: int = 20000) -> list:
        """Every timed event of one UTC day, oldest first, as dicts (the day
        summary reads them; story_digest)."""
        rows = self.conn.execute(
            "SELECT * FROM events WHERE ts_start >= ? AND ts_start < ? "
            "ORDER BY ts_start, event_id LIMIT ?",
            (day + " 00:00:00", day + " 99", int(limit))).fetchall()
        return [dict(r) for r in rows]

    def query_events(self, filters: Optional[dict] = None,
                     cursor: Optional[str] = None,
                     page_size: int = 200) -> dict:
        """Keyset-paginated event query, newest first by default.

        cursor is "<ts_start>|<event_id>" of the last row of the previous
        page. Timeless events are excluded unless filters['timeless'] is
        truthy, in which case ONLY timeless events are returned.

        filters['order'] = 'asc' reads the story forwards instead. Timestamps
        are fixed-width UTC strings, so string comparison is chronological and
        both directions stay keyset-paginated.
        """
        filters = filters or {}
        where, params = self._build_where(filters)

        ascending = str(filters.get("order", "desc")).lower() == "asc"
        timeless = bool(filters.get("timeless"))
        if timeless:
            where.append("ts_start IS NULL")
        else:
            where.append("ts_start IS NOT NULL")
            if cursor and "|" in cursor:
                ts, eid = cursor.split("|", 1)
                comparison = ">" if ascending else "<"
                # A row value, so the (ts_start, event_id) index answers it.
                # Written as an OR the planner made a multi-index OR and then
                # sorted: 0.23 s for every page after the first, on 38,611
                # activities, against 0.003 s.
                where.append("(ts_start, event_id) {0} (?, ?)".format(comparison))
                params.extend([ts, eid])

        where_sql = " AND ".join(where) if where else "1=1"
        if timeless:
            order = "ORDER BY actor_name, activity"
        elif ascending:
            order = "ORDER BY ts_start ASC, event_id ASC"
        else:
            order = "ORDER BY ts_start DESC, event_id DESC"
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

        # Who drove it (who_drove.py): one key per event, the same expression
        # the "drivers" filter matches, so a tile's number is what it opens.
        driver_heatmap = [
            {"day": r["d"], "hour": r["h"], "driver": r["k"], "events": r["n"]}
            for r in self.conn.execute(
                "SELECT substr(ts_start, 1, 10) AS d, "
                "CAST(substr(ts_start, 12, 2) AS INTEGER) AS h, {} AS k, COUNT(*) AS n "
                "FROM events WHERE ts_start IS NOT NULL AND {} "
                "GROUP BY d, h, k".format(DRIVER_SQL, where_sql), params)
        ]
        return {
            "by_driver": _group(DRIVER_SQL, "driver"),
            "by_app_state": _group("app_state", "app_state"),
            "driver_heatmap": driver_heatmap,
            "by_class": _group("behavior_class", "behavior_class"),
            "by_rule": _group("rule_id", "rule_id"),
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

        _in("rule_id", filters.get("rules"))
        _in("behavior_class", filters.get("classes"))
        _in("severity", filters.get("severities"))
        _in("activity", filters.get("activities"))
        _in("confidence", filters.get("confidences"))
        _in("app_name", filters.get("apps"))
        # The person key: one SID matches every name that person appeared
        # under. "" is not accepted here - an unresolved SID is not a person.
        _in("actor_sid", [s for s in (filters.get("actor_sids") or []) if s])
        _in("host", filters.get("hosts"))
        _in("({})".format(DRIVER_SQL), filters.get("drivers"))
        _in("app_state", filters.get("app_states"))

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
        # An analyst-created rule's event (the window's "Your rule" icon).
        d["user_rule"] = bool(d.get("user_rule"))
        d["details"] = json.loads(d.pop("details_json") or "{}")
        evidence = json.loads(d.pop("evidence_json") or "[]")
        d["evidence_count"] = sum(e.get("count", 0) or len(e.get("rowids", []))
                                  for e in evidence) or len(evidence)
        d["evidence"] = evidence
        return d
