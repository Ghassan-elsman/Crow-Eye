"""
Behaviour context for the Time and Identity engines.

UBA turns artifact rows into behaviour events - "Ghass ran X", "files were
copied into Documents", "a USB storage drive was connected" - each with the
person it belongs to and the artifact rows it rests on. Two things follow for
the engines that correlate the artifacts themselves:

* A behaviour event is never independent evidence. It is derived from an
  artifact row, so a Prefetch row and the program_run event UBA made from it
  are one fact, not two. A feather of the Behaviour type is therefore CONTEXT:
  it never counts toward a Wing's corroboration floor and never moves the
  weighted score (Ghassan, 2026-10-31).
* What it adds is who and what: for each match, the people and activities UBA
  recorded for the same program or file around the same time. That is the
  match's ``behaviour_context``, attached after the engine has written its
  matches (``attach_to_execution``), so the score and the floor are exactly
  what they were.

Every time here is naive UTC text, as UBA and the engines store it.
"""

import json
import logging
import os
import re
import sqlite3
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

CONTEXT_ARTIFACT_TYPES = frozenset({"behaviour"})

# How far either side of a match a behaviour event may sit and still be the
# match's context.
DEFAULT_MARGIN_MINUTES = 30
MAX_ACTIVITIES = 20
MAX_PEOPLE = 10

_NAME_KEYS = ("executable", "program", "file", "name", "task")
_PATH_KEYS = ("path", "image_path", "program_path", "document", "library",
              "original_path", "shortcut_path", "command")
_FMT = "%Y-%m-%d %H:%M:%S"


def is_context_type(artifact_type) -> bool:
    """True for a feather type that is context, never corroboration."""
    return str(artifact_type or "").strip().lower() in CONTEXT_ARTIFACT_TYPES


def _attr(spec, key, default=None):
    if isinstance(spec, dict):
        return spec.get(key, default)
    return getattr(spec, key, default)


def context_feather_ids(wing) -> set:
    """The ids of a Wing's feathers that are context (Behaviour)."""
    feathers = _attr(wing, "feathers", None) or []
    return {str(_attr(f, "feather_id", "") or "") for f in feathers
            if is_context_type(_attr(f, "artifact_type", ""))}


def corroborating_count(feather_ids: Iterable[str], context_ids: set) -> int:
    """How many of ``feather_ids`` count toward the floor."""
    return sum(1 for f in feather_ids if f not in context_ids)


# --------------------------------------------------------------- the index --
def _key(value) -> List[str]:
    """Lookup keys for a program or file name: the lower-case base name, and
    the name without its extension, so CHROME.EXE, chrome.exe and
    C:\\...\\chrome.exe meet."""
    if value is None:
        return []
    text = str(value).strip().strip('"').strip()
    if not text:
        return []
    if text.startswith("@"):
        text = text[1:]
    # A command line: the program is everything up to its first ".exe".
    m = re.match(r'^"?(.+?\.exe)(?:"|\s|,|$)', text, re.I)
    if m:
        text = m.group(1)
    base = re.split(r"[\\/]", text)[-1].strip().lower()
    if not base or len(base) < 2:
        return []
    out = [base]
    stem = base.rsplit(".", 1)[0] if "." in base else ""
    if stem and len(stem) >= 2 and stem != base:
        out.append(stem)
    return out


def _parse_time(value) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip().replace("T", " ")[:19]
    try:
        return datetime.strptime(text, _FMT)
    except ValueError:
        try:
            return datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None


class BehaviourIndex:
    """UBA's events by program/file name, each name's events in time order."""

    def __init__(self, conn: sqlite3.Connection):
        self._by_key: Dict[str, List[Tuple[datetime, datetime, Dict[str, Any]]]] = defaultdict(list)
        self.events = 0
        cur = conn.execute(
            "SELECT event_id, rule_id, activity, ts_start, ts_end, actor_sid, actor_name, "
            "actor_type, severity, app_name, details_json FROM events")
        for (event_id, rule_id, activity, ts_start, ts_end, sid, name, atype,
             severity, app, details_json) in cur:
            start = _parse_time(ts_start)
            if start is None:
                continue
            end = _parse_time(ts_end) or start
            try:
                details = json.loads(details_json or "{}")
            except ValueError:
                details = {}
            keys = set(_key(app))
            for k in _NAME_KEYS + _PATH_KEYS:
                v = details.get(k)
                if isinstance(v, str):
                    keys.update(_key(v))
            if not keys:
                continue
            ev = {"event_id": event_id, "rule_id": rule_id, "activity": activity,
                  "start": start, "end": end, "sid": sid or "", "name": name or "",
                  "actor_type": atype or "", "severity": severity or ""}
            for k in keys:
                self._by_key[k].append((start, end, ev))
            self.events += 1
        self._starts: Dict[str, List[datetime]] = {}
        for k, items in self._by_key.items():
            items.sort(key=lambda t: (t[0], str(t[2]["event_id"])))
            self._starts[k] = [t[0] for t in items]

    @classmethod
    def from_uba(cls, uba) -> Optional["BehaviourIndex"]:
        """From an opened BehaviorEngine (its in-memory store)."""
        store = getattr(uba, "store", None)
        conn = getattr(store, "conn", None)
        return cls(conn) if conn is not None else None

    def context(self, name, path, start, end,
                margin_minutes: int = DEFAULT_MARGIN_MINUTES) -> Optional[Dict[str, Any]]:
        """The people and activities UBA recorded for ``name`` / ``path``
        between ``start - margin`` and ``end + margin``, or None."""
        s, e = _parse_time(start), _parse_time(end) or _parse_time(start)
        if s is None:
            return None
        if e is None or e < s:
            e = s
        lo, hi = s - timedelta(minutes=margin_minutes), e + timedelta(minutes=margin_minutes)
        found: Dict[Any, Dict[str, Any]] = {}
        for k in set(_key(name)) | set(_key(path)):
            items, starts = self._by_key.get(k), self._starts.get(k)
            if not items:
                continue
            # Events that start before hi and end after lo. A burst can start
            # earlier than lo, so step back over the events that started
            # within a day before it.
            i = bisect_left(starts, lo - timedelta(days=1))
            j = bisect_right(starts, hi)
            for ev_start, ev_end, ev in items[i:j]:
                if ev_end >= lo:
                    found[ev["event_id"]] = ev
        if not found:
            return None
        people = Counter()
        names = {}
        acts: Dict[str, Dict[str, Any]] = {}
        for ev in found.values():
            # A person is a user account or a system account. UBA names the
            # PROGRAM as the actor of an event no account is recorded for
            # (a Prefetch run: actor_type "Application"), which is not a who.
            if ev["actor_type"] in ("User", "System") and (ev["sid"] or ev["name"]):
                who = ev["sid"] or ev["name"]
            else:
                who = "(no account recorded)"
            people[who] += 1
            names.setdefault(who, ev["name"] if who != "(no account recorded)" else who)
            a = acts.setdefault(ev["rule_id"], {"rule_id": ev["rule_id"], "activity": ev["activity"],
                                                "count": 0, "first": ev["start"], "last": ev["end"],
                                                "severity": ev["severity"]})
            a["count"] += 1
            a["first"] = min(a["first"], ev["start"])
            a["last"] = max(a["last"], ev["end"])
        activities = sorted(acts.values(), key=lambda a: (a["first"], a["rule_id"]))
        return {
            "window": [lo.strftime(_FMT), hi.strftime(_FMT)],
            "basis": ("UBA events naming the same program or file within %d minutes "
                      "of the match; context, not corroboration" % margin_minutes),
            "events": len(found),
            "people": [{"sid": who if who.startswith("S-1-") else "", "name": names.get(who) or who,
                        "events": n} for who, n in people.most_common(MAX_PEOPLE)],
            "activities": [dict(a, first=a["first"].strftime(_FMT), last=a["last"].strftime(_FMT))
                           for a in activities[:MAX_ACTIVITIES]],
            "activities_total": len(activities),
        }


# ------------------------------------------------------ attach to the results --
def ensure_column(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(matches)")}
    if "behaviour_context" not in cols:
        conn.execute("ALTER TABLE matches ADD COLUMN behaviour_context TEXT")


def attach_to_execution(db_path: str, execution_id: int, index: "BehaviourIndex",
                        result_ids: Optional[Iterable[int]] = None,
                        margin_minutes: int = DEFAULT_MARGIN_MINUTES) -> Dict[str, int]:
    """Write each match's behaviour context. Matches of ``result_ids`` (one
    Wing's results) or of the whole execution. Returns counts."""
    stats = {"matches": 0, "with_context": 0}
    if index is None or not db_path or not os.path.exists(db_path):
        return stats
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        ensure_column(conn)
        if result_ids:
            ids = [int(r) for r in result_ids]
            where, params = "result_id IN (%s)" % ",".join("?" * len(ids)), ids
        else:
            where = "result_id IN (SELECT result_id FROM results WHERE execution_id = ?)"
            params = [execution_id]
        rows = conn.execute(
            "SELECT match_id, matched_application, matched_file_path, timestamp, "
            "anchor_start_time, anchor_end_time FROM matches WHERE " + where, params).fetchall()
        updates = []
        for match_id, app, path, ts, a_start, a_end in rows:
            stats["matches"] += 1
            ctx = index.context(app, path, a_start or ts, a_end or a_start or ts, margin_minutes)
            if ctx:
                stats["with_context"] += 1
                updates.append((json.dumps(ctx, sort_keys=True), match_id))
        conn.executemany("UPDATE matches SET behaviour_context = ? WHERE match_id = ?", updates)
        conn.commit()
    finally:
        conn.close()
    return stats
