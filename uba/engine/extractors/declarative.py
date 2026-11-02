"""
Analyst-created behaviour rules, run without Python of their own.

A built-in rule is metadata plus a Python extractor; an analyst's rule
(uba/engine/user_rules.py) is data only, and this module runs it:

* **Table rules** read one parsed table. Each row is tested with the Wing
  condition language - ``correlation_engine.config.semantic_mapping``'s
  ``SemanticRule.evaluate`` over ``SemanticCondition`` and ``condition_groups``
  - so a behaviour rule and a Wing rule mean the same thing by the same
  words. The column map says where the time, the person and the program are;
  the person goes through the same ``ActorResolver`` ladder the built-in rules
  use, so the event carries ``actor_sid`` exactly as theirs do. BehaviorEngine
  runs every table rule after every built-in extractor.
* **Derived rules** filter events already in the store (built-in or user
  rules, by rule id or activity) with conditions over the event's fields,
  ``details.<key>`` included. Each match becomes the rule's own event (its id,
  title, severity) carrying the base event's evidence. They run last, in file
  order, so a derived rule can build on a table rule or an earlier derived
  rule.

Every column a table rule names - in a condition, the column map or the
description - must exist in the case's table (``has_column``). A rule that
names a missing one is refused with the reason, never run half-blind: a
missing column would otherwise make every condition on it false and the rule
would report "nothing found" with the run still green.

Headless: the condition classes are imported from correlation_engine's config
package, which needs no Qt (checked by a boundary test).
"""

import logging
import re
from typing import Dict, List, Optional, Tuple

from uba.engine import description as _description
from uba.engine.attribution import Actor
from uba.engine.models import (BehaviorEvent, EvidenceRef, CONF_ARTIFACT_ONLY,
                               CONF_LOG_ONLY)
from uba.engine.user_rules import (DEFAULT_DERIVED_DESCRIPTION, DERIVED_FEATHER,
                                   KIND_DERIVED, KIND_TABLE)
from uba.utils.db_access import table_columns, table_exists
from uba.utils.timeparse import normalize_ts

logger = logging.getLogger(__name__)

# The key a table row is evaluated under. The stored conditions keep the
# table's name as their feather_id (the Wing format, readable in the file);
# a behaviour rule reads one row, so every condition is evaluated against it.
ROW_FEATHER = "row"

# A rule that matches far more than any analyst could read ("every MFT row")
# stops here, and its coverage note says so - the window is not flooded and
# the cap is never silent.
MAX_EVENTS_PER_RULE = 20000
# Aggregated events list up to this many rowids, plus the full count (as the
# built-in burst rules do).
MAX_ROWIDS = 50

DEFAULT_TABLE_DESCRIPTION = "{title} ({table} row)"

CAVEAT_AT_OR_BEFORE = (
    "The rule's author marked this time as an upper bound: the column records "
    "when something was last written, so the behaviour happened at or before "
    "it - read it as 'at or before', not as when this happened.")

# Placeholders a description may use besides the table's own columns.
_TABLE_WORDS = ("actor", "app", "time", "table", "db", "title", "count")
# The event fields a derived rule's conditions and description may name.
EVENT_FIELDS = ("rule_id", "behavior_class", "activity", "ts_start", "ts_end",
                "actor_type", "actor_name", "actor_basis", "actor_sid", "description",
                "severity", "confidence", "session_context", "caveat", "session_user",
                "app_name", "host", "aggregate_count")
_DERIVED_WORDS = ("actor", "app", "time", "title", "count")

_PLACEHOLDER = re.compile(r"\{([^{}]+)\}")


class RuleRefused(Exception):
    """The rule cannot run on this case; the message says why, in plain words."""


# --------------------------------------------------------------- conditions
def _semantic_classes():
    try:
        from correlation_engine.config.semantic_mapping import SemanticCondition, SemanticRule
    except Exception as e:                  # pragma: no cover - stripped host
        raise RuleRefused("The Wing condition language is not available here (%s)." % e)
    return SemanticCondition, SemanticRule


def _all_conditions(rule: dict) -> List[dict]:
    out = [c for c in rule.get("conditions") or [] if isinstance(c, dict)]
    for group in rule.get("condition_groups") or []:
        out.extend(c for c in (group or {}).get("conditions") or [] if isinstance(c, dict))
    return out


def compile_rule(rule: dict, field_of=None, feather: str = ROW_FEATHER):
    """The rule's conditions as a SemanticRule evaluated under ``feather``.

    ``field_of`` maps a stored field name to the key the record really uses
    (a table's own column spelling); identity when None."""
    SemanticCondition, SemanticRule = _semantic_classes()
    field_of = field_of or (lambda name: name)

    def one(cond):
        return {"feather_id": feather,
                "field_name": field_of(str(cond.get("field_name") or "")),
                "value": str(cond.get("value", "")),
                "operator": cond.get("operator", "equals") or "equals",
                "negate": bool(cond.get("negate", False))}

    conditions = [SemanticCondition.from_dict(one(c))
                  for c in rule.get("conditions") or [] if isinstance(c, dict)]
    groups = []
    for group in rule.get("condition_groups") or []:
        if not isinstance(group, dict):
            continue
        groups.append({"logic_operator": str(group.get("logic_operator", "AND")).upper(),
                       "conditions": [one(c) for c in group.get("conditions") or []
                                      if isinstance(c, dict)]})
    return SemanticRule(rule_id=str(rule.get("id") or ""), name=str(rule.get("title") or ""),
                        conditions=conditions, condition_groups=groups,
                        logic_operator=str(rule.get("logic_operator", "AND")).upper())


def template_fields(template: str) -> List[str]:
    return [m.strip() for m in _PLACEHOLDER.findall(str(template or ""))]


def _short(value, limit=160):
    if value is None:
        return ""
    if isinstance(value, bytes):
        return "<%d bytes>" % len(value)
    text = str(value)
    return text if len(text) <= limit else text[:limit - 1] + "…"


def render(template: str, values: Dict[str, object]) -> str:
    """``{name}`` -> values[name] (case-insensitive). Unknown names are left
    as written, so a typo shows rather than vanishing."""
    lower = {str(k).lower(): v for k, v in values.items()}

    def sub(match):
        key = match.group(1).strip().lower()
        if key in lower:
            return _short(lower[key])
        return match.group(0)
    return _PLACEHOLDER.sub(sub, str(template or ""))


# ------------------------------------------------------------ table rules
def named_columns(rule: dict) -> List[Tuple[str, str]]:
    """(what it is for, column) for every column a table rule names."""
    out = []
    for cond in _all_conditions(rule):
        out.append(("a condition", str(cond.get("field_name") or "")))
    columns = rule.get("columns") or {}
    if columns.get("time"):
        out.append(("the time", str(columns["time"])))
    actor = columns.get("actor") or {}
    if isinstance(actor, dict) and actor.get("column") and actor.get("mode") != "none":
        out.append(("the person", str(actor["column"])))
    if columns.get("app"):
        out.append(("the program", str(columns["app"])))
    for name in template_fields(rule.get("description") or ""):
        if name.lower() not in _TABLE_WORDS:
            out.append(("the description", name))
    return [(why, col) for why, col in out if col]


def check_table_rule(pool, rule: dict) -> List[str]:
    """Why this table rule cannot run on the case behind ``pool`` ([] = it can)."""
    source = rule.get("source") or {}
    db, table = str(source.get("db") or ""), str(source.get("table") or "")
    conn = pool.get(db) if db else None
    if conn is None:
        return ["The database '%s' is not in this case's Target_Artifacts." % db]
    if not table_exists(conn, table):
        return ["The table '%s' is not in the database '%s' in this case." % (table, db)]
    try:
        present = {c.lower() for c in table_columns(conn, table)}
    except Exception as e:
        return ["The columns of '%s' cannot be read: %s" % (table, e)]
    problems, seen = [], set()
    for why, col in named_columns(rule):
        if col.lower() in present or (col.lower(), why) in seen:
            continue
        seen.add((col.lower(), why))
        problems.append("The column '%s' (%s) is not in the table '%s' in this case."
                        % (col, why, table))
    return problems


def _actor(ctx, rule: dict, rec: dict, label: str, field_of) -> Actor:
    """The person a row belongs to, by the rule's actor mode - through the
    same ActorResolver ladder as the built-in rules, so it never guesses."""
    actor = (rule.get("columns") or {}).get("actor") or {}
    mode = actor.get("mode", "none") if isinstance(actor, dict) else "none"
    col = field_of(actor.get("column")) if isinstance(actor, dict) and actor.get("column") else None
    value = rec.get(col) if col else None
    text = str(value).strip() if value not in (None, "") else ""
    if mode == "sid":
        return ctx.resolver.from_sid(text, label) if text else Actor()
    if mode == "username":
        return ctx.resolver.from_account_name(text, label) if text else Actor()
    if mode == "hive_owner":
        if not col or not text:
            # No owner on the row: the hive's only profile, on a one-profile
            # machine; otherwise nobody (from_user_hive never picks one of two).
            return ctx.resolver.from_user_hive(label)
        if text.upper().startswith("S-1-"):
            return ctx.resolver.from_user_hive(label, sid=text)
        if "\\" in text or "/" in text:
            folder = ctx.resolver.profile_folder_in(text)
            return ctx.resolver.from_user_hive(label, owner=folder) if folder else Actor()
        return ctx.resolver.from_user_hive(label, owner=text)
    return Actor()


def _like_pattern(value: str, contains: bool) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return "%" + escaped + "%" if contains else escaped


def _pushdown(rule: dict, field_of) -> Tuple[List[str], list]:
    """SQL that keeps a superset of the matching rows, for speed only: an AND
    rule's plain equals / contains conditions on ASCII text become LIKE (which
    folds ASCII case as the condition language does). The condition language
    still decides every row that comes back."""
    if str(rule.get("logic_operator", "AND")).upper() != "AND":
        return [], []
    where, params = [], []
    for cond in rule.get("conditions") or []:
        op = cond.get("operator", "equals")
        value = str(cond.get("value", ""))
        if cond.get("negate") or op not in ("equals", "contains") or value == "*":
            continue
        if not value or not value.isascii():
            continue
        col = field_of(cond.get("field_name"))
        where.append('"{}" LIKE ? ESCAPE \'\\\''.format(col.replace('"', '""')))
        params.append(_like_pattern(value, contains=(op == "contains")))
    return where, params


def _matching_rows(ctx, rule: dict):
    """(columns used, field_of, generator of (rowid, record)) for a table rule.
    Raises RuleRefused when the case cannot run it."""
    problems = check_table_rule(ctx.pool, rule)
    if problems:
        raise RuleRefused(" ".join(problems))
    source = rule["source"]
    db, table = str(source["db"]), str(source["table"])
    conn = ctx.pool.get(db)
    actual = table_columns(conn, table)
    by_lower = {c.lower(): c for c in actual}

    def field_of(name):
        return by_lower.get(str(name or "").lower(), str(name or ""))

    srule = compile_rule(rule, field_of)
    used = []
    for _why, col in named_columns(rule):
        real = field_of(col)
        if real not in used:
            used.append(real)
    where, params = _pushdown(rule, field_of)
    col_sql = ", ".join('"{}"'.format(c.replace('"', '""')) for c in used) if used else "NULL"
    sql = 'SELECT rowid, {} FROM "{}"'.format(col_sql, table.replace('"', '""'))
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY rowid"

    def rows():
        for row in conn.execute(sql, params):
            rec = {col: row[i + 1] for i, col in enumerate(used)}
            ok, _labels = srule.evaluate({ROW_FEATHER: rec})
            if ok:
                yield row[0], rec
    return used, field_of, rows()


def table_rule_events(ctx, rule: dict, max_events: Optional[int] = MAX_EVENTS_PER_RULE
                      ) -> Tuple[List[BehaviorEvent], dict]:
    """(events, info) for one table rule. ``info``: matched_rows, capped.

    Raises RuleRefused when the case lacks the table or a named column."""
    used, field_of, rows = _matching_rows(ctx, rule)
    source = rule["source"]
    db, table = str(source["db"]), str(source["table"])
    columns = rule.get("columns") or {}
    time_col = field_of(columns["time"]) if columns.get("time") else None
    app_col = field_of(columns["app"]) if columns.get("app") else None
    at_or_before = columns.get("time_basis", "exact") == "at_or_before"
    caveat = ""
    if at_or_before:
        if db == "registry":
            from uba.engine.extractors.artifacts import CAVEAT_KEY_TIME
            caveat = CAVEAT_KEY_TIME
        else:
            caveat = CAVEAT_AT_OR_BEFORE
    label = "the {} record".format(table)
    template = rule.get("description") or DEFAULT_TABLE_DESCRIPTION
    confidence = CONF_LOG_ONLY if db == "logs" else CONF_ARTIFACT_ONLY
    agg = (rule.get("aggregation") or {}).get("mode", "none")

    matched = []          # (rowid, rec, ts, actor, app)
    capped = False
    for rowid, rec in rows:
        ts = normalize_ts(rec.get(time_col)) if time_col else None
        actor = _actor(ctx, rule, rec, label, field_of)
        app = _description.app_display_name(rec.get(app_col)) if app_col and rec.get(app_col) else ""
        matched.append((rowid, rec, ts, actor, app))
        if agg == "none" and max_events and len(matched) >= max_events:
            capped = True
            break

    def values_for(rec, actor, app, ts, count=1):
        vals = dict(rec)
        vals.update({"actor": actor[1] or "Someone", "app": app or "",
                     "time": ("at or before %s" % ts if at_or_before else ts) if ts else "",
                     "table": table, "db": db, "title": rule.get("title", ""),
                     "count": count})
        return vals

    def details_for(rec, rowid):
        return {"source": "{}:{}".format(db, table), "rowid": rowid,
                "time_column": time_col or "", "time_basis": "at_or_before" if at_or_before else "exact",
                "row": {k: _short(v, 300) for k, v in rec.items()}}

    def make(ts, ts_end, actor, text, rowids, count, app, rec, rowid):
        return BehaviorEvent(
            rule_id=rule["id"], behavior_class=rule["behavior_class"],
            activity=rule["activity"], ts_start=ts, ts_end=ts_end or ts,
            actor_type=actor[0], actor_name=actor[1], actor_basis=actor[2],
            actor_sid=getattr(actor, "sid", ""),
            description=text, severity=rule["severity"], confidence=confidence,
            caveat=caveat, app_name=app,
            session_context=ctx.session_context(ts) if ts else "",
            aggregate_count=count, details=details_for(rec, rowid),
            evidence=[EvidenceRef(db=db, table=table, rowids=list(rowids[:MAX_ROWIDS]),
                                  count=count)],
            user_rule=True)

    events: List[BehaviorEvent] = []
    if agg == "none":
        for rowid, rec, ts, actor, app in matched:
            events.append(make(ts, ts, actor, render(template, values_for(rec, actor, app, ts)),
                               [rowid], 1, app, rec, rowid))
    else:
        # Per person (SID first, else name), then by day or by burst.
        gap_seconds = float((rule.get("aggregation") or {}).get("gap_minutes") or 0) * 60
        buckets: Dict[tuple, list] = {}
        order = []
        for item in matched:
            rowid, rec, ts, actor, app = item
            who = getattr(actor, "sid", "") or actor[1] or ""
            if agg == "per_actor_day":
                key = (who, ts[:10] if ts else None)
                if key not in buckets:
                    buckets[key] = []
                    order.append(key)
                buckets[key].append(item)
            else:
                key = (who,)
                if key not in buckets:
                    buckets[key] = []
                    order.append(key)
                buckets[key].append(item)
        groups = []
        for key in order:
            items = buckets[key]
            if agg == "burst":
                from uba.utils.timeparse import epoch_seconds
                timed = sorted((i for i in items if i[2]), key=lambda i: (i[2], i[0]))
                current, last = [], None
                for item in timed:
                    epoch = epoch_seconds(item[2])
                    if current and last is not None and epoch is not None \
                            and epoch - last > gap_seconds:
                        groups.append(current)
                        current = []
                    current.append(item)
                    last = epoch if epoch is not None else last
                if current:
                    groups.append(current)
                untimed = [i for i in items if not i[2]]
                if untimed:
                    groups.append(untimed)
            else:
                groups.append(sorted(items, key=lambda i: (i[2] or "", i[0])))
        for items in groups:
            first = items[0]
            rowid, rec, ts, actor, app = first
            times = [i[2] for i in items if i[2]]
            start, end = (min(times), max(times)) if times else (None, None)
            count = len(items)
            text = render(template, values_for(rec, actor, app, start, count))
            if count > 1:
                if agg == "per_actor_day" and start:
                    text += " ({} matching rows that day)".format(count)
                elif start:
                    text += " ({} matching rows between {} and {})".format(count, start, end)
                else:
                    text += " ({} matching rows without a time)".format(count)
            events.append(make(start, end, actor, text, [i[0] for i in items], count,
                               app, rec, rowid))
            if max_events and len(events) >= max_events:
                capped = True
                break
    return events, {"matched_rows": len(matched), "capped": capped}


# ----------------------------------------------------------- derived rules
def _event_field_ok(name: str) -> bool:
    low = name.lower()
    return low in EVENT_FIELDS or (low.startswith("details.") and len(low) > 8)


def check_derived_rule(rule: dict) -> List[str]:
    """Why this derived rule cannot run ([] = it can). Its fields must be
    event fields or ``details.<key>``."""
    problems = []
    for cond in _all_conditions(rule):
        name = str(cond.get("field_name") or "")
        if not _event_field_ok(name):
            problems.append("'%s' is not a field of a behaviour event (use one of %s, "
                            "or details.<key>)." % (name, ", ".join(EVENT_FIELDS)))
    for name in template_fields(rule.get("description") or ""):
        if name.lower() not in _DERIVED_WORDS and not _event_field_ok(name):
            problems.append("The description names '{%s}', which is not a field of a "
                            "behaviour event." % name)
    return problems


def _event_record(event: dict, wanted_details) -> dict:
    """An event as the flat record a derived rule's conditions read: the
    event's fields plus ``details.<key>``. Every detail a condition names is
    present (None when the event lacks it), so a missing detail reads as
    "no value" instead of falling through to fuzzy field matching."""
    rec = {f: event.get(f) for f in EVENT_FIELDS}
    for key, value in (event.get("details") or {}).items():
        rec["details." + str(key)] = value if not isinstance(value, (dict, list)) else str(value)
    for key in wanted_details:
        rec.setdefault(key, None)
    return rec


def derived_rule_events(store, rule: dict, max_events: Optional[int] = MAX_EVENTS_PER_RULE
                        ) -> Tuple[List[BehaviorEvent], dict]:
    """(events, info) for one derived rule over the events in ``store``."""
    problems = check_derived_rule(rule)
    if problems:
        raise RuleRefused(" ".join(problems))
    base = rule.get("base") or {}
    ids = [str(x) for x in base.get("rule_ids") or [] if str(x).strip()]
    acts = [str(x) for x in base.get("activities") or [] if str(x).strip()]
    wanted = []
    for cond in _all_conditions(rule):
        name = str(cond.get("field_name") or "")
        if name.lower().startswith("details."):
            wanted.append("details." + name[8:])
    canon = {f.lower(): f for f in EVENT_FIELDS}

    def field_of(name):
        name = str(name or "")
        if name.lower().startswith("details."):
            return "details." + name[8:]
        return canon.get(name.lower(), name)

    srule = compile_rule(rule, field_of, feather=DERIVED_FEATHER)
    where, params = [], []
    if ids:
        where.append("rule_id IN ({})".format(",".join("?" for _ in ids)))
        params.extend(ids)
    if acts:
        where.append("activity IN ({})".format(",".join("?" for _ in acts)))
        params.extend(acts)
    sql = ("SELECT * FROM events WHERE ({}) AND rule_id != ? "
           "ORDER BY ts_start, event_id").format(" OR ".join(where))
    template = rule.get("description") or DEFAULT_DERIVED_DESCRIPTION
    events, matched, capped = [], 0, False
    for row in store.conn.execute(sql, params + [rule["id"]]).fetchall():
        ev = store._row_to_dict(row)
        rec = _event_record(ev, wanted)
        ok, _labels = srule.evaluate({DERIVED_FEATHER: rec})
        if not ok:
            continue
        matched += 1
        vals = dict(rec)
        vals.update({"actor": ev.get("actor_name") or "Someone",
                     "app": ev.get("app_name") or "", "time": ev.get("ts_start") or "",
                     "title": rule.get("title", ""), "count": ev.get("aggregate_count") or 1})
        details = dict(ev.get("details") or {})
        details["derived_from"] = {"rule_id": ev.get("rule_id"), "event_id": ev.get("event_id")}
        evidence = []
        for ref in ev.get("evidence") or []:
            try:
                evidence.append(EvidenceRef(
                    db=ref.get("db"), table=ref.get("table"), role=ref.get("role", "primary"),
                    rowids=list(ref.get("rowids") or []), rowid_range=ref.get("rowid_range"),
                    count=int(ref.get("count") or 0)))
            except Exception:
                continue
        events.append(BehaviorEvent(
            rule_id=rule["id"], behavior_class=rule["behavior_class"],
            activity=rule["activity"], ts_start=ev.get("ts_start"), ts_end=ev.get("ts_end"),
            actor_type=ev.get("actor_type") or "", actor_name=ev.get("actor_name") or "",
            actor_basis=ev.get("actor_basis") or "", actor_sid=ev.get("actor_sid") or "",
            description=render(template, vals), severity=rule["severity"],
            confidence=ev.get("confidence") or CONF_ARTIFACT_ONLY,
            session_context=ev.get("session_context") or "", caveat=ev.get("caveat") or "",
            session_user=ev.get("session_user") or "", app_name=ev.get("app_name") or "",
            host=ev.get("host") or "", aggregate_count=int(ev.get("aggregate_count") or 1),
            details=details, evidence=evidence, user_rule=True))
        if max_events and len(events) >= max_events:
            capped = True
            break
    return events, {"matched_rows": matched, "capped": capped}


# ------------------------------------------------------------------ preview
class _NoSessions:
    """A preview labels nothing with sessions: building them reads the whole
    Security log, and the preview is about whether the rule matches."""

    def context_for(self, _epoch):
        return ""

    def user_at(self, _epoch):
        return ""


def preview_table_rule(artifacts_dir: str, rule: dict, limit: int = 25,
                       max_events: Optional[int] = 5000) -> dict:
    """"Test on this case" for a table rule, on a pool of its own (call it on
    the thread that will use the result; its connections close here).

    {"ok", "problems", "count", "matched_rows", "capped", "events": [first
    ``limit`` events as dicts with "rowid"]}."""
    from uba.engine.attribution import ActorResolver
    from uba.engine.extractors.context import ExtractorContext
    from uba.utils.db_access import DbPool
    pool = DbPool(artifacts_dir)
    try:
        resolver = ActorResolver(pool)
        ctx = ExtractorContext(pool, resolver, _NoSessions())
        try:
            events, info = table_rule_events(ctx, rule, max_events=max_events)
        except RuleRefused as e:
            return {"ok": False, "problems": [str(e)], "count": 0, "events": []}
        for ev in events:
            if ev.actor_type == "User" and not ev.actor_sid and ev.actor_name:
                ev.actor_sid = resolver.sid_for_account(ev.actor_name)
        return {"ok": True, "problems": [], "count": len(events),
                "matched_rows": info["matched_rows"], "capped": info["capped"],
                "events": [_preview_row(ev) for ev in events[:limit]]}
    finally:
        pool.close()


def preview_derived_rule(store, rule: dict, limit: int = 25,
                         max_events: Optional[int] = 5000) -> dict:
    """"Test on this case" for a derived rule, over a stored analysis."""
    if store is None:
        return {"ok": False, "count": 0, "events": [],
                "problems": ["There is no analysis of this case yet: open User Behavior "
                             "once so the behaviours a derived rule filters exist."]}
    try:
        events, info = derived_rule_events(store, rule, max_events=max_events)
    except RuleRefused as e:
        return {"ok": False, "problems": [str(e)], "count": 0, "events": []}
    return {"ok": True, "problems": [], "count": len(events),
            "matched_rows": info["matched_rows"], "capped": info["capped"],
            "events": [_preview_row(ev) for ev in events[:limit]]}


def _preview_row(ev: BehaviorEvent) -> dict:
    ref = ev.evidence[0] if ev.evidence else None
    return {"ts_start": ev.ts_start, "actor_name": ev.actor_name, "actor_type": ev.actor_type,
            "actor_sid": ev.actor_sid, "actor_basis": ev.actor_basis,
            "description": ev.description, "app_name": ev.app_name,
            "severity": ev.severity, "aggregate_count": ev.aggregate_count,
            "evidence": "{}:{}:{}".format(ref.db, ref.table, ",".join(
                str(r) for r in ref.rowids[:5])) if ref else ""}


def is_user_meta(rule: dict) -> bool:
    return bool(rule.get("user_rule")) and rule.get("user_kind") in (KIND_TABLE, KIND_DERIVED)
