"""Evidence accounting and a cost preflight for a run over several machines
(Sentinel 14.6), used by execute_wing_partitioned.

**Accounting.** Every row of every feather the Wing reads, in every partition,
ends in exactly one place:

- ``in_matches`` - it is part of a match;
- a named drop bucket, in this order of precedence:
  ``outside_wing_targets`` (the Wing's target application / path / Event IDs
  exclude it), ``no_identity`` (nothing names what it is about),
  ``timeless_not_joined`` (its feather has no time at all and its identity
  joined no match), ``no_timestamp`` (no time it could be placed in a window
  by), ``uncorroborated`` (named and timed, but no other feather backed it
  inside the Wing's window - the engine's corroboration floor);
- ``pending`` - the whole feather, when the caller says it has not arrived yet
  (``pending={agent_id: [feather_id, ...]}``). Pending is never dropped and
  never read: the rows are not there to count.

A feather a partition names with no file is ``not_collected`` (0 rows, nothing
dropped). Per partition and feather the buckets sum to the rows: the check is
in ``balanced``, and a mismatch is reported, never hidden.

**Preflight.** ``preflight(wing, partitions, max_cost)`` counts each
partition's rows (COUNT(*), no row read) and estimates the work: a same_host
Wing sorts each machine's rows on its own (sum of n log2 n), an any_host Wing
sorts every machine's rows together (N log2 N), and each sequence or
composition rule adds a hash join over its feathers' rows. Past ``max_cost``
the run is refused (``PreflightRefused``, carrying the estimate) before any
engine starts.
"""

import json
import math
import os
import sqlite3
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

BUCKETS = ("outside_wing_targets", "no_identity", "timeless_not_joined", "no_timestamp",
           "uncorroborated")


class PreflightRefused(RuntimeError):
    """The estimated cost is past the caller's threshold; ``estimate`` says why."""

    def __init__(self, estimate: Dict[str, Any]):
        super().__init__("Wing %r refused by preflight: estimated cost %s is above %s"
                         % (estimate.get("wing_id"), estimate.get("cost_units"),
                            estimate.get("max_cost")))
        self.estimate = estimate


def _ro(path):
    return sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True)


def _tables(con) -> List[str]:
    return [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "AND name != 'feather_metadata'")]


def _rows_in(path) -> int:
    con = _ro(path)
    try:
        return sum(con.execute('SELECT COUNT(*) FROM "%s"' % t.replace('"', '""')).fetchone()[0]
                   for t in _tables(con))
    finally:
        con.close()


def _pending_of(pending) -> Dict[str, Set[str]]:
    return {a: set(f or []) for a, f in (pending or {}).items()}


# --------------------------------------------------------------- preflight --
def preflight(wing, partitions: Dict[str, Dict[str, str]], max_cost: Optional[float] = None,
              pending=None) -> Dict[str, Any]:
    """The estimate (see the module docstring); ``allowed`` is False past
    ``max_cost``. Reads row counts only."""
    from .partitioned import _scope_of
    from .fleet_rules import _rules_of, _cross_conditions
    scope = _scope_of(wing)
    held = _pending_of(pending)
    per_partition: Dict[str, Dict[str, Any]] = {}
    for agent in sorted(partitions):
        feathers = {}
        for fid, path in sorted(partitions[agent].items()):
            if fid in held.get(agent, set()):
                feathers[fid] = "pending"
            elif path and os.path.isfile(path):
                feathers[fid] = _rows_in(path)
            else:
                feathers[fid] = "not_collected"
        per_partition[agent] = feathers

    def rows(agent, fids=None):
        return sum(v for f, v in per_partition[agent].items()
                   if isinstance(v, int) and (fids is None or f in fids))

    total = sum(rows(a) for a in per_partition)
    if scope == "same_host":
        scan = sum(rows(a) * math.log2(rows(a) + 1) for a in per_partition)
    else:
        scan = total * math.log2(total + 1)
    joins = []
    for rule in _rules_of(wing):
        kind = str(rule.get("rule_type") or "match").lower()
        if kind == "sequence":
            fids = set()
            for st in (rule.get("sequence") or {}).get("steps") or []:
                for c in (st.get("conditions") if isinstance(st, dict) and "conditions" in st
                          else [st]):
                    if isinstance(c, dict) and c.get("feather_id"):
                        fids.add(c["feather_id"])
        elif kind == "match":
            fids = {x for c in _cross_conditions(rule)
                    for x in (c.get("feather_id"), c.get("compare_to_feather"))}
        else:
            continue
        n = sum(rows(a, fids) for a in per_partition)
        joins.append({"rule_id": rule.get("rule_id"), "kind": "hash_join", "rows": n})
    cost = round(scan + sum(j["rows"] for j in joins), 1)
    estimate = {"wing_id": getattr(wing, "wing_id", None), "host_scope": scope,
                "partitions": len(per_partition), "rows": total,
                "per_partition": per_partition, "scan_cost": round(scan, 1), "joins": joins,
                "cost_units": cost, "max_cost": max_cost,
                "allowed": max_cost is None or cost <= max_cost,
                "pending": {a: sorted(f) for a, f in held.items() if f}}
    return estimate


# -------------------------------------------------------------- accounting --
def _signature(row: Dict[str, Any], columns: Iterable[str]) -> Tuple:
    return tuple("" if row.get(c) is None else str(row.get(c)) for c in columns)


def _match_rows(result, partitions) -> Dict[Tuple[str, str], List[Dict[str, Any]]]:
    """(agent, feather_id) -> the rows the matches hold."""
    from .partitioned import AGENT_COLUMN
    out: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for m in result.matches or []:
        for fid, value in (m.feather_records or {}).items():
            rows = value if isinstance(value, list) else [value]
            for r in rows:
                if not isinstance(r, dict):
                    continue
                agent = r.get(AGENT_COLUMN) or m.agent_id or (m.hosts[0] if m.hosts else None)
                if agent is not None:
                    out[(str(agent), fid)].append(r)
    return out


def account(result, wing, partitions: Dict[str, Dict[str, str]], pending=None) -> Dict[str, Any]:
    """Where every row went (see the module docstring)."""
    from .fleet_rules import _evaluator, _identity
    from .time_based_engine import CORE_IDENTITY_FIELDS
    from ..config import feather_schemas as fs
    targets = None
    try:
        from .wing_targets import WingTargets
        t = WingTargets(wing, CORE_IDENTITY_FIELDS)
        targets = t if t.active else None
    except Exception:
        targets = None
    held = _pending_of(pending)
    ev = _evaluator()
    matched = _match_rows(result, partitions)
    per: Dict[str, Dict[str, Any]] = {}
    totals = defaultdict(int)
    balanced = True
    for agent in sorted(partitions):
        per[agent] = {}
        for fid, path in sorted(partitions[agent].items()):
            if fid in held.get(agent, set()):
                per[agent][fid] = {"status": "pending"}
                totals["pending_feathers"] += 1
                continue
            if not path or not os.path.isfile(path):
                per[agent][fid] = {"status": "not_collected", "rows": 0}
                totals["not_collected_feathers"] += 1
                continue
            entry = {"status": "read", "rows": 0, "in_matches": 0}
            entry.update({b: 0 for b in BUCKETS})
            con = _ro(path)
            con.row_factory = sqlite3.Row
            try:
                for table in _tables(con):
                    cols = [r[1] for r in con.execute('PRAGMA table_info("%s")'
                                                      % table.replace('"', '""'))]
                    in_match = {_signature(r, cols) for r in matched.get((agent, fid), [])}
                    ts_cols = fs.all_timestamp_columns(table, cols) or []
                    timeless = not ts_cols and not any(
                        c in cols for c in ev._TS_FIELD_CANDIDATES)
                    for row in con.execute('SELECT * FROM "%s"' % table.replace('"', '""')):
                        row = dict(row)
                        entry["rows"] += 1
                        if _signature(row, cols) in in_match:
                            entry["in_matches"] += 1
                        elif targets is not None and not targets.record_matches(row):
                            entry["outside_wing_targets"] += 1
                        elif not _identity(table, row):
                            entry["no_identity"] += 1
                        elif timeless:
                            entry["timeless_not_joined"] += 1
                        elif ev._row_ts(row) is None and not any(
                                ev._parse_ts(row.get(c)) for c in ts_cols):
                            entry["no_timestamp"] += 1
                        else:
                            entry["uncorroborated"] += 1
            finally:
                con.close()
            entry["balanced"] = entry["rows"] == entry["in_matches"] + sum(entry[b] for b in BUCKETS)
            balanced = balanced and entry["balanced"]
            for k in ("rows", "in_matches") + BUCKETS:
                totals[k] += entry[k]
            per[agent][fid] = entry
    return {"per_partition": per, "totals": dict(totals), "buckets": list(BUCKETS),
            "balanced": balanced}
