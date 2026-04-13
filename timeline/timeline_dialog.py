"""
Timeline Dialog - Main window for forensic timeline visualization using React.

This module provides the main dialog window for the timeline visualization feature,
integrating the React frontend inside a QWebEngineView and establishing a QWebChannel
bridge to serve forensic database queries.
"""

import os
import json
import logging
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QMessageBox
from PyQt5.QtCore import Qt, pyqtSignal, QUrl
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWebChannel import QWebChannel

from timeline.timeline_bridge import TimelineBridge
from timeline.utils.error_handler import ErrorHandler
from timeline.utils.loading_indicator import LoadingOverlay
from ui.row_detail_dialog import RowDetailDialog

# Configure logger
logger = logging.getLogger(__name__)


class TimelineDialog(QDialog):
    """
    Main timeline visualization dialog window (React Version).
    
    Hosts the Vite React Single-Page Application (SPA) inside a QWebEngineView
    and exposes the Python TimelineBridge to the JavaScript context via QWebChannel.
    """
    
    event_double_clicked = pyqtSignal(dict)  # Emits event data for navigation
    
    def __init__(self, parent=None):
        """
        Initialize the timeline dialog.
        
        Args:
            parent: Parent widget (main Crow Eye window)
        """
        super().__init__(parent)
        
        self.main_window = parent
        self.case_directory = None
        
        # UI components
        self.web_view = None
        self.web_channel = None
        self.bridge = None
        self.loading_overlay = None
        
        # Initialize error handler
        self.error_handler = ErrorHandler(self)
        
        try:
            self.case_directory = self._get_case_directory()
            self._init_ui()
            self._setup_bridge()
            self._load_react_app()
        except ValueError as e:
            self.error_handler.handle_error(e, "loading case", show_dialog=True)
        except Exception as e:
            self.error_handler.handle_error(e, "initializing timeline", show_dialog=True)
            
    def _init_ui(self):
        """Initialize the user interface components."""
        self.setWindowTitle("Forensic Timeline Visualization")
        self.setMinimumSize(1200, 800)
        # Enable standard minimize/maximize/close buttons on the dialog title bar
        self.setWindowFlags(
            Qt.Window |
            Qt.WindowMinimizeButtonHint |
            Qt.WindowMaximizeButtonHint |
            Qt.WindowCloseButtonHint
        )
        self.showMaximized()
        
        # Apply dark theme base
        self.setStyleSheet("""
            QDialog {
                background-color: #0A0E1A;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Create QWebEngineView to hold React App
        self.web_view = QWebEngineView(self)
        # Forward JS console messages to Python terminal
        self.web_view.page().javaScriptConsoleMessage = self._handle_console_message
        
        # Hide the web view initially
        self.web_view.hide()
        
        layout.addWidget(self.web_view)
        
        # Add loading overlay
        self.loading_overlay = LoadingOverlay(self)
        self.loading_overlay.set_message("Initializing Forensic Timeline...")
        
    def resizeEvent(self, event):
        """Resize the overlay when the dialog resizes."""
        super().resizeEvent(event)
        if hasattr(self, 'loading_overlay') and self.loading_overlay:
            self.loading_overlay.resize(event.size())
            
    def _setup_bridge(self):
        """Setup QWebChannel bridge for Python <-> JavaScript communication."""
        self.web_channel = QWebChannel(self.web_view.page())
        
        # Instantiate the bridge
        self.bridge = TimelineBridge(self.case_directory, parent=self)

        # Connect the detail dialog signal
        self.bridge.show_event_detail.connect(self._open_event_detail_dialog)

        # Register the bridge object. In JS this will be accessible as `channel.objects.bridge`.
        self.web_channel.registerObject("bridge", self.bridge)        
        # Attach the channel to the web page
        self.web_view.page().setWebChannel(self.web_channel)
        
    def _load_react_app(self):
        """Load the built React index.html file into the web view."""
        # Calculate path to the built React app
        base_dir = os.path.dirname(os.path.abspath(__file__))
        react_build_path = os.path.join(base_dir, 'react-timeline', 'dist', 'index.html')
        
        if not os.path.exists(react_build_path):
            QMessageBox.critical(self, "Error", 
                                 f"React timeline build not found at:\n{react_build_path}\n\n"
                                 f"Please run 'npm run build' inside timeline/react-timeline/")
            return
            
        url = QUrl.fromLocalFile(react_build_path)
        logger.info(f"Loading React Timeline: {url.toString()}")
        
        self.web_view.loadFinished.connect(self._on_load_finished)
        self.web_view.load(url)
        
    def _on_load_finished(self, ok):
        """Called when the web view finishes loading the React app."""
        if ok:
            if hasattr(self, 'loading_overlay') and self.loading_overlay:
                self.loading_overlay.hide()
            self.web_view.show()
        else:
            self.error_handler.handle_error(Exception("Failed to load React Timeline HTML"), "loading web view", show_dialog=True)
        
    def _handle_console_message(self, level, message, line, source):
        """Forward JavaScript console messages to Python logging."""
        level_map = {0: 'INFO', 1: 'WARN', 2: 'ERROR'}
        level_name = level_map.get(level, 'LOG')
        print(f"[JS {level_name}] {message}  (line {line})")
        if level >= 2:
            logger.error(f"[React] {message}")
        else:
            logger.debug(f"[React] {message}")

    def _open_event_detail_dialog(self, event_json):
        """Open the native RowDetailDialog with data from React."""
        try:
            event_data = json.loads(event_json)
            # Find a suitable title and row name
            title = event_data.get('source', event_data.get('type', 'Event Detail'))
            
            # Extract common identifier fields
            row_name = (event_data.get('name') or 
                        event_data.get('app_name') or 
                        event_data.get('filename') or 
                        event_data.get('executable_name') or 
                        event_data.get('target_path') or 
                        event_data.get('path') or 
                        'Unknown')
            
            # FIX: Bug 3 - Store dialog reference to prevent garbage collection
            self.current_detail_dialog = RowDetailDialog(
                event_data, 
                title=str(title).capitalize(), 
                row_name=str(row_name), 
                parent=self
            )
            self.current_detail_dialog.show()
        except Exception as e:
            logger.error(f"Error opening event detail dialog: {e}")
            QMessageBox.warning(self, "Error", f"Failed to open event detail: {str(e)}")

    def _get_case_directory(self) -> str:
        """Get the Target_Artifacts directory of the current case."""
        # 1. Try to get artifacts_dir directly from Crow-Eye's case_paths
        ui = getattr(self.main_window, 'ui', None)
        if ui and hasattr(ui, 'case_paths') and 'artifacts_dir' in ui.case_paths:
            artifacts_dir = ui.case_paths['artifacts_dir']
            if os.path.exists(artifacts_dir):
                return artifacts_dir
        
        # 2. Fallback to case_dir (backwards compatibility)
        case_dir = getattr(self.main_window, 'case_dir', None)
        if case_dir:
            target_dir = os.path.join(case_dir, "Target_Artifacts")
            if os.path.exists(target_dir):
                return target_dir
                
        # 3. Development/Test fallback
        test_target = r"C:\Users\Ghass\Downloads\test 1\Target_Artifacts"
        if os.path.exists(test_target):
            logger.info(f"Using test Target_Artifacts directory: {test_target}")
            return test_target
            
        raise ValueError("No case is currently loaded or Target_Artifacts not found.")
