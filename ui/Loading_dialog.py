# type: ignore
# pylint: disable-all
"""
Dark cyberpunk loading dialog with real-time log display for the Crow Eye application.
"""

import sys
import os
import io
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import QTimer, pyqtSignal
from PyQt5.QtWidgets import QApplication

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
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        self.last_progress_line = None  # Track last progress bar update
        
    def __enter__(self):
        # Store original streams as attributes on the LogCapture object
        # This allows parsers to detect and bypass log capture for performance
        sys.stdout = self
        sys.stderr = self
        # Expose original streams as attributes for detection
        self.original_stdout_ref = self.original_stdout
        self.original_stderr_ref = self.original_stderr
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stdout = self.original_stdout
        sys.stderr = self.original_stderr
    
    def write(self, text):
        # Write to original stdout/stderr
        self.original_stdout.write(text)
        
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
    
    def flush(self):
        self.original_stdout.flush()


class LoadingDialog(QtWidgets.QDialog):
    """Dark cyberpunk loading dialog with real-time log display and glow effects"""
    
    log_signal = pyqtSignal(str)  # Signal for thread-safe log updates
    cancelled = pyqtSignal()      # Signal emitted when cancel button is clicked
    
    def __init__(self, title="CROW EYE SYSTEM", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Crow Eye - Processing")
        
        # Set Crow Eye icon for the dialog window. Use QIcon(path) so Qt loads all embedded
        # .ico sizes (16..256) and stays sharp; load from the on-disk (freshly regenerated)
        # icon via get_resource_path rather than the stale compiled ':/Icons/CrowEye.ico'.
        try:
            from utils.path_utils import get_resource_path
            self.setWindowIcon(QtGui.QIcon(get_resource_path("GUI Resources", "CrowEye.ico")))
        except Exception:
            pass  # Fallback if icon resource is not available
        
        # NOTE: deliberately NOT WindowStaysOnTopHint. The dialog stays modal (below)
        # so it sits above the main window and blocks the half-loaded UI, but it must
        # NOT force itself above a *newer* modal QMessageBox — otherwise any dialog
        # shown during a load gets trapped behind the loading screen and freezes it.
        self.setWindowFlags(QtCore.Qt.Dialog | QtCore.Qt.FramelessWindowHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setModal(True)
        
        # Dialog properties
        self.title_text = title
        self.operation_steps = []
        self.current_step = 0
        self._is_cancelled = False
        
        # Animation properties - cyberpunk glow effects
        self.glow_opacity = 0.0
        self.glow_direction = 1
        
        # Setup UI
        self.setup_ui()
        self.setup_animations()
        
        # Connect log signal for thread-safe updates
        self.log_signal.connect(self.add_log_message_safe)
        
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
        
        # Logo - centered with minimal container
        logo_container = QtWidgets.QHBoxLayout()
        logo_container.addStretch(1)
        
        # Setup logo
        self.setup_logo(logo_container)
        
        logo_container.addStretch(1)
        content_layout.addLayout(logo_container)
        
        # Small gap
        content_layout.addSpacing(10)
        
        # Progress bar - directly added
        self.progress_bar = QtWidgets.QProgressBar()
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
        self.center_on_screen()
        # Without WindowStaysOnTopHint, raise once so the frameless dialog reliably
        # appears in front of the main window when shown.
        self.raise_()
        
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
                ":/Icons/Crow-Eye.png",
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
                    ":/Icons/CrowEye.ico",
                    os.path.join(base_dir, "GUI Resources", "CrowEye.ico"),
                    "GUI Resources/CrowEye.ico",
                    "../GUI Resources/CrowEye.ico",
                ]
                for path in ico_candidates:
                    try:
                        ico = QtGui.QIcon(path)
                        if not ico.isNull():
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
            
            # Update progress if we have determinant steps
            if len(self.operation_steps) > 0:
                target_progress = int((step_index + 1) * 100 / len(self.operation_steps))
                
                # Smooth progress animation
                self.animate_progress_to(target_progress)
                
                # Update progress bar format
                self.progress_bar.setFormat(f"Step {step_index + 1}/{len(self.operation_steps)}: {target_progress}%")
                
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
        QApplication.processEvents()

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
        
    def closeEvent(self, event):
        """Handle dialog close event"""
        self.stop_log_capture()
        super().closeEvent(event)
        
    def show_completion(self, message="OPERATION COMPLETED SUCCESSFULLY"):
        """Show completion message"""
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat("COMPLETE")
        
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