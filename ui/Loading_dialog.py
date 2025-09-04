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
        
    def __enter__(self):
        sys.stdout = self
        sys.stderr = self
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stdout = self.original_stdout
        sys.stderr = self.original_stderr
    
    def write(self, text):
        # Write to original stdout/stderr
        self.original_stdout.write(text)
        
        # Also send to log display if it's meaningful content
        if text.strip():
            self.log_display_callback(text.strip())
    
    def flush(self):
        self.original_stdout.flush()


class LoadingDialog(QtWidgets.QDialog):
    """Dark cyberpunk loading dialog with real-time log display and glow effects"""
    
    log_signal = pyqtSignal(str)  # Signal for thread-safe log updates
    
    def __init__(self, title="CROW EYE SYSTEM", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Crow Eye - Processing")
        
        # Set Crow Eye icon for the dialog window
        try:
            icon = QtGui.QIcon()
            icon.addPixmap(QtGui.QPixmap(":/Icons/CrowEye.ico"), QtGui.QIcon.Normal, QtGui.QIcon.Off)
            self.setWindowIcon(icon)
        except Exception:
            pass  # Fallback if icon resource is not available
        
        self.setWindowFlags(QtCore.Qt.WindowStaysOnTopHint | QtCore.Qt.FramelessWindowHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setModal(True)
        
        # Dialog properties
        self.title_text = title
        self.operation_steps = []
        self.current_step = 0
        
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
        self.setFixedSize(800, 650)
        
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
                color: #00ffff;
                font-weight: bold;
                text-align: center;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0,
                                          stop: 0 #007acc, stop: 1 #00ffff);
                border-radius: 6px;
                margin: 1px;
            }
        """)
        self.progress_bar.setFixedHeight(35)
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
        
        # Add backdrop to main
        main_layout.addWidget(self.backdrop)
        self.setLayout(main_layout)
        
        # Center the dialog
        self.center_on_screen()
        
    def setup_logo(self, layout):
        """Setup logo with comprehensive fallback paths"""
        try:
            self.icon_label = QtWidgets.QLabel()
            self.icon_label.setFixedSize(200, 200)  # Clean 200x200 size
            icon_pixmap = None
            
            # Enhanced icon loading with multiple fallback paths
            icon_paths = [
                ":/Icons/CrowEye.ico",  # Qt resource (if compiled)
                "GUI Resources/CrowEye.ico",  # Relative path
                "GUI Resources/CrowEye.jpg",  # Alternative format
                "../GUI Resources/CrowEye.ico",  # Parent directory
                "../GUI Resources/CrowEye.jpg",  # Parent directory alternative
                os.path.join(os.path.dirname(os.path.dirname(__file__)), "GUI Resources", "CrowEye.ico"),  # Absolute path
                os.path.join(os.path.dirname(os.path.dirname(__file__)), "GUI Resources", "CrowEye.jpg")   # Absolute path alternative
            ]
            
            for path in icon_paths:
                try:
                    print(f"Trying to load icon from: {path}")  # Debug output
                    icon_pixmap = QtGui.QPixmap(path)
                    if icon_pixmap and not icon_pixmap.isNull():
                        print(f"Successfully loaded icon from: {path}")  # Debug output
                        break
                    else:
                        print(f"Failed to load icon from: {path} (null pixmap)")  # Debug output
                except Exception as ex:
                    print(f"Exception loading icon from {path}: {ex}")  # Debug output
                    continue
            
            if icon_pixmap and not icon_pixmap.isNull():
                # Scale icon to 190x190 for clean appearance
                scaled_pixmap = icon_pixmap.scaled(190, 190, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
                self.icon_label.setPixmap(scaled_pixmap)
                self.icon_label.setStyleSheet(CrowEyeStyles.LOADING_DIALOG_ICON)
                self.icon_label.setAlignment(QtCore.Qt.AlignCenter)
                self.icon_label.setToolTip("Crow Eye Digital Forensics Tool")
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
        
    def update_glow(self):
        """Update the subtle glow effect on the title"""
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
                text-transform: uppercase;
                letter-spacing: 3px;
                padding: 5px 20px 5px 20px;
                background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0,
                                          stop: 0 rgba(0, 255, 255, 0.1),
                                          stop: 0.5 {glow_color},
                                          stop: 1 rgba(0, 255, 255, 0.1));
                border: 2px solid rgba(0, 255, 255, 0.8);  /* Darker border */
                border-radius: 10px;
            }}
        """)
        

        
    def animate_progress_text(self):
        """Animate the progress bar text"""
        self.progress_dots = (self.progress_dots + 1) % 4
        dots = "." * self.progress_dots
        spaces = " " * (3 - self.progress_dots)
        self.progress_bar.setFormat(f"PROCESSING{dots}{spaces}")
        
    def center_on_screen(self):
        """Center the dialog on the screen"""
        screen = QApplication.desktop().screenGeometry()
        size = self.geometry()
        self.move((screen.width() - size.width()) // 2,
                 (screen.height() - size.height()) // 2)
                 
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
                
    def animate_progress_to(self, target_value):
        """Smoothly animate progress bar to target value"""
        current_value = self.progress_bar.value()
        
        # If we're in indeterminate mode, switch to determinate
        if self.progress_bar.minimum() == 0 and self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 100)
            current_value = 0
            
        # Animate smoothly to target
        if current_value < target_value:
            for i in range(current_value, target_value + 1, max(1, (target_value - current_value) // 10)):
                self.progress_bar.setValue(i)
                QApplication.processEvents()
                import time
                time.sleep(0.02)  # Small delay for smooth animation
        else:
            self.progress_bar.setValue(target_value)
        

        

        

        
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
        
        # Process events to ensure UI updates
        QApplication.processEvents()
        
    def format_log_message(self, message):
        """Format log messages with cyberpunk styling"""
        timestamp = QtCore.QTime.currentTime().toString("hh:mm:ss.zzz")
        
        # Color code based on message content with cyberpunk colors
        if "[Error]" in message or "Error" in message or "failed" in message.lower():
            color = "#ff4444"
            prefix = "[ERR]"
        elif "[Warning]" in message or "Warning" in message or "warning" in message.lower():
            color = "#ffaa00"
            prefix = "[WARN]"
        elif "[Success]" in message or "Success" in message or "completed" in message.lower():
            color = "#44ff44"
            prefix = "[OK]"
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