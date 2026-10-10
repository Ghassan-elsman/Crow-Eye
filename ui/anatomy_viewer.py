"""The Anatomy pages, read inside Crow-Eye.

An Anatomy button used to hand a crow-eye.com URL to the system browser,
which needs the internet - and examiner workstations are routinely cut off
from it. The pages are now bundled (docs/anatomy, written by
scripts/sync_anatomy_pages.py) and shown here, at the section the button
names.

A QWebEngineView and not the system browser, because ShellExecute drops the
#fragment of a file: URL: the browser would open the top of a 190 KB page
instead of the table's own section, which is the whole point of the button.

Links between bundled pages stay in this window. Anything else - the site's
own navigation, a page not bundled - goes to the system browser, so an
offline machine never shows a blank error page in here.
"""
import logging
import os

from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QDialog, QVBoxLayout
from PyQt5.QtWebEngineWidgets import QWebEnginePage, QWebEngineView

logger = logging.getLogger(__name__)


class _Page(QWebEnginePage):
    """Keeps local pages in the viewer and sends the web to the browser."""

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        if url.scheme() in ("http", "https", "mailto"):
            if is_main_frame:
                QDesktopServices.openUrl(url)
            return False
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)

    def javaScriptConsoleMessage(self, level, message, line, source):
        # The site script expects a server (analytics, the download gate). From
        # disk those calls fail harmlessly; keep them out of the case log.
        pass


class AnatomyViewer(QDialog):
    """One window for every Anatomy button; a second click re-points it."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Anatomy")
        self.setMinimumSize(960, 680)
        self.setWindowFlags(
            Qt.Window | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint | Qt.WindowCloseButtonHint)
        try:
            from styles import CrowEyeStyles as _CES
            _CES.give_window_a_taskbar_button(self)
        except Exception:
            pass
        self.setStyleSheet("QDialog { background-color: #0a1028; }")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.web_view = QWebEngineView(self)
        self.web_view.setPage(_Page(self.web_view))
        self.web_view.titleChanged.connect(
            lambda t: self.setWindowTitle(("Anatomy - " + t) if t else "Anatomy"))
        layout.addWidget(self.web_view)
        self.resize(1280, 860)

    def show_section(self, path, anchor=""):
        """Load the bundled page and land on its section."""
        url = QUrl.fromLocalFile(os.path.abspath(path))
        if anchor:
            url.setFragment(anchor)
        current = self.web_view.url()
        if current.isValid() and current.toLocalFile() == url.toLocalFile() and anchor:
            # Same page: jump without a reload, which would lose the scroll
            # history the reader may want with Back.
            self.web_view.page().runJavaScript(
                "(function(a){var e=document.getElementById(a);"
                "if(e){e.scrollIntoView();history.replaceState(null,'','#'+a);}})(%r)" % anchor)
        else:
            logger.info("Anatomy: %s", url.toString())
            self.web_view.load(url)
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()
