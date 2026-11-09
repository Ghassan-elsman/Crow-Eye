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

from timeline.timeline_bridge import TimelineBridge, SOURCE_KEYS
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
        # Owned windows get no taskbar button on Windows, whatever their title
        # says - so a minimized Crow-Eye window had nowhere to show its name.
        # See CrowEyeStyles.give_window_a_taskbar_button for the measurements.
        try:
            from styles import CrowEyeStyles as _CES
            _CES.give_window_a_taskbar_button(self)
        except Exception:
            pass
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
        # Suppress Qt's default WebEngine right-click menu ("View page source",
        # "Save page", "Reload", …) — it doesn't work in this embedded app and isn't
        # needed. The React app's own DOM/JS context menus (e.g. LaneDataModal's
        # "Show in Timeline") are unaffected by this Qt widget policy.
        self.web_view.setContextMenuPolicy(Qt.NoContextMenu)
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
        # A link's "Show in table" (an AI step, or the Windows row beside it)
        self.bridge.show_in_table.connect(
            lambda db, table, rid: self.show_in_table(db, table, rid))

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
            if hasattr(self, 'loading_overlay') and self.loading_overlay:
                self.loading_overlay.hide()
            
            err_msg = f"React timeline build not found at:\n{react_build_path}\n\nPlease run 'npm run build' inside timeline/react-timeline/"
            QMessageBox.critical(self, "Build Missing", err_msg)
            
            # Load fallback HTML instead of leaving it blank
            fallback_html = f"""
            <html><body style="background-color: #0A0E1A; color: #E2E8F0; font-family: 'Segoe UI', sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; text-align: center;">
                <div>
                    <h2 style="color: #ff5555;">Timeline Interface Missing</h2>
                    <p>The React timeline application build was not found.</p>
                    <code style="background: #1E293B; padding: 4px 8px; border-radius: 4px; font-size: 12px; margin-top: 10px; display: inline-block;">{react_build_path}</code>
                    <p style="margin-top: 20px; color: #94A3B8;">Please ensure Node.js is installed and restart the app, or manually build the timeline.</p>
                </div>
            </body></html>
            """
            self.web_view.setHtml(fallback_html)
            self.web_view.show()
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
            # The lane's source row, if its query named one (TimelineBridge
            # _query_db): kept for "Show in table", never shown as a field.
            source = tuple(event_data.pop(k, None) for k in SOURCE_KEYS)
            if None in source and event_data.get('db') and event_data.get('table') \
                    and event_data.get('row_id') not in (None, ''):
                source = (event_data['db'], event_data['table'], event_data['row_id'])
            # Find a suitable title and row name
            title = event_data.get('source', event_data.get('type', 'Event Detail'))
            label = None

            # A mark that names its source row (`db`, `table`, `row_id` - the
            # AI agents lane) opens THAT row, every column of it, rather than
            # the trimmed copy the lane drew from. The lane leaves a step's
            # `text` in the database; this is where it is read. One row by
            # rowid, through the bridge's own allow-listed lookup.
            if event_data.get('db') and event_data.get('table') and \
                    event_data.get('row_id') not in (None, ''):
                try:
                    full = json.loads(self.bridge.getEventDetail(
                        str(event_data['db']), str(event_data['table']),
                        str(event_data['row_id'])))
                except Exception as exc:
                    full = {'error': str(exc)}
                if isinstance(full, dict) and 'error' not in full:
                    label = event_data.get('ai_label') or event_data.get('name')
                    title = event_data.get('table') or title
                    event_data = dict(full)

            # Extract common identifier fields
            row_name = (label or event_data.get('name') or
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
            if all(v not in (None, '') for v in source) and self.has_table_tab(source[1]):
                self.current_detail_dialog.add_action(
                    "Show in table",
                    "Open this row in its tab in the main window",
                    lambda _c=False, s=source: self.show_in_table(*s))
            self.current_detail_dialog.show()
        except Exception as e:
            logger.error(f"Error opening event detail dialog: {e}")
            QMessageBox.warning(self, "Error", f"Failed to open event detail: {str(e)}")

    def _tools(self):
        ui = getattr(self.main_window, 'ui', None)
        return getattr(ui, 'investigator_tools', None)

    def has_table_tab(self, table):
        """True when a main-window tab shows `table`. No button that leads
        nowhere."""
        tools = self._tools()
        return tools is not None and tools.table_view_for(table) is not None

    def show_in_table(self, db_name, table, row_id):
        """Select the row in its main-window tab (InvestigatorTools.show_row)
        and bring the main window forward. The Timeline stays open behind it
        (it is not modal), so the analyst can come back."""
        tools = self._tools()
        if tools is None:
            return False
        try:
            ok, why = tools.show_row(str(db_name), str(table), row_id)
        except Exception as e:
            logger.error(f"Show in table failed: {e}")
            ok, why = False, str(e)
        if not ok:
            QMessageBox.information(self, "Show in table", why)
            return False
        win = self.main_window
        if win is not None:
            if win.isMinimized():
                win.showNormal()
            win.raise_()
            win.activateWindow()
        return True

    def _get_case_directory(self) -> str:
        """Get the Target_Artifacts directory of the current case."""
        # 1. Try to get artifacts_dir directly from Crow-Eye's case_paths
        ui = getattr(self.main_window, 'ui', None)
        if ui and hasattr(ui, 'case_paths') and 'artifacts_dir' in ui.case_paths:
            artifacts_dir = ui.case_paths['artifacts_dir']
            if artifacts_dir and os.path.exists(artifacts_dir):
                return artifacts_dir

        # 2. Fallback to case_dir (backwards compatibility)
        case_dir = getattr(self.main_window, 'case_dir', None)
        if case_dir:
            target_dir = os.path.join(case_dir, "Target_Artifacts")
            if os.path.exists(target_dir):
                return target_dir

        raise ValueError(
            "No case is currently loaded. Open or create a case and parse the "
            "computer's artifacts first, then open the Timeline.")
