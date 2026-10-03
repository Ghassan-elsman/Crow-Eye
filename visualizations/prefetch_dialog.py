"""Prefetch ("program executions") visualization window.

Hosts the react-prefetch SPA in a QWebEngineView over a QWebChannel - same shape as
visualizations/mftusn_dialog.py.
"""

import os
import logging

from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QMessageBox
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWebChannel import QWebChannel

from visualizations.prefetch_bridge import PrefetchBridge

logger = logging.getLogger(__name__)


class PrefetchDialog(QDialog):
    """A maximised window that renders the Prefetch React chart app."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self.web_view = None
        self.web_channel = None
        self.bridge = None
        try:
            self.case_directory = self._get_case_directory()
            self._init_ui()
            self._setup_bridge()
            self._load_react_app()
        except Exception as e:
            logger.error(f"Failed to open Prefetch visualization: {e}")
            QMessageBox.critical(self, "Visualization", f"Could not open the chart:\n{e}")

    def _get_case_directory(self) -> str:
        ui = getattr(self.main_window, "ui", None)
        for holder in (ui, self.main_window):
            paths = getattr(holder, "case_paths", None)
            if isinstance(paths, dict):
                art = paths.get("artifacts_dir")
                if art and os.path.exists(art):
                    return art
        return ""

    def _init_ui(self):
        self.setWindowTitle("Prefetch - Program Executions")
        self.setMinimumSize(1100, 720)
        self.setWindowFlags(
            Qt.Window | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint | Qt.WindowCloseButtonHint)
        # Owned windows get no taskbar button on Windows, whatever their title
        # says - so a minimized Crow-Eye window had nowhere to show its name.
        # See CrowEyeStyles.give_window_a_taskbar_button for the measurements.
        try:
            from styles import CrowEyeStyles as _CES
            _CES.give_window_a_taskbar_button(self)
        except Exception:
            pass
        self.showMaximized()
        self.setStyleSheet("QDialog { background-color: #0a1028; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.web_view = QWebEngineView(self)
        self.web_view.setContextMenuPolicy(Qt.NoContextMenu)
        layout.addWidget(self.web_view)

    def _setup_bridge(self):
        self.web_channel = QWebChannel(self.web_view.page())
        self.bridge = PrefetchBridge(self.case_directory, parent=self)
        self.web_channel.registerObject("bridge", self.bridge)
        self.web_view.page().setWebChannel(self.web_channel)

    def _load_react_app(self):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        build = os.path.join(base_dir, "react-prefetch", "dist", "index.html")
        if not os.path.exists(build):
            self.web_view.setHtml(_missing_build_html(build))
            return
        url = QUrl.fromLocalFile(build)
        logger.info(f"Loading react-prefetch: {url.toString()}")
        self.web_view.load(url)


def _missing_build_html(path: str) -> str:
    return f"""
    <html><body style="background:#0a1028;color:#f8fafc;font-family:'Barlow Semi Condensed','Bahnschrift','Segoe UI',sans-serif;
        display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center;">
      <div>
        <h2 style="color:#f43f5e;">Visualization build missing</h2>
        <p>The Prefetch chart's React build was not found.</p>
        <code style="background:#0f172a;padding:4px 8px;border-radius:4px;font-size:12px;">{path}</code>
        <p style="color:#94a3b8;margin-top:18px;">Ensure Node.js is installed and restart Crow-Eye,
        or run <code>npm install &amp;&amp; npm run build</code> in visualizations/react-prefetch/.</p>
      </div>
    </body></html>
    """
