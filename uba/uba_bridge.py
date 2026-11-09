"""
UBABridge — QWebChannel bridge between the UBA React app and the Python
behavior engine.

All slots return JSON strings (the React ``callBridge`` helper JSON-parses
them). The heavy analysis runs once in a background QThread; interactive
slots serve the derived in-memory event store and never touch the evidence
databases except through the lazy EvidenceFetcher.

The analysis is ``BehaviorEngine.run_or_load()``: the case's stored analysis
(<case>/UBA/uba_events.db) is reused while it is fresh, so reopening the
window does not re-read every artifact database. The Rules view's switches
(getRuleSwitches / setRuleEnabled) write the same saved setting as Settings ->
User Behavior; a change takes effect when the analysis is run again
(rerunAnalysis), because the stored answer's stamp includes the switches.

The Rules view's "New behaviour rule" button (openRuleCreator) asks the
window to open the Behaviour Rule Creator (uba/ui/behaviour_rule_dialog.py);
when a rule is saved or deleted the window sends ``rulesChanged`` back, with
whether the analyst asked to analyse again now.

**Initial filter.** A window opened from elsewhere - the Behaviour Results
view's "Open in User Behavior" - can arrive filtered: one person (by SID, the
person key, or by name) and a UTC time range. The opener hands it to the
bridge (``set_initial_filter``); React reads it on load (``getInitialFilter``)
and applies it to its filter state, and ``initialFilterChanged`` re-applies a
new one to a window that is already open, so a second "Open in User Behavior"
narrows the window on screen rather than opening another.
"""

import json
import logging
import os
import re

from PyQt5.QtCore import pyqtSlot, pyqtSignal, QThread

from uba.engine import rule_switches
from visualizations.async_bridge import AsyncBridge
from uba.engine.behavior_engine import BehaviorEngine
from uba.engine.evidence import EvidenceFetcher
from uba.utils.db_access import data_status

logger = logging.getLogger(__name__)

# The store's own time shape (UTC, naive): 'YYYY-MM-DD HH:MM:SS'. A time given
# with a 'T', fractional seconds or a 'Z' is brought to it; anything else is
# dropped rather than sent to React as a filter it would compare as text.
_TS = re.compile(r"^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})(:\d{2})?(?:\.\d+)?Z?$")


def _store_time(value):
    m = _TS.match(str(value or "").strip())
    if not m:
        return ""
    return "%s %s%s" % (m.group(1), m.group(2), m.group(3) or ":00")


def normalise_initial_filter(raw):
    """The initial filter in the shape React's filter state takes, or None.

    {"actor_sids": [...], "actors": [...], "start": UTC, "end": UTC,
    "label": "where it came from"}. Empty SIDs are dropped (an unresolved SID
    is not a person; the store refuses '' too). Names keep '' - it is the
    store's "unattributed". A filter that narrows nothing is None."""
    if not isinstance(raw, dict):
        return None
    sids = [str(s) for s in (raw.get("actor_sids") or []) if s]
    actors = [str(a) for a in (raw.get("actors") or []) if a is not None]
    start, end = _store_time(raw.get("start")), _store_time(raw.get("end"))
    if start and end and start > end:
        start, end = end, start
    if not (sids or actors or start or end):
        return None
    return {"actor_sids": sids, "actors": actors, "start": start, "end": end,
            "label": str(raw.get("label") or "")}


class AnalysisWorker(QThread):
    """Runs BehaviorEngine.run() off the GUI thread."""
    progress = pyqtSignal(int, str)
    finished_ok = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, engine: BehaviorEngine, parent=None, force=False):
        super().__init__(parent)
        self.engine = engine
        self.force = force

    def run(self):
        try:
            # The stored analysis when it is still fresh; otherwise a full run
            # that is then stored for the next window and for Eye.
            self.engine.run_or_load(
                progress_cb=lambda p, l: self.progress.emit(p, l), force=self.force)
            self.finished_ok.emit()
        except Exception as e:
            logger.exception("UBA: analysis worker failed")
            self.failed.emit(str(e))
        finally:
            # Every evidence connection the analysis opened belongs to THIS
            # thread and cannot be closed from anywhere else, so hand them back
            # here rather than leaving them for the pool's own teardown. Same
            # contract as timeline/data/query_worker.py at the end of run().
            try:
                self.engine.db_pool.cleanup_thread_connections()
            except Exception:
                logger.debug("UBA: worker connection cleanup skipped", exc_info=True)


# Slots the page may run off the GUI thread (callAsync): the two that read the
# evidence databases for the Who drove it tab, and the event store's heavier
# readers. The store is one in-memory connection opened with
# check_same_thread=False; every slot that reads it holds its lock
# (_store_slot), so a worker and the GUI thread never use it at once.
# getSessions, getRowEvidence and getEvidence run off the GUI thread too now:
# getSessions hands this thread's pool connections back afterwards
# (_cleanup_worker_pool), and the two evidence slots read on a throwaway own
# pool (_on_own_pool), so a worker thread never shares a connection with the GUI
# thread (SQLite connections are thread-bound).
# Measured on a real case (38,611 activities): getSummary 0.39 s,
# getDriversByPerson 0.24 s, a story page 0.24 s, getSessions/getEvidence
# 0.24-0.39 s - each a stall of the window when it runs on the GUI thread.
ASYNC_SLOTS = {"getInputLayer", "getAgentSessions", "getSummary", "getDriversByPerson",
               "getBehaviorEvents", "getDaySummary",
               "getSessions", "getRowEvidence", "getEvidence"}


def _store_slot(fn):
    """Run a slot that reads the engine's event store under the store's lock."""
    import functools

    @functools.wraps(fn)
    def run(self, *args):
        engine = self.engine
        lock = getattr(getattr(engine, "store", None), "lock", None)
        if lock is None:
            return fn(self, *args)
        with lock:
            return fn(self, *args)
    return run
# Tables the Who drove it tab may open a row of (getRowEvidence).
ROW_TABLES = {("ai_agents", "ai_agent_steps"), ("ai_agents", "ai_agent_sessions"),
              ("srum", "srum_app_timeline")}


class UBABridge(AsyncBridge):
    analysisProgress = pyqtSignal(int, str)
    analysisComplete = pyqtSignal(str)
    analysisError = pyqtSignal(str)
    show_evidence_detail = pyqtSignal(str)
    # To the window: open the Behaviour Rule Creator ({"rule_id"?, "kind"?}).
    open_rule_creator = pyqtSignal(str)
    # To React: an analyst rule was saved or deleted ({"rerun": bool, ...}).
    rulesChanged = pyqtSignal(str)
    # To React: apply this filter now (the window was already open when
    # "Open in User Behavior" asked again). Same JSON as getInitialFilter.
    initialFilterChanged = pyqtSignal(str)

    def __init__(self, artifacts_dir: str, parent=None, initial_filter=None):
        super().__init__(parent)
        self.artifacts_dir = artifacts_dir
        self.engine = None
        self.worker = None
        self.fetcher = None
        self._analysis_done = False
        # Bumped on every set, so React applies each request once even when
        # two in a row are identical (the analyst cleared it in between).
        self._initial_filter = normalise_initial_filter(initial_filter)
        self._initial_filter_seq = 1 if self._initial_filter else 0

    # ------------------------------------------------------------------ #
    def set_initial_filter(self, initial_filter) -> dict:
        """Store a new initial filter and tell React to apply it. Returns
        what getInitialFilter now answers."""
        self._initial_filter = normalise_initial_filter(initial_filter)
        self._initial_filter_seq += 1
        payload = self._initial_filter_payload()
        self.initialFilterChanged.emit(self._dumps(payload))
        return payload

    def _initial_filter_payload(self) -> dict:
        return {"filter": self._initial_filter, "seq": self._initial_filter_seq}

    @pyqtSlot(result=str)
    def getInitialFilter(self) -> str:
        """{"filter": {actor_sids, actors, start, end, label} or null, "seq": n}.
        Read by React on load; a filter is applied once per seq."""
        return self._dumps(self._initial_filter_payload())

    # ------------------------------------------------------------------ #
    def _dumps(self, obj) -> str:
        try:
            return json.dumps(obj, default=str)
        except Exception as e:
            logger.error("UBA: JSON encode failed: %s", e)
            return json.dumps({"error": str(e)})

    # ------------------------------------------------------------------ #
    @pyqtSlot(result=str)
    def getStatus(self) -> str:
        """Which parsed databases exist and whether analysis has run.

        Drives the React gate: empty-state vs progress vs main UI.
        """
        status = data_status(self.artifacts_dir)
        status["analysis_done"] = self._analysis_done
        status["case_dir"] = self.artifacts_dir
        return self._dumps(status)

    @pyqtSlot(result=str)
    def startAnalysis(self) -> str:
        if self._analysis_done:
            return self._dumps({"started": False, "already_done": True})
        return self._start(force=False)

    @pyqtSlot(result=str)
    def rerunAnalysis(self) -> str:
        """Analyse again with the switches as they are now saved.

        Not forced: when nothing but the switches changed, the store's stamp
        no longer matches and a full run happens; when the switches were put
        back the way the store was built, the stored answer is the right one
        and is loaded."""
        if self.worker is not None and self.worker.isRunning():
            return self._dumps({"started": False, "running": True})
        old = self.engine
        self._analysis_done = False
        self.fetcher = None
        result = self._start(force=False)
        if old is not None:
            try:
                old.close()
            except Exception:
                logger.debug("UBA: closing the previous engine failed", exc_info=True)
        return result

    def _start(self, force=False) -> str:
        if self.worker is not None and self.worker.isRunning():
            return self._dumps({"started": False, "running": True})
        try:
            self.engine = BehaviorEngine(self.artifacts_dir)
        except Exception as e:
            logger.exception("UBA: engine init failed")
            self.analysisError.emit(str(e))
            return self._dumps({"started": False, "error": str(e)})

        self.worker = AnalysisWorker(self.engine, force=force)
        self.worker.progress.connect(
            lambda p, l: self.analysisProgress.emit(p, l))
        self.worker.finished_ok.connect(self._on_analysis_done)
        self.worker.failed.connect(lambda e: self.analysisError.emit(e))
        self.worker.start()
        return self._dumps({"started": True})

    def _on_analysis_done(self):
        self._analysis_done = True
        # The engine's DbPool now opens a connection per thread, so the fetcher
        # can share it: asking for one on the GUI thread gets a GUI-thread
        # connection. This used to be a second pool built here by hand, because
        # the pool was keyed on the database name alone and handing the fetcher
        # the engine's pool meant handing it the worker's connections. That
        # workaround covered evidence only - getSessions took the same route
        # and crashed. See DbPool's docstring.
        self.fetcher = EvidenceFetcher(self.engine.db_pool)
        summary = {
            "total_events": self.engine.stats.get("total_events", 0),
            "elapsed_seconds": self.engine.stats.get("elapsed_seconds", 0),
            "users": self.engine.users(),
            "coverage_counts": self.engine.coverage_report.get("counts", {}),
            "loaded_from_store": self.engine.loaded_from_store,
            "built_at_utc": self.engine.built_at_utc,
            "host": self.engine.host,
        }
        self.analysisComplete.emit(self._dumps(summary))

    # ------------------------------------------------------------------ #
    def _ensure_ready(self):
        return self._analysis_done and self.engine is not None

    @pyqtSlot(result=str)
    @_store_slot
    def getUsers(self) -> str:
        if not self._ensure_ready():
            return self._dumps({"pending": True, "users": []})
        return self._dumps({"users": self.engine.users()})

    @pyqtSlot(result=str)
    @_store_slot
    def getApps(self) -> str:
        if not self._ensure_ready():
            return self._dumps({"pending": True, "apps": []})
        return self._dumps({"apps": self.engine.apps()})

    @pyqtSlot(result=str)
    def getRules(self) -> str:
        """Every rule with its status and event count — drives the rule picker."""
        if not self._ensure_ready():
            return self._dumps({"pending": True, "rules": []})
        return self._dumps({"rules": self.engine.rules_catalog()})

    @pyqtSlot(result=str)
    def getRuleSwitches(self) -> str:
        """Every rule with its on/off switch (the Rules view).

        Answers before the analysis has run too: switches are a setting, not
        a result. ``needs_rerun`` is true when the saved switches differ from
        the ones the analysis on screen was built with."""
        try:
            # Read from the files now, not from the engine: a rule saved in
            # the Behaviour Rule Creator since the analysis ran is listed too.
            rows = rule_switches.switch_rows()
        except Exception as e:
            logger.exception("UBA: rule switches unavailable")
            return self._dumps({"error": str(e), "rules": []})
        status, counts = {}, {}
        if self._ensure_ready():
            for entry in self.engine.rules_catalog():
                status[entry["rule_id"]] = entry["status"]
                counts[entry["rule_id"]] = entry["event_count"]
        for row in rows:
            row["status"] = status.get(row["rule_id"])
            row["event_count"] = counts.get(row["rule_id"])
        saved_off = {r["rule_id"] for r in rows if not r["enabled"]}
        ran_off = set(self.engine.disabled_rules) if self.engine is not None else saved_off
        rules_changed = False
        if self.engine is not None and self._analysis_done:
            try:
                rules_changed = self.engine.user_rules_changed()
            except Exception:
                logger.debug("UBA: user-rule change check failed", exc_info=True)
        return self._dumps({
            "rules": rows,
            "off_count": len(saved_off),
            "user_rule_count": sum(1 for r in rows if r.get("user_rule")),
            "analysis_done": self._analysis_done,
            "rules_changed": bool(rules_changed),
            "needs_rerun": bool(self._analysis_done and (saved_off != ran_off or rules_changed)),
        })

    @pyqtSlot(str, result=str)
    def openRuleCreator(self, request_json: str) -> str:
        """{"rule_id": id to edit (optional), "kind": "table"|"derived"} -> the
        window opens the Behaviour Rule Creator. Returns at once; the editor
        is modal in the window, and its outcome comes back as rulesChanged."""
        request = self._parse(request_json)
        self.open_rule_creator.emit(json.dumps({
            "rule_id": str(request.get("rule_id") or ""),
            "kind": str(request.get("kind") or "")}))
        return self._dumps({"opening": True})

    def current_store(self):
        """The analysis on screen (a derived rule's test reads it), or None."""
        return self.engine.store if self._ensure_ready() else None

    @pyqtSlot(str, result=str)
    def setRuleEnabled(self, request_json: str) -> str:
        """{"rule_id": id, "enabled": bool} -> the switch list after the change.

        Saved at once to the same setting Settings -> User Behavior edits.
        {"all_on": true} turns every rule back on."""
        request = self._parse(request_json)
        if request.get("all_on"):
            saved = rule_switches.set_disabled_rules([])
        else:
            rule_id = str(request.get("rule_id") or "")
            if not rule_id:
                return self._dumps({"error": "rule_id is required"})
            saved = rule_switches.set_rule_enabled(rule_id, bool(request.get("enabled")))
        out = json.loads(self.getRuleSwitches())
        out["saved"] = bool(saved)
        return self._dumps(out)

    @pyqtSlot(result=str)
    @_store_slot
    def getSessions(self) -> str:
        """Sign-in sessions, accounts, machine uptime and the auditing note."""
        if not self._ensure_ready():
            return self._dumps({"pending": True, "sessions": []})
        try:
            return self._dumps(self.engine.sessions_report())
        finally:
            # sessions_report reads the registry/logs through the engine's
            # shared thread-local pool; when this runs on an async worker thread
            # those connections belong to that thread, so hand them back rather
            # than leaving them on the async thread pool.
            self._cleanup_worker_pool()

    @pyqtSlot(result=str)
    def getCoverage(self) -> str:
        if not self._ensure_ready():
            return self._dumps({"pending": True})
        return self._dumps(self.engine.coverage_report)

    @pyqtSlot(str, result=str)
    @_store_slot
    def getSummary(self, filters_json: str) -> str:
        if not self._ensure_ready():
            return self._dumps({"pending": True})
        filters = self._parse(filters_json)
        return self._dumps(self.engine.store.summary(filters))

    # ---------------------------------------------------------------- #
    # Who drove it (uba/engine/drivers.py)
    @pyqtSlot(str, str, str)
    def callAsync(self, method, request_id, args_json):
        if method not in ASYNC_SLOTS:
            self.asyncResult.emit(request_id, json.dumps(
                {"__asyncError": "not callable off the GUI thread: %r" % method}))
            return
        super().callAsync(method, request_id, args_json)

    @pyqtSlot(str, result=str)
    @_store_slot
    def getDriversByPerson(self, filters_json: str) -> str:
        if not self._ensure_ready():
            return self._dumps({"pending": True, "people": []})
        from uba.engine import drivers
        return self._dumps(drivers.by_person(self.engine.store, self._parse(filters_json)))

    def _cleanup_worker_pool(self):
        """Close this thread's engine-pool connections, but only when we are NOT
        on the GUI thread (an async worker) - the GUI thread's connections are
        reused by other reads and must be left in place."""
        try:
            from PyQt5.QtCore import QThread
            from PyQt5.QtWidgets import QApplication
            app = QApplication.instance()
            if app is not None and QThread.currentThread() is not app.thread():
                self.engine.db_pool.cleanup_thread_connections()
        except Exception:
            logger.debug("UBA: worker pool cleanup skipped", exc_info=True)

    def _on_own_pool(self, fn):
        """fn(pool) on a DbPool of this thread's own, closed after: the slot
        runs on a worker thread, and SQLite connections are thread-bound."""
        from uba.utils.db_access import DbPool
        pool = DbPool(self.artifacts_dir)
        try:
            return fn(pool)
        finally:
            try:
                pool.cleanup_thread_connections()
                pool.close()
            except Exception:
                logger.debug("UBA: Who drove it pool cleanup skipped", exc_info=True)

    @pyqtSlot(str, result=str)
    def getInputLayer(self, request_json: str) -> str:
        """One day of SRUM's App Timeline per program ({"day"})."""
        from uba.engine import drivers
        day = str(self._parse(request_json).get("day") or "")[:10]
        return self._dumps(self._on_own_pool(lambda pool: drivers.input_layer(pool, day)))

    @pyqtSlot(str, result=str)
    def getAgentSessions(self, request_json: str) -> str:
        """AI agent sessions overlapping {"start", "end"}, with their marks."""
        from uba.engine import drivers
        req = self._parse(request_json)
        start, end = str(req.get("start") or ""), str(req.get("end") or "")
        if not start or not end:
            return self._dumps({"available": False, "sessions": [], "reason": "No time range was chosen."})
        return self._dumps(self._on_own_pool(lambda pool: drivers.agent_sessions(pool, start, end)))

    @pyqtSlot(str, result=str)
    def getRowEvidence(self, request_json: str) -> str:
        """Rows of one source table by rowid ({"db", "table", "rowids", "title"}),
        in the shape getEvidence answers - for a mark or a program row."""
        if not self._ensure_ready():
            return self._dumps({"pending": True})
        req = self._parse(request_json)
        db, table = str(req.get("db") or ""), str(req.get("table") or "")
        if (db, table) not in ROW_TABLES:
            return self._dumps({"error": "rows of %s/%s are not opened here" % (db, table)})
        rowids = [int(r) for r in (req.get("rowids") or []) if str(r).lstrip("-").isdigit()][:500]
        ref = {"db": db, "table": table, "rowids": rowids, "count": len(rowids), "role": "primary"}
        # On its own thread-local pool (cleaned up after) so this slot is safe to
        # run off the GUI thread: SQLite connections are thread-bound.
        from uba.engine.evidence import EvidenceFetcher
        result = self._on_own_pool(lambda pool: EvidenceFetcher(pool).fetch(
            [ref], offset=int(req.get("offset", 0) or 0),
            page_size=int(req.get("page_size", 50) or 50)))
        result["event"] = {"description": str(req.get("title") or ""), "activity": "", "severity": "routine",
                           "confidence": "", "actor_type": "", "actor_name": "", "event_id": ""}
        result["details"] = {}
        return self._dumps(result)

    @pyqtSlot(str, result=str)
    @_store_slot
    def getBehaviorEvents(self, query_json: str) -> str:
        if not self._ensure_ready():
            return self._dumps({"pending": True, "events": []})
        query = self._parse(query_json)
        cursor = query.pop("cursor", None)
        page_size = int(query.pop("page_size", 200) or 200)
        page_size = max(1, min(page_size, 500))
        grouped = bool(query.pop("grouped", False))
        page = self.engine.store.query_events(
            filters=query, cursor=cursor, page_size=page_size)
        if grouped and page.get("events"):
            # Alike activity in a run folds into one line that keeps its members
            # (story_digest.group_repeats); the page's cursor is unchanged.
            from uba.engine import story_digest
            by_id = {e.get("event_id"): e for e in page["events"]}
            items = story_digest.group_repeats(page["events"])
            for item in items:
                if item.get("kind") == "group":
                    item["members"] = [by_id[i] for i in item["event_ids"] if i in by_id]
            page["events"] = items
        return self._dumps(page)

    @pyqtSlot(str, result=str)
    @_store_slot
    def getDaySummary(self, request_json: str) -> str:
        """The opening card of one day of the Activity Story (story_digest)."""
        if not self._ensure_ready():
            return self._dumps({"pending": True})
        request = self._parse(request_json)
        day = str(request.get("day") or "")[:10]
        if len(day) != 10:
            return self._dumps({"lines": []})
        from uba.engine import story_digest
        rows = self.engine.store.events_for_day(day)
        return self._dumps(story_digest.day_summary(rows, day, request.get("person") or None))

    @pyqtSlot(str, result=str)
    @_store_slot
    def getEvidence(self, request_json: str) -> str:
        if not self._ensure_ready():
            return self._dumps({"pending": True})
        request = self._parse(request_json)
        event = self.engine.store.get_event(request.get("event_id", ""))
        if not event:
            return self._dumps({"error": "event not found"})
        # Own thread-local pool (cleaned up after) so this is safe off the GUI
        # thread; the store read above is already guarded by @_store_slot.
        from uba.engine.evidence import EvidenceFetcher
        result = self._on_own_pool(lambda pool: EvidenceFetcher(pool).fetch(
            event["evidence"], offset=int(request.get("offset", 0) or 0),
            page_size=int(request.get("page_size", 50) or 50)))
        result["event"] = {k: event[k] for k in (
            "event_id", "description", "actor_type", "actor_name",
            "actor_basis", "severity", "confidence", "activity",
            "behavior_class", "ts_start", "session_context", "caveat",
            "session_user", "user_rule")}
        result["details"] = event.get("details", {})
        return self._dumps(result)

    @pyqtSlot(str)
    def openEvidenceDetail(self, row_json: str):
        """Ask the dialog to open the native RowDetailDialog for one record."""
        self.show_evidence_detail.emit(row_json)

    @pyqtSlot(str)
    def log(self, message: str):
        logger.info("[UBA React] %s", message)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse(text: str) -> dict:
        if not text:
            return {}
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else {}
        except (ValueError, TypeError):
            return {}

    def cleanup(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.wait(3000)
        if self.engine is not None:
            # Closes this thread's connections and drops any the worker left;
            # DbPool.close() will not try to close another thread's.
            self.engine.close()
