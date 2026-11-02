"""
UBADialog — hosts the UBA React single-page app in a QWebEngineView and
exposes UBABridge over a QWebChannel. Mirrors timeline/timeline_dialog.py so
it inherits the same look, load flow and RowDetailDialog evidence hookup.

``open_user_behavior(parent, artifacts_dir, initial_filter)`` is the door
other windows use (the Behaviour Results view's "Open in User Behavior"): it
opens the window filtered to one person and / or a UTC time range, or, when a
User Behavior window for that case is already open, re-applies the filter to
it instead of opening a second one. It is busy-guarded like every @gated
opener: nothing opens while Crow-Eye parses or loads.
"""

import os
import json
import logging
import weakref

from PyQt5.QtWidgets import QDialog, QVBoxLayout, QMessageBox
from PyQt5.QtCore import Qt, QUrl, QTimer
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWebChannel import QWebChannel

from uba.uba_bridge import UBABridge
from ui.row_detail_dialog import RowDetailDialog

logger = logging.getLogger(__name__)

# Every User Behavior window still alive, so a second open for the same case
# re-uses the one on screen (weak: a closed, deleted window drops out).
_OPEN_WINDOWS = weakref.WeakSet()

FEATURE = "User Behavior Analytics"


class UBADialog(QDialog):
    """User Behavior Analytics window (React in QWebEngineView).

    ``artifacts_dir``: the case's Target_Artifacts to open, instead of the one
    the main window has loaded. ``initial_filter``: see open_user_behavior."""

    def __init__(self, parent=None, artifacts_dir=None, initial_filter=None):
        super().__init__(parent)
        self.main_window = parent
        self.case_directory = None
        self.web_view = None
        self.web_channel = None
        self.bridge = None
        self.current_detail_dialog = None
        self._artifacts_dir = artifacts_dir
        self._initial_filter = initial_filter
        _OPEN_WINDOWS.add(self)

        try:
            self.case_directory = self._get_case_directory()
            self._init_ui()
            self._setup_bridge()
            self._load_react_app()
        except ValueError as e:
            QMessageBox.warning(self, "No Case Loaded", str(e))
            self._load_error_page(str(e))
        except Exception as e:
            logger.exception("UBA: failed to initialize dialog")
            QMessageBox.critical(self, "UBA Error",
                                 "Failed to open User Behavior Analytics:\n{}".format(e))

    # ------------------------------------------------------------------ #
    def _init_ui(self):
        self.setWindowTitle("User Behavior Analytics")
        self.setMinimumSize(1200, 820)
        self.setWindowFlags(
            Qt.Window | Qt.WindowMinimizeButtonHint |
            Qt.WindowMaximizeButtonHint | Qt.WindowCloseButtonHint)
        # Owned windows get no taskbar button on Windows, whatever their title
        # says - so a minimized Crow-Eye window had nowhere to show its name.
        # See CrowEyeStyles.give_window_a_taskbar_button for the measurements.
        try:
            from styles import CrowEyeStyles as _CES
            _CES.give_window_a_taskbar_button(self)
        except Exception:
            pass
        self.showMaximized()
        self.setStyleSheet("QDialog { background-color: #070911; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.web_view = QWebEngineView(self)
        self.web_view.page().javaScriptConsoleMessage = self._handle_console_message
        layout.addWidget(self.web_view)

    def _setup_bridge(self):
        self.web_channel = QWebChannel(self.web_view.page())
        self.bridge = UBABridge(self.case_directory, parent=self,
                                initial_filter=self._initial_filter)
        self.bridge.show_evidence_detail.connect(self._open_evidence_detail_dialog)
        # Queued: the slot that asked returns to React first, then the modal
        # editor opens (a modal opened inside a QWebChannel call holds the call).
        self.bridge.open_rule_creator.connect(self._open_rule_creator, Qt.QueuedConnection)
        self.web_channel.registerObject("bridge", self.bridge)
        self.web_view.page().setWebChannel(self.web_channel)

    def _load_react_app(self):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        react_build = os.path.join(base_dir, "react-uba", "dist", "index.html")
        if not os.path.exists(react_build):
            msg = ("UBA interface build not found at:\n{}\n\n"
                   "Run 'npm install && npm run build' inside uba/react-uba/."
                   .format(react_build))
            QMessageBox.critical(self, "Build Missing", msg)
            self._load_error_page(msg)
            return
        url = QUrl.fromLocalFile(react_build)
        logger.info("UBA: loading React app %s", url.toString())
        self.web_view.load(url)

    def _load_error_page(self, message):
        html = """
        <html><body style="background:#070911;color:#e9ecf4;
            font-family:'Segoe UI',sans-serif;display:flex;justify-content:center;
            align-items:center;height:100vh;margin:0;text-align:center;">
          <div><h2 style="color:#ff3b56;">User Behavior Analytics</h2>
          <p style="color:#8c95ab;max-width:520px;">%s</p></div>
        </body></html>""" % (message.replace("\n", "<br>"))
        if self.web_view:
            self.web_view.setHtml(html)

    # ------------------------------------------------------------------ #
    def _handle_console_message(self, level, message, line, source):
        tag = {0: "INFO", 1: "WARN", 2: "ERROR"}.get(level, "LOG")
        logger.debug("[UBA JS %s] %s (line %s)", tag, message, line)

    def _open_evidence_detail_dialog(self, row_json):
        """Open the native RowDetailDialog for one evidence record."""
        try:
            data = json.loads(row_json)
            record = data.get("record", data)
            title = data.get("table", "Evidence Record")
            row_name = (record.get("__rowid__") and "row {}".format(record["__rowid__"])) \
                or data.get("db", "Evidence")
            self.current_detail_dialog = RowDetailDialog(
                record, title=str(title), row_name=str(row_name), parent=self)
            self.current_detail_dialog.show()
        except Exception as e:
            logger.error("UBA: evidence detail dialog failed: %s", e)
            QMessageBox.warning(self, "Error",
                                "Failed to open evidence detail: {}".format(e))

    def _open_rule_creator(self, request_json):
        """The User Behavior window's door to the Behaviour Rule Creator.
        Busy-guarded inside open_behaviour_rule_creator (the @gated rule)."""
        try:
            request = json.loads(request_json or "{}")
        except ValueError:
            request = {}
        try:
            from uba.ui.behaviour_rule_dialog import open_behaviour_rule_creator
            result = open_behaviour_rule_creator(
                self, artifacts_dir=self.case_directory,
                rule_id=request.get("rule_id") or None, kind=request.get("kind") or None,
                store=self.bridge.current_store() if self.bridge else None)
        except Exception as e:
            logger.exception("UBA: Behaviour Rule Creator failed")
            QMessageBox.warning(self, "Behaviour Rule Creator",
                                "The Behaviour Rule Creator could not open: {}".format(e))
            return
        if not result or not (result.get("saved") or result.get("deleted")):
            return
        saved = result.get("saved") or {}
        payload = json.dumps({"rerun": bool(result.get("rerun")),
                              "saved": saved.get("id") if isinstance(saved, dict) else None,
                              "deleted": result.get("deleted")})
        # After the editor has closed, so React redraws a window in front.
        QTimer.singleShot(0, lambda: self.bridge.rulesChanged.emit(payload))

    # ------------------------------------------------------------------ #
    def apply_initial_filter(self, initial_filter):
        """Narrow this window to ``initial_filter`` now and bring it forward."""
        if self.bridge is not None:
            self.bridge.set_initial_filter(initial_filter)
        if self.isMinimized():
            self.showMaximized()
        self.raise_()
        self.activateWindow()

    def shows_case(self, artifacts_dir) -> bool:
        """Whether this window is open on ``artifacts_dir``."""
        if not self.case_directory or not artifacts_dir:
            return False
        return _same_folder(self.case_directory, artifacts_dir)

    # ------------------------------------------------------------------ #
    def _get_case_directory(self) -> str:
        if self._artifacts_dir:
            if os.path.isdir(self._artifacts_dir):
                return self._artifacts_dir
            raise ValueError(
                "The case folder this window was asked to open is not there any more:\n"
                "{}".format(self._artifacts_dir))
        ui = getattr(self.main_window, "ui", None)
        if ui and hasattr(ui, "case_paths") and "artifacts_dir" in ui.case_paths:
            artifacts_dir = ui.case_paths["artifacts_dir"]
            if artifacts_dir and os.path.exists(artifacts_dir):
                return artifacts_dir
        case_dir = getattr(self.main_window, "case_dir", None)
        if case_dir:
            target = os.path.join(case_dir, "Target_Artifacts")
            if os.path.exists(target):
                return target
        raise ValueError(
            "No case is currently loaded. Open or create a case and parse the "
            "computer's artifacts first, then open User Behavior Analytics.")

    def closeEvent(self, event):
        _OPEN_WINDOWS.discard(self)
        if self.bridge is not None:
            self.bridge.cleanup()
        super().closeEvent(event)


# ---------------------------------------------------------------------- #
def _same_folder(a, b) -> bool:
    try:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))
    except (TypeError, ValueError):
        return False


def _feature_gate_owner(widget):
    """The Crow-Eye main UI object that owns ``_feature_gate`` (the @gated
    busy check), found from ``widget``'s parents or, for a window with no
    parent chain to it (the Correlation Engine), from the top-level windows."""
    w = widget
    while w is not None:
        if hasattr(w, "_feature_gate"):
            return w
        ui = getattr(w, "ui", None)
        if ui is not None and hasattr(ui, "_feature_gate"):
            return ui
        w = w.parent() if hasattr(w, "parent") else None
    try:
        from PyQt5.QtWidgets import QApplication
        for top in QApplication.topLevelWidgets():
            ui = getattr(top, "ui", None)
            if ui is not None and hasattr(ui, "_feature_gate"):
                return ui
    except Exception:
        pass
    return None


def _allowed_now(parent, retry) -> bool:
    """The busy guard: True when nothing is parsing or loading. Through the
    main window's feature gate when it is reachable (busy dialog with "Open
    when ready"), else ui.busy_guard directly."""
    owner = _feature_gate_owner(parent)
    if owner is not None:
        try:
            return bool(owner._feature_gate(FEATURE, needs=None, kind="view", retry=retry))
        except Exception:
            logger.debug("UBA: feature gate unavailable", exc_info=True)
    try:
        from ui import busy_guard
    except ImportError:
        return True
    if busy_guard.is_busy():
        reason, _elapsed = busy_guard.current()
        QMessageBox.information(
            parent, "Crow-Eye is busy",
            "Crow-Eye is still working: %s.\n\nUser Behavior Analytics will be "
            "available when it has finished." % (reason or "working"))
        return False
    return True


def find_open_window(artifacts_dir):
    """The User Behavior window already open on ``artifacts_dir``, or None."""
    for window in list(_OPEN_WINDOWS):
        try:
            if window.isVisible() and window.shows_case(artifacts_dir):
                return window
        except RuntimeError:            # its C++ object is already gone
            _OPEN_WINDOWS.discard(window)
    return None


def open_user_behavior(parent, artifacts_dir, initial_filter=None):
    """Open User Behavior on ``artifacts_dir`` (a case's Target_Artifacts),
    filtered by ``initial_filter``::

        {"actor_sids": [SID, ...], "actors": [name, ...],
         "start": "YYYY-MM-DD HH:MM:SS", "end": "...", "label": "..."}

    every key optional; times UTC. A window already open on that case is
    re-filtered and brought forward instead. Returns the window, or None when
    the busy guard refused (a queued "Open when ready" opens it later)."""
    retry = lambda: open_user_behavior(parent, artifacts_dir, initial_filter)
    if not _allowed_now(parent, retry):
        return None
    existing = find_open_window(artifacts_dir)
    if existing is not None:
        existing.apply_initial_filter(initial_filter)
        return existing
    window = UBADialog(parent, artifacts_dir=artifacts_dir, initial_filter=initial_filter)
    window.setAttribute(Qt.WA_DeleteOnClose, True)
    window.show()
    return window
