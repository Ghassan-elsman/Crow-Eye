"""Two notices on the main window, for clicks that cannot do what they look like.

BusyNotice - a tab or a table clicked while Crow-Eye is still parsing or
loading. The click goes through (tabs still switch), but the tables are not
filled yet, which looked like missing data. The first such click in a run gets
a small popup saying so; later clicks in the same run get a banner along the
top of the window. Both go away when the work finishes (ui/busy_guard.py).

BlockingWindowNotice - a click on the main window while a modal dialog blocks
it. Qt disables the blocked window (EnableWindow(FALSE)), so the click does
nothing at all, and when the dialog sits behind another program or on another
screen nothing on screen says why. Windows still sends the disabled window a
WM_SETCURSOR carrying the button press; a native event filter sees it, brings
the dialog forward, flashes it in the taskbar and names it in a toast. Qt drops
mouse events to blocked windows before any Qt event filter sees them, which is
why this is a native filter (Windows only; window managers on Linux keep a
modal dialog above its parent themselves).
"""

import time

from PyQt5 import QtCore, QtGui, QtWidgets

from ui import busy_guard

# Busy sections that are not "the data is not in the GUI yet": the tables are
# loaded and usable while these run.
NOT_LOADING = ("Database Search", "Correlation Engine pipeline", "Feather import")

_CARD_QSS = """
QFrame#busyNoticeCard { background: #0f172a; border: 1px solid #f59e0b; border-radius: 10px; }
QLabel { background: transparent; color: #e2e8f0; font-family: 'Segoe UI'; font-size: 13px; }
QLabel#busyNoticeTitle { color: #fbbf24; font-size: 15px; font-weight: 700; }
QLabel#busyNoticeNow { color: #94a3b8; font-size: 12px; font-family: 'Consolas'; }
QPushButton { background: #1e293b; color: #e2e8f0; border: 1px solid #334155; border-radius: 6px;
              padding: 6px 22px; font-weight: 700; }
QPushButton:hover { border-color: #fbbf24; color: #fbbf24; }
"""


def loading_section():
    """(reason, elapsed) of the oldest parse/load section running, or (None, 0)."""
    for reason, elapsed in busy_guard.sections():
        if not reason.startswith(NOT_LOADING):
            return reason, elapsed
    return None, 0.0


def _is_data_surface(widget, window):
    """A tab bar or a table/tree/list (or its header/viewport) in `window`."""
    w = widget
    while w is not None and w is not window:
        if isinstance(w, (QtWidgets.QTabBar, QtWidgets.QAbstractItemView)):
            return True
        if w.isWindow():
            return False
        w = w.parentWidget()
    return False


def _icon_label(name, size):
    label = QtWidgets.QLabel()
    try:
        from correlation_engine.gui.crow_eye_icons import CrowEyeIcons
        icon = getattr(CrowEyeIcons, name)()
        pm = icon.pixmap(size, size)
        if not pm.isNull():
            label.setPixmap(pm)
    except Exception:
        pass
    label.setFixedSize(size, size)
    return label


class _Popup(QtWidgets.QDialog):
    """Non-modal: a modal box here would block the very GUI that is loading."""

    def __init__(self, parent):
        super().__init__(parent, QtCore.Qt.Dialog | QtCore.Qt.FramelessWindowHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setWindowTitle("Crow-Eye - still loading")
        self.setModal(False)
        self.setStyleSheet(_CARD_QSS)
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QtWidgets.QFrame()
        card.setObjectName("busyNoticeCard")
        outer.addWidget(card)
        lay = QtWidgets.QVBoxLayout(card)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(10)
        head = QtWidgets.QHBoxLayout()
        head.addWidget(_icon_label("hourglass", 22))
        title = QtWidgets.QLabel("Please wait - the data is not loaded yet")
        title.setObjectName("busyNoticeTitle")
        head.addWidget(title, 1)
        lay.addLayout(head)
        body = QtWidgets.QLabel(
            "Crow-Eye is still analysing. The parsed data has not been loaded into "
            "the GUI yet, so this tab or table may look empty or incomplete. It "
            "fills in by itself when Crow-Eye finishes.")
        body.setWordWrap(True)
        lay.addWidget(body)
        self.now = QtWidgets.QLabel("")
        self.now.setObjectName("busyNoticeNow")
        lay.addWidget(self.now)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        ok = QtWidgets.QPushButton("OK")
        ok.setCursor(QtCore.Qt.PointingHandCursor)
        ok.clicked.connect(self.close)
        ok.setDefault(True)
        row.addWidget(ok)
        lay.addLayout(row)
        self.setFixedWidth(470)


class _Banner(QtWidgets.QFrame):
    """A thin amber strip along the bottom of the main window's central widget
    (the top holds the tab bars being clicked)."""

    def __init__(self, host):
        super().__init__(host)
        self.setObjectName("busyNoticeBanner")
        self.setStyleSheet(
            "QFrame#busyNoticeBanner { background: rgba(120,72,6,0.94); border: 1px solid #f59e0b;"
            " border-radius: 6px; }"
            " QLabel { background: transparent; color: #fde68a; font-family: 'Segoe UI';"
            " font-size: 12px; font-weight: 600; }"
            " QToolButton { background: transparent; color: #fde68a; border: none; font-weight: 700; }")
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(10, 5, 6, 5)
        lay.addWidget(_icon_label("hourglass", 16))
        self.text = QtWidgets.QLabel("")
        lay.addWidget(self.text, 1)
        close = QtWidgets.QToolButton()
        close.setText("x")
        close.setToolTip("Hide until the next click")
        close.setCursor(QtCore.Qt.PointingHandCursor)
        close.clicked.connect(self.hide)
        lay.addWidget(close)
        self.hide()
        host.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Resize and self.isVisible():
            self.place()
        return False

    def place(self):
        host = self.parentWidget()
        self.setGeometry(12, max(0, host.height() - 38), max(200, host.width() - 24), 30)
        self.raise_()


class BusyNotice(QtCore.QObject):
    """Install once: BusyNotice(main_window)."""

    def __init__(self, main_window):
        super().__init__(main_window)
        self._win = main_window
        self._shown_this_run = False
        self._last_press = 0.0
        self._popup = None
        self._banner = None
        self._tick = QtCore.QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._refresh)
        QtWidgets.QApplication.instance().installEventFilter(self)
        busy_guard.add_listener(self._on_busy_changed)

    # A press is delivered to the widget and then to each parent that ignores
    # it; the application filter sees every hop, so one click is one notice.
    def eventFilter(self, obj, event):
        if event.type() != QtCore.QEvent.MouseButtonPress or not isinstance(obj, QtWidgets.QWidget):
            return False
        try:
            if obj.window() is not self._win or not _is_data_surface(obj, self._win):
                return False
            now = time.monotonic()
            if now - self._last_press < 0.3:
                return False
            self._last_press = now
            reason, _elapsed = loading_section()
            if reason:
                self.notify()
        except RuntimeError:
            pass                                    # widget deleted mid-delivery
        return False                                # the click itself goes through

    def notify(self):
        if not self._shown_this_run:
            self._shown_this_run = True
            self._show_popup()
        elif self._popup is None or not self._popup.isVisible():
            self._show_banner()
        self._refresh()
        self._tick.start()

    def _show_popup(self):
        if self._popup is None:
            self._popup = _Popup(self._win)
        self._popup.adjustSize()
        geo = self._win.frameGeometry()
        self._popup.move(geo.center() - self._popup.rect().center())
        self._popup.show()
        self._popup.raise_()

    def _show_banner(self):
        host = self._win.centralWidget() or self._win
        if self._banner is None or self._banner.parentWidget() is not host:
            self._banner = _Banner(host)
        self._banner.place()
        self._banner.show()

    def _refresh(self):
        reason, elapsed = loading_section()
        if not reason:
            self._on_busy_changed(False)
            return
        what = "%s - %s elapsed" % (reason, busy_guard.format_elapsed(elapsed))
        try:
            if self._popup is not None and self._popup.isVisible():
                self._popup.now.setText("Now: " + what)
            if self._banner is not None and self._banner.isVisible():
                self._banner.text.setText(
                    "Still analysing (%s). The data is not loaded into the GUI yet - "
                    "tabs fill in when Crow-Eye finishes." % what)
        except RuntimeError:
            pass

    def _on_busy_changed(self, busy):
        if busy and loading_section()[0]:
            return
        # Idle (or only non-loading work left): the next run gets its popup again.
        self._shown_this_run = False
        self._tick.stop()
        for w in (self._popup, self._banner):
            try:
                if w is not None:
                    w.hide()
            except RuntimeError:
                pass


# -- the window that is blocking input ---------------------------------------------

WM_SETCURSOR = 0x0020
_PRESSES = (0x0201, 0x0204, 0x0207)          # WM_L/R/MBUTTONDOWN


def _describe(widget):
    title = (widget.windowTitle() or "").strip()
    if title:
        return title
    for attr in ("objectName",):
        name = getattr(widget, attr)()
        if name:
            return name
    return "a dialog"


class _Toast(QtWidgets.QLabel):
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("blockingToast")
        self.setStyleSheet(
            "QLabel#blockingToast { background: rgba(15,23,42,0.97); color: #e2e8f0;"
            " border: 1px solid #38bdf8; border-radius: 8px; padding: 10px 16px;"
            " font-family: 'Segoe UI'; font-size: 13px; }")
        self.setWordWrap(True)
        self._hide = QtCore.QTimer(self)
        self._hide.setSingleShot(True)
        self._hide.timeout.connect(self.hide)
        self.hide()

    def flash(self, html, ms=4500):
        self.setText(html)
        host = self.parentWidget()
        self.setFixedWidth(min(560, max(320, host.width() - 80)))
        self.adjustSize()
        self.move((host.width() - self.width()) // 2, max(40, host.height() // 3))
        self.show()
        self.raise_()
        self._hide.start(ms)


class BlockingWindowNotice(QtCore.QAbstractNativeEventFilter):
    """Install once: BlockingWindowNotice(main_window) (no-op off Windows)."""

    def __init__(self, main_window):
        super().__init__()
        self._win = main_window
        self._last = 0.0
        self._toast = None
        self._installed = False
        import sys
        if sys.platform != "win32":
            return
        try:
            import ctypes
            from ctypes import wintypes
            self._MSG = wintypes.MSG
            self._user32 = ctypes.windll.user32
            self._user32.GetAncestor.restype = wintypes.HWND
            self._user32.GetAncestor.argtypes = (wintypes.HWND, ctypes.c_uint)
            QtWidgets.QApplication.instance().installNativeEventFilter(self)
            self._installed = True
        except Exception:
            pass

    def nativeEventFilter(self, event_type, message):
        try:
            msg = self._MSG.from_address(int(message))
            if msg.message == WM_SETCURSOR and ((msg.lParam >> 16) & 0xFFFF) in _PRESSES:
                root = self._user32.GetAncestor(msg.hWnd, 2) or msg.hWnd     # GA_ROOT
                if int(root or 0) == int(self._win.winId()):
                    # Sent from inside the window procedure: act after it returns.
                    QtCore.QTimer.singleShot(0, self._main_clicked)
        except Exception:
            pass
        return False, 0

    def blocker(self):
        """The modal widget blocking the main window, or None."""
        modal = QtWidgets.QApplication.activeModalWidget()
        return None if modal is None or modal is self._win else modal

    def _main_clicked(self):
        now = time.monotonic()
        if now - self._last < 0.4:
            return
        self._last = now
        try:
            modal = self.blocker()
            if modal is None:
                return
            self.bring_forward(modal)
        except RuntimeError:
            pass

    def bring_forward(self, modal):
        if modal.isMinimized():
            modal.showNormal()
        # Off every screen (a monitor unplugged since it was moved there):
        # put it back over the main window.
        if QtWidgets.QApplication.screenAt(modal.frameGeometry().center()) is None:
            modal.move(self._win.frameGeometry().center() - modal.rect().center())
        modal.raise_()
        modal.activateWindow()
        QtWidgets.QApplication.alert(modal, 3000)
        import html
        if self._toast is None:
            self._toast = _Toast(self._win)
        self._toast.flash("<b style='color:#7dd3fc'>%s</b> is waiting for an answer. "
                          "Close it (or answer it) to use the main window again."
                          % html.escape(_describe(modal)))


def install(main_window):
    """Both notices on the main window; returns them so they stay referenced."""
    return BusyNotice(main_window), BlockingWindowNotice(main_window)
