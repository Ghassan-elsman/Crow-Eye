# type: ignore
# pylint: disable-all
"""
Dark cyberpunk loading dialog with real-time log display for the Crow Eye application.
"""

import sys
import os
import io
import re
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


class LogCapture:
    """Capture stdout and stderr for log display"""
    
    def __init__(self, log_display_callback):
        self.log_display_callback = log_display_callback
        # Captured at ENTER, not here: this object is built with the dialog and
        # may be entered much later, by which time a case may have been opened
        # and utils.logging_setup may have put its console tee in place. Holding
        # a stream from construction time meant restoring the wrong one.
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        self.last_progress_line = None  # Track last progress bar update

    def __enter__(self):
        # Whatever is in place right now is what gets restored, and what gets
        # written through - so the case's console.log tee stays in the chain
        # instead of being cut out of it.
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
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
        if sys.stdout is self:
            sys.stdout = self.original_stdout
        if sys.stderr is self:
            sys.stderr = self.original_stderr
    
    def write(self, text):
        # Write to original stdout/stderr — unstripped, so a real terminal
        # still gets its colours.
        self.original_stdout.write(text)

        # The display renders HTML, so escape codes have to come out here.
        text = ANSI_ESCAPE.sub('', text)

        # Filter out progress bar updates (lines starting with carriage return or containing progress bars)
        if text.strip():
            # Skip progress bar lines (they contain █ or ░ characters and percentage)
            if '█' in text or '░' in text or ('\r' in text and '%' in text):
                # This is a progress bar update - only show the final one
                self.last_progress_line = text.strip()
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
    """Dark cyberpunk loading dialog with real-time log display and glow effects"""
    
    log_signal = pyqtSignal(str)     # Signal for thread-safe log updates
    status_signal = pyqtSignal(str)  # Same, for the status line
    cancelled = pyqtSignal()      # Signal emitted when cancel button is clicked
    
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
        # Set once a real (completed, total) count reaches the bar; see
        # update_task_progress and _animate_dots.
        self._has_real_count = False
        self._phase = phase if phase in ("parsing", "loading") else "loading"
        self._taskbar_open = False
        
        # Animation properties - cyberpunk glow effects
        self.glow_opacity = 0.0
        self.glow_direction = 1
        
        # Setup UI
        self.setup_ui()
        self.setup_animations()
        
        # Connect log signal for thread-safe updates
        self.log_signal.connect(self.add_log_message_safe)
        self.status_signal.connect(self.set_status_safe)
        
        # Log capture
        self.log_capture = LogCapture(self.add_log_message)
        
    def setup_ui(self):
        """Setup clean, single-dialog UI with no spacing above title"""
        # Set dialog size
        self.setFixedSize(800, 720) # Increased height to accommodate cancel button
        
        # Single main layout with no margins
        main_layout = QtWidgets.QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Single backdrop frame
        self.backdrop = QtWidgets.QFrame()
        self.backdrop.setStyleSheet(CrowEyeStyles.LOADING_DIALOG_BACKDROP)
        
        # Single content layout with minimal margins
        content_layout = QtWidgets.QVBoxLayout(self.backdrop)
        content_layout.setContentsMargins(20, 5, 20, 20)  # Minimal top margin
        content_layout.setSpacing(5)  # Minimal spacing
        
        # Title - directly added with no container
        self.title_label = QtWidgets.QLabel(self.title_text)
        self.title_label.setStyleSheet(CrowEyeStyles.LOADING_DIALOG_TITLE)
        self.title_label.setAlignment(QtCore.Qt.AlignCenter)
        self.title_label.setFixedHeight(80)
        content_layout.addWidget(self.title_label)

        # Status line — what is happening right now, as opposed to the title,
        # which says what the dialog is. Two places in Crow Eye.py already look
        # for a QLabel named "statusLabel" to apply CrowEyeStyles.OVERLAY_STATUS
        # to; the widget had never been added, so both were quietly doing
        # nothing. Hidden until something has a status to report, so a run that
        # never sets one looks exactly as it did before.
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setAlignment(QtCore.Qt.AlignCenter)
        self.status_label.setWordWrap(True)
        # A default look of its own. Unstyled, it inherited the backdrop's
        # QFrame border and gradient (QLabel is a QFrame) and drew black text
        # in a cyan box - the live parse never applies OVERLAY_STATUS.
        self.status_label.setStyleSheet(
            "QLabel { color: #7dd3fc; font-family: 'Consolas', 'Courier New', monospace;"
            " font-size: 13px; font-weight: bold; background: transparent; border: none;"
            " padding: 2px; }")
        self.status_label.hide()
        content_layout.addWidget(self.status_label)
        
        # Logo - centered with minimal container
        logo_container = QtWidgets.QHBoxLayout()
        logo_container.addStretch(1)
        
        # Setup logo
        self.setup_logo(logo_container)
        
        logo_container.addStretch(1)
        content_layout.addLayout(logo_container)
        
        # Small gap
        content_layout.addSpacing(10)
        
        # Progress bar - directly added. Animated: a light sweep keeps moving
        # between real updates, so a long step never looks like a freeze.
        self.progress_bar = AnimatedProgressBar(accent="#00FFFF")
        self.progress_bar.setRange(0, 0)  # Start as indeterminate
        self.progress_bar.setStyleSheet(CrowEyeStyles.LOADING_DIALOG_PROGRESS + """
            QProgressBar {
                border: 2px solid #00ffff;
                border-radius: 8px;
                background-color: #1a1a1a;
                color: #ffffff;
                font-weight: 900;
                font-size: 14px;
                text-align: center;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0,
                                          stop: 0 #007acc, stop: 1 #00ffff);
                border-radius: 6px;
                margin: 1px;
            }
        """)
        self.progress_bar.setFixedHeight(40)
        content_layout.addWidget(self.progress_bar)

        # Elapsed clock under the bar: proof of life even when no step has
        # finished for minutes. Ticks on every animation frame (see
        # _on_frame), including frames pumped while the GUI thread is busy.
        self.elapsed_label = QtWidgets.QLabel("Elapsed 00:00")
        self.elapsed_label.setObjectName("elapsedLabel")
        self.elapsed_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.elapsed_label.setStyleSheet(
            # border: none - QLabel is a QFrame, so the backdrop's QFrame rule
            # would otherwise draw its cyan border around this label.
            "QLabel { color: #7dd3fc; font-family: 'Consolas', 'Courier New', monospace;"
            " font-size: 12px; background: transparent; border: none;"
            " padding: 2px 4px 0 0; }")
        content_layout.addWidget(self.elapsed_label)

        # Small gap
        content_layout.addSpacing(10)
        
        # Log display - directly added
        self.log_display = QtWidgets.QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setStyleSheet(CrowEyeStyles.LOADING_DIALOG_LOG_DISPLAY)
        self.log_display.setMinimumHeight(180)
        self.log_display.setMaximumHeight(220)
        content_layout.addWidget(self.log_display)
        
        # Cancel Button
        self.cancel_button = QtWidgets.QPushButton("CANCEL OPERATION")
        self.cancel_button.setCursor(QtCore.Qt.PointingHandCursor)
        self.cancel_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 68, 68, 0.1);
                color: #ff4444;
                border: 2px solid #ff4444;
                border-radius: 6px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 14px;
                font-weight: bold;
                padding: 10px;
                margin-top: 10px;
            }
            QPushButton:hover {
                background-color: #ff4444;
                color: #ffffff;
            }
            QPushButton:pressed {
                background-color: #cc0000;
                border-color: #cc0000;
            }
        """)
        self.cancel_button.clicked.connect(self.on_cancel_clicked)
        content_layout.addWidget(self.cancel_button)
        
        # Add backdrop to main
        main_layout.addWidget(self.backdrop)
        self.setLayout(main_layout)
        
    def on_cancel_clicked(self):
        """Handle cancel button click"""
        self._is_cancelled = True
        self.cancel_button.setEnabled(False)
        self.cancel_button.setText("CANCELLING...")
        self.add_log_message("[Warning] Cancellation requested by user...")
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
                text = "Elapsed " + self._fmt_elapsed(now - self._clock_t0)
                if text != self._clock_text:
                    self._clock_text = text
                    self.elapsed_label.setText(text)
                    self.elapsed_label.repaint()
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
        
    def setup_logo(self, layout):
        """Setup logo with comprehensive fallback paths"""
        try:
            self.icon_label = QtWidgets.QLabel()
            icon_pixmap = None

            # Render at 2x for HiDPI sharpness, then downscale to display size.
            device_ratio = self.devicePixelRatioF() if hasattr(self, "devicePixelRatioF") else 1.0
            target_size = 200  # icon edge length in logical pixels
            border_px = 4      # must match LOADING_DIALOG_ICON border width (premium thicker border)
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

                # Soft cyan halo around the frame (drop shadow with no offset).
                self.logo_halo = QtWidgets.QGraphicsDropShadowEffect(self.icon_label)
                self.logo_halo.setColor(QtGui.QColor(0, 255, 255, 180))
                self.logo_halo.setBlurRadius(35)
                self.logo_halo.setOffset(0, 0)
                self.icon_label.setGraphicsEffect(self.logo_halo)

                layout.addWidget(self.icon_label)
            else:
                print("No valid icon found, using fallback placeholder")  # Debug output
                # Professional fallback
                placeholder = QtWidgets.QLabel("CROW EYE\nFORENSICS")
                placeholder.setFixedSize(200, 200)
                placeholder.setStyleSheet("""
                    QLabel {
                        color: #ffffff;
                        font-size: 18px;
                        font-weight: bold;
                        font-family: 'Arial', sans-serif;
                        background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1,
                                                  stop: 0 rgba(70, 130, 180, 0.8),
                                                  stop: 0.5 rgba(100, 149, 237, 0.9),
                                                  stop: 1 rgba(70, 130, 180, 0.8));
                        border: 2px solid #4682B4;
                        border-radius: 15px;
                        padding: 20px;
                    }
                """)
                placeholder.setAlignment(QtCore.Qt.AlignCenter)
                placeholder.setWordWrap(True)
                layout.addWidget(placeholder)
                
        except Exception as e:
            print(f"Icon loading exception: {e}")  # Enhanced debug output
            # Debug placeholder
            debug_label = QtWidgets.QLabel("LOGO\nUNAVAILABLE")
            debug_label.setFixedSize(200, 200)
            debug_label.setStyleSheet("""
                QLabel {
                    color: #2F4F4F;
                    font-size: 16px;
                    font-weight: bold;
                    font-family: 'Arial', sans-serif;
                    background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1,
                                              stop: 0 rgba(211, 211, 211, 0.8),
                                              stop: 1 rgba(169, 169, 169, 0.8));
                    border: 2px solid #A9A9A9;
                    border-radius: 10px;
                    padding: 20px;
                }
            """)
            debug_label.setAlignment(QtCore.Qt.AlignCenter)
            debug_label.setWordWrap(True)
            layout.addWidget(debug_label)

        
    def setup_animations(self):
        """Setup cyberpunk animations with glow effects"""
        # Glow animation for title
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
        """Update the subtle glow effect on the title and logo border"""
        self.glow_opacity += 0.03 * self.glow_direction  # Slower animation
        
        if self.glow_opacity >= 0.6:  # Lower maximum opacity
            self.glow_opacity = 0.6
            self.glow_direction = -1
        elif self.glow_opacity <= 0.2:  # Higher minimum opacity
            self.glow_opacity = 0.2
            self.glow_direction = 1
            
        # Update title with subtle glow - darker colors
        glow_color = f"rgba(0, 255, 255, {self.glow_opacity * 0.5})"  # Reduced intensity
        self.title_label.setStyleSheet(f"""
            QLabel {{
                color: #00ffff;
                font-size: 32px;
                font-weight: bold;
                font-family: 'Consolas', 'Courier New', monospace;
                padding: 5px 20px 5px 20px;
                background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0,
                                          stop: 0 rgba(0, 255, 255, 0.1),
                                          stop: 0.5 {glow_color},
                                          stop: 1 rgba(0, 255, 255, 0.1));
                border: 2px solid rgba(0, 255, 255, 0.8);  /* Darker border */
                border-radius: 10px;
            }}
        """)
        
        # Update logo halo (dynamic breathing glow effect)
        if hasattr(self, 'logo_halo') and self.logo_halo:
            try:
                # Oscillate blur radius between 25 and 45
                current_blur = int(25 + (self.glow_opacity - 0.2) * 50)
                self.logo_halo.setBlurRadius(current_blur)
                
                # Oscillate drop shadow opacity between 120 and 220
                alpha = int(120 + (self.glow_opacity - 0.2) * 250)
                self.logo_halo.setColor(QtGui.QColor(0, 255, 255, alpha))
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
        if getattr(self, "_has_real_count", False):
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
        QApplication.processEvents()
        
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
                QApplication.processEvents()
    
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
                QApplication.processEvents()
        except Exception as e:
            print(f"[LoadingDialog] Error updating progress: {e}")
                
    def animate_progress_to(self, target_value):
        """Set progress bar to target value without blocking animation"""
        # If we're in indeterminate mode, switch to determinate
        if self.progress_bar.minimum() == 0 and self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 100)

        self.progress_bar.setValue(target_value)
        QApplication.processEvents()
        
    def update_overall_progress(self, percentage, completed_steps, total_steps):
        """Update the progress bar with overall percentage across all parallel steps"""
        # If we're in indeterminate mode, switch to determinate
        if self.progress_bar.minimum() == 0 and self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 100)

        self.progress_bar.setValue(percentage)
        self.progress_bar.setFormat(f"Progress: {completed_steps}/{total_steps} tasks ({percentage}%)")
        self._taskbar("set_percent", percentage)
        QApplication.processEvents()

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
        """Add a message to the log (thread-safe via signal)"""
        self.log_signal.emit(message)
        
    def add_log_message_safe(self, message):
        """Add a message to the log display (called from signal)"""
        # Format the message with professional styling
        formatted_message = self.format_log_message(message)
        
        # Add to log display
        self.log_display.append(formatted_message)
        
        # Auto-scroll to bottom
        scrollbar = self.log_display.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        # Painted by the next frame even if the event loop is blocked.
        self._log_dirty = True
        
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
            
        return f'<span style="color: #666666;">{timestamp}</span> <span style="color: {color}; font-weight: bold;">{prefix}</span> <span style="color: {color};">{message}</span>'
        
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
        super().done(result)
        
    def show_completion(self, message="OPERATION COMPLETED SUCCESSFULLY"):
        """Show completion message"""
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat("COMPLETE")
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
        self.add_log_message(f"[Success] {message}")
        
        QApplication.processEvents()


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