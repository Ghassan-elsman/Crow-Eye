"""
Behavioural Engine

Runs Behaviour Wings over the behaviour events UBA produces for a case, one
person (SID) at a time. A Behaviour Wing names no Feathers: it is a set of
behaviour steps - each a UBA rule (built-in or analyst-created) or an
activity, with optional extra conditions and a minimum count - that must all
happen for one person, in order or in any order, inside a time range
(config/wing_config.py, BEHAVIOUR_FIELDS).

How a run works
---------------
1. Open the case's stored UBA analysis (``<case>/UBA/uba_events.db``) through
   ``BehaviorEngine.run_or_load()``: reused while fresh, rebuilt otherwise, so
   the User Behavior window, Eye and this engine read one answer.
2. Per Wing, select the events its steps (and its own advanced rules) name.
3. Split them by person key: events attributed to a profile carry its SID.
   Events no person is recorded for (a service the Service Control Manager
   installed, a program known from Prefetch, a USB device) are "machine"
   events, usable only by steps that say ``"actor": "machine"`` or ``"any"``.
4. Hand each person's rows to ``SemanticRuleEvaluator.evaluate_identity`` -
   the steps are compiled into its ``sequence`` rule (ordered or not,
   ``within_minutes``, per-step ``min_count``), and a Wing's own absence /
   threshold / sequence rules run as they are. No new rule format.
5. Store what fired in ``correlation_results.db`` (behaviour_hits,
   behaviour_actors, behaviour_runs) through ResultsDatabase.

Honesty
-------
- Every event the steps name is either evaluated or counted as not
  evaluated, with the reason: no time recorded, attributed to a name that
  matches no profile (no SID), or outside the run's time filter. Nothing is
  dropped silently.
- A step whose UBA rule is turned off in Settings is reported "not evaluated:
  rule X is turned off in Settings"; one whose rule has no data in this case
  (``unavailable``) is reported not evaluable. The Wing's other rules still run.
- An absence rule needs its source to be complete: when the rule it expects
  to be absent is unavailable, degraded or off, the absence is "not
  evaluable", never a hit.
- A hit is a POINTER to UBA events, which point at artifact rows. It is
  stored with kind 'pointer' and is not cited until those rows are re-read.

Every time is naive UTC ('YYYY-MM-DD HH:MM:SS', UBA's own format);
``hour_local`` uses the case's time zone bias from the registry.

Headless: imports config.semantic_mapping / config.wing_config, the evaluator,
the engine registry, progress tracking and uba.engine - no Qt. The Sentinel
server imports it as it is (tests/test_behavioural_engine_is_headless.py).
"""

import hashlib
import json
import logging
import os
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..config.wing_config import (
    BEHAVIOUR_EVENT_FIELDS, UBA_SEVERITIES, WING_CATEGORY_BEHAVIOUR,
    WingConfig, behaviour_step_label,
)
from . import engine_registry
from .base_engine import BaseCorrelationEngine, EngineMetadata, FilterConfig
from .progress_tracking import (ProgressEvent, ProgressEventType, ProgressListener,
                                ProgressTracker)
from .semantic_rule_evaluator import SemanticRuleEvaluator

logger = logging.getLogger(__name__)

# UBA severity -> correlation severity (the alert scale).
SEVERITY_MAP = {"routine": "info", "notable": "low", "suspicious": "high",
                "critical": "critical"}
_UBA_RANK = {s: i for i, s in enumerate(UBA_SEVERITIES)}
_ALERT_RANK = {s: i for i, s in enumerate(("info", "low", "medium", "high", "critical"))}

PERSON, MACHINE, ANY = "person", "machine", "any"
# A hit resting only on events with no account recorded is capped here
# ('low' = UBA 'notable'): it describes the machine, not a person.
MACHINE_ONLY_MAX_SEVERITY = "low"
HIT_IS_A_POINTER = ("A pointer to UBA behaviour events, not evidence. Cite the artifact rows "
                    "its evidence references name, re-read from the case.")
_TS_FORMAT = "%Y-%m-%d %H:%M:%S"


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).strftime(_TS_FORMAT)


def _naive_utc_text(value) -> Optional[str]:
    """A filter boundary as UBA's naive-UTC text, or None."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value.strftime(_TS_FORMAT)
    return None


def wing_hash(wing: WingConfig) -> str:
    """SHA-256 of what the Wing says (its dict without save times)."""
    data = wing.to_dict()
    for volatile in ("created_date", "last_modified"):
        data.pop(volatile, None)
    text = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class _NoSharedRules:
    """The evaluator's rule manager for this engine: a Behaviour Wing's rules
    are its own (wing_rules_only), never the global or pipeline rule sets,
    and building the real manager would read and write rule files."""

    def get_rules(self, *args, **kwargs):
        return []


@dataclass
class BehaviourWingResult:
    """What one Behaviour Wing found in one run."""
    wing_id: str
    wing_name: str
    wing_hash: str = ""
    status: str = "COMPLETED"           # COMPLETED | NOT_EVALUABLE | CANCELLED | FAILED
    hits: List[Dict[str, Any]] = field(default_factory=list)
    people: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)            # not evaluable / degraded
    not_evaluated: Dict[str, int] = field(default_factory=dict)
    events_selected: int = 0
    events_evaluated: int = 0
    people_evaluated: int = 0
    duration_seconds: float = 0.0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    result_id: Optional[int] = None

    # What PipelineExecutor reads off any engine's result.
    @property
    def matches(self) -> List[Dict[str, Any]]:
        return self.hits

    @property
    def total_matches(self) -> int:
        return len(self.hits)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "wing_id": self.wing_id, "wing_name": self.wing_name,
            "wing_hash": self.wing_hash, "status": self.status,
            "hits": self.hits, "notes": self.notes,
            "not_evaluated": self.not_evaluated,
            "events_selected": self.events_selected,
            "events_evaluated": self.events_evaluated,
            "people_evaluated": self.people_evaluated,
            "duration_seconds": self.duration_seconds,
            "errors": self.errors, "warnings": self.warnings,
        }


class BehaviouralEngine(BaseCorrelationEngine):
    """Evaluates Behaviour Wings over UBA's behaviour events, keyed by SID."""

    ENGINE_TYPE = engine_registry.BEHAVIOURAL
    SUPPORTS_STREAMING = False

    def __init__(self, config: Any = None, filters: Optional[FilterConfig] = None, *,
                 case_dir: Optional[str] = None, artifacts_dir: Optional[str] = None,
                 output_dir: Optional[str] = None, uba_store_path: Optional[str] = None,
                 disabled_rules: Optional[Iterable[str]] = None,
                 write_ledger: bool = True, debug_mode: bool = False):
        super().__init__(config, filters)
        self.debug_mode = debug_mode
        self.case_dir, self.artifacts_dir = self._resolve_case(config, case_dir, artifacts_dir)
        self.output_dir = output_dir or getattr(config, "output_directory", None) or None
        self.uba_store_path = uba_store_path
        self._disabled_rules = None if disabled_rules is None else list(disabled_rules)
        self.write_ledger = write_ledger
        self._cancelled = False
        self._cancel_reason = ""
        self.progress_tracker = ProgressTracker(debug_mode=debug_mode)
        self.evaluator = SemanticRuleEvaluator(semantic_manager=_NoSharedRules(),
                                               enable_parallel=False)
        self.evaluator.keep_witness_rows = True
        self.uba = None                       # uba.engine.behavior_engine.BehaviorEngine
        self.results: List[BehaviourWingResult] = []
        self.execution_id: Optional[int] = None
        self.run_record: Dict[str, Any] = {}
        self.statistics: Dict[str, Any] = {}
        self._tz_offset_minutes: Optional[int] = None
        self._tz_note = ""
        self._rule_status: Dict[str, str] = {}
        self._rule_notes: Dict[str, str] = {}
        self._rules_by_activity: Dict[str, List[str]] = {}

    # ------------------------------------------------------------ contract --
    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name="Behavioural Engine",
            version="1.0.0",
            description=("Runs Behaviour Wings - behaviour steps in order or in any "
                         "order within a time range - over UBA's behaviour events, "
                         "one person (SID) at a time."),
            complexity="O(E log E) per person",
            best_for=["Per-person behaviour sequences", "Thresholds over bursts",
                      "Absence of expected behaviour"],
            supports_identity_filter=False,
        )

    def set_output_directory(self, output_dir: str, execution_id: int = None):
        self.output_dir = output_dir
        if execution_id is not None:
            self.execution_id = execution_id

    def register_progress_listener(self, listener):
        if hasattr(listener, "on_progress_event"):
            self.progress_tracker.add_listener(listener)
            return

        class _Callable(ProgressListener):
            def __init__(self, callback):
                self.callback = callback

            def on_progress_event(self, event):
                self.callback(event)

        self.progress_tracker.add_listener(_Callable(listener))

    def request_cancellation(self, reason: Optional[str] = None):
        self._cancelled = True
        self._cancel_reason = reason or "Cancelled"
        logger.info("[Behavioural Engine] cancellation requested: %s", self._cancel_reason)

    def get_results(self) -> List[BehaviourWingResult]:
        return list(self.results)

    def get_statistics(self) -> Dict[str, Any]:
        return dict(self.statistics)

    # ------------------------------------------------------------ helpers --
    @staticmethod
    def _resolve_case(config, case_dir, artifacts_dir) -> Tuple[Optional[str], Optional[str]]:
        """(case folder, Target_Artifacts folder) from what was given."""
        if artifacts_dir:
            artifacts_dir = os.path.abspath(artifacts_dir)
            if not case_dir:
                parent = os.path.dirname(artifacts_dir.rstrip("\\/"))
                case_dir = parent if os.path.basename(
                    artifacts_dir.rstrip("\\/")).lower() == "target_artifacts" else None
            return case_dir, artifacts_dir
        if not case_dir:
            case_dir = getattr(config, "case_directory", None) or None
        if not case_dir:
            out = getattr(config, "output_directory", None) or ""
            if out:
                path = os.path.abspath(out)
                # <case>/Correlation/output -> <case>
                while path and os.path.basename(path).lower() != "correlation":
                    parent = os.path.dirname(path)
                    if parent == path:
                        path = ""
                        break
                    path = parent
                if path:
                    case_dir = os.path.dirname(path)
        if case_dir:
            case_dir = os.path.abspath(case_dir)
            return case_dir, os.path.join(case_dir, "Target_Artifacts")
        return None, None

    def _emit_phase_progress(self, label: str, done, total, unit: str = "items"):
        """The phase the analyst sees: the log line and a WINDOW_PROGRESS event
        carrying additional_data['phase_progress'] (the GUI's phase bar)."""
        pct = (done / total * 100.0) if total else 0.0
        print(f"[Behavioural Engine] {label}: {done:,}/{total:,} {unit} ({pct:.0f}%)")
        try:
            event = ProgressEvent(
                event_type=ProgressEventType.WINDOW_PROGRESS,
                timestamp=datetime.now(),
                overall_progress=self.progress_tracker._create_overall_progress(),
                message=label,
                additional_data={"phase_progress": {
                    "label": label, "done": int(done), "total": int(total), "unit": unit}},
            )
            self.progress_tracker._emit_event(event)
        except Exception as e:                       # pragma: no cover - display only
            logger.debug("[Behavioural Engine] phase progress not emitted: %s", e)

    # ----------------------------------------------------------------- UBA --
    def open_uba(self):
        """The case's UBA analysis, loaded from its store or rebuilt."""
        if self.uba is not None:
            return self.uba
        if not self.artifacts_dir or not os.path.isdir(self.artifacts_dir):
            raise FileNotFoundError(
                f"No Target_Artifacts folder for this case ({self.artifacts_dir!r}); "
                f"the Behavioural engine reads UBA's behaviour events from it.")
        from uba.engine.behavior_engine import BehaviorEngine
        uba = BehaviorEngine(self.artifacts_dir, disabled_rules=self._disabled_rules,
                             store_path=self.uba_store_path)
        uba.run_or_load(progress_cb=lambda pct, label: self._emit_phase_progress(
            f"User behaviour: {label}", pct, 100, unit="%"))
        self.uba = uba
        self._index_rules()
        self._read_case_time_zone()
        return uba

    def attach_uba(self, uba):
        """Use a UBA analysis another run of this case already opened.

        The Execution tab runs each Wing in its own executor; without this
        every Behaviour Wing re-loaded the same stored analysis. ``uba`` must
        be for this engine's Target_Artifacts folder and rule switches.
        """
        self.uba = uba
        self._index_rules()
        self._read_case_time_zone()
        return uba

    def _index_rules(self):
        """Every rule the analysis knows (built-in, analyst-created, coverage),
        with its coverage status, so a step can be checked before it runs."""
        uba = self.uba
        status, notes, by_activity = {}, {}, defaultdict(list)
        for rule in (uba.rules_config or {}).get("rules", []) or []:
            rid = str(rule.get("id"))
            status.setdefault(rid, "active")
            by_activity[str(rule.get("activity") or "")].append(rid)
        for entry in (uba.coverage_report or {}).get("rules", []) or []:
            rid = str(entry.get("rule_id"))
            status[rid] = entry.get("status") or status.get(rid, "active")
            notes[rid] = entry.get("note") or ""
            act = str(entry.get("activity") or "")
            if rid not in by_activity[act]:
                by_activity[act].append(rid)
        for rid in uba.disabled_rules or ():
            if rid in status:
                status[rid] = "off"
        try:
            for (rid, act) in uba.store.conn.execute(
                    "SELECT DISTINCT rule_id, activity FROM events"):
                status.setdefault(rid, "active")
                if rid not in by_activity[act]:
                    by_activity[act].append(rid)
        except Exception as e:                       # pragma: no cover
            logger.debug("[Behavioural Engine] rule index from events failed: %s", e)
        self._rule_status, self._rule_notes = status, notes
        self._rules_by_activity = dict(by_activity)

    def _read_case_time_zone(self):
        """The case's UTC offset in minutes (registry TimeZoneInformation:
        ActiveTimeBias, else Bias). UTC = local + bias."""
        self._tz_offset_minutes, self._tz_note = None, ""
        pool = getattr(self.uba, "db_pool", None)
        conn = pool.get("registry") if pool is not None else None
        bias = None
        try:
            if conn is not None and pool.has_table("registry", "TimeZoneInfo"):
                cols = {r[1] for r in conn.execute("PRAGMA table_info(TimeZoneInfo)")}
                for col in ("active_time_bias", "bias"):
                    if col in cols:
                        row = conn.execute(f'SELECT "{col}" FROM TimeZoneInfo '
                                           f'WHERE "{col}" IS NOT NULL LIMIT 1').fetchone()
                        if row and str(row[0]).strip() not in ("", "None"):
                            bias = int(float(row[0]))
                            break
            if bias is None and conn is not None and pool.has_table("registry", "time_zone"):
                cols = {r[1] for r in conn.execute("PRAGMA table_info(time_zone)")}
                value_col = "data" if "data" in cols else ("row_data" if "row_data" in cols else None)
                if value_col:
                    for name in ("ActiveTimeBias", "Bias"):
                        row = conn.execute(f'SELECT "{value_col}" FROM time_zone '
                                           f'WHERE lower(name) = lower(?) LIMIT 1', (name,)).fetchone()
                        if row and str(row[0]).strip() not in ("", "None"):
                            bias = int(float(row[0]))
                            break
        except Exception as e:
            logger.warning("[Behavioural Engine] case time zone not read: %s", e)
        if bias is None:
            self._tz_note = ("The case's time zone was not found in the registry, so "
                             "hour_local is empty and a step conditioned on it cannot match.")
            return
        if bias >= 2 ** 31:                  # stored as an unsigned DWORD
            bias -= 2 ** 32
        self._tz_offset_minutes = -bias
        self._tz_note = (f"hour_local uses the case's time zone bias at collection "
                         f"(UTC{'+' if -bias >= 0 else '-'}{abs(bias) // 60:02d}:{abs(bias) % 60:02d}); "
                         f"daylight-saving changes before then are not applied.")

    # ----------------------------------------------------------- compiling --
    def _step_rule_ids(self, step: Dict[str, Any]) -> Tuple[List[str], List[str]]:
        """(rule ids, activities) a step names."""
        def as_list(value):
            if value is None or value == "":
                return []
            return [str(v) for v in value] if isinstance(value, (list, tuple)) else [str(value)]
        return as_list(step.get("rule_id")), as_list(step.get("activity"))

    def _step_availability(self, step: Dict[str, Any], index: int) -> Tuple[bool, List[str]]:
        """(can it run, notes). Off / unavailable / unknown rules make a step
        not evaluable; a degraded one runs with a note."""
        rule_ids, activities = self._step_rule_ids(step)
        label = behaviour_step_label(step, index)
        notes: List[str] = []
        candidates: List[str] = list(rule_ids)
        for act in activities:
            found = self._rules_by_activity.get(act, [])
            if not found:
                notes.append(f"{label} is not evaluable: no UBA rule records the "
                             f"activity '{act}'.")
                return False, notes
            candidates.extend(found)
        usable = []
        for rid in candidates:
            status = self._rule_status.get(rid)
            if status is None:
                notes.append(f"{label} is not evaluable: there is no UBA rule '{rid}' "
                             f"(built-in or analyst-created).")
            elif status == "off":
                notes.append(f"{label} not evaluated: rule {rid} is turned off in Settings.")
            elif status == "unavailable":
                why = self._rule_notes.get(rid) or "its data was not parsed for this case"
                notes.append(f"{label} is not evaluable: rule {rid} is unavailable ({why}).")
            else:
                if status == "degraded":
                    why = self._rule_notes.get(rid) or "part of its data is missing"
                    notes.append(f"{label}: rule {rid} is degraded ({why}); a hit still "
                                 f"stands, but no hit is not evidence it did not happen.")
                usable.append(rid)
        return bool(usable), notes

    def _compile_step(self, step: Dict[str, Any]) -> Dict[str, Any]:
        """A Behaviour Wing step as an evaluator sequence step (AND conditions
        on one feather: person, machine or any)."""
        fid = step.get("actor", PERSON) or PERSON
        rule_ids, activities = self._step_rule_ids(step)
        conds = []

        def one_of(field_name, values):
            if len(values) == 1:
                return {"feather_id": fid, "field_name": field_name,
                        "operator": "equals", "value": values[0]}
            return {"feather_id": fid, "field_name": field_name, "operator": "regex",
                    "value": "^(?:" + "|".join(re.escape(v) for v in values) + ")$"}

        if rule_ids:
            conds.append(one_of("rule_id", rule_ids))
        if activities:
            conds.append(one_of("activity", activities))
        min_sev = step.get("min_severity")
        if min_sev in _UBA_RANK:
            allowed = [s for s in UBA_SEVERITIES if _UBA_RANK[s] >= _UBA_RANK[min_sev]]
            conds.append(one_of("severity", allowed))
        for c in step.get("conditions") or []:
            cond = {"feather_id": fid, "field_name": c.get("field_name"),
                    "operator": c.get("operator", "equals"), "value": c.get("value")}
            if c.get("negate"):
                cond["negate"] = True
            conds.append(cond)
        return {"conditions": conds, "logic_operator": "AND",
                "min_count": int(step.get("min_count", 1) or 1),
                "count_field": "aggregate_count"}

    def _steps_rule(self, wing: WingConfig) -> Dict[str, Any]:
        alert = wing.alert or {}
        spec = {
            "steps": [self._compile_step(s) for s in wing.steps],
            "ordered": wing.ordered is not False,
            "within_minutes": wing.within_minutes,
            "count_field": "aggregate_count",
            "end_field": "ts_end",      # a burst lasts from ts_start to ts_end
        }
        if wing.ordered is not False and wing.max_gap_minutes is not None:
            spec["max_gap_minutes"] = wing.max_gap_minutes
        return {
            "rule_id": f"{wing.wing_id}:steps",
            "name": wing.wing_name,
            "semantic_value": wing.proves or wing.wing_name,
            "description": wing.description,
            "rule_type": "sequence",
            "sequence": spec,
            "scope": "wing",
            "severity": alert.get("severity") or "info",
            "technique_id": list(alert.get("technique_id") or []),
            "tactic": list(alert.get("tactic") or []),
        }

    @staticmethod
    def _steps_rule_type(wing: WingConfig) -> str:
        if len(wing.steps) == 1:
            return "threshold" if int(wing.steps[0].get("min_count", 1) or 1) > 1 else "match"
        return "sequence" if wing.ordered is not False else "unordered"

    def _referenced_rules(self, rule: Dict[str, Any], keys=("require_absent",)) -> Tuple[List[str], bool]:
        """UBA rule ids an advanced rule's blocks name through rule_id /
        activity conditions, and whether every such block named one."""
        found: List[str] = []
        all_named = True
        absence = rule.get("absence") or {}
        for key in keys:
            for cond in absence.get(key, []) or []:
                field_name = str(cond.get("field_name") or "")
                value = str(cond.get("value") or "")
                op = cond.get("operator", "equals")
                if field_name not in ("rule_id", "activity") or op not in ("equals", "regex"):
                    all_named = False
                    continue
                names = ([value] if op == "equals"
                         else [v for v in re.findall(r"[A-Za-z0-9_]+", value)])
                for name in names:
                    if field_name == "rule_id":
                        found.append(name)
                    else:
                        found.extend(self._rules_by_activity.get(name, []))
        return found, all_named

    def _absence_problems(self, rule: Dict[str, Any]) -> List[str]:
        """Why an absence rule cannot be evaluated on this case (empty = it can)."""
        rid = rule.get("rule_id", "?")
        names, all_named = self._referenced_rules(rule)
        problems = []
        if not names:
            problems.append(f"Absence rule '{rid}' is not evaluable: its required-absent "
                            f"behaviour names no UBA rule or activity, so its coverage "
                            f"cannot be checked.")
            return problems
        for name in names:
            status = self._rule_status.get(name)
            if status is None:
                problems.append(f"Absence rule '{rid}' is not evaluable: there is no UBA "
                                f"rule '{name}'.")
            elif status == "off":
                problems.append(f"Absence rule '{rid}' is not evaluable: rule {name} is "
                                f"turned off in Settings, so its absence says nothing.")
            elif status in ("unavailable", "degraded"):
                problems.append(f"Absence rule '{rid}' is not evaluable: rule {name} is "
                                f"{status} on this case ({self._rule_notes.get(name) or 'its data is incomplete'}), "
                                f"so its absence says nothing.")
        if not all_named and not problems:
            problems.append(f"Absence rule '{rid}' is not evaluable: one of its "
                            f"required-absent conditions names no UBA rule or activity.")
        return problems

    # --------------------------------------------------------------- events --
    def _select_events(self, rule_ids: List[str], activities: List[str],
                       everything: bool, detail_keys: Iterable[str] = ()) -> List[Dict[str, Any]]:
        """The events the Wing's rules can read: by rule id, by activity, or
        by a details key they name. ``everything`` when a rule names none."""
        conn = self.uba.store.conn
        if everything:
            cursor = conn.execute("SELECT * FROM events")
        else:
            where, params = [], []
            if rule_ids:
                where.append("rule_id IN ({})".format(",".join("?" for _ in rule_ids)))
                params.extend(rule_ids)
            if activities:
                where.append("activity IN ({})".format(",".join("?" for _ in activities)))
                params.extend(activities)
            for key in sorted(set(detail_keys)):
                # LIKE's '_' matches any one character: a superset, never a miss.
                where.append("details_json LIKE ?")
                params.append('%"' + key.replace('%', '') + '":%')
            if not where:
                return []
            cursor = conn.execute("SELECT * FROM events WHERE " + " OR ".join(where), params)
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]

    def _event_row(self, ev: Dict[str, Any], extra_fields: Iterable[str]) -> Dict[str, Any]:
        """An event as the evaluator's row: its fields, the hours, details.*"""
        row = {k: ev.get(k) for k in BEHAVIOUR_EVENT_FIELDS if k in ev}
        ts = ev.get("ts_start")
        row["timestamp"] = ts
        row["hour_utc"] = row["hour_local"] = None
        if ts:
            try:
                dt = datetime.strptime(ts[:19], _TS_FORMAT)
                row["hour_utc"] = dt.hour
                if self._tz_offset_minutes is not None:
                    row["hour_local"] = (dt + timedelta(minutes=self._tz_offset_minutes)).hour
            except ValueError:
                pass
        try:
            details = json.loads(ev.get("details_json") or "{}")
        except ValueError:
            details = {}
        for key, value in (details or {}).items():
            if isinstance(value, (dict, list, tuple)):
                value = json.dumps(value, default=str)
            row[f"details.{key}"] = value
        for name in extra_fields:
            row.setdefault(name, None)
        try:
            row["_evidence"] = json.loads(ev.get("evidence_json") or "[]")
        except ValueError:
            row["_evidence"] = []
        return row

    @staticmethod
    def _condition_fields(rules: List[Dict[str, Any]]) -> List[str]:
        """Every field a compiled rule's conditions name, so each row carries it
        (an absent key would send the evaluator to its fuzzy field matching)."""
        names = set()

        def walk(obj):
            if isinstance(obj, dict):
                if "field_name" in obj and obj.get("field_name"):
                    names.add(str(obj["field_name"]))
                for v in obj.values():
                    walk(v)
            elif isinstance(obj, list):
                for v in obj:
                    walk(v)
        for rule in rules:
            walk(rule)
        return sorted(names)

    def _subjects(self, wing: WingConfig, person_sids: Dict[str, Counter]) -> Tuple[List[str], List[str]]:
        """(SIDs to evaluate, notes) for the Wing's subject."""
        subject = wing.subject or {}
        scope = subject.get("scope", "everyone") or "everyone"
        notes: List[str] = []
        known = dict(getattr(getattr(self.uba, "resolver", None), "known_users", {}) or {})
        if scope == "everyone":
            return sorted(person_sids), notes
        if scope == "sids":
            wanted = {str(s).split(" ")[0].upper() for s in subject.get("sids") or []}
            return sorted(s for s in set(person_sids) | set(known) if s.upper() in wanted), notes
        if scope == "accounts":
            wanted = {str(a).split("\\")[-1].lower() for a in subject.get("accounts") or []}
            sids = set()
            for sid, names in person_sids.items():
                if any(str(n).split("\\")[-1].lower() in wanted for n in names):
                    sids.add(sid)
            for sid, name in known.items():
                if str(name).lower() in wanted:
                    sids.add(sid)
            return sorted(sids), notes
        if scope == "groups":
            wanted = {str(g).lower() for g in subject.get("groups") or []}
            pool = self.uba.db_pool
            if not pool.has_table("registry", "local_groups"):
                notes.append("Subject is a group, but this case has no parsed local group "
                             "membership (registry local_groups): nobody was evaluated.")
                return [], notes
            sids = set()
            try:
                for name, member in pool.get("registry").execute(
                        "SELECT group_name, member_sid FROM local_groups"):
                    if str(name or "").lower() in wanted and member:
                        sids.add(str(member).split(" ")[0])
            except Exception as e:
                notes.append(f"Group membership could not be read ({e}): nobody was evaluated.")
                return [], notes
            return sorted(sids), notes
        notes.append(f"Unknown subject scope '{scope}': nobody was evaluated.")
        return [], notes

    # ----------------------------------------------------------------- run --
    def execute_wing(self, wing, feather_paths: Optional[Dict[str, str]] = None) -> BehaviourWingResult:
        """Run one Behaviour Wing. ``wing`` is its WingConfig (or the dict a
        Wing file holds) - never the executor's converted ``Wing``, which does
        not carry what a Behaviour Wing is made of."""
        wing = self._as_wing_config(wing)
        started = time.time()
        result = BehaviourWingResult(wing_id=wing.wing_id, wing_name=wing.wing_name,
                                     wing_hash=wing_hash(wing))
        ok, reason = engine_registry.check_wing(wing, self.ENGINE_TYPE)
        if not ok:
            result.status = "SKIPPED"
            result.notes.append(reason)
            return result
        problems = wing.category_problems()
        if problems:
            result.status = "NOT_EVALUABLE"
            result.notes.extend(f"Wing '{wing.wing_name}' cannot run: {p}" for p in problems)
            return result
        try:
            self.open_uba()
        except Exception as e:
            result.status = "FAILED"
            result.errors.append(f"User behaviour analysis unavailable: {e}")
            return result
        try:
            self._evaluate_wing(wing, result)
        except Exception as e:
            logger.exception("[Behavioural Engine] Wing %s failed", wing.wing_name)
            result.status = "FAILED"
            result.errors.append(f"Wing '{wing.wing_name}' failed: {e}")
        if self._cancelled and result.status == "COMPLETED":
            result.status = "CANCELLED"
        result.duration_seconds = round(time.time() - started, 3)
        return result

    @staticmethod
    def _as_wing_config(wing) -> WingConfig:
        if isinstance(wing, WingConfig):
            return wing
        if isinstance(wing, dict):
            import contextlib, io
            with contextlib.redirect_stdout(io.StringIO()):   # from_dict prints its steps
                return WingConfig.from_dict(dict(wing))
        raise TypeError(
            f"The Behavioural engine runs a WingConfig (or a Wing file's dict), not a "
            f"{type(wing).__name__}: the converted Wing does not carry a Behaviour "
            f"Wing's steps, time range and subject.")

    def _evaluate_wing(self, wing: WingConfig, result: BehaviourWingResult):
        # Compiled rules are cached by rule id; a Wing edited between two runs
        # of one engine must not reuse its old steps.
        self.evaluator.clear_cache()
        include_service = bool((wing.subject or {}).get("include_service_accounts"))
        rules: List[Dict[str, Any]] = []
        rule_types: Dict[str, str] = {}
        machine_capable = False
        person_capable = False

        # The steps, if every one of them can run.
        rule_ids, activities = [], []
        if wing.steps:
            runnable = True
            for i, step in enumerate(wing.steps):
                ok, notes = self._step_availability(step, i)
                result.notes.extend(notes)
                runnable = runnable and ok
                ids, acts = self._step_rule_ids(step)
                rule_ids.extend(ids)
                activities.extend(acts)
            if runnable:
                compiled = self._steps_rule(wing)
                rules.append(compiled)
                rule_types[compiled["rule_id"]] = self._steps_rule_type(wing)
                actors = {s.get("actor", PERSON) or PERSON for s in wing.steps}
                machine_capable = machine_capable or bool(actors & {MACHINE, ANY})
                person_capable = person_capable or bool(actors & {PERSON, ANY})
            else:
                result.notes.append(
                    f"The steps of '{wing.wing_name}' were not evaluated: every step must be "
                    f"able to run for the set to be found. The Wing's other rules still ran.")

        # The Wing's own advanced rules (absence / threshold / sequence).
        select_everything = False
        detail_keys: List[str] = []
        for rule in wing.semantic_rules or []:
            rtype = str(rule.get("rule_type", "match") or "match").lower()
            rid = rule.get("rule_id", "?")
            if rtype == "match":
                result.notes.append(f"Rule '{rid}' was not evaluated: in a Behaviour Wing a "
                                    f"single behaviour is written as a step.")
                continue
            if rtype == "absence":
                problems = self._absence_problems(rule)
                if problems:
                    result.notes.extend(problems)
                    continue
            rules.append(rule)
            rule_types[rid] = rtype
            fids = set(self._feathers_of(rule))
            machine_capable = machine_capable or bool(fids & {MACHINE, ANY})
            person_capable = person_capable or bool(fids & {PERSON, ANY})
            ids, acts, keys, everything = self._selectors_of_rule(rule)
            rule_ids.extend(ids)
            activities.extend(acts)
            detail_keys.extend(keys)
            select_everything = select_everything or everything

        if not rules:
            result.status = "NOT_EVALUABLE"
            return

        extra_fields = self._condition_fields(rules)
        events = self._select_events(sorted(set(rule_ids)), sorted(set(activities)),
                                     select_everything, detail_keys)
        result.events_selected = len(events)
        start = _naive_utc_text(getattr(self.filters, "time_period_start", None))
        end = _naive_utc_text(getattr(self.filters, "time_period_end", None))

        person_rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        names_by_sid: Dict[str, Counter] = defaultdict(Counter)
        machine_rows: List[Dict[str, Any]] = []
        timeless: Counter = Counter()
        outside: Counter = Counter()
        no_sid = 0
        for ev in events:
            sid = ev.get("actor_sid") or ""
            actor_type = ev.get("actor_type") or ""
            is_person = (actor_type == "User" and sid) or (
                include_service and sid and actor_type == "System")
            key = sid if is_person else ""
            ts = ev.get("ts_start")
            if not ts:
                timeless[key] += 1
                continue
            if (start and (ev.get("ts_end") or ts) < start) or (end and ts > end):
                outside[key] += 1
                continue
            if is_person:
                row = self._event_row(ev, extra_fields)
                person_rows[sid].append(row)
                if ev.get("actor_name"):
                    names_by_sid[sid][ev["actor_name"]] += 1
            elif actor_type == "User":
                no_sid += 1               # a name that matches no profile: not a person key
            else:
                machine_rows.append(self._event_row(ev, extra_fields))
        result.not_evaluated = {
            "timeless": sum(timeless.values()),
            "no_sid": no_sid,
            "outside_time_filter": sum(outside.values()),
        }
        if no_sid:
            result.notes.append(
                f"{no_sid} event(s) were not evaluated: they name a person whose account "
                f"matches no profile on this computer, so they carry no SID.")
        if result.not_evaluated["timeless"]:
            result.notes.append(
                f"{result.not_evaluated['timeless']} event(s) were not evaluated: they have "
                f"no recorded time, so they cannot be placed in a time range.")
        if result.not_evaluated["outside_time_filter"]:
            result.notes.append(
                f"{result.not_evaluated['outside_time_filter']} event(s) fall outside the "
                f"run's time filter and were not evaluated.")
        if self._tz_offset_minutes is None and any(f == "hour_local" for f in extra_fields):
            result.notes.append(self._tz_note)

        sids, subject_notes = self._subjects(wing, names_by_sid)
        result.notes.extend(subject_notes)
        subjects: List[Tuple[str, List[Dict[str, Any]]]] = []
        if person_capable:
            subjects.extend((sid, person_rows.get(sid, [])) for sid in sids)
        if machine_capable:
            subjects.append(("", []))          # the machine itself: no person's events
        machine_ids = {id(r) for r in machine_rows}
        result.events_evaluated = (sum(len(person_rows.get(s, [])) for s in sids)
                                   + (len(machine_rows) if machine_capable else 0))
        # Every selected event is evaluated or counted with its reason.
        if machine_rows and not machine_capable:
            result.not_evaluated["no_person"] = len(machine_rows)
            result.notes.append(
                f"{len(machine_rows)} event(s) were not evaluated: they name no person "
                f"(the system, a program, or no account recorded), and this Wing's steps "
                f"take only a person's own events.")
        watched = set(sids) if person_capable else set()
        outside_subject = sum(len(rows) for sid, rows in person_rows.items()
                              if sid not in watched)
        if outside_subject:
            result.not_evaluated["outside_subject"] = outside_subject
            result.notes.append(
                f"{outside_subject} event(s) belong to people outside this Wing's subject "
                f"and were not evaluated.")

        total = len(subjects)
        for done, (sid, rows) in enumerate(subjects, 1):
            if self._cancelled:
                result.status = "CANCELLED"
                result.notes.append(f"Cancelled ({self._cancel_reason}) after "
                                    f"{done - 1} of {total} people.")
                break
            name = self._display_name(sid, names_by_sid.get(sid))
            entry = result.people.setdefault(sid, {
                "actor_sid": sid, "actor_name": name,
                "names": sorted(names_by_sid.get(sid, {})),
                # The machine subject is evaluated over the machine events.
                "events_evaluated": len(rows) if sid else len(machine_rows),
                "events_timeless": timeless.get(sid, 0),
                "events_outside_time_filter": outside.get(sid, 0), "hits": 0})
            capped = False
            for rule in rules:
                for match in self._occurrences(wing, sid, rule, rows, machine_rows,
                                               machine_ids):
                    if entry["hits"] >= self.OCCURRENCE_CAP:
                        capped = True
                        break
                    hit = self._hit(wing, result, match, sid, name, rule_types, machine_ids)
                    hit["occurrence"] = entry["hits"] + 1
                    result.hits.append(hit)
                    entry["hits"] += 1
                if capped:
                    break
            if capped:
                text = (f"{name}: the first {self.OCCURRENCE_CAP} occurrences of "
                        f"'{wing.wing_name}' are listed; later ones were not searched "
                        f"(occurrence cap).")
                entry["note"] = text
                result.notes.append(text)
            self._emit_phase_progress(f"Behaviour Wing '{wing.wing_name}'", done, total,
                                      unit="people")
        result.people_evaluated = len([s for s, _ in subjects if s])

    # Every non-overlapping occurrence of a Wing's rule for one person is its
    # own hit, up to this many per Wing per person (a cap reached is noted on
    # the Wing's result and the person's behaviour_actors row).
    OCCURRENCE_CAP = 100

    def _occurrences(self, wing: WingConfig, sid: str, rule: Dict[str, Any],
                     rows: List[Dict[str, Any]], machine_rows: List[Dict[str, Any]],
                     machine_ids: set):
        """Each non-overlapping occurrence of ``rule`` for one person, earliest
        first: evaluate, keep the hit, take its events out of the pool, look
        again.

        Step sets and sequences find the earliest set first, so everything that
        starts at or before a hit's end is dropped before the next search: the
        next occurrence starts after it. A threshold reports its busiest window,
        so only the rows inside that window are dropped, and a later window that
        would overlap an earlier one is not counted twice. An absence is one
        statement per person. A person's occurrence that rests only on machine
        events is not theirs; it is skipped (the machine row reports it).
        """
        rtype = str(rule.get("rule_type", "match") or "match").lower()
        forward = rtype == "sequence"
        person_pool, machine_pool = list(rows), list(machine_rows)
        spans: List[Tuple[str, str]] = []
        found = 0
        for _ in range(self.OCCURRENCE_CAP * 4):
            evidence = ([{"feather_id": PERSON, "data": r} for r in person_pool]
                        + [{"feather_id": MACHINE, "data": r} for r in machine_pool]
                        + [{"feather_id": ANY, "data": r} for r in person_pool + machine_pool])
            matches = self.evaluator.evaluate_identity(
                {"identity_type": "person", "identity_value": sid, "evidence": evidence},
                wing_id=wing.wing_id, wing_rules=[rule], allow_advanced=True,
                wing_rules_only=True)
            if not matches:
                return
            match = matches[0]
            witness = match.witness or []
            starts = [r.get("ts_start") for r in witness if r.get("ts_start")]
            ends = [r.get("ts_end") or r.get("ts_start") for r in witness if r.get("ts_start")]
            span = (min(starts), max(ends)) if starts else None
            machine_only = bool(witness) and all(id(r) in machine_ids for r in witness)
            overlaps = span is not None and any(
                not (span[1] < a or span[0] > b) for a, b in spans)
            if not (sid and machine_only) and not overlaps:
                found += 1
                if span is not None:
                    spans.append(span)
                yield match
                if found > self.OCCURRENCE_CAP:
                    return            # one past the cap: enough to say the cap was reached
            if rtype == "absence" or span is None:
                return
            before = len(person_pool) + len(machine_pool)
            if forward:
                keep = lambda r: (r.get("ts_start") or "") > span[1]
            else:
                keep = lambda r: not (span[0] <= (r.get("ts_start") or "") <= span[1])
            person_pool = [r for r in person_pool if keep(r)]
            machine_pool = [r for r in machine_pool if keep(r)]
            if len(person_pool) + len(machine_pool) == before:
                return                # nothing left to take: no further occurrence

    @staticmethod
    def _feathers_of(rule: Dict[str, Any]) -> List[str]:
        from ..config.wing_config import _rule_feather_ids
        return _rule_feather_ids(rule)

    def _selectors_of_rule(self, rule: Dict[str, Any]) -> Tuple[List[str], List[str], List[str], bool]:
        """(rule ids, activities, details keys, everything) an advanced rule
        reads. Each condition block (an absence condition, a threshold
        condition, a sequence step) must name a rule id, an activity or a
        details key; one that names none means every event is read."""
        ids: List[str] = []
        acts: List[str] = []
        keys: List[str] = []
        everything = False

        def narrow(cond) -> bool:
            if not isinstance(cond, dict):
                return False
            field_name = str(cond.get("field_name") or "")
            op = cond.get("operator", "equals")
            value = str(cond.get("value") or "")
            if cond.get("negate") or op in ("not_equals",):
                return False
            if field_name in ("rule_id", "activity"):
                names = [value] if op == "equals" else re.findall(r"[A-Za-z][A-Za-z0-9_]*", value)
                if not names:
                    return False
                if field_name == "rule_id":
                    ids.extend(names)
                else:
                    acts.extend(names)
                    for name in names:
                        ids.extend(self._rules_by_activity.get(name, []))
                return True
            if field_name.startswith("details."):
                keys.append(field_name[len("details."):])
                return True
            return False

        blocks: List[Tuple[List[Dict[str, Any]], bool]] = []   # (conditions, AND?)
        absence = rule.get("absence") or {}
        for key in ("expect_present", "require_absent"):
            for cond in absence.get(key, []) or []:
                blocks.append(([cond], False))
        threshold = rule.get("threshold") or {}
        if threshold.get("condition"):
            blocks.append(([threshold["condition"]], False))
        if threshold.get("conditions"):
            blocks.append((list(threshold["conditions"]),
                           str(threshold.get("logic_operator", "") or "").upper() == "AND"))
        for st in (rule.get("sequence") or {}).get("steps", []) or []:
            conds = st.get("conditions") or ([st] if "field_name" in st else [])
            and_mode = str(st.get("logic_operator", "") or "").upper() == "AND"
            blocks.append((conds, and_mode))
        if not blocks:
            return ids, acts, keys, True
        for conds, and_mode in blocks:
            if and_mode:
                # Every condition must hold, so ONE narrowing condition selects
                # a superset - the most specific: a rule or activity first.
                ranked = sorted(conds, key=lambda c: 0 if isinstance(c, dict) and str(
                    c.get("field_name") or "") in ("rule_id", "activity") else 1)
                ok = any(narrow(c) for c in ranked)   # stops at the first that narrows
            else:
                results = [narrow(c) for c in conds]
                ok = bool(results) and all(results)
            if not ok:
                everything = True
        return ids, acts, keys, everything

    def _display_name(self, sid: str, names: Optional[Counter]) -> str:
        if not sid:
            return "(no account recorded)"
        known = getattr(getattr(self.uba, "resolver", None), "known_users", {}) or {}
        if sid in known:
            return str(known[sid])
        if names:
            return names.most_common(1)[0][0]
        return sid

    def _hit(self, wing: WingConfig, result: BehaviourWingResult, match, sid: str,
             name: str, rule_types: Dict[str, str], machine_ids: set) -> Dict[str, Any]:
        witness = match.witness or []
        steps_rows = match.witness_steps or [witness]
        event_ids = list(dict.fromkeys(r.get("event_id") for r in witness if r.get("event_id")))
        refs: Dict[tuple, Dict[str, Any]] = {}
        for row in witness:
            for ref in row.get("_evidence") or []:
                key = (ref.get("db"), ref.get("table"), ref.get("role", "primary"))
                merged = refs.setdefault(key, {"db": key[0], "table": key[1], "role": key[2],
                                               "rowids": [], "count": 0, "event_ids": []})
                for rid in ref.get("rowids") or []:
                    if rid not in merged["rowids"]:
                        merged["rowids"].append(rid)
                if ref.get("rowid_range"):
                    merged.setdefault("rowid_ranges", []).append(ref["rowid_range"])
                merged["count"] += int(ref.get("count") or len(ref.get("rowids") or []))
                if row.get("event_id") and row["event_id"] not in merged["event_ids"]:
                    merged["event_ids"].append(row["event_id"])
        starts = [r.get("ts_start") for r in witness if r.get("ts_start")]
        ends = [r.get("ts_end") or r.get("ts_start") for r in witness if r.get("ts_start")]
        uba_sev = max((r.get("severity") for r in witness if r.get("severity") in _UBA_RANK),
                      key=lambda s: _UBA_RANK[s], default="routine")
        is_steps = match.rule_id == f"{wing.wing_id}:steps"
        alert = wing.alert or {}
        severity = (alert.get("severity") if is_steps else match.severity) or ""
        if severity not in _ALERT_RANK:
            severity = SEVERITY_MAP.get(uba_sev, "info")
        # Nobody's account is recorded on any of its events: such a hit is
        # context about the machine, never an accusation - at most 'low'
        # (UBA's 'notable').
        machine_only = not sid or (bool(witness) and all(id(r) in machine_ids for r in witness))
        note = None
        if machine_only:
            if _ALERT_RANK[severity] > _ALERT_RANK[MACHINE_ONLY_MAX_SEVERITY]:
                note = (f"Rests only on events with no account recorded: severity capped at "
                        f"'{MACHINE_ONLY_MAX_SEVERITY}' (the Wing's alert says '{severity}').")
                severity = MACHINE_ONLY_MAX_SEVERITY
        steps = []
        for i, rows in enumerate(steps_rows):
            if is_steps and i < len(wing.steps):
                label = behaviour_step_label(wing.steps[i], i)
            elif len(steps_rows) > 1:
                label = f"Step {i + 1} of rule {match.rule_id}"
            else:
                label = f"Events that met rule {match.rule_id}"
            steps.append({
                "step": i + 1, "label": label,
                "actor": (wing.steps[i].get("actor", PERSON) if is_steps and i < len(wing.steps)
                          else None),
                "event_ids": [r.get("event_id") for r in rows],
                "rule_ids": sorted({r.get("rule_id") for r in rows if r.get("rule_id")}),
                "first_ts": min((r.get("ts_start") for r in rows if r.get("ts_start")), default=None),
                "machine_events": all(id(r) in machine_ids for r in rows) if rows else False,
                "count": sum(int(r.get("aggregate_count") or 1) for r in rows),
            })
        hosts = [r.get("host") for r in witness if r.get("host")]
        return {
            "wing_id": wing.wing_id, "wing_name": wing.wing_name,
            "rule": match.rule_id, "rule_name": match.rule_name,
            "rule_type": rule_types.get(match.rule_id, match.rule_type),
            "actor_sid": sid, "actor_name": name,
            "host": hosts[0] if hosts else (getattr(self.uba, "host", "") or ""),
            "first_ts": min(starts) if starts else None,
            "last_ts": max(ends) if ends else None,
            "severity": severity, "uba_severity": uba_sev,
            "technique_id": list((alert.get("technique_id") if is_steps else match.technique_id) or []),
            "tactic": list((alert.get("tactic") if is_steps else match.tactic) or []),
            "event_ids": event_ids,
            "steps": steps,
            "evidence_refs": list(refs.values()),
            "conditions": list(match.conditions or []),
            "machine_steps": sum(1 for s in steps if s["machine_events"]),
            "uba_rules_hash": self._uba_rules_hash(),
            "wing_hash": result.wing_hash,
            "machine_only": machine_only,
            "note": (f"{HIT_IS_A_POINTER} {note}" if note else None),
        }

    def _uba_rules_hash(self) -> str:
        stamp = getattr(self.uba, "stamp", None) or {}
        rules_sha = stamp.get("rules_sha256") or ""
        user = stamp.get("user_rules_hash") or ""
        if not user:
            return rules_sha
        return hashlib.sha256(f"{rules_sha}:{user}".encode("utf-8")).hexdigest()

    # ------------------------------------------------------------- execute --
    def execute(self, wing_configs: List[Any]) -> Dict[str, Any]:
        """Run every Behaviour Wing given; store the run when an output folder
        is known. A Wing of another category is recorded SKIPPED with its
        reason, never dropped."""
        started_utc = _utc_now_text()
        t0 = time.time()
        self.results = []
        errors: List[str] = []
        warnings: List[str] = []
        wings = [self._as_wing_config(w) for w in (wing_configs or [])]
        # A run holding only Wings of other categories records them SKIPPED;
        # it has no reason to open (or rebuild) the case's UBA analysis.
        if any(engine_registry.check_wing(w, self.ENGINE_TYPE)[0] for w in wings):
            try:
                self.open_uba()
            except Exception as e:
                errors.append(f"User behaviour analysis unavailable: {e}")

        db = None
        if self.output_dir:
            os.makedirs(self.output_dir, exist_ok=True)
            from .database_persistence import ResultsDatabase
            db = ResultsDatabase(os.path.join(self.output_dir, "correlation_results.db"))
            if self.execution_id is None:
                self.execution_id = db.create_execution_placeholder(
                    pipeline_name=getattr(self.config, "pipeline_name", None) or "Behaviour Wings",
                    output_dir=self.output_dir,
                    case_name=getattr(self.config, "case_name", "") or "",
                    investigator=getattr(self.config, "investigator", "") or "",
                    engine_type=self.ENGINE_TYPE,
                    pipeline_config=(self.config.to_dict() if hasattr(self.config, "to_dict") else None),
                    time_period_start=_naive_utc_text(getattr(self.filters, "time_period_start", None)),
                    time_period_end=_naive_utc_text(getattr(self.filters, "time_period_end", None)),
                    run_group_id=getattr(self.config, "run_group_id", None))
        try:
            for wing in wings:
                if self._cancelled:
                    warnings.append(f"Cancelled ({self._cancel_reason}) before Wing "
                                    f"'{wing.wing_name}'.")
                    break
                ok, reason = engine_registry.check_wing(wing, self.ENGINE_TYPE)
                if not ok:
                    warnings.append(reason)
                    print(f"[WARN] {reason}")
                    if db is not None:
                        db.record_skipped_wing(self.execution_id, {
                            "wing_id": wing.wing_id, "wing_name": wing.wing_name,
                            "wing_category": wing.wing_category,
                            "engine_type": self.ENGINE_TYPE, "reason": reason})
                    continue
                if errors and self.uba is None:
                    res = BehaviourWingResult(wing_id=wing.wing_id, wing_name=wing.wing_name,
                                              wing_hash=wing_hash(wing), status="FAILED",
                                              errors=list(errors))
                else:
                    res = self.execute_wing(wing)
                self.results.append(res)
                for note in res.notes:
                    logger.info("[Behavioural Engine] %s: %s", wing.wing_name, note)
                errors.extend(res.errors)
                if db is not None:
                    res.result_id = db.save_behaviour_result(
                        self.execution_id, wing.wing_id, wing.wing_name,
                        total_hits=len(res.hits), events_evaluated=res.events_evaluated,
                        duration_seconds=res.duration_seconds, status=res.status,
                        info={"notes": res.notes, "not_evaluated": res.not_evaluated,
                              "events_selected": res.events_selected,
                              "people_evaluated": res.people_evaluated,
                              "wing_hash": res.wing_hash, "wing_category": WING_CATEGORY_BEHAVIOUR},
                        filters={"time_period_start": _naive_utc_text(
                                     getattr(self.filters, "time_period_start", None)),
                                 "time_period_end": _naive_utc_text(
                                     getattr(self.filters, "time_period_end", None))})
                    db.save_behaviour_hits(self.execution_id, res.result_id, res.hits)
            finished_utc = _utc_now_text()
            self.run_record = self._run_record(wings, started_utc, finished_utc, errors)
            actors = self._actor_rows()
            if db is not None:
                db.save_behaviour_actors(self.execution_id, actors)
                db.save_behaviour_run(self.execution_id, self.run_record)
                db.update_execution_stats(self.execution_id, execution_duration=time.time() - t0,
                                          errors=errors, warnings=warnings)
        finally:
            if db is not None:
                db.close()
        self.statistics = {
            "wings": len(self.results),
            "hits": sum(len(r.hits) for r in self.results),
            "people": len({sid for r in self.results for sid in r.people if sid}),
            "execution_time": round(time.time() - t0, 3),
            "cancelled": self._cancelled,
        }
        self._ledger()
        return {"result": self.results, "engine_type": self.ENGINE_TYPE,
                "execution_id": self.execution_id, "errors": errors, "warnings": warnings,
                "statistics": self.statistics,
                "filters_applied": {
                    "time_period_start": _naive_utc_text(getattr(self.filters, "time_period_start", None)),
                    "time_period_end": _naive_utc_text(getattr(self.filters, "time_period_end", None))}}

    def _actor_rows(self) -> List[Dict[str, Any]]:
        """One row per person across the run's Wings."""
        people: Dict[str, Dict[str, Any]] = {}
        no_sid = 0
        for res in self.results:
            no_sid += int(res.not_evaluated.get("no_sid") or 0)
            for sid, p in res.people.items():
                entry = people.setdefault(sid, {
                    "actor_sid": sid, "actor_name": p["actor_name"], "names": set(),
                    "host": getattr(self.uba, "host", "") or "",
                    "events_evaluated": 0, "events_timeless": 0,
                    "events_outside_time_filter": 0, "hits": 0, "wings": {}})
                entry["names"].update(p.get("names") or [])
                entry["events_evaluated"] += p["events_evaluated"]
                entry["events_timeless"] += p["events_timeless"]
                entry["events_outside_time_filter"] += p["events_outside_time_filter"]
                entry["hits"] += p["hits"]
                entry["wings"][res.wing_id] = {"events_evaluated": p["events_evaluated"],
                                               "hits": p["hits"]}
                if not sid:
                    entry["note"] = ("Events no person is recorded for (machine events), "
                                     "evaluated by machine steps only; hits on them are "
                                     f"capped at '{MACHINE_ONLY_MAX_SEVERITY}'.")
                if p.get("note"):                      # the occurrence cap was reached
                    entry["wings"][res.wing_id]["note"] = p["note"]
                    entry["note"] = " ".join(x for x in (entry.get("note"), p["note"]) if x)
        out = []
        for entry in people.values():
            entry["names"] = sorted(entry["names"])
            out.append(entry)
        if no_sid:
            out.append({"actor_sid": "", "actor_name": "(name without a profile)",
                        "names": [], "host": getattr(self.uba, "host", "") or "",
                        "events_evaluated": 0, "events_timeless": 0,
                        "events_outside_time_filter": 0, "hits": 0, "wings": {},
                        "note": f"{no_sid} event(s) not evaluated: attributed to an account "
                                f"name that matches no profile, so they carry no SID."})
        return out

    def _run_record(self, wings: List[WingConfig], started: str, finished: str,
                    errors: List[str]) -> Dict[str, Any]:
        """The run's custody record: what was read, under which rules, when."""
        uba = self.uba
        stamp = (getattr(uba, "stamp", None) or {}) if uba is not None else {}
        sources = stamp.get("sources") or {}
        status = "CANCELLED" if self._cancelled else ("FAILED" if errors and not self.results
                                                    else "COMPLETED")
        evidence_tables = sorted({(ref.get("db"), ref.get("table"))
                                  for res in self.results for hit in res.hits
                                  for ref in hit.get("evidence_refs") or []})
        return {
            "status": status,
            "started_utc": started, "finished_utc": finished,
            "engine": self.ENGINE_TYPE, "engine_version": self.metadata.version,
            "case_directory": self.case_dir, "artifacts_directory": self.artifacts_dir,
            "uba_store_path": getattr(uba, "store_path", None),
            "uba_built_at_utc": getattr(uba, "built_at_utc", None),
            "uba_loaded_from_store": bool(getattr(uba, "loaded_from_store", False)),
            "uba_rules_version": stamp.get("rules_version"),
            "uba_rules_sha256": stamp.get("rules_sha256"),
            "uba_rules_count": stamp.get("rules_count"),
            "uba_engine_code": stamp.get("engine_code"),
            "uba_disabled_rules": sorted(getattr(uba, "disabled_rules", ()) or ()),
            "uba_user_rules_hash": stamp.get("user_rules_hash") or "",
            "wing_hashes": {r.wing_id: r.wing_hash for r in self.results},
            "wings": [{"wing_id": r.wing_id, "wing_name": r.wing_name, "status": r.status,
                       "hits": len(r.hits), "notes": r.notes} for r in self.results],
            "source_tables": {"uba_sources": sources,
                              "evidence_tables": [f"{db}/{table}" for db, table in evidence_tables]},
            "not_evaluated": {r.wing_id: r.not_evaluated for r in self.results},
            "time_zone": self._tz_note,
            "filters": {"time_period_start": _naive_utc_text(getattr(self.filters, "time_period_start", None)),
                        "time_period_end": _naive_utc_text(getattr(self.filters, "time_period_end", None))},
            "execution_id": self.execution_id,
            "hits_are": "pointers to UBA events; cite the artifact rows they name",
        }

    def _ledger(self):
        """One line in the case's custody ledger (utils/custody.py) when the
        desktop's custody module is present and the case is known."""
        if not self.write_ledger or not self.case_dir:
            return
        try:
            from utils import custody
        except Exception:                            # headless host: no ledger here
            return
        record = self.run_record or {}
        custody.ledger(self.case_dir, "behaviour engine run",
                       execution_id=self.execution_id,
                       results_db=(os.path.join(self.output_dir, "correlation_results.db")
                                   if self.output_dir else None),
                       status=record.get("status"),
                       wings=[{"wing_id": w.get("wing_id"), "hits": w.get("hits"),
                               "status": w.get("status")} for w in record.get("wings", [])],
                       wing_hashes=record.get("wing_hashes"),
                       uba_rules_sha256=record.get("uba_rules_sha256"),
                       uba_store=record.get("uba_store_path"),
                       uba_built_at_utc=record.get("uba_built_at_utc"),
                       started_utc=record.get("started_utc"),
                       finished_utc=record.get("finished_utc"))


def run_behaviour_wings(case_dir: str, wings: Optional[List[Any]] = None,
                        output_dir: Optional[str] = None, **kwargs) -> Dict[str, Any]:
    """Run Behaviour Wings on a case (all shipped ones when ``wings`` is None)
    and store the run under ``<case>/Correlation/output`` unless told otherwise."""
    if wings is None:
        wings = shipped_behaviour_wings()
    engine = BehaviouralEngine(
        case_dir=case_dir,
        output_dir=output_dir or os.path.join(case_dir, "Correlation", "output"),
        **kwargs)
    return engine.execute(wings)


def shipped_behaviour_wings() -> List[WingConfig]:
    """The Behaviour Wings shipped in integration/default_wings."""
    import contextlib, io
    folder = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "integration", "default_wings")
    out = []
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(folder, name), encoding="utf-8") as fh:
            data = json.load(fh)
        if str(data.get("wing_category") or "").lower() != WING_CATEGORY_BEHAVIOUR:
            continue
        with contextlib.redirect_stdout(io.StringIO()):
            out.append(WingConfig.from_dict(data))
    return out
