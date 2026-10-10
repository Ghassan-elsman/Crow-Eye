# type: ignore
# pylint: disable-all
"""
The loading / parse dialog, in the website's look, with a real-time log.
"""

import sys
import os
import io
import re
import html as _html
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import QTimer, pyqtSignal
from PyQt5.QtWidgets import QApplication

# The bar that never looks frozen, and the pump that keeps it (and the elapsed
# clock) moving while the GUI thread is busy filling tables.
if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ui.animated_progress_bar import (AnimatedProgressBar, add_frame_callback,
                                      keep_alive, remove_frame_callback)

# Terminal colour codes, which several parsers emit through colorama and which
# this dialog would otherwise embed into HTML as literal escape sequences.
# Stripped centrally so no parser has to remember — the MFT, USN, Registry and
# live-collection paths all push coloured text down this same capture.
ANSI_ESCAPE = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')

# Add parent directory to path for standalone execution
if __name__ == "__main__":
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)
    sys.path.insert(0, parent_dir)

# Import styles from centralized styles module
try:
    from styles import CrowEyeStyles
except ImportError:
    # Create a minimal placeholder for standalone testing
    class CrowEyeStyles:
        LOADING_DIALOG_BACKDROP = "QFrame { background: #2d2d2d; border: 1px solid #666; }"
        LOADING_DIALOG_TITLE = "QLabel { color: #fff; font-size: 24px; font-weight: bold; }"
        LOADING_DIALOG_ICON = "QLabel { background: #444; border: 1px solid #666; }"
        LOADING_DIALOG_PROGRESS = "QProgressBar { border: 1px solid #666; }"
        LOADING_DIALOG_STEP = "QLabel { color: #fff; }"
        LOADING_DIALOG_LOG_HEADER = "QLabel { color: #fff; }"
        LOADING_DIALOG_LOG_DISPLAY = "QTextEdit { background: #333; color: #fff; }"


import logging

# Everything the dialog shows is also filed in the case log under this name
# (routed to parsers.log). Lines the dialog captured from stdout are not: the
# stdout tee and the parser's own run logger already have those.
_dialog_log = logging.getLogger("crow_eye.parsing")


def _paint_status_icon(state, size=14):
    """A small status mark drawn in code: no font glyph, no emoji, no file.

    waiting = hollow grey ring, running = cyan dot, done = green check,
    warning = amber dot with a bar, not_found = indigo dash, failed = rose
    cross, skipped = grey dash. The website's tones.
    """
    pm = QtGui.QPixmap(size, size)
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    c = size / 2.0
    colours = {"waiting": "#64748b", "running": "#22d3ee", "done": "#4ade80",
               "warning": "#fbbf24", "not_found": "#818cf8", "failed": "#f43f5e",
               "skipped": "#64748b"}
    col = QtGui.QColor(colours.get(state, "#64748b"))
    pen = QtGui.QPen(col, 2.0)
    pen.setCapStyle(QtCore.Qt.RoundCap)
    p.setPen(pen)
    if state == "waiting":
        p.drawEllipse(QtCore.QRectF(2, 2, size - 4, size - 4))
    elif state == "running":
        p.setBrush(col)
        p.drawEllipse(QtCore.QRectF(3, 3, size - 6, size - 6))
    elif state == "done":
        path = QtGui.QPainterPath()
        path.moveTo(2.5, c)
        path.lineTo(c - 1, size - 3.5)
        path.lineTo(size - 2.5, 3)
        p.drawPath(path)
    elif state == "warning":
        p.setBrush(col)
        p.setPen(QtCore.Qt.NoPen)
        p.drawEllipse(QtCore.QRectF(1, 1, size - 2, size - 2))
        p.setPen(QtGui.QPen(QtGui.QColor("#1a1a1a"), 2.0))
        p.drawLine(QtCore.QPointF(c, 4), QtCore.QPointF(c, size - 6))
        p.drawPoint(QtCore.QPointF(c, size - 3.5))
    elif state in ("not_found", "skipped"):
        p.drawLine(QtCore.QPointF(3, c), QtCore.QPointF(size - 3, c))
    elif state == "failed":
        p.drawLine(QtCore.QPointF(3, 3), QtCore.QPointF(size - 3, size - 3))
        p.drawLine(QtCore.QPointF(size - 3, 3), QtCore.QPointF(3, size - 3))
    p.end()
    return QtGui.QIcon(pm)


# The site look's pieces live in ui/site_theme.py now (Settings, Eye AI's
# Advanced dialog and Database Search share them); the old names stay.
from ui.site_theme import Card as _Card, Grip as _Grip, families as _fonts, font as _font


# Parse Status statuses (utils.parse_status.ParseStatus values) -> row state.
_OUTCOME_STATE = {
    "PARSED": "done", "NO_RECORDS": "not_found", "SOURCE_NOT_FOUND": "not_found",
    "FEATURE_DISABLED": "skipped", "NOT_RUN": "skipped",
    "UNSUPPORTED_FORMAT": "warning", "ACCESS_DENIED": "warning",
    "DEPENDENCY_MISSING": "warning", "PARTIAL": "warning", "FAILED": "failed",
}
_OUTCOME_NOTE = {
    "NO_RECORDS": "no records (not a failure)",
    "SOURCE_NOT_FOUND": "not found (not a failure)",
    "FEATURE_DISABLED": "turned off on this system",
    "NOT_RUN": "not run",
    "UNSUPPORTED_FORMAT": "unsupported format",
    "ACCESS_DENIED": "access denied",
    "DEPENDENCY_MISSING": "missing component",
    "PARTIAL": "partly parsed",
}


class LogCapture:
    """Capture stdout and stderr for log display"""

    def __init__(self, log_display_callback, now_callback=None):
        self.log_display_callback = log_display_callback
        # Where a carriage-return progress line goes: the dialog's "Now:" line.
        # They used to be dropped, so a parser that only reports through a
        # progress bar showed nothing at all while it ran.
        self.now_callback = now_callback
        # Captured at ENTER, not here: this object is built with the dialog and
        # may be entered much later, by which time a case may have been opened
        # and utils.logging_setup may have put its console tee in place. Holding
        # a stream from construction time meant restoring the wrong one.
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        self.last_progress_line = None  # Track last progress bar update
        # Set when the capture is stopped, or when its dialog has gone. A
        # capture can stay in the stdout chain after it is stopped (a parser's
        # own capture wrapped it and they unwound out of order); from then on
        # it only passes text through - a write to a deleted dialog used to
        # raise RuntimeError inside the parser's print() and abort the parse.
        self._passthrough = False

    def __enter__(self):
        # Whatever is in place right now is what gets restored, and what gets
        # written through - so the case's console.log tee stays in the chain
        # instead of being cut out of it.
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        self._passthrough = False
        # Store original streams as attributes on the LogCapture object
        # This allows parsers to detect and bypass log capture for performance
        sys.stdout = self
        sys.stderr = self
        # Expose original streams as attributes for detection
        self.original_stdout_ref = self.original_stdout
        self.original_stderr_ref = self.original_stderr
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Only put the streams back if they are still ours. A case switch during
        # a long parse re-points logging and installs a new tee; blindly
        # restoring here would tear that out and leave writes going to a closed
        # file handle.
        self._passthrough = True
        if sys.stdout is self:
            sys.stdout = self.original_stdout
        if sys.stderr is self:
            sys.stderr = self.original_stderr

    def write(self, text):
        try:
            self._write(text)
        except Exception:
            # Never let the display break the parser that is printing.
            self._passthrough = True
        return len(text or "")

    def _write(self, text):
        # Write to original stdout/stderr - unstripped, so a real terminal
        # still gets its colours. A windowless build has no stdout at all
        # (None) when no case is capturing it: then the display is the only
        # place this text goes, and print() must not raise on the way.
        if self.original_stdout is not None:
            try:
                self.original_stdout.write(text)
            except Exception:
                pass
        if self._passthrough or not text:
            return

        # The display renders HTML, so escape codes have to come out here.
        text = ANSI_ESCAPE.sub('', text)

        # Filter out progress bar updates (lines starting with carriage return or containing progress bars)
        if text.strip():
            # A progress bar (block characters, or a \r-rewritten line): not a
            # log line, but it is what the parser is doing right now.
            if '█' in text or '░' in text or '\r' in text:
                self.last_progress_line = text.replace('\r', '\n').strip().splitlines()[-1].strip()
                if self.now_callback is not None and self.last_progress_line:
                    try:
                        self.now_callback(self.last_progress_line)
                    except Exception:
                        pass
                keep_alive()
                return
            
            # Skip carriage return only lines
            if text.strip() == '\r' or text == '\r':
                return
            
            # Send meaningful log messages to display
            self.log_display_callback(text.strip())

        # Every print() during GUI-thread work (the table loaders print
        # constantly) doubles as an animation frame, so the bar, the clock and
        # this log keep moving while the event loop cannot run. Throttled and
        # GUI-thread-only inside keep_alive; never runs the event loop.
        keep_alive()
    
    def flush(self):
        try:
            self.original_stdout.flush()
        except Exception:
            pass


class LoadingDialog(QtWidgets.QDialog):
    """Progress card in the website's look: checklist, live log, cancel."""
    
    log_signal = pyqtSignal(str)     # Signal for thread-safe log updates
    # Lines from worker threads are batched: one queued signal per batch, not
    # one per printed line (a parse printing 50,000 lines queued 50,000 events
    # and the dialog lagged behind for minutes).
    _flush_signal = pyqtSignal()
    status_signal = pyqtSignal(str)  # Same, for the status line
    cancelled = pyqtSignal()      # Signal emitted when cancel button is clicked
    # Thread-safe routes into the checklist (see on_artifact_event /
    # on_parse_outcome / set_now).
    artifact_event_signal = pyqtSignal(object)
    outcome_signal = pyqtSignal(object)
    now_signal = pyqtSignal(str)
    # Once, when the dialog goes away (close(), or done()/accept()/reject()).
    # The Parse Status report opens on it, instead of after a guessed delay.
    closed = pyqtSignal()
    
    def __init__(self, title="CROW EYE SYSTEM", parent=None, phase="loading"):
        """`phase` colours the taskbar icon: "parsing" green, "loading" blue.

        It cannot be inferred from the title - the live parse and the case load
        both call themselves "CROW EYE SYSTEM" - so the three parsing call sites
        say so explicitly and everything else stays on the default.
        """
        super().__init__(parent)
        self.setWindowTitle("Crow Eye - Processing")
        
        # Set the Crow Eye icon from the .ico on disk, so Qt loads all the
        # embedded sizes (16..256) and stays sharp.
        #
        # This used to call utils.path_utils.get_resource_path, which exists
        # only in the EXE tree - in source the import raised straight into
        # the except below and the dialog simply had no icon, silently.
        try:
            from styles import CrowEyeStyles as _CES
            _icon = _CES.crow_eye_icon()
            if _icon is not None:
                self.setWindowIcon(_icon)
        except Exception:
            pass  # an icon is never a reason to fail to show progress
        
        # NOTE: deliberately NOT WindowStaysOnTopHint, and deliberately NOT modal.
        #
        # It must not force itself above a *newer* modal QMessageBox - otherwise a
        # dialog shown during a load is trapped behind the loading screen and
        # freezes it. And it must not take the input grab: an investigator is
        # entitled to open Settings, read a tab or look at the case while a long
        # parse runs. Without the grab, clicking the main window simply brings the
        # main window in front of this one, which is the whole behaviour asked for
        # - the loading screen keeps its size and its centred position and carries
        # on reporting, it just stops being in the way.
        self.setWindowFlags(QtCore.Qt.Dialog | QtCore.Qt.FramelessWindowHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setModal(False)
        
        # Dialog properties
        self.title_text = title
        self.operation_steps = []
        self.current_step = 0
        self._is_cancelled = False
        # The live checklist (set_checklist): artifact key -> row state.
        self._rows = {}
        self._row_order = []
        self._log_lines = 0
        self._source_text = ""
        # Checklist row updates arrive from worker threads (the offline parse
        # runs in a QThread); they are queued onto the GUI thread.
        self.artifact_event_signal.connect(self._apply_artifact_event)
        self.outcome_signal.connect(self._apply_outcome)
        self.now_signal.connect(self._apply_now)
        # Set once a real (completed, total) count reaches the bar; see
        # update_task_progress and _animate_dots.
        self._has_real_count = False
        self._phase = phase if phase in ("parsing", "loading") else "loading"
        self._taskbar_open = False
        
        # The breathing halo round the big logo.
        self.glow_opacity = 0.0
        self.glow_direction = 1
        # Dragging (mousePressEvent) and whether to keep re-centring.
        self._drag_from = None
        self._user_moved = False
        
        # Setup UI
        self.setup_ui()
        self.setup_animations()
        
        # Connect log signal for thread-safe updates
        self.log_signal.connect(self._post_line)
        import threading as _threading
        self._line_lock = _threading.Lock()
        self._pending_lines = []
        self._flush_scheduled = False
        self._dropped_lines = 0
        self._flush_signal.connect(self._flush_lines, QtCore.Qt.QueuedConnection)
        self.status_signal.connect(self.set_status_safe)
        
        # Log capture. Captured lines are shown but not re-logged (the console
        # tee and the parser's run logger already file them), and a \r progress
        # line becomes the "Now:" line.
        self.log_capture = LogCapture(self._show_captured_line, self.set_now)

    # Room round the card for its soft indigo glow (painted in paintEvent).
    _SHADOW = 14

    def setup_ui(self):
        """The card, in the website's look.

        Every widget other code reaches for keeps its name: title_label,
        status_label, source_label, logo_widget, now_label, progress_bar,
        elapsed_label, checklist, log_toggle, log_panel, log_display and
        cancel_button.
        """
        ui_font, mono_font = _fonts()
        self._ui_font, self._mono_font = ui_font, mono_font
        # Movable (drag any empty part of the card) and resizable (the grip in
        # the corner). It was fixed at 800 x 720 and could not be moved. No
        # explicit minimum on the dialog: that would replace the layout's own,
        # and a dialog dragged smaller than its rows would draw them on top of
        # each other. The card's minimum width feeds the layout instead.
        self.resize(800 + 2 * self._SHADOW, 720)

        main_layout = QtWidgets.QVBoxLayout()
        s = self._SHADOW
        main_layout.setContentsMargins(s, s, s, s)
        main_layout.setSpacing(0)

        # The card: #0f172a, hairline edge, 20 px corners, gradient strip.
        self.backdrop = _Card()
        self.backdrop.setObjectName("loadingCard")
        self.backdrop.setStyleSheet(CrowEyeStyles.LOADING_DIALOG_BACKDROP)
        self.backdrop.setMinimumWidth(720 - 2 * self._SHADOW)

        content_layout = QtWidgets.QVBoxLayout(self.backdrop)
        content_layout.setContentsMargins(24, 22, 24, 14)
        content_layout.setSpacing(12)
        self._content_layout = content_layout

        # Title, with a small Crow-Eye logo beside it in the checklist view
        # (the big logo folds away there to make room for the rows).
        self.title_label = QtWidgets.QLabel(self.title_text)
        self.title_label.setObjectName("loadingTitle")
        self.title_label.setStyleSheet(CrowEyeStyles.LOADING_DIALOG_TITLE)
        self.title_label.setFont(_font(ui_font, 26, QtGui.QFont.ExtraBold, upper=True, spacing=104))
        self.title_label.setAlignment(QtCore.Qt.AlignCenter)
        self.title_label.setMinimumHeight(40)
        header = QtWidgets.QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(14)
        self.mini_logo = QtWidgets.QLabel()
        self.mini_logo.setObjectName("miniLogo")
        self.mini_logo.setFixedSize(40, 40)
        self.mini_logo.setStyleSheet("QLabel { background: transparent; border: none; }")
        pm = self._logo_pixmap(40)
        if pm is not None:
            self.mini_logo.setPixmap(pm)
        self.mini_logo.hide()
        # Kept for callers; the checklist header is left-aligned now, so the
        # title no longer needs a counterweight to stay centred.
        self._mini_logo_balance = QtWidgets.QWidget()
        self._mini_logo_balance.setFixedSize(40, 40)
        self._mini_logo_balance.setStyleSheet("background: transparent; border: none;")
        self._mini_logo_balance.hide()
        header.addWidget(self.mini_logo, 0, QtCore.Qt.AlignVCenter)
        header.addWidget(self.title_label, 1)
        header.addWidget(self._mini_logo_balance, 0, QtCore.Qt.AlignVCenter)
        content_layout.addLayout(header)

        # Status line - what is happening right now, as opposed to the title,
        # which says what the dialog is. Hidden until something has a status
        # to report.
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setAlignment(QtCore.Qt.AlignCenter)
        self.status_label.setWordWrap(True)
        self.status_label.setFont(_font(ui_font, 15, QtGui.QFont.DemiBold))
        self.status_label.setStyleSheet(
            "QLabel { color: #A5B4FC; background: transparent; border: none; padding: 0; }")
        self.status_label.hide()
        content_layout.addWidget(self.status_label)

        # What is being parsed ("Parsing C:\ (live)"). Hidden until set_source().
        self.source_label = QtWidgets.QLabel("")
        self.source_label.setObjectName("sourceLabel")
        self.source_label.setAlignment(QtCore.Qt.AlignCenter)
        self.source_label.setWordWrap(True)
        self.source_label.setFont(_font(mono_font, 12))
        self.source_label.setStyleSheet(
            "QLabel { color: #94A3B8; background: transparent; border: none; padding: 0; }")
        self.source_label.hide()
        content_layout.addWidget(self.source_label)

        # The big logo, in a widget of its own so the checklist view can fold
        # it away.
        self.logo_widget = QtWidgets.QWidget()
        self.logo_widget.setStyleSheet("background: transparent; border: none;")
        logo_container = QtWidgets.QHBoxLayout(self.logo_widget)
        logo_container.setContentsMargins(0, 8, 0, 8)
        logo_container.addStretch(1)
        self.setup_logo(logo_container)
        logo_container.addStretch(1)
        content_layout.addWidget(self.logo_widget)

        # Small gap
        self._logo_gap = QtWidgets.QWidget()
        self._logo_gap.setFixedHeight(2)
        self._logo_gap.setStyleSheet("background: transparent; border: none;")
        content_layout.addWidget(self._logo_gap)

        # "Now:" - the file or hive being read, or the parser's own progress
        # line. Hidden until something reports one.
        self.now_label = QtWidgets.QLabel("")
        self.now_label.setObjectName("nowLabel")
        self.now_label.setWordWrap(False)
        self.now_label.setTextFormat(QtCore.Qt.PlainText)
        self.now_label.setFont(_font(mono_font, 12))
        self.now_label.setStyleSheet(
            "QLabel { color: #67E8F9; background: rgba(34, 211, 238, 0.06);"
            " border: 1px solid rgba(34, 211, 238, 0.18); border-radius: 8px; padding: 6px 10px; }")
        self.now_label.hide()
        content_layout.addWidget(self.now_label)

        # The bar's text sits ABOVE it ("6 of 11 artifacts (54%)"), with the
        # elapsed clock on the right: a 10 px pill has no room for text.
        caption = QtWidgets.QHBoxLayout()
        caption.setContentsMargins(0, 0, 0, 0)
        caption.setSpacing(12)
        self.progress_caption = QtWidgets.QLabel("")
        self.progress_caption.setObjectName("progressCaption")
        self.progress_caption.setFont(_font(ui_font, 14, QtGui.QFont.DemiBold))
        self.progress_caption.setStyleSheet(
            "QLabel { color: #F8FAFC; background: transparent; border: none; padding: 0; }")
        caption.addWidget(self.progress_caption, 1)

        # Elapsed clock: proof of life even when no step has finished for
        # minutes. Ticks on every animation frame (see _on_frame), including
        # frames pumped while the GUI thread is busy.
        self.elapsed_label = QtWidgets.QLabel("Elapsed 00:00")
        self.elapsed_label.setObjectName("elapsedLabel")
        self.elapsed_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.elapsed_label.setFont(_font(mono_font, 12))
        self.elapsed_label.setStyleSheet(
            "QLabel { color: #94A3B8; background: transparent; border: none; padding: 0; }")
        caption.addWidget(self.elapsed_label, 0)
        content_layout.addLayout(caption)

        # Progress: a slim indigo -> cyan pill. Animated: a light sweep keeps
        # moving between real updates, so a long step never looks like a freeze.
        self.progress_bar = AnimatedProgressBar(accent="#A5B4FC")
        self.progress_bar.setInset(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 0)  # Start as indeterminate
        self.progress_bar.setStyleSheet(CrowEyeStyles.LOADING_DIALOG_PROGRESS)
        self.progress_bar.setFixedHeight(10)
        # The caption follows the bar's text: on every setFormat, every value
        # change, and every animation frame.
        _set_format = self.progress_bar.setFormat

        def _format_and_caption(fmt, _orig=_set_format):
            _orig(fmt)
            self._sync_caption()
        self.progress_bar.setFormat = _format_and_caption
        self.progress_bar.valueChanged.connect(lambda _v: self._sync_caption())
        content_layout.addWidget(self.progress_bar)

        # The checklist: one row per artifact, filled in as each one runs.
        # Hidden until set_checklist(); dialogs that never call it (the case
        # load, the single searches) keep the big-logo layout.
        self.checklist = QtWidgets.QTreeWidget()
        self.checklist.setObjectName("parseChecklist")
        self.checklist.setColumnCount(4)
        self.checklist.setHeaderLabels(["Artifact", "Records", "Time", "Note"])
        self.checklist.setRootIsDecorated(False)
        self.checklist.setUniformRowHeights(True)
        self.checklist.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.checklist.setFocusPolicy(QtCore.Qt.NoFocus)
        self.checklist.setIconSize(QtCore.QSize(14, 14))
        self.checklist.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.checklist.setFont(_font(ui_font, 14))
        _hdr = self.checklist.header()
        _hdr.setFont(_font(ui_font, 11, QtGui.QFont.Bold, upper=True, spacing=108))
        _hdr.setStretchLastSection(True)
        _hdr.setSectionResizeMode(0, QtWidgets.QHeaderView.Fixed)
        _hdr.setSectionResizeMode(1, QtWidgets.QHeaderView.Fixed)
        _hdr.setSectionResizeMode(2, QtWidgets.QHeaderView.Fixed)
        self.checklist.setColumnWidth(0, 240)
        for _col in (1, 2):
            self.checklist.headerItem().setTextAlignment(
                _col, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.checklist.setColumnWidth(1, 96)
        self.checklist.setColumnWidth(2, 76)
        # No `color` on ::item: it would override the Note column's colours.
        self.checklist.setStyleSheet("""
            QTreeWidget { background: rgba(10, 12, 16, 0.55); color: #E2E8F0;
                          border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 12px;
                          outline: 0; }
            QTreeWidget::item { padding: 5px 4px; border: none;
                                border-bottom: 1px solid rgba(255, 255, 255, 0.04); }
            QHeaderView { background: transparent; border: none; }
            QHeaderView::section { background: transparent; color: #94A3B8; border: none;
                                   border-bottom: 1px solid rgba(255, 255, 255, 0.08);
                                   padding: 8px 8px 6px 8px; }
        """)
        self.checklist.hide()
        content_layout.addWidget(self.checklist, 1)

        # In the checklist view the raw log folds away behind this toggle.
        self.log_toggle = QtWidgets.QPushButton("Show log (0 lines)")
        self.log_toggle.setObjectName("logToggle")
        self.log_toggle.setCursor(QtCore.Qt.PointingHandCursor)
        self.log_toggle.setCheckable(True)
        self.log_toggle.setFont(_font(ui_font, 13, QtGui.QFont.DemiBold))
        self.log_toggle.setStyleSheet(
            "QPushButton { color: #A5B4FC; background: transparent; border: none;"
            " text-align: left; padding: 2px 0; }"
            "QPushButton:hover { color: #F8FAFC; }")
        self.log_toggle.toggled.connect(self._toggle_log)
        self.log_toggle.hide()
        content_layout.addWidget(self.log_toggle)

        # The log pane: a toolbar (level filter, find, follow, copy) over a
        # plain-text view coloured by ui/log_highlighter.py, like an IDE's
        # output panel.
        self.log_panel = QtWidgets.QWidget()
        self.log_panel.setObjectName("logPanel")
        self.log_panel.setStyleSheet("QWidget#logPanel { background: transparent; border: none; }")
        lp = QtWidgets.QVBoxLayout(self.log_panel)
        lp.setContentsMargins(0, 0, 0, 0)
        lp.setSpacing(8)
        lp.addLayout(self._build_log_toolbar())
        self.log_display = QtWidgets.QPlainTextEdit()
        self.log_display.setObjectName("logDisplay")
        self.log_display.setReadOnly(True)
        self.log_display.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        # Bounded: a parse that prints 100,000 lines keeps the last 5000 here
        # (every line is in the case log).
        self.log_display.document().setMaximumBlockCount(5000)
        self.log_display.setStyleSheet(CrowEyeStyles.LOADING_DIALOG_LOG_DISPLAY_PLAIN.replace(
            "'JetBrains Mono'", "'%s'" % mono_font))
        self.log_display.setMinimumHeight(180)
        from ui.log_highlighter import LogHighlighter
        self._log_highlighter = LogHighlighter(self.log_display.document())
        lp.addWidget(self.log_display)
        # Grows with the dialog in the big-logo view; in the checklist view
        # the list takes the extra height instead (set_checklist).
        content_layout.addWidget(self.log_panel, 1)

        # Cancel: a ghost pill that turns rose on hover.
        footer = QtWidgets.QHBoxLayout()
        footer.setContentsMargins(0, 2, 0, 0)
        footer.addStretch(1)
        self.cancel_button = QtWidgets.QPushButton("CANCEL OPERATION")
        self.cancel_button.setObjectName("cancelButton")
        self.cancel_button.setCursor(QtCore.Qt.PointingHandCursor)
        self.cancel_button.setFont(_font(ui_font, 13, QtGui.QFont.Bold, spacing=106))
        self.cancel_button.setFixedHeight(34)
        self.cancel_button.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #94A3B8;
                border: 1px solid rgba(255, 255, 255, 0.14);
                border-radius: 16px;
                padding: 0 28px;
            }
            QPushButton:hover {
                color: #FFFFFF;
                background: #F43F5E;
                border-color: #F43F5E;
            }
            QPushButton:pressed {
                background: #E11D48;
                border-color: #E11D48;
            }
            QPushButton:disabled {
                color: #FDA4AF;
                background: rgba(244, 63, 94, 0.08);
                border-color: rgba(244, 63, 94, 0.35);
            }
        """)
        self.cancel_button.clicked.connect(self.on_cancel_clicked)
        footer.addWidget(self.cancel_button)
        footer.addStretch(1)
        content_layout.addLayout(footer)

        # Resize grip, pinned to the card's bottom-right corner by _Card.
        self._grip = _Grip(self.backdrop)
        self.backdrop.grip = self._grip

        main_layout.addWidget(self.backdrop)
        self.setLayout(main_layout)

    # -- look and feel: glow, dragging, caption ------------------------------
    def paintEvent(self, event):
        """A soft indigo glow round the card (the window is translucent).

        Drawn once per size into a pixmap and blitted: the progress bar
        repaints ~30 times a second, and on a translucent window each of those
        repaints the glow under it - 14 antialiased rounded rects every time
        (2026-10-09: 0.16 ms a paint, 60% of a busy second in the glow)."""
        glow = self._glow_pixmap()
        if glow is None:
            return
        p = QtGui.QPainter(self)
        r = event.rect()
        p.drawPixmap(r, glow, QtCore.QRect(int(r.x() * glow.devicePixelRatio()),
                                           int(r.y() * glow.devicePixelRatio()),
                                           int(r.width() * glow.devicePixelRatio()),
                                           int(r.height() * glow.devicePixelRatio())))
        p.end()

    def _glow_pixmap(self):
        card = self.backdrop.geometry() if getattr(self, "backdrop", None) is not None else None
        if card is None or card.isEmpty():
            return None
        dpr = self.devicePixelRatioF() if hasattr(self, "devicePixelRatioF") else 1.0
        key = (self.width(), self.height(), card.x(), card.y(), card.width(), card.height(), dpr)
        if getattr(self, "_glow_key", None) == key:
            return self._glow_cache
        pm = QtGui.QPixmap(int(self.width() * dpr), int(self.height() * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(pm)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        p.setBrush(QtCore.Qt.NoBrush)
        rect = QtCore.QRectF(card)
        s = self._SHADOW
        for i in range(1, s + 1):
            alpha = int(38 * (1.0 - i / float(s + 1)) ** 2)
            p.setPen(QtGui.QPen(QtGui.QColor(99, 102, 241, alpha), 1.0))
            r = rect.adjusted(-i + 0.5, -i + 0.5, i - 0.5, i - 0.5)
            p.drawRoundedRect(r, _Card.RADIUS + i, _Card.RADIUS + i)
        p.end()
        self._glow_cache, self._glow_key = pm, key
        self.glow_builds = getattr(self, "glow_builds", 0) + 1
        return pm

    def mousePressEvent(self, event):
        # Presses on the card and its labels arrive here (they do not take
        # mouse input); buttons, the list, the log and the grip keep theirs.
        if event.button() == QtCore.Qt.LeftButton:
            self._drag_from = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_from is not None and event.buttons() & QtCore.Qt.LeftButton:
            self.move(event.globalPos() - self._drag_from)
            self._user_moved = True
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_from = None
        super().mouseReleaseEvent(event)

    def _sync_caption(self):
        """Mirror the bar's text into the caption above it. True if changed."""
        try:
            text = self.progress_bar.text()
            if text == self.progress_caption.text():
                return False
            self.progress_caption.setText(text)
            return True
        except (RuntimeError, AttributeError):
            return False

    def _fit(self, height):
        """Resize to `height` (capped to the screen), keeping the width the
        investigator chose; re-centred unless they moved the dialog."""
        h = min(self._screen_height() - 40, int(height))
        lay = self.layout()
        floor = lay.totalMinimumSize().height() if lay is not None else 0
        self.resize(max(self.width(), 860), max(h, floor))
        if self.isVisible() and not self._user_moved:
            self.center_on_screen()

    def on_cancel_clicked(self):
        """Handle cancel button click"""
        self._is_cancelled = True
        self.cancel_button.setEnabled(False)
        self.cancel_button.setText("CANCELLING - WAITING FOR THE CURRENT STEP TO STOP...")
        self.add_log_message("[Warning] Cancellation requested by user...")
        # Rows that never started will not start now.
        for row in self._rows.values():
            if row["state"] == "waiting":
                row["state"] = "skipped"
                row["note"] = "cancelled"
        for key in list(self._rows):
            self._paint_row(key)
        self.cancelled.emit()
    
    def showEvent(self, event):
        """Override showEvent to center dialog after Qt finalizes geometry"""
        super().showEvent(event)
        # The taskbar indicator lives exactly as long as this dialog is up.
        # showEvent can fire more than once (hide/show), so it is guarded.
        if not self._taskbar_open:
            self._taskbar_open = True
            self._taskbar("begin", self._phase)
        self._start_clock()
        if not self._user_moved:
            self.center_on_screen()
        # Without WindowStaysOnTopHint, raise once so the frameless dialog reliably
        # appears in front of the main window when shown.
        self.raise_()
        
    # -- elapsed clock + busy-thread frames ----------------------------------
    def _start_clock(self):
        if getattr(self, "_clock_ref", None) is not None:
            return                                   # showEvent can fire twice
        import time as _time
        self._clock_t0 = _time.monotonic()
        self._clock_frozen = False
        self._clock_text = ""
        self._log_dirty = False
        self._last_log_paint = 0.0
        self._clock_ref = add_frame_callback(self._on_frame)

    def _stop_clock(self):
        ref = getattr(self, "_clock_ref", None)
        if ref is not None:
            remove_frame_callback(ref)
            self._clock_ref = None

    @staticmethod
    def _fmt_elapsed(seconds):
        seconds = int(seconds)
        h, rem = divmod(seconds, 3600)
        m, s = divmod(rem, 60)
        return "%d:%02d:%02d" % (h, m, s) if h else "%02d:%02d" % (m, s)

    def _on_frame(self):
        """One animation frame - from the shared timer or from keep_alive().

        Under keep_alive the event loop is NOT running, so a plain update()
        would never be painted: what changed is repainted directly. Cheap -
        the clock text changes once a second and the log at most ~7x/s.
        """
        try:
            if not self.isVisible():
                return
            import time as _time
            now = _time.monotonic()
            if not getattr(self, "_clock_frozen", False):
                elapsed = now - self._clock_t0
                text = "Elapsed " + self._fmt_elapsed(elapsed) + self._eta_text(elapsed)
                if text != self._clock_text:
                    self._clock_text = text
                    self.elapsed_label.setText(text)
                    self.elapsed_label.repaint()
                    # Running rows tick with the clock.
                    for key, row in self._rows.items():
                        if row["state"] == "running" and row["started"] is not None:
                            row["item"].setText(2, self._fmt_elapsed(now - row["started"]))
                    if self._rows:
                        self.checklist.viewport().repaint()
            if self._sync_caption():
                self.progress_caption.repaint()
            if self._log_dirty and now - self._last_log_paint > 0.15:
                self._log_dirty = False
                self._last_log_paint = now
                self.log_display.viewport().repaint()
                self.status_label.repaint()
        except RuntimeError:
            self._stop_clock()                       # widget already deleted

    def is_cancelled(self):
        """Check if cancellation has been requested"""
        return self._is_cancelled
        
    def _logo_pixmap(self, size):
        """The Crow-Eye logo at ``size`` px (HiDPI-sharp), or None."""
        base_dir = os.path.dirname(os.path.dirname(__file__))
        for name in ("CrowEye_rounded.png", "Crow-Eye.png", "CrowEye.png"):
            pm = QtGui.QPixmap(os.path.join(base_dir, "GUI Resources", name))
            if pm.isNull():
                continue
            try:
                ratio = max(1.0, float(self.devicePixelRatioF()))
            except Exception:
                ratio = 1.0
            side = int(size * ratio)
            pm = pm.scaled(side, side, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
            pm.setDevicePixelRatio(ratio)
            return pm
        return None

    def setup_logo(self, layout):
        """Setup logo with comprehensive fallback paths"""
        try:
            self.icon_label = QtWidgets.QLabel()
            icon_pixmap = None

            # Render at 2x for HiDPI sharpness, then downscale to display size.
            device_ratio = self.devicePixelRatioF() if hasattr(self, "devicePixelRatioF") else 1.0
            target_size = 176  # icon edge length in logical pixels
            border_px = 2      # must match LOADING_DIALOG_ICON border width
            padding_px = 8     # must match LOADING_DIALOG_ICON padding (inset margin)
            total_offset = border_px + padding_px
            self.icon_label.setFixedSize(target_size + 2 * total_offset, target_size + 2 * total_offset)
            self.icon_label.setContentsMargins(0, 0, 0, 0)
            render_size = int(target_size * max(device_ratio, 2.0))

            # Prefer high-res PNG sources; only use ICO as last resort and request
            # its largest embedded variant via QIcon to avoid the 16x13 default.
            base_dir = os.path.dirname(os.path.dirname(__file__))
            png_candidates = [
                # Square, high-res, already-rounded master first -> crisp + correctly
                # proportioned in the square frame (the other PNGs are landscape 2018x1614).
                os.path.join(base_dir, "GUI Resources", "CrowEye_rounded.png"),
                os.path.join(base_dir, "GUI Resources", "Crow-Eye.png"),
                os.path.join(base_dir, "GUI Resources", "CrowEye.png"),
                "GUI Resources/Crow-Eye.png",
                "GUI Resources/CrowEye.png",
                "../GUI Resources/Crow-Eye.png",
                "../GUI Resources/CrowEye.png",
                os.path.join(base_dir, "GUI Resources", "CrowEye.jpg"),
                "GUI Resources/CrowEye.jpg",
            ]

            for path in png_candidates:
                try:
                    candidate = QtGui.QPixmap(path)
                    if candidate and not candidate.isNull() and candidate.width() >= 128:
                        icon_pixmap = candidate
                        break
                except Exception:
                    continue

            # ICO fallback — pull the largest embedded size, not the default 16x13.
            if icon_pixmap is None or icon_pixmap.isNull():
                ico_candidates = [
                    os.path.join(base_dir, "GUI Resources", "CrowEye.ico"),
                    "GUI Resources/CrowEye.ico",
                    "../GUI Resources/CrowEye.ico",
                ]
                for path in ico_candidates:
                    try:
                        ico = QtGui.QIcon(path)
                        # Not ico.isNull(): QIcon is lazy and says False
                        # for a path that resolves to nothing.
                        if ico.availableSizes() or not ico.pixmap(32, 32).isNull():
                            sizes = ico.availableSizes()
                            if sizes:
                                largest = max(sizes, key=lambda s: s.width() * s.height())
                                candidate = ico.pixmap(largest)
                            else:
                                candidate = ico.pixmap(QtCore.QSize(render_size, render_size))
                            if candidate and not candidate.isNull():
                                icon_pixmap = candidate
                                break
                    except Exception:
                        continue

            if icon_pixmap and not icon_pixmap.isNull():
                # Center-crop to a SQUARE first so the logo sits correctly in the square,
                # rounded frame. The source PNGs are landscape (2018x1614); scaling with
                # KeepAspectRatio alone yields a non-square pixmap -> asymmetric border and a
                # layout jump when the label is re-sized to the pixmap below.
                _iw, _ih = icon_pixmap.width(), icon_pixmap.height()
                if _iw != _ih:
                    _side = min(_iw, _ih)
                    icon_pixmap = icon_pixmap.copy((_iw - _side) // 2, (_ih - _side) // 2, _side, _side)
                # Scale to render_size (HiDPI-aware) with smooth transform, then
                # tag the pixmap's device pixel ratio so Qt draws it at target_size.
                scaled_pixmap = icon_pixmap.scaled(
                    render_size, render_size,
                    QtCore.Qt.KeepAspectRatio,
                    QtCore.Qt.SmoothTransformation,
                )
                dpr = render_size / target_size
                # Round the logo's corners for a modern rounded-square look. Do the clip at
                # DEVICE resolution while the pixmap's DPR is still 1.0 -> drawPixmap uses the
                # full render_size pixels. (If the DPR were set first, drawPixmap would paint
                # the pixmap at its logical/half size into the corner -> off-center, tiny logo.)
                # The device-pixel ratio is applied ONCE, after rounding, just below.
                try:
                    _rw, _rh = scaled_pixmap.width(), scaled_pixmap.height()
                    _radius = int(min(_rw, _rh) * 0.14)
                    _rounded = QtGui.QPixmap(_rw, _rh)
                    _rounded.fill(QtCore.Qt.transparent)
                    _painter = QtGui.QPainter(_rounded)
                    _painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
                    _painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
                    _path = QtGui.QPainterPath()
                    _path.addRoundedRect(QtCore.QRectF(0, 0, _rw, _rh), _radius, _radius)
                    _painter.setClipPath(_path)
                    _painter.drawPixmap(0, 0, scaled_pixmap)
                    _painter.end()
                    scaled_pixmap = _rounded
                except Exception:
                    pass
                # Tag the device pixel ratio ONCE so Qt draws the (now rounded) pixmap at
                # target_size logical points.
                scaled_pixmap.setDevicePixelRatio(dpr)
                # Resize the label to the pixmap's actual logical size so the
                # cyan border hugs the icon's true bounding box (no inner gaps).
                logical_w = int(scaled_pixmap.width() / dpr)
                logical_h = int(scaled_pixmap.height() / dpr)
                self.icon_label.setFixedSize(logical_w + 2 * total_offset, logical_h + 2 * total_offset)
                self.icon_label.setPixmap(scaled_pixmap)
                self.icon_label.setStyleSheet(CrowEyeStyles.LOADING_DIALOG_ICON)
                self.icon_label.setAlignment(QtCore.Qt.AlignCenter)
                self.icon_label.setToolTip("Crow Eye Digital Forensics Tool")

                # Soft indigo halo around the frame (drop shadow with no offset).
                self.logo_halo = QtWidgets.QGraphicsDropShadowEffect(self.icon_label)
                self.logo_halo.setColor(QtGui.QColor(99, 102, 241, 150))
                self.logo_halo.setBlurRadius(40)
                self.logo_halo.setOffset(0, 0)
                self.icon_label.setGraphicsEffect(self.logo_halo)

                layout.addWidget(self.icon_label)
            else:
                print("No valid icon found, using fallback placeholder")  # Debug output
                # Professional fallback
                placeholder = QtWidgets.QLabel("CROW EYE\nFORENSICS")
                placeholder.setFixedSize(176, 176)
                placeholder.setFont(_font(_fonts()[0], 24, QtGui.QFont.ExtraBold, spacing=104))
                placeholder.setStyleSheet("""
                    QLabel {
                        color: #F8FAFC;
                        background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1,
                                                  stop: 0 rgba(99, 102, 241, 0.85),
                                                  stop: 1 rgba(34, 211, 238, 0.85));
                        border: none;
                        border-radius: 24px;
                        padding: 20px;
                    }
                """)
                placeholder.setAlignment(QtCore.Qt.AlignCenter)
                placeholder.setWordWrap(True)
                layout.addWidget(placeholder)
                
        except Exception as e:
            print(f"Icon loading exception: {e}")  # Enhanced debug output
            # Debug placeholder
            debug_label = QtWidgets.QLabel("CROW EYE")
            debug_label.setFixedSize(176, 176)
            debug_label.setFont(_font(_fonts()[0], 24, QtGui.QFont.ExtraBold, spacing=104))
            debug_label.setStyleSheet("""
                QLabel {
                    color: #94A3B8;
                    background: rgba(99, 102, 241, 0.08);
                    border: 1px solid rgba(255, 255, 255, 0.08);
                    border-radius: 24px;
                    padding: 20px;
                }
            """)
            debug_label.setAlignment(QtCore.Qt.AlignCenter)
            debug_label.setWordWrap(True)
            layout.addWidget(debug_label)

        
    def setup_animations(self):
        """The halo, the PROCESSING dots and the dots after a percentage."""
        # The logo's breathing halo
        self.glow_timer = QTimer()
        self.glow_timer.timeout.connect(self.update_glow)
        self.glow_timer.start(100)  # 100ms interval
        
        # Progress bar text animation
        self.progress_text_timer = QTimer()
        self.progress_text_timer.timeout.connect(self.animate_progress_text)
        self.progress_text_timer.start(500)  # 500ms interval
        
        self.progress_dots = 0
        
        # Animation timer for dots indicator (Bug Fix #2)
        self.animation_timer = QTimer()
        self.animation_timer.timeout.connect(self._animate_dots)
        self.animation_timer.start(500)  # 500ms interval
        
        self.dot_state = 0  # 0, 1, 2 for ".", "..", "..."
        
    def update_glow(self):
        """Breathe the big logo's halo. (The title used to pulse too, restyled
        on every tick; it is plain text now, like the website's headings.)"""
        self.glow_opacity += 0.03 * self.glow_direction
        if self.glow_opacity >= 0.6:
            self.glow_opacity = 0.6
            self.glow_direction = -1
        elif self.glow_opacity <= 0.2:
            self.glow_opacity = 0.2
            self.glow_direction = 1
        self._update_halo()

    def _update_halo(self):
        """The logo's breathing halo - not while the logo is folded away."""
        if getattr(self, "logo_widget", None) is not None and self.logo_widget.isHidden():
            return
        if hasattr(self, 'logo_halo') and self.logo_halo:
            try:
                # Oscillate blur radius between 25 and 45
                current_blur = int(25 + (self.glow_opacity - 0.2) * 50)
                self.logo_halo.setBlurRadius(current_blur)
                
                # Oscillate the indigo halo's opacity between 100 and 200
                alpha = int(100 + (self.glow_opacity - 0.2) * 250)
                self.logo_halo.setColor(QtGui.QColor(99, 102, 241, alpha))
            except Exception:
                pass
        

        
    def animate_progress_text(self):
        """Animate the progress bar text - handles PROCESSING... animation"""
        current_text = self.progress_bar.format()
        
        # Only animate "PROCESSING..." if we're in indeterminate mode
        # Check if the text is actually "PROCESSING" (not a percentage display)
        if not current_text or not current_text.startswith("PROCESSING"):
            return
        
        # Animate "PROCESSING..." for indeterminate mode
        self.progress_dots = (self.progress_dots + 1) % 4
        dots = "." * self.progress_dots
        spaces = " " * (3 - self.progress_dots)
        self.progress_bar.setFormat(f"PROCESSING{dots}{spaces}")
    
    def _animate_dots(self):
        """Animate the dots indicator next to percentage (Bug Fix #2)"""
        # This method animates dots for percentage displays (like "Step 1/5: 45% ...")

        # Not while a real count is on the bar. This timer rewrites the format
        # string every 500 ms, so it used to overwrite "Collected 4 of 13" with
        # its own rstrip-and-append version a moment after it was written - the
        # count flickered and lost its trailing characters to rstrip(". ").
        if getattr(self, "_has_real_count", False) or self._rows:
            return

        current_text = self.progress_bar.format()
        if not current_text:
            # If no text, set default
            self.progress_bar.setFormat("PROCESSING")
            return
        
        # Don't animate "PROCESSING..." (that's handled by animate_progress_text)
        if current_text.startswith("PROCESSING"):
            return
        
        # Animate dots for percentage displays
        dots = [".", "..", "..."]
        self.dot_state = (self.dot_state + 1) % 3
        
        # Remove existing dots at the end (strip all dots and spaces)
        base_text = current_text.rstrip(". ")
        
        # Add animated dots with a space before them
        self.progress_bar.setFormat(base_text + " " + dots[self.dot_state])
        
    def center_on_screen(self):
        """Center the dialog on the screen using modern Qt5 API"""
        # Use modern Qt5 API instead of deprecated desktop()
        screen = QApplication.screenAt(self.pos())
        if screen is None:
            screen = QApplication.primaryScreen()
        
        # Use availableGeometry to exclude taskbar area
        screen_geometry = screen.availableGeometry()
        dialog_geometry = self.frameGeometry()
        
        # Calculate center position
        center_point = screen_geometry.center()
        dialog_geometry.moveCenter(center_point)
        self.move(dialog_geometry.topLeft())
                 
    def update_task_progress(self, completed, total, label=""):
        """Show a real count of finished work: `completed` of `total`.

        Driven by Progress_Reporter.task_progress_updated, which carries a
        counter that only ever increases. The older update_step() renders a
        parser's hard-coded step constant instead, and the parallel pool
        finishes out of order, so that number can go down. Once this has been
        called the dots animation stands down for the rest of the run.
        """
        try:
            total = int(total)
            completed = int(completed)
        except (TypeError, ValueError):
            return
        if total <= 0:
            return
        completed = max(0, min(completed, total))
        self._has_real_count = True
        pct = int(completed * 100 / total)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(pct)
        self.progress_bar.setFormat("%d of %d complete (%d%%)" % (completed, total, pct))
        self._taskbar("set_value", completed, total)
        if label:
            self.set_status_safe(label)

    def _taskbar(self, action, *args):
        """Drive the taskbar indicator. Never lets it affect the operation.

        Everything long-running in Crow-Eye drives one of these dialogs, so
        this is the only wiring the feature needs - no call site has to know
        the taskbar exists.
        """
        try:
            from ui.taskbar_progress import taskbar
            getattr(taskbar(), action)(*args)
        except Exception:
            pass

    def set_phase(self, phase):
        """Recolour the taskbar icon: "parsing" green, "loading" blue.

        Parse Offline Artifacts opens one dialog to scan the image and then
        reuses it for the parse, so a phase fixed at construction would be
        wrong for the longer half of that run.
        """
        if phase in ("parsing", "loading"):
            self._phase = phase
            if self._taskbar_open:
                self._taskbar("set_phase", phase)

    def set_title(self, title):
        """Retitle the dialog while it is open.

        `Crow Eye.py` has called this since Parse Offline Artifacts was written,
        and the method did not exist. The AttributeError was swallowed by the
        caller's own handler, which left this dialog - application-modal and
        frameless at the time - on screen with no way to close it. Adding the
        method is the fix; the modal grab went away separately.
        """
        self.title_text = title or ""
        try:
            self.title_label.setText(self.title_text)
            self.setWindowTitle("Crow Eye - %s" % self.title_text
                                if self.title_text else "Crow Eye - Processing")
        except Exception:
            pass

    def set_steps(self, steps):
        """Set the operation steps"""
        self.operation_steps = steps
        self.current_step = 0
        
        # Initialize progress bar for determinate mode
        if len(steps) > 0:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat(f"Step 0/{len(steps)}: 0%")
        else:
            self.progress_bar.setRange(0, 0)  # Indeterminate mode
            
        # Force GUI update
        keep_alive()
        
    # -- the live checklist -------------------------------------------------
    def set_source(self, text):
        """What is being parsed, e.g. "Parsing C:\\ (live)". Shown under the title."""
        self._source_text = text or ""
        self.source_label.setText(self._source_text)
        self.source_label.setVisible(bool(self._source_text))

    def set_checklist(self, items):
        """Show one row per artifact: [(key, label), ...] in run order.

        Keys are utils.parse_status artifact names ("registry", "prefetch",
        ...), the same keys the parser frame (utils.parse_logging) and the
        Parse Status outcomes carry, so rows fill in from either.
        """
        self.checklist.clear()
        self.checklist.setHeaderLabels(
            ["Artifact" if self._phase == "parsing" else "Step", "Records", "Time", "Note"])
        self._rows = {}
        self._row_order = []
        for key, label in items:
            item = QtWidgets.QTreeWidgetItem([label, "", "", "waiting"])
            self._style_item(item)
            self.checklist.addTopLevelItem(item)
            self._rows[key] = {"item": item, "label": label, "state": "waiting",
                               "records": None, "warnings": 0, "started": None,
                               "elapsed": None, "note": "waiting", "messages": [],
                               "details": [], "icon_state": None}
            self._row_order.append(key)
            self._paint_row(key)
        on = bool(items)
        # Room for the rows: the 230 px logo folds away, the log goes behind
        # its toggle, and the dialog gets taller to fit the list.
        self.logo_widget.setVisible(not on)
        self._logo_gap.setVisible(not on)
        # The halo breathes only while the logo is on screen.
        timer = getattr(self, "glow_timer", None)
        if timer is not None:
            (timer.stop() if on else timer.start(100))
        self.mini_logo.setVisible(on and self.mini_logo.pixmap() is not None)
        self._mini_logo_balance.hide()
        # The checklist view reads like a page header: logo, title and the
        # lines under it on the left. The big-logo view stays centred.
        align = (QtCore.Qt.AlignLeft if on else QtCore.Qt.AlignHCenter) | QtCore.Qt.AlignVCenter
        for label in (self.title_label, self.status_label, self.source_label):
            label.setAlignment(align)
        self.checklist.setVisible(on)
        self.log_toggle.setVisible(on)
        self.log_panel.setVisible(not on or self.log_toggle.isChecked())
        # The extra height goes to the list in the checklist view, to the log
        # otherwise.
        self._content_layout.setStretchFactor(self.log_panel, 0 if on else 1)
        if on:
            # Tall enough for every row where the screen allows; on a short
            # screen the list scrolls instead of running under the buttons.
            self._rows_h = min(len(items), 16) * self._ROW_H + 34
            self.checklist.setMinimumHeight(min(self._rows_h, 6 * self._ROW_H + 34))
            self._fit(self._BASE_H + self._rows_h
                      + (self._LOG_H if self.log_toggle.isChecked() else 0))
        self._refresh_counts()

    # Row height of the checklist, the height of everything but the list,
    # and what the open log adds - for sizing the dialog to its rows.
    _ROW_H = 30
    _BASE_H = 330
    _LOG_H = 250

    def _style_item(self, item):
        """Records and Time in JetBrains Mono, right-aligned."""
        mono = _font(self._mono_font, 12)
        for col in (1, 2):
            item.setTextAlignment(col, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            item.setFont(col, mono)

    def _screen_height(self):
        try:
            screen = QApplication.screenAt(self.pos()) or QApplication.primaryScreen()
            return screen.availableGeometry().height()
        except Exception:
            return 900

    def _toggle_log(self, shown):
        # The list and the log share the height: with the log open the list
        # may shrink to four rows (it scrolls), and the log to 100 px.
        rows_h = getattr(self, "_rows_h", 0)
        self.checklist.setMinimumHeight(min(rows_h, (4 if shown else 6) * self._ROW_H + 34))
        self.log_display.setMinimumHeight(120 if self._rows else 180)
        self.log_panel.setVisible(shown)
        self.log_toggle.setText(("Hide log (%d lines)" if shown else "Show log (%d lines)")
                                % self._log_lines)
        if self._rows:
            # Grow or shrink by the log's share, from the size the dialog has
            # now - the investigator may have resized it.
            self._fit(self.height() + (self._LOG_H if shown else -self._LOG_H))

    def on_artifact_event(self, event):
        """A parser frame event (utils.parse_logging). Safe from any thread."""
        self.artifact_event_signal.emit(event)

    def on_parse_outcome(self, outcome):
        """A Parse Status outcome dict for one artifact. Safe from any thread."""
        self.outcome_signal.emit(outcome)

    def set_now(self, text):
        """The "Now:" line. Safe from any thread."""
        self.now_signal.emit(text or "")

    def _row_for(self, key):
        if key in self._rows:
            return key
        # A key the checklist was not told about (a correlation stage on a run
        # that did not list it): add it rather than lose it.
        if not key:
            return None
        item = QtWidgets.QTreeWidgetItem([str(key), "", "", ""])
        self._style_item(item)
        self.checklist.addTopLevelItem(item)
        self._rows[key] = {"item": item, "label": str(key), "state": "waiting", "records": None,
                           "warnings": 0, "started": None, "elapsed": None, "note": "",
                           "messages": [], "details": [], "icon_state": None}
        self._row_order.append(key)
        return key

    def _apply_artifact_event(self, event):
        try:
            import time as _time
            key = self._row_for((event or {}).get("artifact"))
            if key is None:
                return
            row = self._rows[key]
            kind = event.get("event")
            label = event.get("label") or row["label"]
            if kind == "start":
                row["state"] = "running"
                row["started"] = _time.monotonic() - float(event.get("elapsed") or 0)
                row["note"] = "running..."
                self._apply_now("%s - starting" % label)
            elif kind == "file":
                path = event.get("path") or ""
                detail = event.get("detail") or ""
                self._apply_now("%s - %s%s" % (label, path, (", " + detail) if detail else ""))
            elif kind == "now":
                self._apply_now("%s - %s" % (label, event.get("text") or ""))
            elif kind == "records":
                row["records"] = event.get("records")
            elif kind == "warning":
                row["warnings"] = int(event.get("warnings") or row["warnings"] + 1)
                self._remember(row, event.get("message"))
            elif kind == "line" and event.get("level") in ("WARNING", "ERROR"):
                row["warnings"] += 1
                self._remember(row, event.get("text"), event.get("level"))
            elif kind == "done":
                row["elapsed"] = event.get("elapsed")
                if event.get("records") is not None:
                    row["records"] = event.get("records")
                if event.get("status") == "failed":
                    row["state"] = "failed"
                    row["note"] = event.get("message") or "failed"
                elif row["state"] in ("running", "waiting"):
                    # The Parse Status outcome, when it comes, has the final say
                    # (not found / unsupported / partial). Warning LINES alone do
                    # not make a row amber: a parser that skipped one corrupt
                    # file of 362 finished its job.
                    row["state"] = "done"
                    row["note"] = self._summary_note(row) or "finished"
            self._paint_row(key)
            self._refresh_counts()
        except RuntimeError:
            pass                                      # dialog already closed

    def _apply_outcome(self, outcome):
        try:
            outcome = outcome or {}
            key = self._row_for(outcome.get("artifact"))
            if key is None:
                return
            row = self._rows[key]
            status = str(outcome.get("status") or "")
            row["state"] = _OUTCOME_STATE.get(status, row["state"])
            if outcome.get("records") is not None and status == "PARSED":
                row["records"] = outcome.get("records")
            note = _OUTCOME_NOTE.get(status)
            row["details"] = [str(d) for d in (outcome.get("details") or [])][:50]
            if status == "PARSED":
                # Green: the artifact was parsed. Skipped files and warning
                # lines are named in the note and the tooltip, not by the icon.
                note = self._summary_note(row) or "parsed"
                counts = self._counts_note(outcome)
                if counts:
                    note = counts if note == "parsed" else "%s; %s" % (counts, note)
            else:
                self._remember(row, outcome.get("message"), "OUTCOME")
                if status == "FAILED":
                    note = (outcome.get("message") or "failed")[:120]
                elif note and outcome.get("message"):
                    note = "%s - %s" % (note, str(outcome.get("message"))[:90])
            row["note"] = note or status.lower()
            if row["started"] is not None and row["elapsed"] is None:
                import time as _time
                row["elapsed"] = _time.monotonic() - row["started"]
            self._paint_row(key)
            self._refresh_counts()
        except RuntimeError:
            pass

    @staticmethod
    def _counts_note(outcome):
        """'12 new, 1,012 already present' from a Parse Status outcome."""
        ins, dup = outcome.get("inserted"), outcome.get("duplicates")
        if ins is None and dup is None:
            return ""
        parts = []
        if ins is not None:
            parts.append("{:,} new".format(max(0, int(ins))))
        if dup is not None:
            parts.append("{:,} already present".format(int(dup)))
        return ", ".join(parts)

    @staticmethod
    def _warning_note(row):
        n = row.get("warnings") or 0
        return ("%d warning%s" % (n, "" if n == 1 else "s")) if n else ""

    @staticmethod
    def _remember(row, text, level="WARNING"):
        """Keep the last 20 messages behind a row's warnings, for its tooltip."""
        text = ANSI_ESCAPE.sub("", str(text or "")).strip()
        if not text:
            return
        msgs = row.setdefault("messages", [])
        if msgs and msgs[-1][1] == text:
            return
        msgs.append((level or "WARNING", text[:400]))
        del msgs[:-20]

    @staticmethod
    def _summary_note(row):
        """'1 file skipped - hover for details' / '2 warnings - hover' / ''."""
        skipped = [d for d in row.get("details") or [] if "skipped" in d.lower()]
        n = row.get("warnings") or 0
        if skipped:
            return "%d file%s skipped - hover for details" % (
                len(skipped), "" if len(skipped) == 1 else "s")
        if n:
            return "%d warning%s - hover for details" % (n, "" if n == 1 else "s")
        return ""

    @staticmethod
    def _tooltip(row):
        """Rich-text tooltip naming what the warnings actually were."""
        import html as _html
        details = row.get("details") or []
        msgs = row.get("messages") or []
        if not details and not msgs:
            return _html.escape(row.get("note") or "")
        colour = {"ERROR": "#fca5a5", "OUTCOME": "#fde68a"}
        parts = ["<b>%s</b>" % _html.escape(row.get("label") or "")]
        if details:
            parts.append("<br><span style='color:#93c5fd'>Details (%d)</span>" % len(details))
            parts += ["<br>&nbsp;&bull; %s" % _html.escape(d[:300]) for d in details[:20]]
        if msgs:
            parts.append("<br><span style='color:#fde68a'>Messages (%d%s)</span>" % (
                len(msgs), ", last 20" if row.get("warnings", 0) > 20 else ""))
            parts += ["<br>&nbsp;<span style='color:%s'>%s</span>&nbsp; %s" % (
                colour.get(lvl, "#fde68a"), _html.escape(lvl.title() if lvl != "OUTCOME" else "Result"),
                _html.escape(t)) for lvl, t in msgs]
        return "<div style='max-width:640px'>%s</div>" % "".join(parts)

    def _apply_now(self, text):
        try:
            text = ANSI_ESCAPE.sub("", text or "").strip()
            if not text:
                return
            # One line: a long path is cut in the middle, keeping both ends.
            metrics = self.now_label.fontMetrics()
            width = max(200, self.now_label.width() - 24)
            shown = metrics.elidedText("Now: " + text, QtCore.Qt.ElideMiddle, width)
            self.now_label.setText(shown)
            self.now_label.setToolTip(text)
            self.now_label.show()
            self._log_dirty = True
        except RuntimeError:
            pass

    def _paint_row(self, key):
        row = self._rows[key]
        item = row["item"]
        # The icon is redrawn only when the state changes: events arrive up to
        # four times a second while a parser runs.
        if row.get("icon_state") != row["state"]:
            item.setIcon(0, _paint_status_icon(row["state"]))
            row["icon_state"] = row["state"]
        records = row["records"]
        item.setText(1, "{:,}".format(records) if isinstance(records, int) else "")
        elapsed = row["elapsed"]
        if elapsed is None and row["state"] == "running" and row["started"] is not None:
            # A running row shows its live time here too. It used to be
            # blanked on every event and restored by the next clock tick,
            # which is the flicker in the Time column.
            import time as _time
            elapsed = _time.monotonic() - row["started"]
        item.setText(2, self._fmt_elapsed(elapsed) if elapsed is not None else "")
        note = row["note"] or ""
        if row["state"] == "running" and row.get("warnings"):
            # Counted as they arrive; the icon stays blue until the outcome.
            note = "%s (%s - hover)" % (note.rstrip("."), self._warning_note(row))
        item.setText(3, note)
        colours = {"failed": "#fda4af", "warning": "#fde68a", "not_found": "#a5b4fc",
                   "skipped": "#94a3b8", "waiting": "#94a3b8"}
        colour = colours.get(row["state"], "#e2e8f0")
        if row["state"] in ("done", "running") and (row.get("details") or row.get("messages")):
            colour = "#e7c983"            # parsed, with something worth a hover
        item.setForeground(3, QtGui.QBrush(QtGui.QColor(colour)))
        tip = self._tooltip(row)
        item.setToolTip(0, tip)
        item.setToolTip(3, tip)

    def _refresh_counts(self):
        """The bar and its text follow the checklist unless a real count drives it."""
        if not self._rows:
            return
        total = len(self._rows)
        finished = sum(1 for r in self._rows.values()
                       if r["state"] not in ("waiting", "running"))
        if not getattr(self, "_has_real_count", False):
            pct = int(finished * 100 / total) if total else 0
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(pct)
            noun = "artifacts" if self._phase == "parsing" else "steps"
            self.progress_bar.setFormat("%d of %d %s (%d%%)" % (finished, total, noun, pct))
            self._taskbar("set_value", finished, total)

    def _eta_text(self, elapsed):
        """'~02:10 left' once two artifacts have finished, else ''."""
        if not self._rows:
            return ""
        total = len(self._rows)
        finished = sum(1 for r in self._rows.values()
                       if r["state"] not in ("waiting", "running"))
        if finished < 2 or finished >= total:
            return ""
        remaining = elapsed / finished * (total - finished)
        return "   ~%s left" % self._fmt_elapsed(remaining)

    def update_step(self, step_index, step_message):
        """Update the current step with a message"""
        if step_index < len(self.operation_steps):
            self.current_step = step_index
            self.add_log_message(f"Step {step_index + 1}: {step_message}")

            # Where a real count is already driving the bar, this stays out of
            # the way: the step index is the sender's own constant, and on the
            # parallel path it does not increase in order. The message still
            # reaches the log and the status line.
            if getattr(self, "_has_real_count", False):
                self.set_status_safe(step_message)
                return

            # Update progress if we have determinant steps
            if len(self.operation_steps) > 0:
                target_progress = int((step_index + 1) * 100 / len(self.operation_steps))
                
                # Smooth progress animation
                self.animate_progress_to(target_progress)
                
                # Update progress bar format
                self.progress_bar.setFormat(f"Step {step_index + 1}/{len(self.operation_steps)}: {target_progress}%")
                self._taskbar("set_percent", target_progress)
                
                # Force GUI update to show progress
                keep_alive()
    
    def update_progress_with_records(self, current_records, total_records, table_name):
        """Update progress bar with record count information
        
        Args:
            current_records (int): Number of records processed
            total_records (int): Total number of records
            table_name (str): Name of the table being processed
        """
        try:
            if total_records > 0:
                # Calculate percentage
                percentage = int((current_records / total_records) * 100)
                
                # Update progress bar
                if self.progress_bar.minimum() == 0 and self.progress_bar.maximum() == 0:
                    # Switch from indeterminate to determinate
                    self.progress_bar.setRange(0, 100)
                
                self.progress_bar.setValue(percentage)
                self.progress_bar.setFormat(f"{table_name}: {current_records}/{total_records} ({percentage}%)")
                
                # Add log message
                self.add_log_message(f"[Progress] {table_name}: {current_records}/{total_records} records")
                
                # Force GUI update
                keep_alive()
        except Exception as e:
            print(f"[LoadingDialog] Error updating progress: {e}")
                
    def animate_progress_to(self, target_value):
        """Set progress bar to target value without blocking animation"""
        # If we're in indeterminate mode, switch to determinate
        if self.progress_bar.minimum() == 0 and self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 100)

        self.progress_bar.setValue(target_value)
        keep_alive()
        
    def update_overall_progress(self, percentage, completed_steps, total_steps):
        """Update the progress bar with overall percentage across all parallel steps"""
        # If we're in indeterminate mode, switch to determinate
        if self.progress_bar.minimum() == 0 and self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 100)

        self.progress_bar.setValue(percentage)
        self.progress_bar.setFormat(f"Progress: {completed_steps}/{total_steps} tasks ({percentage}%)")
        self._taskbar("set_percent", percentage)
        keep_alive()

    def set_status(self, message):
        """Set the status line (thread-safe via signal).

        Safe to call from a worker thread — which is the point, since the
        parsers run inside FunctionWorker. Note that update_step() is NOT:
        it touches the progress bar and calls processEvents() directly.
        """
        self.status_signal.emit(message or "")

    def set_status_safe(self, message):
        """Apply the status line (called from the signal, on the GUI thread)."""
        if not message:
            self.status_label.hide()
            return
        self.status_label.setText(message)
        self.status_label.show()

    def add_log_message(self, message):
        """Add a message to the log (thread-safe via signal).

        Also filed in the case log (crow_eye.parsing -> parsers.log): what the
        investigator watched scroll past is on disk afterwards. It used to be
        display-only.
        """
        try:
            text = ANSI_ESCAPE.sub("", str(message or "")).strip()
            if text:
                from utils.parse_logging import line_level
                _dialog_log.log(line_level(text), text)
        except Exception:
            pass
        self._post_line(message)

    def _show_captured_line(self, message):
        """A line captured from stdout: shown only (it is already logged)."""
        self._post_line(message)

    _MAX_PENDING = 5000

    def _post_line(self, message):
        """Show a line now (GUI thread) or batch it (any other thread)."""
        if QtCore.QThread.currentThread() is self.thread():
            self._flush_lines()
            self.add_log_message_safe(message)
            return
        with self._line_lock:
            self._pending_lines.append(message)
            if len(self._pending_lines) > self._MAX_PENDING:
                drop = len(self._pending_lines) - self._MAX_PENDING
                del self._pending_lines[:drop]
                self._dropped_lines += drop
            if self._flush_scheduled:
                return
            self._flush_scheduled = True
        self._flush_signal.emit()

    def _flush_lines(self):
        """Append every batched line in one pass (GUI thread)."""
        with self._line_lock:
            lines, self._pending_lines = self._pending_lines, []
            dropped, self._dropped_lines = self._dropped_lines, 0
            self._flush_scheduled = False
        if not lines and not dropped:
            return
        try:
            self.log_display.setUpdatesEnabled(False)
            if dropped:
                self.add_log_message_safe("[Info] %d earlier line(s) not shown (they are in the case log)"
                                          % dropped)
            for line in lines:
                self.add_log_message_safe(line)
        finally:
            self.log_display.setUpdatesEnabled(True)

    def add_log_message_safe(self, message):
        """Add a message to the log display (called from signal)"""
        formatted_message = self.format_log_message(message)
        self._log_buffer.append(formatted_message)
        if self._line_matches(formatted_message):
            self.log_display.appendPlainText(formatted_message)
        self._log_lines += 1
        if not self.log_toggle.isHidden():
            self.log_toggle.setText(("Hide log (%d lines)" if self.log_toggle.isChecked()
                                     else "Show log (%d lines)") % self._log_lines)
        if self._log_follow.isChecked():
            scrollbar = self.log_display.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
        # Painted by the next frame even if the event loop is blocked.
        self._log_dirty = True

    # -- log toolbar -------------------------------------------------------------------
    def _build_log_toolbar(self):
        from collections import deque
        self._log_buffer = deque(maxlen=5000)
        self._log_level = "ALL"
        bar = QtWidgets.QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(8)
        ui_font, mono_font = _fonts()
        # Small pills, as on the website; a checked one fills with its colour.
        btn_qss = ("QPushButton { background: transparent; color: #94A3B8;"
                   " border: 1px solid rgba(255,255,255,0.10); border-radius: 12px;"
                   " padding: 0 13px; }"
                   " QPushButton:hover { color: #F8FAFC; border-color: %s; }"
                   " QPushButton:checked { color: %s; border-color: %s; background: %s; }")
        pill_font = _font(ui_font, 12, QtGui.QFont.DemiBold)
        self._log_level_btns = {}
        for key, label, colour, fill in (
                ("ALL", "All", "#A5B4FC", "rgba(99,102,241,0.16)"),
                ("WARNING", "Warnings", "#FBBF24", "rgba(251,191,36,0.12)"),
                ("ERROR", "Errors", "#FDA4AF", "rgba(244,63,94,0.14)")):
            b = QtWidgets.QPushButton(label)
            b.setObjectName("logLevel_" + key)
            b.setCheckable(True)
            b.setChecked(key == "ALL")
            b.setCursor(QtCore.Qt.PointingHandCursor)
            b.setFont(pill_font)
            b.setFixedHeight(26)
            b.setStyleSheet(btn_qss % (colour, colour, colour, fill))
            b.clicked.connect(lambda _c=False, k=key: self.set_log_level(k))
            self._log_level_btns[key] = b
            bar.addWidget(b)
        self._log_find = QtWidgets.QLineEdit()
        self._log_find.setObjectName("logFind")
        self._log_find.setPlaceholderText("Find in log...")
        self._log_find.setFont(_font(mono_font, 12))
        self._log_find.setFixedHeight(26)
        self._log_find.setStyleSheet(
            "QLineEdit { background: #0A0C10; color: #E2E8F0;"
            " border: 1px solid rgba(255,255,255,0.10); border-radius: 12px; padding: 0 12px; }"
            " QLineEdit:focus { border-color: #6366F1; }")
        self._log_find.returnPressed.connect(self._find_in_log)
        bar.addWidget(self._log_find, 1)
        self._log_follow = QtWidgets.QCheckBox("Follow")
        self._log_follow.setChecked(True)
        self._log_follow.setToolTip("Keep the newest line in view")
        self._log_follow.setFont(pill_font)
        self._log_follow.setStyleSheet("QCheckBox { color: #94A3B8; background: transparent; spacing: 6px; }")
        bar.addWidget(self._log_follow)
        copy = QtWidgets.QPushButton("Copy all")
        copy.setCursor(QtCore.Qt.PointingHandCursor)
        copy.setFont(pill_font)
        copy.setFixedHeight(26)
        copy.setStyleSheet(btn_qss % ("#6366F1", "#F8FAFC", "#6366F1", "transparent"))
        copy.clicked.connect(self._copy_log)
        bar.addWidget(copy)
        return bar

    def _line_matches(self, line):
        if self._log_level == "ALL":
            return True
        from ui.log_highlighter import level_of
        lvl = level_of(line)
        return lvl == "ERROR" if self._log_level == "ERROR" else lvl in ("ERROR", "WARNING")

    def set_log_level(self, level):
        """Show all lines, warnings and errors, or errors only."""
        self._log_level = level
        for key, btn in self._log_level_btns.items():
            btn.setChecked(key == level)
        self.log_display.setPlainText("\n".join(l for l in self._log_buffer if self._line_matches(l)))
        sb = self.log_display.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _find_in_log(self):
        text = self._log_find.text()
        if not text:
            return
        if not self.log_display.find(text):
            # Wrap around to the top.
            self.log_display.moveCursor(QtGui.QTextCursor.Start)
            self.log_display.find(text)
        self._log_follow.setChecked(False)

    def _copy_log(self):
        QApplication.clipboard().setText("\n".join(self._log_buffer))
        
    def format_log_message(self, message):
        """Format log messages with cyberpunk styling"""
        timestamp = QtCore.QTime.currentTime().toString("hh:mm:ss.zzz")
        
        # Color code based on message content with cyberpunk colors
        # Check for actual errors (not just Python logging level names)
        is_error = (
            "[Error]" in message or 
            "Error:" in message or 
            " - ERROR - " in message or  # Python logging format
            "failed" in message.lower() and "may have failed" not in message.lower()
        )
        
        is_warning = (
            "[Warning]" in message or 
            "Warning:" in message or 
            " - WARNING - " in message or  # Python logging format
            "warning" in message.lower()
        )
        
        # Prioritize specific artifact tags over generic error detection
        if "[MFT]" in message or "[Offline MFT]" in message:
            color = "#44ff44"  # Green for MFT
            prefix = "[MFT]"
        elif "[USN]" in message or "[Offline USN]" in message:
            color = "#44ff44"  # Green for USN
            prefix = "[USN]"
        elif "[Registry]" in message:
            color = "#ff00ff"
            prefix = "[REG]"
        elif "[LNK]" in message or "[JumpList]" in message:
            color = "#00aaff"
            prefix = "[LNK]"
        elif "[Prefetch]" in message:
            color = "#ffff00"
            prefix = "[PREF]"
        elif "[Logs]" in message:
            color = "#ff8800"
            prefix = "[LOG]"
        elif is_error:
            color = "#ff4444"
            prefix = "[ERR]"
        elif is_warning:
            color = "#ffaa00"
            prefix = "[WARN]"
        elif "[Success]" in message or "Success" in message or "completed" in message.lower() or "successfully" in message.lower():
            color = "#44ff44"
            prefix = "[OK]"
        elif "Processing:" in message or "%" in message:
            color = "#aaaaff"
            prefix = "[PROC]"
        else:
            color = "#00ff00"
            prefix = "[INFO]"
            
        # Plain text in fixed columns - time, level, source tag, message - for
        # the highlighter to colour. (It was HTML spans, which the level filter
        # and the find box could not see through.)
        level = {"[ERR]": "ERROR", "[WARN]": "WARN", "[OK]": "OK", "[PROC]": "PROC"}.get(prefix, "INFO")
        if prefix in ("[MFT]", "[USN]", "[REG]", "[LNK]", "[PREF]", "[LOG]"):
            level = "ERROR" if is_error else ("WARN" if is_warning else "INFO")
            tag = prefix
        else:
            tag = ""
        text = ANSI_ESCAPE.sub("", str(message)).replace("\r", " ").replace("\n", " ").strip()
        return "%s  %-5s  %-6s %s" % (timestamp, level, tag, text)
        
    def start_log_capture(self):
        """Start capturing stdout/stderr"""
        self.log_capture.__enter__()
        
    def stop_log_capture(self):
        """Stop capturing stdout/stderr"""
        self.log_capture.__exit__(None, None, None)
        
    def _end_taskbar(self):
        """Release the taskbar indicator, once, however this dialog ends."""
        if self._taskbar_open:
            self._taskbar_open = False
            self._taskbar("end")

    def closeEvent(self, event):
        """Handle dialog close event"""
        # Every dismissal in Crow-Eye today is dialog.close(), including the
        # QTimer.singleShot(..., dialog.close) ones - and a cancelled parse
        # never sends its worker a "DONE", so anything that waited for the
        # worker would leave the taskbar stuck at whatever it last showed.
        self._end_taskbar()
        self._stop_clock()
        self.stop_log_capture()
        super().closeEvent(event)
        self._emit_closed()

    def _emit_closed(self):
        if not getattr(self, "_closed_sent", False):
            self._closed_sent = True
            self.closed.emit()

    def done(self, result):
        """QDialog.done() - and so accept() and reject() - hides the dialog
        WITHOUT sending a closeEvent.

        Nothing dismisses a LoadingDialog that way at the moment, which is the
        only reason closeEvent alone was enough. This is here so the first
        caller that reaches for accept() does not leave a percentage sitting in
        the taskbar for the rest of the session, with nothing on screen to
        explain it.
        """
        self._end_taskbar()
        self._stop_clock()
        self.stop_log_capture()
        super().done(result)
        self._emit_closed()
        
    def show_completion(self, message="OPERATION COMPLETED SUCCESSFULLY", ok=True):
        """Show the closing line. ``ok=False`` says the run finished with
        problems (or was cancelled) instead of claiming success."""
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat("COMPLETE" if ok else "FINISHED")
        self.set_status_safe(message)
        self.now_label.hide()                 # nothing is being read any more
        self._taskbar("set_percent", 100)
        # Freeze the clock on the total: "Completed in 02:13".
        try:
            import time as _time
            if getattr(self, "_clock_ref", None) is not None and not self._clock_frozen:
                self._clock_frozen = True
                self.elapsed_label.setText(
                    "Completed in " + self._fmt_elapsed(_time.monotonic() - self._clock_t0))
        except Exception:
            pass
        
        # Add final log message
        self.add_log_message(("[Success] %s" if ok else "[Warning] %s") % message)
        
        keep_alive()


if __name__ == "__main__":
    # Test the dialog
    app = QApplication(sys.argv)
    dialog = LoadingDialog()
    dialog.show()
    
    # Simulate some operations
    import time
    def simulate_work():
        steps = [
            "Initializing system components...",
            "Loading forensic modules...", 
            "Connecting to databases...",
            "Preparing analysis engines...",
            "Ready for operation"
        ]
        
        dialog.set_steps(steps)
        for i, step in enumerate(steps):
            dialog.add_log_message(f"Step {i+1}: {step}")
            time.sleep(1)
            
        dialog.show_completion()
    
    QTimer.singleShot(1000, simulate_work)
    sys.exit(app.exec_())