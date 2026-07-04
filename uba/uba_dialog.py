"""
UBADialog — hosts the UBA React single-page app in a QWebEngineView and
exposes UBABridge over a QWebChannel. Mirrors timeline/timeline_dialog.py so
it inherits the same look, load flow and RowDetailDialog evidence hookup.
"""

import os
import json
import logging

from PyQt5.QtWidgets import QDialog, QVBoxLayout, QMessageBox
from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWebChannel import QWebChannel

from uba.uba_bridge import UBABridge
from ui.row_detail_dialog import RowDetailDialog

logger = logging.getLogger(__name__)


class UBADialog(QDialog):
    """User Behavior Analytics window (React in QWebEngineView)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self.case_directory = None
        self.web_view = None
        self.web_channel = None
        self.bridge = None
        self.current_detail_dialog = None

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
        self.showMaximized()
        self.setStyleSheet("QDialog { background-color: #070911; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.web_view = QWebEngineView(self)
        self.web_view.page().javaScriptConsoleMessage = self._handle_console_message
        layout.addWidget(self.web_view)

    def _setup_bridge(self):
        self.web_channel = QWebChannel(self.web_view.page())
        self.bridge = UBABridge(self.case_directory, parent=self)
        self.bridge.show_evidence_detail.connect(self._open_evidence_detail_dialog)
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

    # ------------------------------------------------------------------ #
    def _get_case_directory(self) -> str:
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
        if self.bridge is not None:
            self.bridge.cleanup()
        super().closeEvent(event)
