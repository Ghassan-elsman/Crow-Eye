"""
Behaviour Results view - what a Behavioural run found, one person at a time.

The Behavioural engine (engine/behavioural_engine.py) runs Behaviour Wings
over UBA's behaviour events, per person (SID), and stores what it found in
correlation_results.db: one ``results`` row per Wing, and its own
``behaviour_hits`` / ``behaviour_actors`` / ``behaviour_runs`` tables. This
view reads them through ResultsDatabase.get_behaviour_*.

Layout:
- Header: people, Wings run, hits; the run's custody line (UBA rules version
  and SHA, when the UBA store was built, loaded or rebuilt); the pointer note.
- Toolbar: person / Wing / minimum severity, and "Open in User Behavior".
- Left: person -> Behaviour Wing -> hit. A Wing with no hits for a person is
  not listed under that person; "(no account recorded)" is a plain entry.
- Right: the selected row. For a hit: what fired, its steps and conditions,
  the UBA events behind it and the artifact rows those name (loaded on a
  worker when the hit is selected, never when the tab opens).
- Bottom: every Wing's outcome with its notes, so "found nothing" and "could
  not evaluate" are never the same line.

A hit is a POINTER to UBA events, not evidence. Every hit carries the note
the engine stored with it, and the view shows it beside the hit: cite the
artifact rows, re-read from the case.

**In order or any order.** A hit's icon says whether its steps had to happen
in order. Decided by ``hit_order``: the hit's ``conditions`` first (the
sequence evaluator writes "in this order" / "in any order" for every rule of
more than one step, a Wing's own steps and its advanced sequence rules
alike), then ``rule_type`` ('unordered' is a Wing's steps in any order,
'sequence' in order), and a one-step Wing ('match' / 'threshold') counts as
in order - there is nothing to reorder. The ``results`` row does not record
it, so it is never read from there.

Severity is ONE palette, UBA's (routine / notable / suspicious / critical):
a hit is coloured by its ``uba_severity`` when stored, else its correlation
severity mapped (info -> routine, low / medium -> notable, high ->
suspicious, critical -> critical). Red means urgent only; "not evaluated" and
"no data" are grey.

Headless parts (load_behaviour_runs, hit_order, display_severity and the
initial-filter builders) need no QApplication, so they are tested directly.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt5.QtGui import QBrush, QColor, QFont, QFontMetrics, QIcon, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView, QComboBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSplitter, QTableWidget,
    QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .crow_eye_icons import CrowEyeIcons, pair_icon_size, wing_icon
from ui import app_theme as _theme

logger = logging.getLogger(__name__)


# --- severity: one palette --------------------------------------------------
UBA_SEVERITIES = ("routine", "notable", "suspicious", "critical")
_UBA_RANK = {s: i for i, s in enumerate(UBA_SEVERITIES)}
# The correlation scale (a Wing's alert) on UBA's.
CORRELATION_TO_UBA = {"info": "routine", "low": "notable", "medium": "notable",
                      "high": "suspicious", "critical": "critical"}
# The UBA tokens (react-uba tokens.js SEVERITY_STYLE, app_theme's
# QLabel[severity=...] rules). Chips take them through set_severity; these
# are for tree / table items, which a property selector cannot reach.
SEVERITY_COLOURS = {"routine": "#8C95AB", "notable": "#F0A93B",
                    "suspicious": "#FF3B56", "critical": "#FF3B56"}
SEVERITY_LABELS = {"routine": "Routine", "notable": "Notable",
                   "suspicious": "Suspicious", "critical": "Critical"}

# Fixed level colours (person blue, Wing sky), muted for the entries that are
# not a person, violet for the analyst's own rules. A Behaviour Wing's icon is
# the Wing art beside the Behavioural engine's icon (wing_icon("behaviour")).
PERSON_TONE = "#60A5FA"
WING_TONE = "#38BDF8"
MUTED_TONE = _theme.MUTED
EMPTY_TONE = "#64748B"
USER_RULE_TONE = "#A78BFA"

# Minutes either side of a hit when User Behavior is opened on it.
UBA_WINDOW_PAD_MINUTES = 5
# Artifact rows fetched per evidence reference per page.
EVIDENCE_PAGE = 50

# Layout only, scoped by objectName so it reaches nothing else; colours all
# come from the window's theme sheet. Set once on the view (keepStyle).
VIEW_QSS = """
QFrame#beToolbar QLabel { font-size: 12px; }
QFrame#beToolbar QComboBox { font-size: 12px; padding: 2px 8px; border-radius: 8px; }
QFrame#beToolbar QComboBox::drop-down { width: 18px; }
QFrame#beToolbar QPushButton { font-size: 11px; padding: 3px 12px; border-radius: 10px; min-height: 0; }
QFrame#beDetail QPushButton { font-size: 11px; padding: 3px 12px; border-radius: 10px; min-height: 0; }
QFrame#beDetail QTableWidget { font-size: 12px; }
QFrame#beDetail QTableWidget::item { padding: 1px 6px; }
QFrame#beDetail QHeaderView::section { padding: 3px 6px; }
QTableWidget#beWings { font-size: 12px; }
QTableWidget#beWings::item { padding: 2px 6px; }
QLabel[chip="user_rule"], QFrame[card="true"] QLabel[chip="user_rule"] {
    color: #A78BFA; background: rgba(139, 92, 246, 0.16);
    border-radius: 9px; padding: 1px 9px; font-weight: 700; font-size: 11px; }
QFrame[card="true"] QLabel[severity] { border-radius: 6px; padding: 2px 8px; font-weight: 600; }
QFrame[card="true"] QLabel[severity="routine"] { color: #8C95AB; background: rgba(154, 163, 184, 0.12); }
QFrame[card="true"] QLabel[severity="notable"] { color: #F0A93B; background: rgba(240, 169, 59, 0.13); }
QFrame[card="true"] QLabel[severity="suspicious"] { color: #FF3B56; background: rgba(255, 59, 86, 0.13); }
QFrame[card="true"] QLabel[severity="critical"] { color: #FFFFFF; background: #FF3B56; }
"""
# The last five: the theme's QLabel[severity=...] chips, again. Inside a card
# the theme's own "QFrame[card] QLabel { background: transparent }" is the
# more specific rule, so a chip lost its fill there and "Critical" read as
# plain white text. Same tokens, card-scoped.


def display_severity(hit: Dict[str, Any]) -> str:
    """The UBA token a hit is shown in: its uba_severity when stored, else
    its correlation severity mapped. 'routine' when neither says anything."""
    uba = str(hit.get("uba_severity") or "").strip().lower()
    if uba in _UBA_RANK:
        return uba
    return CORRELATION_TO_UBA.get(str(hit.get("severity") or "").strip().lower(), "routine")


def hit_order(hit: Dict[str, Any]) -> str:
    """'ordered', 'any' or 'single' - see the module docstring."""
    conditions = [str(c).strip().lower() for c in (hit.get("conditions") or [])]
    if "in any order" in conditions:
        return "any"
    if "in this order" in conditions:
        return "ordered"
    rule_type = str(hit.get("rule_type") or "").strip().lower()
    if rule_type == "unordered":
        return "any"
    if rule_type in ("match", "threshold") and len(hit.get("steps") or []) <= 1:
        return "single"
    return "ordered"


def hit_is_ordered(hit: Dict[str, Any]) -> bool:
    return hit_order(hit) != "any"


ORDER_TEXT = {"ordered": "in order", "any": "any order", "single": "one step"}


# --- times ------------------------------------------------------------------
def _parse_utc(text):
    if not text:
        return None
    try:
        from utils.time_utils import parse_unknown_timestamp
        return parse_unknown_timestamp(str(text))
    except Exception:
        return None


def _utc_text(dt) -> str:
    if dt is None:
        return ""
    from utils.time_utils import format_forensic_timestamp
    return format_forensic_timestamp(dt)


def span_text(first, last) -> str:
    """'2026-02-15 17:38:17 -> 17:48:24' (the date once when both share it)."""
    first, last = str(first or ""), str(last or "")
    if not first:
        return "(no time)"
    if not last or last == first:
        return first
    if last[:10] == first[:10]:
        return "%s → %s" % (first, last[11:])
    return "%s → %s" % (first, last)


def _short_sid(sid: str) -> str:
    """S-1-5-21-...-1001: the domain part elided, the RID kept."""
    parts = str(sid or "").split("-")
    if len(parts) > 5 and parts[:4] == ["S", "1", "5", "21"]:
        return "S-1-5-21-…-%s" % parts[-1]
    return str(sid or "")


def _step_label(step: Dict[str, Any]) -> str:
    """The step's own words: 'Files permanently deleted in bulk' out of
    'Step 1 (Files permanently deleted in bulk)'."""
    label = str(step.get("label") or "")
    head = "Step %s (" % step.get("step")
    if label.startswith(head) and label.endswith(")"):
        return label[len(head):-1]
    return label or "Step %s" % step.get("step", "?")


def step_summary(hit: Dict[str, Any]) -> str:
    steps = hit.get("steps") or []
    if not steps:
        return ""
    parts = ["%s (%s)" % (_step_label(s), s.get("count", len(s.get("event_ids") or [])))
             for s in steps]
    if len(parts) == 1:
        return parts[0]
    joiner = " → " if hit_order(hit) != "any" else " + "
    return "%d steps: %s" % (len(parts), joiner.join(parts))


def _within(hit: Dict[str, Any]) -> str:
    for c in hit.get("conditions") or []:
        c = str(c)
        if c.startswith("within "):
            return c
    return ""


# --- initial filters for User Behavior --------------------------------------
def initial_filter_for_person(person: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """One person, no time limit. None for an entry that is not a person (no
    SID: the store's person key; a name without a profile is not one)."""
    sid = str(person.get("sid") or "")
    if not sid:
        return None
    return {"actor_sids": [sid], "actors": [], "start": "", "end": "",
            "label": "Behaviour Results: %s" % (person.get("name") or _short_sid(sid))}


def initial_filter_for_hit(hit: Dict[str, Any]) -> Dict[str, Any]:
    """The hit's person (when it has one) from first_ts - 5 min to
    last_ts + 5 min, UTC."""
    from datetime import timedelta
    pad = timedelta(minutes=UBA_WINDOW_PAD_MINUTES)
    first = _parse_utc(hit.get("first_ts"))
    last = _parse_utc(hit.get("last_ts")) or first
    sid = str(hit.get("actor_sid") or "")
    who = hit.get("actor_name") or (_short_sid(sid) if sid else "no account recorded")
    return {
        "actor_sids": [sid] if sid else [], "actors": [],
        "start": _utc_text(first - pad) if first else "",
        "end": _utc_text(last + pad) if last else "",
        "label": "Behaviour Results: %s, %s, %s" % (
            who, hit.get("wing_name") or hit.get("wing_id") or "hit",
            span_text(hit.get("first_ts"), hit.get("last_ts"))),
    }


# --- reading the run (headless) ---------------------------------------------
def _json(value, default):
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def wing_outcome(wing: Dict[str, Any]) -> (str, str):
    """(kind, words) for a Wing's results row. kind: 'hits', 'none' (found
    nothing), 'partial' (found nothing, and some events or steps were not
    evaluated), 'not_evaluated', 'failed', 'cancelled'."""
    status = str(wing.get("status") or "COMPLETED").upper()
    hits = int(wing.get("hits") or 0)
    if status == "SKIPPED":
        return "not_evaluated", "Skipped (not a Behaviour Wing)"
    if status == "NOT_EVALUABLE":
        return "not_evaluated", "Not evaluated"
    if status == "FAILED":
        return "failed", "Failed"
    if status == "CANCELLED":
        return "cancelled", "Cancelled"
    if hits:
        return "hits", "%d hit%s" % (hits, "" if hits == 1 else "s")
    if wing.get("notes"):
        return "partial", "No hits - part not evaluated"
    return "none", "No hits"


OUTCOME_TONE = {"hits": "accent", "none": "neutral", "partial": "neutral",
                "not_evaluated": "neutral", "failed": "warn", "cancelled": "neutral"}


def load_behaviour_runs(database_path: str, execution_ids) -> Dict[str, Any]:
    """Everything the view shows, read once. A live run gives each Wing its
    own execution, sharing a run_group_id: every Behavioural execution of
    the groups named is read, so they show as one run."""
    from correlation_engine.engine.database_persistence import ResultsDatabase
    wanted: List[int] = []
    for value in (execution_ids if isinstance(execution_ids, (list, tuple, set))
                  else [execution_ids]):
        try:
            value = int(value)
        except (TypeError, ValueError):
            continue
        if value not in wanted:
            wanted.append(value)
    model = {"execution_ids": [], "executions": [], "runs": {}, "people": [],
             "hits": [], "wings": [], "errors": []}
    db = ResultsDatabase(database_path)
    try:
        ids = list(wanted)
        for eid in wanted:
            row = db._rows_as_dicts(
                "SELECT run_group_id FROM executions WHERE execution_id = ?", (eid,))
            group = row[0].get("run_group_id") if row else None
            if group:
                for sib in db._rows_as_dicts(
                        "SELECT execution_id FROM executions WHERE run_group_id = ? "
                        "AND engine_type = 'behavioural' ORDER BY execution_id", (group,)):
                    if sib["execution_id"] not in ids:
                        ids.append(sib["execution_id"])
        ids.sort()
        model["execution_ids"] = ids
        people: Dict[str, Dict[str, Any]] = {}
        for eid in ids:
            ex = db._rows_as_dicts(
                "SELECT execution_id, run_name, execution_time, execution_duration_seconds, "
                "errors, warnings, engine_type, run_group_id FROM executions "
                "WHERE execution_id = ?", (eid,))
            if ex:
                model["executions"].append(ex[0])
            run = db.get_behaviour_run(eid)
            if run:
                model["runs"][eid] = run
            for a in db.get_behaviour_actors(eid):
                sid = a.get("actor_sid") or ""
                key = sid or "name:" + (a.get("actor_name") or "")
                p = people.setdefault(key, {
                    "key": key, "sid": sid, "name": a.get("actor_name") or "",
                    "names": [], "host": a.get("host") or "", "events_evaluated": 0,
                    "events_timeless": 0, "events_outside_time_filter": 0, "hits": 0,
                    "wings": {}, "note": "", "is_person": bool(sid)})
                for n in a.get("names_json") or []:
                    if n not in p["names"]:
                        p["names"].append(n)
                for k in ("events_evaluated", "events_timeless",
                          "events_outside_time_filter", "hits"):
                    p[k] += int(a.get(k) or 0)
                for wid, w in (a.get("wings_json") or {}).items():
                    acc = p["wings"].setdefault(wid, {"events_evaluated": 0, "hits": 0})
                    acc["events_evaluated"] += int((w or {}).get("events_evaluated") or 0)
                    acc["hits"] += int((w or {}).get("hits") or 0)
                p["note"] = p["note"] or (a.get("note") or "")
                p["host"] = p["host"] or (a.get("host") or "")
            model["hits"].extend(db.get_behaviour_hits(execution_id=eid))
            for w in db._rows_as_dicts(
                    "SELECT result_id, execution_id, wing_id, wing_name, total_matches, "
                    "total_records_scanned, status, progress_info FROM results "
                    "WHERE execution_id = ? ORDER BY result_id", (eid,)):
                info = _json(w.get("progress_info"), {})
                info = info if isinstance(info, dict) else {}
                model["wings"].append({
                    "result_id": w["result_id"], "execution_id": eid,
                    "wing_id": w.get("wing_id") or "", "wing_name": w.get("wing_name") or "",
                    "status": w.get("status") or "COMPLETED",
                    "hits": int(w.get("total_matches") or 0),
                    "events_evaluated": int(w.get("total_records_scanned") or 0),
                    "events_selected": int(info.get("events_selected") or 0),
                    "people_evaluated": int(info.get("people_evaluated") or 0),
                    "not_evaluated": info.get("not_evaluated") or {},
                    "notes": [str(n) for n in (info.get("notes") or []) if n],
                })
        # A hit's person is always listed, even with no actor row for it.
        for h in model["hits"]:
            sid = h.get("actor_sid") or ""
            key = sid or "name:" + (h.get("actor_name") or "")
            if key not in people:
                people[key] = {"key": key, "sid": sid, "name": h.get("actor_name") or "",
                               "names": [], "host": h.get("host") or "", "events_evaluated": 0,
                               "events_timeless": 0, "events_outside_time_filter": 0,
                               "hits": 0, "wings": {}, "note": "", "is_person": bool(sid)}
            h["_person"] = key
            h["_order"] = hit_order(h)
            h["_severity"] = display_severity(h)
        model["hits"].sort(key=lambda h: (str(h.get("first_ts") or "~"), h.get("hit_id") or 0))
        for p in people.values():
            p["hit_count"] = sum(1 for h in model["hits"] if h["_person"] == p["key"])
        model["people"] = sorted(
            people.values(),
            key=lambda p: (not p["is_person"], -p["hit_count"], p["name"].lower()))
    finally:
        try:
            db.close()
        except Exception:
            logger.debug("Behaviour Results: closing the results database failed", exc_info=True)
    return model


# --- the UBA store and the artifact rows (worker side, headless) ------------
_STAMP_WORDS = {
    "sources": "the case's artifact databases changed (parsed again)",
    "rules_version": "the UBA rules changed", "rules_sha256": "the UBA rules changed",
    "rules_count": "the UBA rules changed", "engine_code": "the UBA engine was updated",
    "disabled_hash": "UBA rules were switched on or off",
    "user_rules_hash": "your behaviour rules changed", "format": "the store format changed",
    "no store": "there is no stored analysis",
}


def check_store(run: Dict[str, Any]) -> Dict[str, Any]:
    """Is the UBA store this run read still there, and still the one it read?

    state: 'ok'; 'changed' (the store is the run's, but the case or UBA's
    rules have changed since it was built: its events are the ones the hit
    names, the artifact rows may have moved); 'rebuilt' (the store was built
    again after the run - its events may not be the ones the hit names);
    'missing'."""
    from uba.engine import persisted_store
    artifacts_dir = run.get("artifacts_directory") or ""
    path = run.get("uba_store_path") or (
        persisted_store.store_path(artifacts_dir) if artifacts_dir else "")
    out = {"path": path, "artifacts_dir": artifacts_dir, "built_at_utc": None,
           "run_built_at_utc": run.get("uba_built_at_utc"), "changes": []}
    if not path or not os.path.isfile(path):
        out.update(state="missing", message=(
            "There is no UBA store at %s, so the behaviour events behind this hit "
            "cannot be shown." % (path or "(no path recorded)")))
        return out
    meta = persisted_store.PersistedStore(artifacts_dir, path).read_meta()
    if not meta:
        out.update(state="missing", message="The UBA store at %s cannot be read." % path)
        return out
    out["built_at_utc"] = meta.get("built_at_utc")
    if run.get("uba_built_at_utc") and meta.get("built_at_utc") != run.get("uba_built_at_utc"):
        out.update(state="rebuilt", message=(
            "The UBA store was built again (%s UTC) after this run read it (built %s UTC). "
            "Its events may not be the ones this hit points to."
            % (meta.get("built_at_utc"), run.get("uba_built_at_utc"))))
        return out
    try:
        from uba.engine.behavior_engine import BehaviorEngine
        engine = BehaviorEngine(artifacts_dir, store_path=path)
        try:
            diffs = persisted_store.stamp_differences(meta.get("stamp"), engine.current_stamp())
        finally:
            engine.close()
    except Exception as e:
        logger.debug("Behaviour Results: store freshness not checked: %s", e)
        diffs = []
    words = []
    for d in diffs:
        w = _STAMP_WORDS.get(d, d)
        if w not in words:
            words.append(w)
    out["changes"] = words
    if words:
        out.update(state="changed", message=(
            "This is the UBA store the run read, but since it was built %s. The events are "
            "the ones this hit names; the artifact rows may have moved." % "; ".join(words)))
    else:
        out.update(state="ok", message="")
    return out


def rule_titles() -> Dict[str, Dict[str, Any]]:
    """{rule_id: {"title", "user_rule"}} for UBA's rules and the analyst's."""
    out = {}
    try:
        from uba.engine.rule_loader import load_rules
        builtin = load_rules()
        for r in builtin.get("rules") or []:
            out[r["id"]] = {"title": r.get("title") or r["id"], "user_rule": False}
        try:
            from uba.engine import user_rules
            loaded, _problems = user_rules.load_user_rules({r["id"] for r in builtin["rules"]})
            for r in loaded:
                if r.get("id"):
                    out[r["id"]] = {"title": r.get("title") or r["id"], "user_rule": True}
        except Exception:
            logger.debug("Behaviour Results: analyst rules not read", exc_info=True)
    except Exception:
        logger.debug("Behaviour Results: rule titles not read", exc_info=True)
    return out


def read_hit_events(store_path: str, event_ids: List[str]) -> Dict[str, Any]:
    """The UBA events a hit names, read-only from the store file (no copy of
    the whole store into memory). {"events": [...], "missing_ids": [...]}."""
    import sqlite3
    from uba.engine.event_store import UBAEventStore
    ids = [str(e) for e in dict.fromkeys(event_ids or []) if e]
    if not ids:
        return {"events": [], "missing_ids": []}
    conn = sqlite3.connect("file:{}?mode=ro".format(store_path.replace("\\", "/")),
                           uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        rows = []
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            rows.extend(conn.execute(
                "SELECT * FROM events WHERE event_id IN (%s)" % ",".join("?" * len(chunk)),
                chunk).fetchall())
        events = [UBAEventStore._row_to_dict(r) for r in rows]
    finally:
        conn.close()
    titles = rule_titles()
    for ev in events:
        meta = titles.get(ev.get("rule_id")) or {}
        ev["title"] = meta.get("title") or ev.get("activity") or ev.get("rule_id")
        ev["user_rule"] = bool(ev.get("user_rule") or meta.get("user_rule"))
    found = {e["event_id"] for e in events}
    events.sort(key=lambda e: (str(e.get("ts_start") or "~"), e.get("event_id")))
    return {"events": events, "missing_ids": [e for e in ids if e not in found]}


def fetch_artifact_rows(artifacts_dir: str, ref: Dict[str, Any], offset: int = 0,
                        page_size: int = EVIDENCE_PAGE) -> Dict[str, Any]:
    """One evidence reference's rows through UBA's EvidenceFetcher, on the
    calling thread: the pool is opened and closed here, so no connection
    outlives the thread that made it."""
    from uba.engine.evidence import EvidenceFetcher
    from uba.utils.db_access import DbPool
    pool = DbPool(artifacts_dir)
    try:
        result = EvidenceFetcher(pool).fetch([ref], offset=offset, page_size=page_size)
    finally:
        pool.close()
    groups = result.get("groups") or [{}]
    return groups[0]


# --- Qt pieces ----------------------------------------------------------------
class _Job(QThread):
    """Runs one function off the GUI thread; ``done(token, result)``."""
    done = pyqtSignal(object, object)

    def __init__(self, token, fn):
        super().__init__()
        self.token = token
        self.fn = fn

    def run(self):
        try:
            result = self.fn()
        except Exception as e:
            logger.warning("Behaviour Results: background load failed: %s", e)
            result = {"error": str(e)}
        self.done.emit(self.token, result)


# Jobs still running, held here (not by the view) so a tab closed mid-load
# never destroys a running QThread.
_LIVE_JOBS = set()

_ICON_CACHE: Dict[tuple, QIcon] = {}


def _tinted(name: str, colour: str) -> QIcon:
    """A CrowEyeIcons glyph recoloured (the hit icons follow the severity)."""
    key = (name, colour)
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
    base = getattr(CrowEyeIcons, name)()
    icon = QIcon()
    for px in (16, 20, 24, 32, 48):
        src = base.pixmap(px, px)
        if src.isNull():
            continue
        pm = QPixmap(src.size())
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.drawPixmap(0, 0, src)
        p.setCompositionMode(QPainter.CompositionMode_SourceIn)
        p.fillRect(pm.rect(), QColor(colour))
        p.end()
        icon.addPixmap(pm)
    _ICON_CACHE[key] = icon if not icon.isNull() else base
    return _ICON_CACHE[key]


def behaviour_tab_icon() -> QIcon:
    """The Behaviour Results tab's icon: "Activity pulse"."""
    return CrowEyeIcons.behaviour()


def _activity_icon(activity: str, user_rule: bool = False) -> Optional[QIcon]:
    key = ("activity", "user_rule" if user_rule else activity)
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
    icon = None
    try:
        from styles import CrowEyeStyles
        name = "user_rule" if user_rule else (activity or "")
        icon = CrowEyeStyles.resource_icon("uba", "icons", "activity", "%s.svg" % name)
    except Exception:
        icon = None
    _ICON_CACHE[key] = icon
    return icon


def _label(text="", role=None, status=None, wrap=False, select=False):
    lbl = QLabel(text)
    if role:
        _theme.set_role(lbl, role)
    if status:
        _theme.set_status(lbl, status)
    if wrap:
        lbl.setWordWrap(True)
    if select:
        lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return lbl


def _chip_width(text: str) -> int:
    """A chip's width in the font it is painted in (the window's 13px, weight
    600 from QLabel[severity]) plus its 8px padding either side - measured
    before the sheet reaches it, a chip came out narrower and clipped."""
    return QFontMetrics(_theme.font("ui", 13, QFont.DemiBold)).horizontalAdvance(text) + 22


def _severity_chip(token: str) -> QLabel:
    text = SEVERITY_LABELS.get(token, token.title())
    chip = QLabel(text)
    _theme.set_severity(chip, token)
    chip.setAlignment(Qt.AlignCenter)
    chip.setMinimumWidth(_chip_width(text))
    chip.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    return chip


def _chip_cell(token: str) -> QWidget:
    """A severity chip for a tree / table cell. The theme styles ``::item``,
    and Qt then ignores an item's own background, so "critical" (white on
    red) cannot be painted as item colours; a chip is the theme's own look."""
    cell = QWidget()
    lay = QHBoxLayout(cell)
    lay.setContentsMargins(2, 1, 2, 1)
    lay.addStretch()
    lay.addWidget(_severity_chip(token))
    lay.addStretch()
    cell.setMinimumWidth(_chip_width(SEVERITY_LABELS.get(token, token)) + 20)
    return cell


# Above this many hits the tree's severity column is text, not chip widgets.
MAX_CHIP_ROWS = 400


def _paint_severity(item, column, token):
    """A tree / table cell in the severity's colour; critical is white on red."""
    setter = (lambda role, v: item.setData(column, role, v)) if isinstance(item, QTreeWidgetItem) \
        else (lambda role, v: item.setData(role, v))
    if token == "critical":
        setter(Qt.ForegroundRole, QBrush(QColor("#FFFFFF")))
        setter(Qt.BackgroundRole, QBrush(QColor(SEVERITY_COLOURS["critical"])))
    else:
        setter(Qt.ForegroundRole, QBrush(QColor(SEVERITY_COLOURS.get(token, MUTED_TONE))))


def _header_font():
    """The theme's header font (apply_theme gives it to the headers that
    exist when a window is themed; tables built later need it set)."""
    return _theme.font("ui", 11, QFont.Bold, upper=True, spacing=108)


def _style_header(view):
    f = _header_font()
    header = view.header() if isinstance(view, QTreeWidget) else view.horizontalHeader()
    header.setFont(f)
    header.viewport().setFont(f)
    return header


def _fit_columns(table, stretch=None, cap=260, sample=200):
    """Column widths from the fonts the cells are painted in (the engine's
    12px items, the theme's uppercase header), not from whatever font the
    table had before the window's sheet reached it - that measured short and
    clipped the titles and the times. ``stretch`` takes the rest."""
    head_fm = QFontMetrics(_header_font())
    body_fm = QFontMetrics(_theme.font("ui", 12))
    header = _style_header(table)
    for c in range(table.columnCount()):
        if c == stretch:
            continue
        title = table.horizontalHeaderItem(c)
        need = head_fm.horizontalAdvance((title.text() if title else "").upper()) + 28
        for r in range(min(table.rowCount(), sample)):
            # A chip sits over an empty item: measure the chip, not the item.
            widget = table.cellWidget(r, c)
            if widget is not None:
                need = max(need, max(widget.sizeHint().width(), widget.minimumWidth()) + 12)
                continue
            item = table.item(r, c)
            if item is None:
                continue
            longest = max((body_fm.horizontalAdvance(line)
                           for line in item.text().split("\n")), default=0)
            extra = 26 if not item.icon().isNull() else 0
            need = max(need, longest + 22 + extra)
        header.setSectionResizeMode(c, QHeaderView.Interactive)
        table.setColumnWidth(c, min(need, cap))
    if stretch is not None:
        header.setStretchLastSection(False)
        header.setSectionResizeMode(stretch, QHeaderView.Stretch)
    else:
        header.setStretchLastSection(True)


def _table(headers, rows, stretch=None, max_rows=10, cap=260, wrap=True):
    """A compact read-only table sized to its rows (the detail pane scrolls,
    not each table). ``wrap`` False keeps every row one line (artifact rows:
    the full record is a double-click away)."""
    t = QTableWidget(len(rows), len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setAlternatingRowColors(True)
    t.setWordWrap(wrap)
    t.verticalHeader().setDefaultSectionSize(26)
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            item = value if isinstance(value, QTableWidgetItem) else QTableWidgetItem(
                "" if value is None else str(value))
            item.setToolTip(item.text())
            t.setItem(r, c, item)
    _fit_columns(t, stretch=stretch, cap=cap)
    if wrap:
        t.resizeRowsToContents()
    _fit_height(t, max_rows)
    return t


def _fit_height(table, max_rows=10):
    shown = min(max(table.rowCount(), 1), max_rows)
    h = max(table.horizontalHeader().sizeHint().height(), 28)
    rows = sum(table.rowHeight(r) for r in range(min(table.rowCount(), shown))) or 24
    table.setFixedHeight(h + rows + 6 + (14 if table.rowCount() > max_rows else 0))


class BehaviourResultsView(QWidget):
    """One Behavioural run (all its executions) as person -> Wing -> hit."""

    # Tree item kinds (Qt.UserRole + 1)
    PERSON, WING, HIT, NO_ACCOUNT = "person", "wing", "hit", "no_account"

    def __init__(self, database_path: str, execution_ids, parent=None):
        super().__init__(parent)
        self.database_path = database_path
        self.execution_ids = list(execution_ids) if isinstance(
            execution_ids, (list, tuple, set)) else [execution_ids]
        self.model: Dict[str, Any] = {"hits": [], "people": [], "wings": [], "runs": {},
                                      "executions": [], "errors": []}
        self._selected = None          # (kind, payload) of the row on the right
        self._token = 0                # the latest detail load; older answers are dropped
        self._store_checks: Dict[int, Dict[str, Any]] = {}
        self._force_stale = set()      # hit ids whose stale-store events were asked for
        self._hide_events = set()      # hit ids shown as the stored hit only
        self.setup_ui()
        try:
            self.model = load_behaviour_runs(database_path, self.execution_ids)
        except Exception as e:
            logger.exception("Behaviour Results: the run could not be read")
            self.model["errors"].append(str(e))
        self._fill_header()
        self._fill_filters()
        self._populate_tree()
        self._fill_wings_table()
        self._show_overview()

    # ------------------------------------------------------------------ layout
    def setup_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(6)
        root.setContentsMargins(4, 4, 4, 4)

        # === Header: totals, custody, the pointer note ===
        header = QFrame()
        header.setObjectName("beHeader")
        _theme.set_card(header)
        hl = QVBoxLayout(header)
        hl.setContentsMargins(14, 10, 14, 10)
        hl.setSpacing(5)
        top = QHBoxLayout()
        top.setSpacing(12)
        glyph = QLabel()
        glyph.setPixmap(behaviour_tab_icon().pixmap(22, 22))
        top.addWidget(glyph)
        title = _label("Behaviour Results", role="section")
        top.addWidget(title)
        self.people_lbl = _label("People: 0", status="info")
        self.people_lbl.setFont(_theme.font("ui", 12, QFont.Bold))
        self.wings_lbl = _label("Wings run: 0", role="muted")
        self.hits_lbl = _label("Hits: 0", status="accent")
        self.hits_lbl.setFont(_theme.font("ui", 12, QFont.Bold))
        for w in (self.people_lbl, self.wings_lbl, self.hits_lbl):
            top.addWidget(w)
        top.addStretch()
        self.run_lbl = _label("", role="muted")
        top.addWidget(self.run_lbl)
        hl.addLayout(top)
        self.custody_lbl = _label("", role="mono", wrap=True, select=True)
        hl.addWidget(self.custody_lbl)
        self.note_lbl = _label("", role="note", wrap=True)
        hl.addWidget(self.note_lbl)
        root.addWidget(header)

        # === Toolbar: filters + Open in User Behavior ===
        bar = QFrame()
        bar.setObjectName("beToolbar")
        _theme.set_card(bar)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(10, 4, 10, 4)
        bl.setSpacing(8)
        bl.addWidget(_label("Person:", role="muted"))
        self.person_filter = QComboBox()
        self.person_filter.setMinimumWidth(220)
        bl.addWidget(self.person_filter)
        bl.addWidget(_label("Behaviour Wing:", role="muted"))
        self.wing_filter = QComboBox()
        self.wing_filter.setMinimumWidth(260)
        bl.addWidget(self.wing_filter)
        bl.addWidget(_label("Min severity:", role="muted"))
        self.severity_filter = QComboBox()
        self.severity_filter.addItem("Any", "routine")
        self.severity_filter.addItem("Notable or above", "notable")
        self.severity_filter.addItem("Suspicious or above", "suspicious")
        self.severity_filter.addItem("Critical", "critical")
        self.severity_filter.setToolTip(
            "On the severity each hit is shown in: its UBA severity, else the Wing "
            "alert's (correlation scale) mapped to UBA's.")
        bl.addWidget(self.severity_filter)
        reset = QPushButton("Reset")
        _theme.set_variant(reset, "ghost")
        reset.clicked.connect(self._reset_filters)
        bl.addWidget(reset)
        bl.addStretch()
        self.open_uba_btn = QPushButton("Open in User Behavior")
        self.open_uba_btn.setIcon(behaviour_tab_icon())
        self.open_uba_btn.setToolTip(
            "Open the User Behavior window on this case, filtered to the selected person "
            "(and, for a hit, its time range with 5 minutes either side).")
        self.open_uba_btn.clicked.connect(self._open_in_uba)
        bl.addWidget(self.open_uba_btn)
        root.addWidget(bar)

        # === Middle: tree | detail ===
        split = QSplitter(Qt.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Person / Behaviour Wing / Hit", "Summary", "Severity"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setIndentation(22)
        # Pair-wide, for the Wing + engine pair; Qt draws the square person and
        # hit icons at their own 18 x 18 inside it.
        self.tree.setIconSize(pair_icon_size(18))
        header = _style_header(self.tree)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        head_fm = QFontMetrics(_header_font())
        body_fm = QFontMetrics(_theme.font("ui", 12))
        self.tree.setColumnWidth(0, 300)
        self.tree.setColumnWidth(2, max(head_fm.horizontalAdvance("SEVERITY") + 28,
                                        body_fm.horizontalAdvance("Suspicious") + 34,
                                        _chip_width("Suspicious") + 16))
        self.tree.itemSelectionChanged.connect(self._on_selection)
        split.addWidget(self.tree)

        self.detail_scroll = QScrollArea()
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setFrameShape(QFrame.NoFrame)
        split.addWidget(self.detail_scroll)
        split.setStretchFactor(0, 5)
        split.setStretchFactor(1, 6)
        split.setSizes([640, 760])

        # === Bottom: every Wing's outcome ===
        wings_box = QFrame()
        wl = QVBoxLayout(wings_box)
        wl.setContentsMargins(0, 4, 0, 0)
        wl.setSpacing(4)
        wl.addWidget(_label("Every Behaviour Wing - what it found, or why it could not look",
                            role="caption"))
        self.wings_table = QTableWidget(0, 6)
        self.wings_table.setObjectName("beWings")
        self.wings_table.setHorizontalHeaderLabels(
            ["Behaviour Wing", "Outcome", "Hits", "Events evaluated", "Not evaluated", "Notes"])
        self.wings_table.horizontalHeaderItem(3).setToolTip(
            "The Wing's results row (total_records_scanned): behaviour events it evaluated, "
            "all people and machine events together.")
        self.wings_table.verticalHeader().setVisible(False)
        self.wings_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.wings_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.wings_table.setAlternatingRowColors(True)
        # One line a Wing; the full notes are the cell's tooltip.
        self.wings_table.setWordWrap(False)
        self.wings_table.setIconSize(pair_icon_size(16))  # Wing + engine pair
        self.wings_table.verticalHeader().setDefaultSectionSize(26)
        self.wings_table.horizontalHeader().setStretchLastSection(True)
        wl.addWidget(self.wings_table)

        vsplit = QSplitter(Qt.Vertical)
        vsplit.addWidget(split)
        vsplit.addWidget(wings_box)
        vsplit.setStretchFactor(0, 4)
        vsplit.setStretchFactor(1, 1)
        vsplit.setSizes([520, 270])
        root.addWidget(vsplit, stretch=1)

        self.setStyleSheet(VIEW_QSS)
        _theme.keep_style(self)
        for combo in (self.person_filter, self.wing_filter, self.severity_filter):
            combo.currentIndexChanged.connect(self._populate_tree)

    # ------------------------------------------------------------------ header
    def _fill_header(self):
        m = self.model
        persons = [p for p in m["people"] if p["is_person"]]
        wing_ids = {w["wing_id"] for w in m["wings"]
                    if str(w.get("status") or "").upper() != "SKIPPED"}
        skipped = {w["wing_id"] for w in m["wings"]} - wing_ids
        self.people_lbl.setText("People: %d" % len(persons))
        self.wings_lbl.setText("Wings run: %d" % len(wing_ids)
                               + (", skipped: %d" % len(skipped) if skipped else ""))
        self.hits_lbl.setText("Hits: %d" % len(m["hits"]))
        _theme.set_status(self.hits_lbl, "accent" if m["hits"] else "neutral")
        runs = []
        for ex in m["executions"]:
            dur = ex.get("execution_duration_seconds")
            runs.append("%s%s" % (ex.get("execution_time") or "",
                                  " UTC, %.1f s" % dur if dur else ""))
        self.run_lbl.setText(
            ("Run %s" % runs[0]) if len(runs) == 1 else
            ("%d executions, %s - %s" % (len(runs), runs[0], runs[-1]) if runs else ""))
        if m["executions"]:
            self.run_lbl.setToolTip("\n".join(str(e.get("run_name") or "") for e in m["executions"]))
        lines = []
        for eid, run in sorted(m["runs"].items()):
            if not run.get("uba_rules_sha256") and not run.get("uba_built_at_utc"):
                continue        # an execution holding only skipped Wings read no store
            sha = str(run.get("uba_rules_sha256") or "")
            line = "UBA rules v%s, sha256 %s, %s rules - store built %s UTC, %s" % (
                run.get("uba_rules_version") or "?", sha[:12] or "?",
                run.get("uba_rules_count") if run.get("uba_rules_count") is not None else "?",
                run.get("uba_built_at_utc") or "?",
                "loaded from store" if run.get("uba_loaded_from_store") else "rebuilt for this run")
            if run.get("uba_user_rules_hash"):
                line += ", your rules %s" % str(run["uba_user_rules_hash"])[:12]
            if line not in lines:
                lines.append(line)
        if not lines:
            lines.append("No custody record for this run (behaviour_runs is empty).")
        self.custody_lbl.setText("\n".join(lines))
        if m["runs"]:
            first = m["runs"][sorted(m["runs"])[0]]
            self.custody_lbl.setToolTip("UBA store: %s\nCase: %s" % (
                first.get("uba_store_path") or "?", first.get("case_directory") or "?"))
        note = ""
        if m["hits"]:
            note = m["hits"][0].get("note") or ""
        if not note:
            try:
                from correlation_engine.engine.database_persistence import ResultsDatabase
                note = ResultsDatabase.BEHAVIOUR_HIT_NOTE
            except Exception:
                note = ("A pointer to UBA behaviour events, not evidence. Cite the artifact "
                        "rows its evidence references name, re-read from the case.")
        self.note_lbl.setText("Every hit is a pointer. " + note)
        if m["errors"]:
            self.note_lbl.setText("The run could not be read: %s" % "; ".join(m["errors"]))
            _theme.set_status(self.note_lbl, "warn")

    def _fill_filters(self):
        for combo in (self.person_filter, self.wing_filter):
            combo.blockSignals(True)
            combo.clear()
        self.person_filter.addItem("All people", None)
        for p in self.model["people"]:
            if p["is_person"]:
                self.person_filter.addItem("%s (%s)" % (p["name"] or "?", _short_sid(p["sid"])),
                                           p["key"])
        self.wing_filter.addItem("All Behaviour Wings", None)
        seen = set()
        for w in sorted(self.model["wings"], key=lambda w: w["wing_name"].lower()):
            if w["wing_id"] in seen:
                continue
            seen.add(w["wing_id"])
            self.wing_filter.addItem(w["wing_name"] or w["wing_id"], w["wing_id"])
        for combo in (self.person_filter, self.wing_filter):
            combo.blockSignals(False)

    def _reset_filters(self):
        for combo in (self.person_filter, self.wing_filter, self.severity_filter):
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        self._populate_tree()

    # ------------------------------------------------------------------ tree
    def _visible_hits(self):
        person = self.person_filter.currentData()
        wing = self.wing_filter.currentData()
        floor = _UBA_RANK.get(self.severity_filter.currentData() or "routine", 0)
        return [h for h in self.model["hits"]
                if (person is None or h["_person"] == person)
                and (wing is None or h.get("wing_id") == wing)
                and _UBA_RANK.get(h["_severity"], 0) >= floor]

    def _populate_tree(self, *_):
        self.tree.blockSignals(True)
        self.tree.clear()
        hits = self._visible_hits()
        person_filter = self.person_filter.currentData()
        narrowed = (self.wing_filter.currentData() is not None
                    or (self.severity_filter.currentData() or "routine") != "routine")
        bold = _theme.font("ui", 12, QFont.Bold)
        for p in self.model["people"]:
            if person_filter is not None and p["key"] != person_filter:
                continue
            mine = [h for h in hits if h["_person"] == p["key"]]
            if not p["is_person"]:
                if not mine and person_filter is None and not narrowed:
                    self.tree.addTopLevelItem(self._no_account_item(p))
                    continue
                if not mine:
                    continue
            if narrowed and not mine:
                continue
            item = QTreeWidgetItem([p["name"] or "(no name)", "", ""])
            item.setData(0, Qt.UserRole, p["key"])
            item.setData(0, Qt.UserRole + 1, self.PERSON)
            item.setIcon(0, CrowEyeIcons.person() if p["is_person"] else QIcon())
            item.setFont(0, bold)
            item.setForeground(0, QBrush(QColor(PERSON_TONE if p["is_person"] else MUTED_TONE)))
            bits = []
            if p["sid"]:
                bits.append(_short_sid(p["sid"]))
            if p["host"]:
                bits.append(p["host"])
            bits.append("%d hit%s" % (len(mine), "" if len(mine) == 1 else "s"))
            bits.append("%d events evaluated" % p["events_evaluated"])
            item.setText(1, " · ".join(bits))
            item.setForeground(1, QBrush(QColor(MUTED_TONE)))
            item.setToolTip(0, "%s\nSID %s\nHost %s" % (p["name"], p["sid"] or "(none)",
                                                       p["host"] or "(unknown)"))
            self.tree.addTopLevelItem(item)
            by_wing: Dict[str, List[Dict[str, Any]]] = {}
            for h in mine:
                by_wing.setdefault(h.get("wing_id") or "", []).append(h)
            for wid in sorted(by_wing, key=lambda k: (by_wing[k][0].get("wing_name") or k).lower()):
                wing_hits = by_wing[wid]
                first = wing_hits[0]
                w_item = QTreeWidgetItem([first.get("wing_name") or wid, "", ""])
                w_item.setData(0, Qt.UserRole, (p["key"], wid))
                w_item.setData(0, Qt.UserRole + 1, self.WING)
                w_item.setIcon(0, wing_icon("behaviour"))  # the Wing, then its engine
                w_item.setForeground(0, QBrush(QColor(WING_TONE)))
                words = ["Behaviour Wing", ORDER_TEXT[first["_order"]]]
                if _within(first):
                    words.append(_within(first))
                words.append("%d hit%s" % (len(wing_hits), "" if len(wing_hits) == 1 else "s"))
                w_item.setText(1, " · ".join(words))
                w_item.setForeground(1, QBrush(QColor(MUTED_TONE)))
                item.addChild(w_item)
                for h in wing_hits:
                    h_item = self._hit_item(h)
                    w_item.addChild(h_item)
                    if len(hits) <= MAX_CHIP_ROWS:
                        h_item.setText(2, "")
                        self.tree.setItemWidget(h_item, 2, _chip_cell(h["_severity"]))
                w_item.setExpanded(True)
            item.setExpanded(True)
        if self.tree.topLevelItemCount() == 0:
            empty = QTreeWidgetItem(["No hits match these filters" if self.model["hits"]
                                     else "This run found no hits", "", ""])
            empty.setForeground(0, QBrush(QColor(EMPTY_TONE)))
            empty.setFlags(Qt.NoItemFlags)
            self.tree.addTopLevelItem(empty)
        self.tree.blockSignals(False)
        self._show_overview()

    def _hit_item(self, h):
        token = h["_severity"]
        item = QTreeWidgetItem([span_text(h.get("first_ts"), h.get("last_ts")),
                                step_summary(h), SEVERITY_LABELS.get(token, token)])
        item.setData(0, Qt.UserRole, h.get("hit_id"))
        item.setData(0, Qt.UserRole + 1, self.HIT)
        icon_name = "hit_any" if h["_order"] == "any" else "hit_ordered"
        item.setIcon(0, _tinted(icon_name, SEVERITY_COLOURS.get(token, MUTED_TONE)))
        item.setForeground(0, QBrush(QColor(_theme.BODY)))
        _paint_severity(item, 2, token)
        item.setTextAlignment(2, Qt.AlignCenter)
        item.setToolTip(0, "Steps %s. %s" % (ORDER_TEXT[h["_order"]], h.get("note") or ""))
        item.setToolTip(1, step_summary(h))
        item.setToolTip(2, "UBA severity %s; Wing alert %s (correlation scale)" % (
            h.get("uba_severity") or "(none)", h.get("severity") or "(none)"))
        return item

    def _no_account_item(self, p):
        """Events no person is recorded for: plain and muted, never a person."""
        item = QTreeWidgetItem([p["name"] or "(no account recorded)", "", ""])
        item.setData(0, Qt.UserRole, p["key"])
        item.setData(0, Qt.UserRole + 1, self.NO_ACCOUNT)
        bits = []
        if p["host"]:
            bits.append(p["host"])
        if p["events_timeless"]:
            bits.append("%d events with no time" % p["events_timeless"])
        bits.append("%d evaluated" % p["events_evaluated"])
        item.setText(1, " · ".join(bits))
        for c in (0, 1):
            item.setForeground(c, QBrush(QColor(EMPTY_TONE)))
        item.setToolTip(0, p["note"] or "No account is recorded for these events.")
        item.setToolTip(1, p["note"] or "")
        return item

    # ------------------------------------------------------------------ wings table
    def _fill_wings_table(self):
        wings = sorted(self.model["wings"],
                       key=lambda w: (wing_outcome(w)[0] != "hits", w["wing_name"].lower()))
        t = self.wings_table
        t.setRowCount(len(wings))
        errors = "; ".join(str(e.get("errors")) for e in self.model["executions"] if e.get("errors"))
        for r, w in enumerate(wings):
            kind, words = wing_outcome(w)
            ne = w.get("not_evaluated") or {}
            ne_total = sum(int(v or 0) for v in ne.values()) if isinstance(ne, dict) else 0
            notes = list(w.get("notes") or [])
            if kind == "failed" and errors:
                notes.append("Run errors: %s" % errors)
            if kind == "none" and not notes:
                notes.append("Evaluated, and nothing met the Wing's steps.")
            cells = [w["wing_name"] or w["wing_id"], words, str(w["hits"]),
                     str(w["events_evaluated"]), str(ne_total) if ne_total else "",
                     "  |  ".join(notes)]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                if c == 0:
                    item.setIcon(wing_icon("behaviour"))
                if c == 1:
                    item.setForeground(QBrush(QColor(_theme.STATUS_COLORS.get(
                        OUTCOME_TONE.get(kind, "neutral"), MUTED_TONE))))
                    item.setFont(_theme.font("ui", 12, QFont.Bold))
                elif c == 0 and kind in ("hits",):
                    item.setForeground(QBrush(QColor(WING_TONE)))
                elif c in (0, 5) and kind != "hits":
                    item.setForeground(QBrush(QColor(MUTED_TONE)))
                if c in (2, 3, 4):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                t.setItem(r, c, item)
        _fit_columns(t, stretch=5, cap=340)

    # ------------------------------------------------------------------ detail
    def _set_detail(self, widget):
        old = self.detail_scroll.takeWidget()
        if old is not None:
            old.hide()
            old.deleteLater()
        self.detail_scroll.setWidget(widget)

    def _card(self):
        frame = QFrame()
        frame.setObjectName("beDetail")
        _theme.set_card(frame)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)
        return frame, lay

    def _show_overview(self):
        """Nothing selected: what the run is and how to read it."""
        self._selected = None
        self._token += 1
        frame, lay = self._card()
        lay.addWidget(_label("Select a hit", role="section"))
        lay.addWidget(_label(
            "Each person is listed by SID with the Behaviour Wings that found something for "
            "them; a hit's icon is the Wing's time range, its steps joined by an arrow when "
            "they had to happen in order and loose when any order counts. Selecting a hit loads "
            "the UBA behaviour events it points to and the artifact rows they name.",
            role="muted", wrap=True))
        lay.addWidget(_label(
            "A hit is a pointer, not evidence: cite the artifact rows, re-read from the case.",
            role="note", wrap=True))
        legend = QGridLayout()
        legend.setHorizontalSpacing(10)
        rows = [(CrowEyeIcons.person(), "Person (by SID)"),
                (wing_icon("behaviour"), "Behaviour Wing"),
                (_tinted("hit_ordered", SEVERITY_COLOURS["notable"]), "Hit, steps in order"),
                (_tinted("hit_any", SEVERITY_COLOURS["notable"]), "Hit, any order")]
        for r, (icon, text) in enumerate(rows):
            g = QLabel()
            # The Wing's pair is twice as wide as the square icons; same height.
            g.setPixmap(icon.pixmap(icon.actualSize(pair_icon_size(18))))
            legend.addWidget(g, r, 0)
            legend.addWidget(_label(text, role="muted"), r, 1)
        legend.setColumnStretch(2, 1)
        lay.addLayout(legend)
        sev = QHBoxLayout()
        sev.addWidget(_label("Severity:", role="muted"))
        for token in UBA_SEVERITIES:
            sev.addWidget(_severity_chip(token))
        sev.addStretch()
        lay.addLayout(sev)
        lay.addStretch()
        self._set_detail(frame)

    def _on_selection(self):
        items = self.tree.selectedItems()
        if not items:
            self._show_overview()
            return
        item = items[0]
        kind = item.data(0, Qt.UserRole + 1)
        key = item.data(0, Qt.UserRole)
        self._token += 1
        if kind == self.HIT:
            hit = self._hit_by_id(key)
            if hit is not None:
                self._selected = (self.HIT, hit)
                self._show_hit(hit)
                return
        if kind in (self.PERSON, self.NO_ACCOUNT):
            person = self._person_by_key(key)
            if person is not None:
                self._selected = (kind, person)
                self._show_person(person)
                return
        if kind == self.WING:
            pkey, wid = key
            self._selected = (self.WING, (self._person_by_key(pkey), wid))
            self._show_wing(self._person_by_key(pkey), wid)
            return
        self._show_overview()

    def _hit_by_id(self, hit_id):
        return next((h for h in self.model["hits"] if h.get("hit_id") == hit_id), None)

    def _person_by_key(self, key):
        return next((p for p in self.model["people"] if p["key"] == key), None)

    def _wing_rows(self, wid):
        return [w for w in self.model["wings"] if w["wing_id"] == wid]

    def _run_of(self, execution_id):
        runs = self.model["runs"]
        return runs.get(execution_id) or (runs[sorted(runs)[0]] if runs else {})

    # .. person / wing ..........................................................
    def _show_person(self, p):
        frame, lay = self._card()
        head = QHBoxLayout()
        if p["is_person"]:
            g = QLabel()
            g.setPixmap(CrowEyeIcons.person().pixmap(22, 22))
            head.addWidget(g)
        head.addWidget(_label(p["name"] or "(no name)", role="section"))
        head.addStretch()
        if p["is_person"]:
            btn = QPushButton("Open in User Behavior")
            btn.setIcon(behaviour_tab_icon())
            btn.clicked.connect(self._open_in_uba)
            head.addWidget(btn)
        lay.addLayout(head)
        if not p["is_person"]:
            lay.addWidget(_label(p["note"] or "No account is recorded for these events: they "
                                 "are context about the machine, not a person.", role="muted",
                                 wrap=True))
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(4)
        fields = [("SID", p["sid"] or "(none recorded)"), ("Host", p["host"] or "(unknown)"),
                  ("Names seen", ", ".join(p["names"]) or "-"),
                  ("Events evaluated", str(p["events_evaluated"])),
                  ("Events with no time (not evaluated)", str(p["events_timeless"])),
                  ("Events outside the run's time filter", str(p["events_outside_time_filter"])),
                  ("Hits", str(p["hit_count"]))]
        self._fill_grid(grid, fields)
        lay.addLayout(grid)
        if p["wings"]:
            lay.addWidget(_label("Per Behaviour Wing", role="caption"))
            names = {w["wing_id"]: w["wing_name"] for w in self.model["wings"]}
            rows = [[names.get(wid, wid), str(v.get("events_evaluated", 0)), str(v.get("hits", 0))]
                    for wid, v in sorted(p["wings"].items(), key=lambda kv: names.get(kv[0], kv[0]))]
            lay.addWidget(_table(["Behaviour Wing", "Events evaluated", "Hits"], rows,
                                 stretch=0, max_rows=12))
        lay.addStretch()
        self._set_detail(frame)

    def _show_wing(self, p, wid):
        frame, lay = self._card()
        rows = self._wing_rows(wid)
        name = rows[0]["wing_name"] if rows else wid
        head = QHBoxLayout()
        g = QLabel()
        g.setPixmap(wing_icon("behaviour").pixmap(pair_icon_size(22)))
        head.addWidget(g)
        head.addWidget(_label(name, role="section"))
        head.addStretch()
        lay.addLayout(head)
        mine = [h for h in self.model["hits"] if h.get("wing_id") == wid
                and (p is None or h["_person"] == p["key"])]
        fields = [("Wing id", wid), ("Hits for %s" % (p["name"] if p else "everyone"), str(len(mine)))]
        if mine:
            fields.append(("Steps", ORDER_TEXT[mine[0]["_order"]]))
            fields.append(("Rule type", mine[0].get("rule_type") or "-"))
        for w in rows:
            kind, words = wing_outcome(w)
            fields.append(("Outcome", words))
            fields.append(("Events evaluated (all people)", str(w["events_evaluated"])))
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        self._fill_grid(grid, fields)
        lay.addLayout(grid)
        notes = [n for w in rows for n in w.get("notes") or []]
        if notes:
            lay.addWidget(_label("Notes", role="caption"))
            for n in notes:
                lay.addWidget(_label(n, role="muted", wrap=True))
        lay.addStretch()
        self._set_detail(frame)

    @staticmethod
    def _fill_grid(grid, fields, start_row=0):
        for r, (k, v) in enumerate(fields, start=start_row):
            key = _label(k, role="muted")
            key.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            grid.addWidget(key, r, 0)
            val = _label(str(v), wrap=True, select=True)
            grid.addWidget(val, r, 1)
        grid.setColumnStretch(1, 1)

    # .. hit .......................................................................
    def _show_hit(self, h):
        frame, lay = self._card()
        token = h["_severity"]
        head = QHBoxLayout()
        g = QLabel()
        g.setPixmap(_tinted("hit_any" if h["_order"] == "any" else "hit_ordered",
                            SEVERITY_COLOURS.get(token, MUTED_TONE)).pixmap(22, 22))
        head.addWidget(g)
        head.addWidget(_label(h.get("wing_name") or h.get("wing_id") or "Hit", role="section"))
        head.addWidget(_severity_chip(token))
        head.addStretch()
        btn = QPushButton("Open in User Behavior")
        btn.setIcon(behaviour_tab_icon())
        btn.setToolTip("This person from 5 minutes before the hit to 5 minutes after it.")
        btn.clicked.connect(self._open_in_uba)
        head.addWidget(btn)
        lay.addLayout(head)
        lay.addWidget(_label(h.get("note") or "", role="note", wrap=True))

        tech = ", ".join(h.get("technique_id") or []) or "-"
        tactic = ", ".join(h.get("tactic") or []) or "-"
        fields = [
            ("Person", "%s  (%s)" % (h.get("actor_name") or "(no account recorded)",
                                     h.get("actor_sid") or "no SID")),
            ("Host", h.get("host") or "-"),
            ("Rule", h.get("rule_name") or h.get("rule") or "-"),
            ("Rule id / type", "%s  /  %s" % (h.get("rule") or "-", h.get("rule_type") or "-")),
            ("Steps", ORDER_TEXT[h["_order"]] + (", " + _within(h) if _within(h) else "")),
            ("Severity (Wing alert, correlation scale)", h.get("severity") or "-"),
            ("UBA severity", h.get("uba_severity") or "-"),
            ("ATT&CK technique", tech),
            ("ATT&CK tactic", tactic),
            ("First (UTC)", h.get("first_ts") or "-"),
            ("Last (UTC)", h.get("last_ts") or "-"),
            ("Wing SHA-256", str(h.get("wing_hash") or "-")[:16]),
            ("UBA rules SHA-256", str(h.get("uba_rules_hash") or "-")[:16]),
        ]
        if h.get("machine_steps"):
            fields.append(("Steps on machine events", str(h["machine_steps"])))
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(3)
        self._fill_grid(grid, fields)
        lay.addLayout(grid)

        lay.addWidget(_label("Conditions", role="caption"))
        for c in h.get("conditions") or ["(none stored)"]:
            lay.addWidget(_label("• " + str(c), role="mono", wrap=True, select=True))

        lay.addWidget(_label("Steps", role="caption"))
        steps = h.get("steps") or []
        lay.addWidget(_table(
            ["Step", "What", "Count", "Who", "First (UTC)", "UBA event ids"],
            [[s.get("step"), _step_label(s), s.get("count"),
              "machine events" if s.get("machine_events") else (s.get("actor") or "-"),
              s.get("first_ts") or "-", ", ".join(str(e) for e in s.get("event_ids") or [])]
             for s in steps], stretch=5, max_rows=8))

        lay.addWidget(_label("UBA behaviour events behind it", role="caption"))
        self._events_box = QVBoxLayout()
        self._events_box.setSpacing(6)
        lay.addLayout(self._events_box)
        self._events_box.addWidget(_label("Loading the events from the UBA store…",
                                          role="muted"))

        lay.addWidget(_label("Artifact rows they name", role="caption"))
        self._evidence_box = QVBoxLayout()
        self._evidence_box.setSpacing(6)
        lay.addLayout(self._evidence_box)
        refs = h.get("evidence_refs") or []
        if not refs:
            self._evidence_box.addWidget(_label("This hit stores no evidence references.",
                                                role="muted"))
        lay.addStretch()
        self._set_detail(frame)
        self._load_events(h)
        for i, ref in enumerate(refs):
            self._add_evidence_group(h, i, ref)

    def _start(self, fn, on_done):
        token = self._token
        job = _Job(token, fn)
        _LIVE_JOBS.add(job)

        def done(tok, result):
            try:
                if tok == self._token:
                    on_done(result)
            except RuntimeError:          # the view was closed meanwhile
                pass

        def finished(job=job):
            # Released only once run() has returned, never while it runs.
            _LIVE_JOBS.discard(job)
            job.deleteLater()

        job.done.connect(done)
        job.finished.connect(finished)
        job.start()
        return job

    # .. UBA events ...............................................................
    def _load_events(self, h):
        run = self._run_of(h.get("execution_id"))
        eid = h.get("execution_id")
        hit_id = h.get("hit_id")
        cached = self._store_checks.get(eid)
        force = hit_id in self._force_stale

        def work():
            check = cached or check_store(run)
            out = {"check": check}
            if check["state"] == "missing" or (check["state"] == "rebuilt" and not force):
                return out
            out.update(read_hit_events(check["path"], h.get("event_ids") or []))
            return out

        self._start(work, lambda result: self._show_events(h, result))

    def _clear(self, box):
        # Hidden at once: deleteLater waits for the event loop, and until then
        # the old label and buttons still paint under the new ones.
        while box.count():
            item = box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.deleteLater()
            elif item.layout() is not None:
                self._clear(item.layout())

    def _show_events(self, h, result):
        box = self._events_box
        self._clear(box)
        if result.get("error"):
            box.addWidget(_label("The UBA events could not be read: %s" % result["error"],
                                 status="warn", wrap=True))
            return
        check = result.get("check") or {}
        if check:
            self._store_checks[h.get("execution_id")] = check
        state = check.get("state")
        hit_id = h.get("hit_id")
        if state == "missing":
            # No data is grey: nothing is wrong with the hit, the store is not there.
            box.addWidget(_label(check.get("message") or "", role="muted", wrap=True))
        elif state in ("rebuilt", "changed"):
            # A caveat on what the events are: amber when they may not be the
            # hit's own, the plain note when they are but the case moved on.
            msg = _label(check.get("message") or "", role="note", wrap=True)
            if state == "rebuilt":
                _theme.set_status(msg, "warn")
            box.addWidget(msg)
        if state == "missing":
            box.addWidget(_label("Only the stored hit is shown: its steps and event ids above, "
                                 "and the artifact rows below, which are read from the case.",
                                 role="muted", wrap=True))
            return
        if state == "rebuilt" and hit_id not in self._force_stale:
            row = QHBoxLayout()
            row.addWidget(_label("Only the stored hit is shown.", role="muted"))
            anyway = QPushButton("Show the store's events anyway")
            _theme.set_variant(anyway, "ghost")
            anyway.clicked.connect(lambda: self._force_events(h))
            row.addWidget(anyway)
            row.addStretch()
            box.addLayout(row)
            return
        if hit_id in self._hide_events:
            row = QHBoxLayout()
            row.addWidget(_label("Showing the stored hit only.", role="muted"))
            again = QPushButton("Show the events")
            _theme.set_variant(again, "ghost")
            again.clicked.connect(lambda: self._toggle_events(h, show=True))
            row.addWidget(again)
            row.addStretch()
            box.addLayout(row)
            return
        if state in ("changed", "rebuilt"):
            row = QHBoxLayout()
            only = QPushButton("Show only the stored hit")
            _theme.set_variant(only, "ghost")
            only.clicked.connect(lambda: self._toggle_events(h, show=False))
            row.addWidget(only)
            row.addStretch()
            box.addLayout(row)
        events = result.get("events") or []
        if result.get("missing_ids"):
            box.addWidget(_label(
                "%d of the hit's events are not in the store: %s" % (
                    len(result["missing_ids"]), ", ".join(result["missing_ids"])),
                status="warn", wrap=True))
        if not events:
            box.addWidget(_label("None of the hit's events are in the store.", role="muted"))
            return
        table = QTableWidget(len(events), 6)
        # Description last and stretching: the card is narrow, and a column
        # after the stretch one was pushed off its edge.
        table.setHorizontalHeaderLabels(["Behaviour", "Severity", "Time (UTC)", "App",
                                         "Rule", "Description"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setWordWrap(True)
        table.setIconSize(QSize(20, 20))
        for r, ev in enumerate(events):
            title = QTableWidgetItem(ev.get("title") or "")
            icon = _activity_icon(ev.get("activity"), ev.get("user_rule"))
            if icon is not None:
                title.setIcon(icon)
            title.setToolTip("%s (%s)" % (ev.get("activity"), ev.get("event_id")))
            table.setItem(r, 0, title)
            if ev.get("user_rule"):
                chip = QLabel("Your rule")
                chip.setProperty("chip", "user_rule")
                chip.setAlignment(Qt.AlignCenter)
                chip.setToolTip("Found by a behaviour rule you created (%s)" % ev.get("rule_id"))
                cell = QWidget()
                cl = QHBoxLayout(cell)
                cl.setContentsMargins(4, 2, 4, 2)
                cl.addWidget(chip)
                cl.addStretch()
                table.setCellWidget(r, 4, cell)
                table.setItem(r, 4, QTableWidgetItem(""))
            else:
                rid = QTableWidgetItem(ev.get("rule_id") or "")
                rid.setForeground(QBrush(QColor(MUTED_TONE)))
                table.setItem(r, 4, rid)
            span = span_text(ev.get("ts_start"), ev.get("ts_end")) if ev.get("ts_start") \
                else "(no time)"
            table.setItem(r, 2, QTableWidgetItem(span))
            table.setItem(r, 3, QTableWidgetItem(ev.get("app_name") or "-"))
            desc = QTableWidgetItem(ev.get("description") or "")
            desc.setToolTip(ev.get("description") or "")
            table.setItem(r, 5, desc)
            sev = str(ev.get("severity") or "routine")
            sev_item = QTableWidgetItem("")
            sev_item.setToolTip("UBA severity: %s" % sev)
            table.setItem(r, 1, sev_item)
            table.setCellWidget(r, 1, _chip_cell(sev))
        _fit_columns(table, stretch=5, cap=240)
        table.resizeRowsToContents()
        _fit_height(table, 8)
        table.setToolTip("Double-click a behaviour event for its full record")
        table.cellDoubleClicked.connect(lambda r, _c: self._open_event(events[r]))
        box.addWidget(table)

    def _force_events(self, h):
        self._force_stale.add(h.get("hit_id"))
        self._hide_events.discard(h.get("hit_id"))
        self._clear(self._events_box)
        self._events_box.addWidget(_label("Loading the events from the UBA store…",
                                          role="muted"))
        self._load_events(h)

    def _toggle_events(self, h, show):
        if show:
            self._hide_events.discard(h.get("hit_id"))
        else:
            self._hide_events.add(h.get("hit_id"))
        self._clear(self._events_box)
        self._events_box.addWidget(_label("…", role="muted"))
        self._load_events(h)

    def _open_event(self, ev):
        record = {k: v for k, v in ev.items() if k not in ("details", "evidence")}
        for k, v in (ev.get("details") or {}).items():
            record["details.%s" % k] = v if not isinstance(v, (list, dict)) else json.dumps(v)
        record["evidence"] = json.dumps(ev.get("evidence") or [])
        self._open_row(record, "UBA behaviour event", ev.get("event_id") or "event")

    # .. artifact rows ...............................................................
    def _add_evidence_group(self, h, index, ref, offset=0, holder=None):
        run = self._run_of(h.get("execution_id"))
        artifacts_dir = run.get("artifacts_directory") or ""
        if holder is None:
            holder = QVBoxLayout()
            holder.setSpacing(4)
            self._evidence_box.addLayout(holder)
            count = ref.get("count") or len(ref.get("rowids") or [])
            holder.addWidget(_label("%s · %s · %s · %s row%s" % (
                ref.get("db"), ref.get("table"), ref.get("role", "primary"), count,
                "" if count == 1 else "s"), role="label"))
            holder.addWidget(_label("Loading…", role="muted"))
        if not artifacts_dir:
            self._clear_after_title(holder)
            holder.addWidget(_label("The run recorded no case folder to read the rows from.",
                                    role="muted"))
            return
        self._start(lambda: fetch_artifact_rows(artifacts_dir, ref, offset),
                    lambda group: self._show_evidence_group(h, index, ref, offset, holder, group))

    def _clear_after_title(self, holder):
        while holder.count() > 1:
            item = holder.takeAt(1)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
            elif item.layout() is not None:
                self._clear(item.layout())

    def _show_evidence_group(self, h, index, ref, offset, holder, group):
        self._clear_after_title(holder)
        if group.get("error"):
            holder.addWidget(_label("Rows not read: %s" % group["error"], role="muted", wrap=True))
            return
        rows = group.get("rows") or []
        if not rows:
            holder.addWidget(_label("No rows came back for this reference.", role="muted"))
            return
        columns = []
        for row in rows:
            for k in row:
                if k not in columns:
                    columns.append(k)
        headers = ["rowid" if c == "__rowid__" else c for c in columns]
        table = _table(headers, [[row.get(c) for c in columns] for row in rows],
                       max_rows=10, cap=260, wrap=False)
        table.setToolTip("Double-click a row (or select it and press Open row) for the full record")
        title = "%s / %s" % (ref.get("db"), ref.get("table"))
        table.cellDoubleClicked.connect(
            lambda r, _c: self._open_row(rows[r], title, "row %s" % rows[r].get("__rowid__")))
        holder.addWidget(table)
        nav = QHBoxLayout()
        open_btn = QPushButton("Open row")
        _theme.set_variant(open_btn, "ghost")

        def open_selected():
            sel = table.selectionModel().selectedRows()
            r = sel[0].row() if sel else 0
            self._open_row(rows[r], title, "row %s" % rows[r].get("__rowid__"))

        open_btn.clicked.connect(open_selected)
        nav.addWidget(open_btn)
        total = group.get("total") or len(rows)
        nav.addWidget(_label("Rows %d-%d of %s" % (offset + 1, offset + len(rows), total),
                             role="muted"))
        if offset > 0:
            prev = QPushButton("Previous %d" % EVIDENCE_PAGE)
            _theme.set_variant(prev, "ghost")
            prev.clicked.connect(lambda: self._page(h, index, ref, max(0, offset - EVIDENCE_PAGE),
                                                    holder))
            nav.addWidget(prev)
        if group.get("has_more"):
            nxt = QPushButton("Next %d" % EVIDENCE_PAGE)
            _theme.set_variant(nxt, "ghost")
            nxt.clicked.connect(lambda: self._page(h, index, ref, offset + EVIDENCE_PAGE, holder))
            nav.addWidget(nxt)
        nav.addStretch()
        holder.addLayout(nav)

    def _page(self, h, index, ref, offset, holder):
        self._clear_after_title(holder)
        holder.addWidget(_label("Loading…", role="muted"))
        self._add_evidence_group(h, index, ref, offset, holder)

    def _open_row(self, record, title, row_name):
        try:
            from ui.row_detail_dialog import RowDetailDialog
            dialog = RowDetailDialog(record, title=str(title), row_name=str(row_name),
                                     parent=self.window())
            dialog.show()
            self._row_dialog = dialog
        except Exception as e:
            logger.error("Behaviour Results: row detail failed: %s", e)
            QMessageBox.warning(self, "Row detail", "The row could not be opened: %s" % e)

    # ------------------------------------------------------------------ User Behavior
    def current_initial_filter(self) -> Optional[Dict[str, Any]]:
        """What "Open in User Behavior" sends for the selection: a hit's person
        and time range, a person, or nothing (the whole case)."""
        if not self._selected:
            person = self.person_filter.currentData()
            p = self._person_by_key(person) if person is not None else None
            return initial_filter_for_person(p) if p else None
        kind, payload = self._selected
        if kind == self.HIT:
            return initial_filter_for_hit(payload)
        if kind == self.PERSON:
            return initial_filter_for_person(payload)
        if kind == self.WING:
            person, _wid = payload
            return initial_filter_for_person(person) if person else None
        return None

    def _artifacts_dir(self) -> str:
        if self._selected and self._selected[0] == self.HIT:
            run = self._run_of(self._selected[1].get("execution_id"))
        else:
            run = self._run_of(None)
        return run.get("artifacts_directory") or ""

    def _open_in_uba(self):
        artifacts_dir = self._artifacts_dir()
        if not artifacts_dir or not os.path.isdir(artifacts_dir):
            QMessageBox.information(
                self, "Open in User Behavior",
                "The case folder this run read is not available:\n%s" % (
                    artifacts_dir or "(none recorded)"))
            return
        try:
            from uba.uba_dialog import open_user_behavior
            open_user_behavior(self.window(), artifacts_dir, self.current_initial_filter())
        except Exception as e:
            logger.exception("Behaviour Results: User Behavior did not open")
            QMessageBox.warning(self, "Open in User Behavior",
                                "User Behavior could not be opened: %s" % e)
