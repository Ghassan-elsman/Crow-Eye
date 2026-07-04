"""
UBABridge — QWebChannel bridge between the UBA React app and the Python
behavior engine.

All slots return JSON strings (the React ``callBridge`` helper JSON-parses
them). The heavy analysis runs once in a background QThread; interactive
slots serve the derived in-memory event store and never touch the evidence
databases except through the lazy EvidenceFetcher.
"""

import json
import logging
import os

from PyQt5.QtCore import QObject, pyqtSlot, pyqtSignal, QThread

from uba.engine.behavior_engine import BehaviorEngine
from uba.engine.evidence import EvidenceFetcher
from uba.utils.db_access import DbPool, data_status

logger = logging.getLogger(__name__)


class AnalysisWorker(QThread):
    """Runs BehaviorEngine.run() off the GUI thread."""
    progress = pyqtSignal(int, str)
    finished_ok = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, engine: BehaviorEngine, parent=None):
        super().__init__(parent)
        self.engine = engine

    def run(self):
        try:
            self.engine.run(progress_cb=lambda p, l: self.progress.emit(p, l))
            self.finished_ok.emit()
        except Exception as e:
            logger.exception("UBA: analysis worker failed")
            self.failed.emit(str(e))


class UBABridge(QObject):
    analysisProgress = pyqtSignal(int, str)
    analysisComplete = pyqtSignal(str)
    analysisError = pyqtSignal(str)
    show_evidence_detail = pyqtSignal(str)

    def __init__(self, artifacts_dir: str, parent=None):
        super().__init__(parent)
        self.artifacts_dir = artifacts_dir
        self.engine = None
        self.worker = None
        self.fetcher = None
        self._evidence_pool = None
        self._analysis_done = False

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
        if self.worker is not None and self.worker.isRunning():
            return self._dumps({"started": False, "running": True})
        try:
            self.engine = BehaviorEngine(self.artifacts_dir)
        except Exception as e:
            logger.exception("UBA: engine init failed")
            self.analysisError.emit(str(e))
            return self._dumps({"started": False, "error": str(e)})

        self.worker = AnalysisWorker(self.engine)
        self.worker.progress.connect(
            lambda p, l: self.analysisProgress.emit(p, l))
        self.worker.finished_ok.connect(self._on_analysis_done)
        self.worker.failed.connect(lambda e: self.analysisError.emit(e))
        self.worker.start()
        return self._dumps({"started": True})

    def _on_analysis_done(self):
        self._analysis_done = True
        # The engine's DbPool was populated inside the worker thread; SQLite
        # connections cannot cross threads, so give the fetcher its own
        # read-only pool bound to this (GUI) thread.
        self._evidence_pool = DbPool(self.artifacts_dir)
        self.fetcher = EvidenceFetcher(self._evidence_pool)
        summary = {
            "total_events": self.engine.stats.get("total_events", 0),
            "elapsed_seconds": self.engine.stats.get("elapsed_seconds", 0),
            "users": self.engine.users(),
            "coverage_counts": self.engine.coverage_report["counts"],
        }
        self.analysisComplete.emit(self._dumps(summary))

    # ------------------------------------------------------------------ #
    def _ensure_ready(self):
        return self._analysis_done and self.engine is not None

    @pyqtSlot(result=str)
    def getUsers(self) -> str:
        if not self._ensure_ready():
            return self._dumps({"pending": True, "users": []})
        return self._dumps({"users": self.engine.users()})

    @pyqtSlot(result=str)
    def getApps(self) -> str:
        if not self._ensure_ready():
            return self._dumps({"pending": True, "apps": []})
        return self._dumps({"apps": self.engine.apps()})

    @pyqtSlot(result=str)
    def getCoverage(self) -> str:
        if not self._ensure_ready():
            return self._dumps({"pending": True})
        return self._dumps(self.engine.coverage_report)

    @pyqtSlot(str, result=str)
    def getSummary(self, filters_json: str) -> str:
        if not self._ensure_ready():
            return self._dumps({"pending": True})
        filters = self._parse(filters_json)
        return self._dumps(self.engine.store.summary(filters))

    @pyqtSlot(str, result=str)
    def getBehaviorEvents(self, query_json: str) -> str:
        if not self._ensure_ready():
            return self._dumps({"pending": True, "events": []})
        query = self._parse(query_json)
        cursor = query.pop("cursor", None)
        page_size = int(query.pop("page_size", 200) or 200)
        page_size = max(1, min(page_size, 500))
        return self._dumps(self.engine.store.query_events(
            filters=query, cursor=cursor, page_size=page_size))

    @pyqtSlot(str, result=str)
    def getEvidence(self, request_json: str) -> str:
        if not self._ensure_ready():
            return self._dumps({"pending": True})
        request = self._parse(request_json)
        event = self.engine.store.get_event(request.get("event_id", ""))
        if not event:
            return self._dumps({"error": "event not found"})
        result = self.fetcher.fetch(
            event["evidence"], offset=int(request.get("offset", 0) or 0),
            page_size=int(request.get("page_size", 50) or 50))
        result["event"] = {k: event[k] for k in (
            "event_id", "description", "actor_type", "actor_name",
            "actor_basis", "severity", "confidence", "activity",
            "behavior_class", "ts_start", "session_context", "caveat",
            "session_user")}
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
        if self._evidence_pool is not None:
            self._evidence_pool.close()
        if self.engine is not None:
            self.engine.close()
