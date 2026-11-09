"""Running a Wing over several machines' feathers in one pass (Sentinel 14.4, E4).

``execute_wing_partitioned(engine, wing, partitions, clock_skew_s=None,
max_workers=1)``: ``partitions`` is ``{agent_id: {feather_id: path}}`` - each
agent's own feathers, named by the feather ids the Wing uses, exactly what
``engine.execute_wing(wing, feather_paths)`` takes for one machine.

The Wing's ``host_scope`` (14.2) decides how they are read:

- **same_host**: one pass per agent, never two agents' rows in one pass, so a
  match can never pair rows from two machines. Partitions run one after the
  other (``max_workers`` = 1, the default, one partition's records in memory at
  a time) or in up to ``max_workers`` processes, each with an engine of its own
  - the engines keep state of their own and are not run side by side in one
  process.
  Every match carries its ``agent_id``.
- **any_host**: each feather the Wing uses is merged across agents into one
  temporary database on disk, every row stamped with its ``agent_id``, and the
  Wing runs once over the merged feathers. A match lists the agents its rows
  came from in ``hosts``. When ``clock_skew_s`` (``{agent_id: seconds}``, how
  far that machine's clock is from true time) is given, the Wing's time window
  is widened by the largest skew between any two agents, and every match
  spanning two or more machines carries ``max_clock_skew_s`` - the skew
  between its own hosts - as a confidence qualifier: co-occurrence across
  machines is a claim about two clocks, and it says so.

A Wing without a host scope is refused (``WingScopeError``), never defaulted.

The order of the matches is fixed: by the earliest time among a match's rows,
then by agent (``agent_id``, or the hosts joined), then by the rows themselves;
and each match_id is derived from the Wing, the agents and the rows - not
random - so two runs over the same feathers give the same result, byte for
byte.
"""

import copy
import contextlib
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import tempfile
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

AGENT_COLUMN = "agent_id"
_TIME_KEYS = ("timestamp", "Timestamp", "time", "event_time", "EventTimestampUTC")


def _scope_of(wing):
    from ..config.wing_config import WingScopeError, normalize_host_scope
    scope = normalize_host_scope(getattr(wing, "host_scope", None))
    if scope is None:
        raise WingScopeError("Wing %r declares no host_scope; a partitioned run needs one"
                             % getattr(wing, "wing_name", getattr(wing, "wing_id", "?")))
    return scope


def _window_minutes(wing):
    rules = getattr(wing, "correlation_rules", None)
    if rules is not None and hasattr(rules, "time_window_minutes"):
        return rules.time_window_minutes
    return getattr(wing, "time_window_minutes", 180)


def _set_window_minutes(wing, minutes):
    rules = getattr(wing, "correlation_rules", None)
    if rules is not None and hasattr(rules, "time_window_minutes"):
        rules.time_window_minutes = minutes
    if hasattr(wing, "time_window_minutes"):
        wing.time_window_minutes = minutes


def _records(match):
    """Every row a match holds: an engine keeps one row or a list of rows per feather."""
    for value in (match.feather_records or {}).values():
        if isinstance(value, dict):
            yield value
        elif isinstance(value, (list, tuple)):
            for rec in value:
                if isinstance(rec, dict):
                    yield rec


def _first_time(match):
    times = []
    for rec in _records(match):
        for key in _TIME_KEYS:
            if rec.get(key):
                times.append(str(rec[key]))
                break
    return min(times) if times else str(match.timestamp or "")


def _rows_key(match):
    return json.dumps(match.feather_records or {}, sort_keys=True, default=str)


def _with_rules(result, wing, partitions, scope, clock_skew_s, pending=None):
    """The Wing's absence / threshold / sequence / composition rules across the
    partitions (engine/fleet_rules.py, Sentinel 14.3), when it has any."""
    from .fleet_rules import _rules_of, evaluate_fleet_rules
    if not _rules_of(wing):
        return result
    hits, info = evaluate_fleet_rules(wing, partitions, scope, clock_skew_s, pending=pending)
    result.fleet_rule_hits = hits
    result.partition_info.update(rule_plans=info["rule_plans"], rules_refused=info["refused"],
                                 collected=info["collected"], rule_rows_read=info["rows_read"])
    return result


def _settle(result, wing, matches):
    """The matches in their fixed order, with ids derived from their content."""
    matches.sort(key=lambda m: (_first_time(m), m.agent_id or ",".join(m.hosts or []),
                                _rows_key(m)))
    for m in matches:
        basis = "|".join([str(getattr(wing, "wing_id", "")), m.agent_id or "",
                          ",".join(m.hosts or []), _rows_key(m)])
        m.match_id = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:32]
    result.matches = matches
    result.total_matches = len(matches)
    return result


@contextlib.contextmanager
def _matches_in_memory(engine):
    """The engine keeps this run's matches on the result instead of streaming
    them to a results database under memory pressure: a streamed match could
    not be given its agent. Memory stays bounded by one partition (one
    machine) at a time. Restored afterwards."""
    had = "_output_dir" in vars(engine)
    saved = getattr(engine, "_output_dir", None)
    engine._output_dir = None
    engine._check_memory_and_enable_streaming = lambda *a, **k: None
    try:
        yield
    finally:
        vars(engine).pop("_check_memory_and_enable_streaming", None)
        if had:
            engine._output_dir = saved
        else:
            vars(engine).pop("_output_dir", None)


def _partition_worker(engine_class, config, filters, wing, agent_id, feather_paths):
    """One partition in a worker process: a new engine of the caller's kind and
    configuration, its matches tagged and returned."""
    engine = engine_class(config, filters)
    result = _run_one(engine, wing, agent_id, feather_paths)
    result._db_writer = None
    return result


def _run_one(engine, wing, agent_id, feather_paths):
    with _matches_in_memory(engine):
        result = engine.execute_wing(wing, feather_paths)
    for m in result.matches or []:
        m.agent_id = agent_id
        m.hosts = [agent_id]
    return result


def execute_wing_partitioned(engine, wing, partitions: Dict[str, Dict[str, str]],
                             clock_skew_s: Optional[Dict[str, float]] = None,
                             max_workers: int = 1, work_dir: Optional[str] = None,
                             pending: Optional[Dict[str, Any]] = None,
                             max_cost: Optional[float] = None, account: bool = True) -> Any:
    """See the module docstring. Returns one CorrelationResult for all agents,
    with ``partition_info`` saying how it was run.

    ``pending``: {agent_id: [feather_id, ...]} not arrived yet - not read, never
    dropped, reported as pending (engine/fleet_accounting.py). ``max_cost``: the
    run is refused (PreflightRefused, with the estimate) when the preflight's
    estimate is above it. ``account``: say where every row went
    (partition_info['accounting']); False skips that second read."""
    from .correlation_result import CorrelationResult
    from .fleet_accounting import PreflightRefused, preflight
    scope = _scope_of(wing)
    if not isinstance(partitions, dict) or not partitions:
        raise ValueError("partitions must be a non-empty {agent_id: {feather_id: path}}")
    estimate = None
    if max_cost is not None:
        estimate = preflight(wing, partitions, max_cost, pending)
        if not estimate["allowed"]:
            raise PreflightRefused(estimate)
    full_partitions = partitions
    held = {a: set(f or []) for a, f in (pending or {}).items()}
    partitions = {a: {f: p for f, p in paths.items() if f not in held.get(a, set())}
                  for a, paths in partitions.items()}
    agents = sorted(partitions)
    max_workers = max(1, int(max_workers or 1))
    skew = {a: float((clock_skew_s or {}).get(a) or 0.0) for a in agents}
    result = CorrelationResult(wing_id=getattr(wing, "wing_id", ""),
                               wing_name=getattr(wing, "wing_name", ""))
    info = {"host_scope": scope, "agents": agents, "max_workers": max_workers,
            "matches_held_in_memory": True}

    if scope == "same_host":
        if max_workers == 1:
            outcomes = [(a, _run_one(engine, wing, a, partitions[a])) for a in agents]
        else:
            with ProcessPoolExecutor(max_workers=min(max_workers, len(agents))) as pool:
                futures = [(a, pool.submit(_partition_worker, type(engine), engine.config,
                                           getattr(engine, "filters", None), wing, a,
                                           partitions[a])) for a in agents]
                outcomes = [(a, f.result()) for a, f in futures]
        matches = []
        for agent, sub in outcomes:
            matches.extend(sub.matches or [])
            result.total_records_scanned += getattr(sub, "total_records_scanned", 0) or 0
            result.errors.extend(["%s: %s" % (agent, e) for e in (getattr(sub, "errors", None) or [])])
        info["passes"] = len(agents)
        result.partition_info = info
        return _finish(_settle(result, wing, matches), wing, full_partitions, scope,
                       clock_skew_s, pending, estimate, account)

    # any_host: one pass over feathers merged across the agents.
    spread = (max(skew.values()) - min(skew.values())) if skew else 0.0
    window = _window_minutes(wing)
    wide = copy.deepcopy(wing)
    if spread:
        _set_window_minutes(wide, window + spread / 60.0)
    owned = work_dir is None
    folder = work_dir or tempfile.mkdtemp(prefix="crow_eye_any_host_")
    try:
        merged = merge_feathers(partitions, folder)
        with _matches_in_memory(engine):
            sub = engine.execute_wing(wide, merged)
    finally:
        if owned:
            shutil.rmtree(folder, ignore_errors=True)
    matches = []
    for m in sub.matches or []:
        hosts = sorted({str(r.get(AGENT_COLUMN)) for r in _records(m)
                        if r.get(AGENT_COLUMN) is not None})
        m.hosts = hosts
        m.agent_id = hosts[0] if len(hosts) == 1 else None
        if len(hosts) > 1:
            own = [skew.get(h, 0.0) for h in hosts]
            m.max_clock_skew_s = max(own) - min(own)
        matches.append(m)
    result.total_records_scanned = getattr(sub, "total_records_scanned", 0) or 0
    result.errors.extend(getattr(sub, "errors", None) or [])
    info.update(passes=1, time_window_minutes=window,
                time_window_minutes_used=_window_minutes(wide),
                clock_skew_spread_s=spread)
    result.partition_info = info
    return _finish(_settle(result, wing, matches), wing, full_partitions, scope,
                   clock_skew_s, pending, estimate, account)


def _finish(result, wing, partitions, scope, clock_skew_s, pending, estimate, account):
    """The fleet rules, the preflight estimate and the accounting, on the result."""
    from .fleet_accounting import account as _account
    _with_rules(result, wing, partitions, scope, clock_skew_s, pending)
    # Who and what each match is about, keyed the same on every machine, and
    # each conclusion carried to the matches that share its subject (14.5).
    from .fleet_identity import reconcile
    result.partition_info["subjects"] = reconcile(result, _tables_of(partitions))
    if estimate is not None:
        result.partition_info["preflight"] = estimate
    if pending:
        result.partition_info["pending"] = {a: sorted(f) for a, f in pending.items() if f}
    if account:
        result.partition_info["accounting"] = _account(result, wing, partitions, pending)
    return result


def _tables_of(partitions) -> Dict[str, str]:
    """feather_id -> its data table, from the first partition that has the file."""
    out = {}
    for agent in sorted(partitions):
        for fid, path in partitions[agent].items():
            if fid in out or not path or not os.path.isfile(path):
                continue
            try:
                con = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True)
                try:
                    row = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND "
                                      "name != 'feather_metadata' AND name NOT LIKE 'sqlite_%' "
                                      "LIMIT 1").fetchone()
                finally:
                    con.close()
                if row:
                    out[fid] = row[0]
            except sqlite3.Error:
                continue
    return out


def merge_feathers(partitions, folder):
    """{feather_id: merged path}: each feather's tables, every agent's rows,
    with an agent_id column. Copied inside SQLite (ATTACH ... INSERT SELECT),
    so no agent's rows are held in Python memory."""
    os.makedirs(folder, exist_ok=True)
    feather_ids = sorted({fid for paths in partitions.values() for fid in paths})
    out = {}
    for fid in feather_ids:
        target = os.path.join(folder, "%s.db" % hashlib.sha1(fid.encode("utf-8")).hexdigest()[:16])
        con = sqlite3.connect(target)
        try:
            made = set()
            for agent in sorted(partitions):
                src = partitions[agent].get(fid)
                if not src or not os.path.isfile(src):
                    continue
                con.execute("ATTACH DATABASE ? AS src", (src,))
                try:
                    tables = [r[0] for r in con.execute(
                        "SELECT name FROM src.sqlite_master WHERE type='table' "
                        "AND name NOT LIKE 'sqlite_%'")]
                    for table in tables:
                        q = '"%s"' % table.replace('"', '""')
                        cols = [r[1] for r in con.execute("PRAGMA src.table_info(%s)" % q)]
                        if table == "feather_metadata":
                            if table not in made:
                                con.execute("CREATE TABLE main.%s AS SELECT * FROM src.%s" % (q, q))
                                made.add(table)
                            continue
                        if table not in made:
                            con.execute("CREATE TABLE main.%s AS SELECT * FROM src.%s WHERE 0"
                                        % (q, q))
                            con.execute("ALTER TABLE main.%s ADD COLUMN %s TEXT" % (q, AGENT_COLUMN))
                            made.add(table)
                        have = {r[1] for r in con.execute("PRAGMA main.table_info(%s)" % q)}
                        shared = [c for c in cols if c in have and c != AGENT_COLUMN]
                        names = ", ".join('"%s"' % c.replace('"', '""') for c in shared)
                        con.execute("INSERT INTO main.%s (%s, %s) SELECT %s, ? FROM src.%s"
                                    % (q, names, AGENT_COLUMN, names, q), (agent,))
                    con.commit()
                finally:
                    con.execute("DETACH DATABASE src")
        finally:
            con.close()
        out[fid] = target
    return out
