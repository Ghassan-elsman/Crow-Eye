"""A Wing's advanced rules across a fleet (Sentinel 14.3), run with
``execute_wing_partitioned``.

On one case a rule is judged over one machine. Across machines each rule type
has to say what it means, and this module refuses a rule that does not:

- **Absence** declares ``absence.scope``: ``absent_on_host`` (the expected trace
  is on a host and the required-absent trace is not on that host) or
  ``absent_everywhere`` (on an any_host Wing: no partition holds the trace). A
  host whose partition has no file for the absent feather never collected it:
  it comes out ``not_collected``, never ``absent``. "absent_everywhere" with a
  host that did not collect the feather is ``not_collected`` too, naming it.
- **Threshold** declares ``threshold.denominator``: ``per_host`` (the count is
  reached on one machine) or ``per_fleet`` (the machines' rows are counted
  together). The hosts that did not collect the feather are listed.
- **Sequence** steps may sit on different machines on an any_host Wing. Each
  step after the first is joined to the one before as a hash join on the join
  key (``sequence.join_fields``, or the identity when none are given): its
  candidates are bucketed by key once, then probed - never every row against
  every row. On a same_host Wing the host is part of the key.
- **Composition** - a match rule whose condition compares a field with another
  feather's field (``compare_to_feather`` / ``compare_to_field``) - may compare
  rows of two different machines on an any_host Wing. An equality is a hash
  join on the compared value; any other operator cannot be planned as a join
  and is refused with the reason, not scanned.

Every join's plan (kind, key, rows built, rows probed, pairs) is in
``partition_info['rule_plans']``. Rows are read once per partition and feather,
and only rows that satisfy one of the rules' conditions are kept, so memory
follows the hits, not the fleet's size.

A hit is a dict: rule_id, rule_type, status (``fired`` / ``absent`` /
``not_collected``), identity, hosts, and what each type adds (scope,
denominator, count, per_host counts, steps, join value, hosts_not_collected,
feathers_not_collected, first_seen / last_seen). The list is in a fixed order.
"""

import logging
import os
import sqlite3
from collections import defaultdict
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

ABSENCE_SCOPES = ("absent_on_host", "absent_everywhere")
THRESHOLD_DENOMINATORS = ("per_host", "per_fleet")
ADVANCED = ("absence", "threshold", "sequence")


class FleetRuleError(ValueError):
    """A rule that does not say what it means across machines."""


def _evaluator():
    """The evaluator's row helpers (timestamps, windows) without its setup."""
    from .semantic_rule_evaluator import SemanticRuleEvaluator
    return object.__new__(SemanticRuleEvaluator)


def _cond(spec):
    from ..config.semantic_mapping import SemanticCondition
    return SemanticCondition.from_dict(spec)


def _lookup(row, field):
    from ..config.semantic_mapping import SemanticCondition
    return SemanticCondition._smart_field_lookup(row, field)


def _rules_of(wing) -> List[Dict[str, Any]]:
    out = []
    for r in getattr(wing, "semantic_rules", None) or []:
        if not isinstance(r, dict):
            continue
        kind = str(r.get("rule_type") or "match").lower()
        if kind in ADVANCED or _cross_conditions(r):
            out.append(r)
    return out


def _cross_conditions(rule) -> List[Dict[str, Any]]:
    """A rule's comparisons of one feather's field with ANOTHER feather's - a
    join between rows. One that compares two fields of the same feather
    ($SI created before $FN created on one MFT record) is a test on one row,
    which the engine already makes on each machine; it is not a join and the
    fleet does not plan one."""
    return [c for c in rule.get("conditions") or []
            if isinstance(c, dict) and c.get("compare_to_feather") and c.get("compare_to_field")
            and c.get("compare_to_feather") != c.get("feather_id")]


def _step_specs(step) -> List[Dict[str, Any]]:
    if not isinstance(step, dict):
        return []
    if "conditions" in step:
        return [c for c in step.get("conditions") or [] if isinstance(c, dict)]
    if "feather_id" in step and "field_name" in step:
        return [step]
    return []


# ----------------------------------------------------------------- reading --
class _Rows:
    """The rows each rule condition matched, per partition: (host, identity,
    ts, row). Read once per partition and feather."""

    def __init__(self, partitions, wanted: Dict[str, List[Any]], pending=None):
        self.partitions = partitions
        self.pending = {a: set(f or []) for a, f in (pending or {}).items()}
        self.collected = {a: {f for f, p in paths.items() if p and os.path.isfile(p)
                              and f not in self.pending.get(a, set())}
                          for a, paths in partitions.items()}
        self.ev = _evaluator()
        self.hits: Dict[int, List[Tuple[str, str, Any, dict]]] = defaultdict(list)
        self.rows_read = 0
        for agent in sorted(partitions):
            for fid, conds in sorted(wanted.items()):
                path = partitions[agent].get(fid)
                if not path or fid not in self.collected[agent]:
                    continue
                for table, row in _feather_rows(path):
                    self.rows_read += 1
                    ident = None
                    for c in conds:
                        if c.matches(row, None):
                            if ident is None:
                                ident = _identity(table, row) or ""
                            self.hits[id(c)].append((agent, ident, self.ev._row_ts(row), row))

    def of(self, cond):
        return self.hits.get(id(cond), [])


def _feather_rows(path):
    con = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True)
    con.row_factory = sqlite3.Row
    try:
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "AND name != 'feather_metadata'")]
        for table in tables:
            for r in con.execute('SELECT * FROM "%s"' % table.replace('"', '""')):
                yield table, dict(r)
    finally:
        con.close()


def _identity(table, row) -> Optional[str]:
    """The same identity the time-window engine gives the row."""
    from .identity_grouping import identity_key
    from .time_based_engine import CORE_IDENTITY_FIELDS
    from ..config import feather_schemas as fs
    fields = []
    schema = fs.get_schema(table) or {}
    if schema.get("table_kind") == "execution_evidence":
        fields.extend(schema.get("identity_columns_preferred") or [])
    fields.extend(CORE_IDENTITY_FIELDS)
    for f in fields:
        v = row.get(f)
        if v and str(v).strip():
            return identity_key(str(v).strip())
    return None


# ---------------------------------------------------------------- helpers --
def _span(rows) -> Dict[str, Optional[str]]:
    times = sorted(t for t in (r[2] for r in rows) if t is not None)
    if not times:
        return {"first_seen": None, "last_seen": None}
    return {"first_seen": times[0].isoformat(sep=" "), "last_seen": times[-1].isoformat(sep=" ")}


def _densest(rows, within, slack_s):
    """The most rows inside any ``within`` minutes (widened by the clock
    skew between the machines), and those rows."""
    if not within:
        return len(rows), rows
    timed = sorted((r for r in rows if r[2] is not None), key=lambda r: r[2])
    if len(timed) < 2:
        return len(rows), rows
    window = timedelta(minutes=float(within), seconds=slack_s)
    best, best_slice, start = 0, (0, 0), 0
    for end in range(len(timed)):
        while timed[end][2] - timed[start][2] > window:
            start += 1
        if end - start + 1 > best:
            best, best_slice = end - start + 1, (start, end + 1)
    return best, timed[best_slice[0]:best_slice[1]]


# ------------------------------------------------------------------ rules --
def _absence(rule, scope_of_wing, rows: _Rows, agents, slack_s):
    spec = rule.get("absence") or {}
    scope = spec.get("scope")
    if scope not in ABSENCE_SCOPES:
        raise FleetRuleError("absence rule %r declares no scope (%s)"
                             % (rule.get("rule_id"), " or ".join(ABSENCE_SCOPES)))
    if scope == "absent_everywhere" and scope_of_wing != "any_host":
        raise FleetRuleError("absence rule %r is absent_everywhere on a same_host Wing: a "
                             "same_host Wing never reads two machines" % rule.get("rule_id"))
    expect = rule["_expect"]
    absent = rule["_absent"]
    absent_fids = sorted({c.feather_id for c in absent})
    within = spec.get("within_minutes")
    win = timedelta(minutes=float(within), seconds=slack_s) if within else None

    # identity -> host -> [rows] per expected condition
    present: Dict[str, Dict[str, List[list]]] = defaultdict(lambda: defaultdict(lambda: [[] for _ in expect]))
    for i, c in enumerate(expect):
        for hit in rows.of(c):
            present[hit[1]][hit[0]][i].append(hit)
    traces: Dict[str, Dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for c in absent:
        for hit in rows.of(c):
            traces[hit[1]][hit[0]].append(hit)

    def near(trace_rows, anchors):
        if win is None:
            return bool(trace_rows)
        times = [a[2] for a in anchors if a[2] is not None]
        if not times:
            return bool(trace_rows)
        return any(t[2] is None or any(abs(t[2] - a) <= win for a in times) for t in trace_rows)

    out = []
    for ident in sorted(present):
        by_host = present[ident]
        hosts_present = sorted(h for h, per in by_host.items() if all(per))
        if scope == "absent_on_host":
            for h in hosts_present:
                anchors = [r for per in by_host[h] for r in per]
                missing = [f for f in absent_fids if f not in rows.collected.get(h, set())]
                waiting = [f for f in missing if f in rows.pending.get(h, set())]
                base = {"rule_id": rule.get("rule_id"), "rule_type": "absence", "scope": scope,
                        "identity": ident, "hosts": [h], **_span(anchors)}
                if waiting:
                    out.append(dict(base, status="pending", hosts_pending=[h],
                                    feathers_pending=waiting))
                elif missing:
                    out.append(dict(base, status="not_collected", hosts_not_collected=[h],
                                    feathers_not_collected=missing))
                elif not near(traces[ident].get(h, []), anchors):
                    out.append(dict(base, status="absent"))
        else:
            if not all(any(by_host[h][i] for h in by_host) for i in range(len(expect))):
                continue
            anchors = [r for h in by_host for per in by_host[h] for r in per]
            all_traces = [t for h in traces[ident] for t in traces[ident][h]]
            if near(all_traces, anchors):
                continue
            missing_hosts = sorted(a for a in agents
                                   if any(f not in rows.collected.get(a, set()) for f in absent_fids))
            waiting_hosts = sorted(a for a in missing_hosts
                                   if any(f in rows.pending.get(a, set()) for f in absent_fids))
            base = {"rule_id": rule.get("rule_id"), "rule_type": "absence", "scope": scope,
                    "identity": ident, "hosts": sorted(by_host), **_span(anchors)}
            if waiting_hosts:
                out.append(dict(base, status="pending", hosts_pending=waiting_hosts,
                                feathers_pending=absent_fids))
            elif missing_hosts:
                out.append(dict(base, status="not_collected", hosts_not_collected=missing_hosts,
                                feathers_not_collected=absent_fids))
            else:
                out.append(dict(base, status="absent"))
    return out


def _threshold(rule, rows: _Rows, agents, slack_s):
    spec = rule.get("threshold") or {}
    denominator = spec.get("denominator")
    if denominator not in THRESHOLD_DENOMINATORS:
        raise FleetRuleError("threshold rule %r declares no denominator (%s)"
                             % (rule.get("rule_id"), " or ".join(THRESHOLD_DENOMINATORS)))
    conds = rule["_conds"]
    min_count = int(spec.get("min_count", 2) or 2)
    within = spec.get("within_minutes")
    group_by = spec.get("group_by")
    fids = sorted({c.feather_id for c in conds})
    not_collected = sorted(a for a in agents if any(f not in rows.collected.get(a, set())
                                                    and f not in rows.pending.get(a, set())
                                                    for f in fids))
    waiting = sorted(a for a in agents if any(f in rows.pending.get(a, set()) for f in fids))
    groups: Dict[Tuple[str, str], List[tuple]] = defaultdict(list)
    seen = set()
    for c in conds:
        for hit in rows.of(c):
            if id(hit[3]) in seen:
                continue
            seen.add(id(hit[3]))
            key = str(_lookup(hit[3], group_by)) if group_by else hit[1]
            groups[(key, "")].append(hit)
    out = []
    for (key, _), grp in sorted(groups.items()):
        if denominator == "per_host":
            for h in sorted({g[0] for g in grp}):
                mine = [g for g in grp if g[0] == h]
                n, witness = _densest(mine, within, 0)
                if n >= min_count:
                    out.append({"rule_id": rule.get("rule_id"), "rule_type": "threshold",
                                "denominator": denominator, "status": "fired", "identity": key,
                                "hosts": [h], "count": n, "min_count": min_count,
                                **_span(witness)})
        else:
            n, witness = _densest(grp, within, slack_s)
            if n >= min_count:
                per_host = defaultdict(int)
                for g in witness:
                    per_host[g[0]] += 1
                out.append({"rule_id": rule.get("rule_id"), "rule_type": "threshold",
                            "denominator": denominator, "status": "fired", "identity": key,
                            "hosts": sorted(per_host), "count": n, "min_count": min_count,
                            "per_host": dict(sorted(per_host.items())),
                            "hosts_not_collected": not_collected, "hosts_pending": waiting,
                            **_span(witness)})
    return out


def _sequence(rule, scope, rows: _Rows, slack_s, plans):
    spec = rule.get("sequence") or {}
    steps = rule["_steps"]
    if len(steps) < 2:
        return []
    join_fields = spec.get("join_fields") or []
    if isinstance(join_fields, str):
        join_fields = [join_fields]
    max_gap = spec.get("max_gap_minutes")
    gap = timedelta(minutes=float(max_gap), seconds=slack_s) if max_gap is not None else None

    def key(hit):
        parts = []
        if join_fields:
            for f in join_fields:
                v = _lookup(hit[3], f)
                if v is None or str(v) == "":
                    return None
                parts.append(str(v).strip().lower())
        else:
            parts.append(hit[1])
        if scope == "same_host":
            parts.append(hit[0])
        return tuple(parts)

    # Each step's candidates, bucketed by join key once (the build side).
    buckets = []
    built = []
    for conds in steps:
        b: Dict[tuple, list] = defaultdict(list)
        n = 0
        for c in conds:
            for hit in rows.of(c):
                k = key(hit)
                if k is None or hit[2] is None:
                    continue
                b[k].append(hit)
                n += 1
        for k in b:
            b[k].sort(key=lambda h: h[2])
        buckets.append(b)
        built.append(n)
    probes = 0
    out = []
    for k in sorted(buckets[0]):
        probes += 1
        if not all(k in b for b in buckets[1:]):
            continue
        chain = _chain(buckets, k, gap)
        if chain:
            hosts = sorted({h[0] for h in chain})
            out.append({"rule_id": rule.get("rule_id"), "rule_type": "sequence", "status": "fired",
                        "identity": chain[0][1], "join_key": list(k[:len(join_fields)] if join_fields
                                                                   else k[:1]),
                        "hosts": hosts, "cross_host": len(hosts) > 1,
                        "steps": [{"host": h[0], "time": h[2].isoformat(sep=" ")} for h in chain],
                        **_span(chain)})
    plans.append({"rule_id": rule.get("rule_id"), "rule_type": "sequence", "join": "hash",
                  "on": list(join_fields) or ["identity"] + (["host"] if scope == "same_host" else []),
                  "build_rows_per_step": built, "keys_probed": probes, "chains": len(out)})
    return out


def _chain(buckets, k, gap):
    """One record per step, in time order, each gap within ``gap``."""
    chosen = []

    def search(i, prev):
        if i == len(buckets):
            return True
        for hit in buckets[i][k]:
            if prev is not None:
                if hit[2] < prev:
                    continue
                if gap is not None and hit[2] - prev > gap:
                    break
            if any(hit is c for c in chosen):
                continue
            chosen.append(hit)
            if search(i + 1, hit[2]):
                return True
            chosen.pop()
        return False
    return list(chosen) if search(0, None) else None


def _composition(rule, scope, rows: _Rows, plans):
    out = []
    for spec in _cross_conditions(rule):
        op = str(spec.get("operator") or "equals").lower()
        plan = {"rule_id": rule.get("rule_id"), "rule_type": "composition",
                "left": "%s.%s" % (spec.get("feather_id"), spec.get("field_name")),
                "right": "%s.%s" % (spec.get("compare_to_feather"), spec.get("compare_to_field"))}
        if op != "equals":
            plans.append(dict(plan, join="not_planned",
                              reason="only an equality can be planned as a join; %r would "
                                     "compare every row with every row" % op))
            continue
        left_c, right_c = rule["_cross"][id(spec)]
        # Build on the right side, probe with the left (a hash join on the value).
        table: Dict[str, list] = defaultdict(list)
        for hit in rows.of(right_c):
            v = _lookup(hit[3], spec["compare_to_field"])
            if v is not None and str(v).strip():
                table[str(v).strip().lower()].append(hit)
        probes = pairs = 0
        found: Dict[str, Dict[str, Any]] = {}
        for hit in rows.of(left_c):
            v = _lookup(hit[3], spec["field_name"])
            if v is None or not str(v).strip():
                continue
            probes += 1
            value = str(v).strip().lower()
            for other in table.get(value, ()):
                if scope == "same_host" and other[0] != hit[0]:
                    continue
                pairs += 1
                entry = found.setdefault(value, {"hosts": set(), "rows": []})
                entry["hosts"].update((hit[0], other[0]))
                entry["rows"].extend((hit, other))
        for value in sorted(found):
            hosts = sorted(found[value]["hosts"])
            out.append({"rule_id": rule.get("rule_id"), "rule_type": "composition",
                        "status": "fired", "join_value": value, "hosts": hosts,
                        "cross_host": len(hosts) > 1, **_span(found[value]["rows"])})
        plans.append(dict(plan, join="hash", on=plan["right"], build_rows=sum(
            len(v) for v in table.values()), probe_rows=probes, pairs=pairs))
    return out


# ------------------------------------------------------------------ entry --
def evaluate_fleet_rules(wing, partitions: Dict[str, Dict[str, str]], scope: str,
                         clock_skew_s: Optional[Dict[str, float]] = None, pending=None
                         ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """The Wing's absence, threshold, sequence and composition rules over every
    partition. Returns (hits, info): info holds rule_plans, rows_read,
    collected (agent -> feathers present) and refused (rule_id -> reason).
    A rule that does not declare its fleet meaning is refused, never run with
    a default."""
    agents = sorted(partitions)
    skew = {a: float((clock_skew_s or {}).get(a) or 0.0) for a in agents}
    slack_s = (max(skew.values()) - min(skew.values())) if (skew and scope == "any_host") else 0.0
    rules = _rules_of(wing)
    refused: Dict[str, str] = {}
    wanted: Dict[str, List[Any]] = defaultdict(list)
    ready = []
    for rule in rules:
        rule = dict(rule)
        kind = str(rule.get("rule_type") or "match").lower()
        try:
            if kind == "absence":
                spec = rule.get("absence") or {}
                rule["_expect"] = [_cond(s) for s in spec.get("expect_present") or []]
                rule["_absent"] = [_cond(s) for s in spec.get("require_absent") or []]
                conds = rule["_expect"] + rule["_absent"]
            elif kind == "threshold":
                spec = rule.get("threshold") or {}
                specs = [spec["condition"]] if spec.get("condition") else spec.get("conditions") or []
                rule["_conds"] = [_cond(s) for s in specs]
                conds = rule["_conds"]
            elif kind == "sequence":
                spec = rule.get("sequence") or {}
                rule["_steps"] = [[_cond(s) for s in _step_specs(st)] for st in spec.get("steps") or []]
                conds = [c for st in rule["_steps"] for c in st]
            else:
                rule["_cross"] = {}
                conds = []
                for spec in _cross_conditions(rule):
                    left = _cond({k: v for k, v in spec.items()
                                  if k not in ("compare_to_feather", "compare_to_field")
                                  } | {"value": "*", "operator": "wildcard"})
                    right = _cond({"feather_id": spec["compare_to_feather"],
                                   "field_name": spec["compare_to_field"], "value": "*",
                                   "operator": "wildcard"})
                    rule["_cross"][id(spec)] = (left, right)
                    conds += [left, right]
        except (ValueError, KeyError, TypeError) as exc:
            refused[str(rule.get("rule_id"))] = "invalid condition: %s" % exc
            continue
        for c in conds:
            wanted[c.feather_id].append(c)
        ready.append((kind, rule))

    rows = _Rows(partitions, wanted, pending)
    hits: List[Dict[str, Any]] = []
    plans: List[Dict[str, Any]] = []
    for kind, rule in ready:
        try:
            if kind == "absence":
                hits.extend(_absence(rule, scope, rows, agents, slack_s))
            elif kind == "threshold":
                hits.extend(_threshold(rule, rows, agents, slack_s))
            elif kind == "sequence":
                hits.extend(_sequence(rule, scope, rows, slack_s, plans))
            else:
                hits.extend(_composition(rule, scope, rows, plans))
        except FleetRuleError as exc:
            refused[str(rule.get("rule_id"))] = str(exc)
    hits.sort(key=lambda h: (str(h.get("rule_id")), str(h.get("first_seen") or ""),
                             str(h.get("identity") or h.get("join_value") or ""),
                             ",".join(h.get("hosts") or [])))
    info = {"rule_plans": plans, "rows_read": rows.rows_read,
            "collected": {a: sorted(rows.collected[a]) for a in agents}, "refused": refused}
    return hits, info
