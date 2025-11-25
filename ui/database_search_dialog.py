"""
Database Search Dialog for Crow Eye - Unified Database Search System.

Provides comprehensive database-driven search functionality across multiple
forensic artifact databases with result navigation, export, and real-time search.

This implementation follows the Unified Database Search specification.
"""

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QThread, QObject
from typing import Optional, Dict, List, Any, Tuple
from collections.abc import Callable
from datetime import datetime, timedelta
import sys
import os
import csv
import json
import time
import logging
import re
from pathlib import Path

# Use package-relative imports instead of sys.path manipulation
try:
    from styles import CrowEyeStyles, Colors
except ImportError:
    # Fallback for different execution contexts
    from pathlib import Path
    import sys
    parent_dir = Path(__file__).resolve().parent.parent
    if str(parent_dir) not in sys.path:
        sys.path.insert(0, str(parent_dir))
    from styles import CrowEyeStyles, Colors

# Import data components
try:
    from data.unified_search_engine import UnifiedDatabaseSearchEngine, SearchParameters
    from data.database_manager import DatabaseManager, SearchResult, DatabaseInfo
    from data.search_history_manager import SearchHistoryManager
except ImportError as e:
    logging.warning(f"Failed to import data components: {e}")
    UnifiedDatabaseSearchEngine = None
    SearchParameters = None
    DatabaseManager = None
    SearchResult = None
    DatabaseInfo = None
    SearchHistoryManager = None





class TimePeriodFilterWidget(QtWidgets.QWidget):
    """
    Collapsible widget for time period filtering controls.
    
    Provides preset time ranges and custom date/time pickers with validation.
    Supports presets: Last 24h, 7d, 30d, 90d, 6mo, 1yr, and Custom.
    
    Signals:
        time_filter_changed: Emitted when time range changes (start_datetime, end_datetime)
        filter_enabled_changed: Emitted when filter is enabled/disabled (bool)
    """
    
    # Signals
    time_filter_changed = pyqtSignal(object, object)  # start_datetime, end_datetime
    filter_enabled_changed = pyqtSignal(bool)
    
    # Preset definitions
    PRESETS = {
        'last_24h': 'Last 24 Hours',
        'last_7d': 'Last 7 Days',
        'last_30d': 'Last 30 Days',
        'last_90d': 'Last 90 Days',
        'last_6mo': 'Last 6 Months',
        'last_1yr': 'Last Year',
        'custom': 'Custom Range'
    }
    
    def __init__(self, parent=None):
        """Initialize the time period filter widget with preset buttons and custom date/time pickers."""
        super().__init__(parent)
        
        self.logger = logging.getLogger(self.__class__.__name__)
        self.current_preset = 'custom'
        self.is_filter_enabled = False
        
        self._setup_ui()
        self._connect_signals()
        self._apply_styles()
        
        # Set default to "Custom Range" but keep filter disabled initially
        # When user enables the filter, it will use the last 30 days as default
        self.preset_buttons['custom'].setChecked(True)
    
    def _setup_ui(self):
        """Set up the user interface components."""
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(8)
        
        # Collapsible group box
        self.group_box = QtWidgets.QGroupBox("Time Period Filter")
        self.group_box.setCheckable(True)
        self.group_box.setChecked(False)
        group_layout = QtWidgets.QVBoxLayout()
        group_layout.setSpacing(10)
        
        # Preset buttons row - HIDDEN (user requested to hide these)
        preset_layout = QtWidgets.QHBoxLayout()
        preset_layout.setSpacing(6)
        
        self.preset_buttons = {}
        preset_order = ['last_24h', 'last_7d', 'last_30d', 'last_90d', 'last_6mo', 'last_1yr', 'custom']
        
        for preset_key in preset_order:
            btn = QtWidgets.QPushButton(self.PRESETS[preset_key])
            btn.setCheckable(True)
            btn.setMinimumHeight(28)
            btn.setProperty('preset_key', preset_key)
            btn.clicked.connect(lambda checked, key=preset_key: self._on_preset_clicked(key))
            btn.setVisible(False)  # Hide all preset buttons
            self.preset_buttons[preset_key] = btn
            preset_layout.addWidget(btn)
        
        # Don't add preset_layout to group_layout - buttons are hidden
        
        # Custom date/time pickers row
        custom_layout = QtWidgets.QHBoxLayout()
        custom_layout.setSpacing(10)
        
        # Start date/time
        start_label = QtWidgets.QLabel("Start:")
        start_label.setMinimumWidth(50)
        custom_layout.addWidget(start_label)
        
        self.start_datetime = QtWidgets.QDateTimeEdit()
        self.start_datetime.setCalendarPopup(True)
        self.start_datetime.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.start_datetime.setMinimumDate(QtCore.QDate(1970, 1, 1))
        self.start_datetime.setMaximumDate(QtCore.QDate(2099, 12, 31))
        # Set default to 30 days ago (datetime already imported at top of file)
        default_start = datetime.now() - timedelta(days=30)
        self.start_datetime.setDateTime(QtCore.QDateTime(default_start))
        self.start_datetime.setEnabled(True)  # Enable by default since preset buttons are hidden
        custom_layout.addWidget(self.start_datetime, stretch=1)
        
        # End date/time
        end_label = QtWidgets.QLabel("End:")
        end_label.setMinimumWidth(50)
        custom_layout.addWidget(end_label)
        
        self.end_datetime = QtWidgets.QDateTimeEdit()
        self.end_datetime.setCalendarPopup(True)
        self.end_datetime.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.end_datetime.setMinimumDate(QtCore.QDate(1970, 1, 1))
        self.end_datetime.setMaximumDate(QtCore.QDate(2099, 12, 31))
        # Set default to now
        self.end_datetime.setDateTime(QtCore.QDateTime(datetime.now()))
        self.end_datetime.setEnabled(True)  # Enable by default since preset buttons are hidden
        custom_layout.addWidget(self.end_datetime, stretch=1)
        
        # Clear button
        self.clear_button = QtWidgets.QPushButton("Clear")
        self.clear_button.setMinimumWidth(70)
        self.clear_button.setMinimumHeight(28)
        self.clear_button.setToolTip("Reset to Custom Range (last 30 days)")
        self.clear_button.clicked.connect(self._on_clear_clicked)
        custom_layout.addWidget(self.clear_button)
        
        group_layout.addLayout(custom_layout)
        
        # Validation message label
        self.validation_label = QtWidgets.QLabel("")
        self.validation_label.setWordWrap(True)
        self.validation_label.setVisible(False)
        group_layout.addWidget(self.validation_label)
        
        self.group_box.setLayout(group_layout)
        main_layout.addWidget(self.group_box)
    
    def _connect_signals(self):
        """Connect widget signals to handlers."""
        self.group_box.toggled.connect(self._on_filter_toggled)
        self.start_datetime.dateTimeChanged.connect(self._on_datetime_changed)
        self.end_datetime.dateTimeChanged.connect(self._on_datetime_changed)
    
    def _apply_styles(self):
        """Apply cyberpunk styles to the widget."""
        # Preset button styles
        preset_button_style = f"""
            QPushButton {{
                background-color: {Colors.BG_PANELS};
                color: {Colors.TEXT_PRIMARY};
                border: 2px solid {Colors.BORDER_SUBTLE};
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: 600;
                font-size: 9pt;
            }}
            QPushButton:hover {{
                background-color: {Colors.ACCENT_BLUE};
                border-color: {Colors.ACCENT_CYAN};
                color: {Colors.TEXT_PRIMARY};
            }}
            QPushButton:checked {{
                background-color: {Colors.ACCENT_CYAN};
                color: {Colors.BG_PRIMARY};
                border-color: {Colors.ACCENT_CYAN};
                font-weight: bold;
            }}
            QPushButton:disabled {{
                background-color: {Colors.BORDER_SUBTLE};
                color: {Colors.TEXT_MUTED};
                border-color: {Colors.BORDER_SUBTLE};
            }}
        """
        
        for btn in self.preset_buttons.values():
            btn.setStyleSheet(preset_button_style)
        
        self.clear_button.setStyleSheet(preset_button_style)
    
        # Date/time picker styles
        self.start_datetime.setStyleSheet(CrowEyeStyles.DATETIME_STYLE)
        self.end_datetime.setStyleSheet(CrowEyeStyles.DATETIME_STYLE)
        
        # Apply calendar styles if calendar popup is enabled
        if self.start_datetime.calendarWidget():
            self.start_datetime.calendarWidget().setStyleSheet(CrowEyeStyles.CALENDAR_STYLE)
        if self.end_datetime.calendarWidget():
            self.end_datetime.calendarWidget().setStyleSheet(CrowEyeStyles.CALENDAR_STYLE)
        
        # Group box style
        self.group_box.setStyleSheet(f"""
            QGroupBox {{
                background-color: {Colors.BG_PANELS};
                border: 2px solid {Colors.ACCENT_BLUE};
                border-radius: 6px;
                margin-top: 10px;
                padding: 10px;
                color: {Colors.ACCENT_CYAN};
                font-weight: bold;
                font-size: 10pt;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 8px;
                color: {Colors.ACCENT_CYAN};
            }}
            QGroupBox::indicator {{
                width: 16px;
                height: 16px;
                border: 2px solid {Colors.BORDER_SUBTLE};
                border-radius: 3px;
                background-color: {Colors.BG_TABLES};
            }}
            QGroupBox::indicator:checked {{
                background-color: {Colors.ACCENT_CYAN};
                border-color: {Colors.ACCENT_CYAN};
            }}
        """)
    
    def _on_filter_toggled(self, checked: bool):
        """Handle filter enable/disable toggle."""
        self.is_filter_enabled = checked
        self.filter_enabled_changed.emit(checked)
        self.logger.debug(f"Time filter {'enabled' if checked else 'disabled'}")
    
    def _on_clear_clicked(self):
        """Handle clear button click - reset to custom range with last 30 days."""
        from datetime import datetime, timedelta
        
        now = datetime.now()
        start = now - timedelta(days=30)
        
        # Reset to custom mode - delete the flag to force re-initialization
        if hasattr(self, '_custom_initialized'):
            delattr(self, '_custom_initialized')
        
        self._on_preset_clicked('custom')
    
    def _on_preset_clicked(self, preset_key: str):
        """Handle preset button clicks."""
        from datetime import datetime, timedelta
        
        self.current_preset = preset_key
        
        # Update button states
        for key, btn in self.preset_buttons.items():
            btn.setChecked(key == preset_key)
        
        # Calculate date range based on preset
        now = datetime.now()
        
        if preset_key == 'custom':
            # Enable custom date pickers
            self.start_datetime.setEnabled(True)
            self.end_datetime.setEnabled(True)
            self.group_box.setChecked(True)
            self.is_filter_enabled = True
            
            # Set default range (last 30 days) if not already set
            if not hasattr(self, '_custom_initialized'):
                start = now - timedelta(days=30)
                self.start_datetime.setDateTime(QtCore.QDateTime(start))
                self.end_datetime.setDateTime(QtCore.QDateTime(now))
                self._custom_initialized = True
            
            self._validate_and_emit()
            
        else:
            # Calculate preset range
            self.start_datetime.setEnabled(False)
            self.end_datetime.setEnabled(False)
            self.group_box.setChecked(True)
            self.is_filter_enabled = True
            
            if preset_key == 'last_24h':
                start = now - timedelta(hours=24)
            elif preset_key == 'last_7d':
                start = now - timedelta(days=7)
            elif preset_key == 'last_30d':
                start = now - timedelta(days=30)
            elif preset_key == 'last_90d':
                start = now - timedelta(days=90)
            elif preset_key == 'last_6mo':
                start = now - timedelta(days=180)
            elif preset_key == 'last_1yr':
                start = now - timedelta(days=365)
            else:
                start = now - timedelta(days=30)
            
            # Update date pickers
            self.start_datetime.setDateTime(QtCore.QDateTime(start))
            self.end_datetime.setDateTime(QtCore.QDateTime(now))
            
            self._validate_and_emit()
        
        self.logger.debug(f"Preset selected: {preset_key}")
    
    def _on_datetime_changed(self):
        """Handle manual date/time changes."""
        if self.current_preset == 'custom' and self.is_filter_enabled:
            self._validate_and_emit()
    
    def _validate_and_emit(self):
        """Validate the current time range and emit signals."""
        is_valid, message = self.validate_range()
        
        if is_valid:
            self.validation_label.setVisible(False)
            start, end = self.get_time_range()
            self.time_filter_changed.emit(start, end)
        else:
            # Show validation message
            self.validation_label.setText(message)
            self.validation_label.setVisible(True)
            
            # Style based on error type
            if "warning" in message.lower() or "future" in message.lower():
                self.validation_label.setStyleSheet(f"color: {Colors.WARNING}; font-size: 9pt; font-weight: bold;")
                # Still emit for warnings
                start, end = self.get_time_range()
                self.time_filter_changed.emit(start, end)
            else:
                self.validation_label.setStyleSheet(f"color: {Colors.ERROR}; font-size: 9pt; font-weight: bold;")
                # Don't emit for errors
    
    def validate_range(self) -> Tuple[bool, str]:
        """
        Validate the current time range.
        
        Returns:
            Tuple of (is_valid, error_message)
            - is_valid: True if range is valid or has warnings only
            - error_message: Empty string if valid, warning/error message otherwise
        """
        from datetime import datetime
        
        if not self.is_filter_enabled:
            return True, ""
        
        start_dt = self.start_datetime.dateTime().toPyDateTime()
        end_dt = self.end_datetime.dateTime().toPyDateTime()
        now = datetime.now()
        
        # Check if start is after end (ERROR)
        if start_dt >= end_dt:
            return False, "⚠️ Error: Start date must be before end date"
        
        # Check for dates outside valid range (ERROR)
        min_date = datetime(1970, 1, 1)
        max_date = datetime(2099, 12, 31)
        
        if start_dt < min_date or end_dt < min_date:
            return False, "⚠️ Error: Dates must be after January 1, 1970"
        
        if start_dt > max_date or end_dt > max_date:
            return False, "⚠️ Error: Dates must be before December 31, 2099"
        
        # Check for future dates (WARNING - still valid)
        if start_dt > now or end_dt > now:
            return True, "⚠️ Warning: Date range includes future dates"
        
        return True, ""
    
    def get_time_range(self) -> Tuple[Optional[object], Optional[object]]:
        """
        Get the current time range.
        
        Returns:
            Tuple of (start_datetime, end_datetime) or (None, None) if disabled
        """
        if not self.is_filter_enabled:
            return None, None
        
        start_dt = self.start_datetime.dateTime().toPyDateTime()
        end_dt = self.end_datetime.dateTime().toPyDateTime()
        
        return start_dt, end_dt
    
    def set_time_range(self, start: object, end: object):
        """
        Programmatically set the time range.
        
        Args:
            start: Start datetime object
            end: End datetime object
        """
        if start and end:
            # Mark custom as initialized to prevent default range from being set
            self._custom_initialized = True
            self._on_preset_clicked('custom')
            # Set the datetime values after switching to custom mode
            self.start_datetime.setDateTime(QtCore.QDateTime(start))
            self.end_datetime.setDateTime(QtCore.QDateTime(end))
            # Validate and emit signals
            self._validate_and_emit()
        else:
            # If no range provided, use custom with default 30 days
            if hasattr(self, '_custom_initialized'):
                delattr(self, '_custom_initialized')
            self._on_preset_clicked('custom')
    
    def is_enabled(self) -> bool:
        """
        Check if time filtering is currently enabled.
        
        Returns:
            True if time filtering is enabled, False otherwise
        """
        return self.is_filter_enabled


class SearchWorker(QObject):
    """
    Worker object for executing database searches in a separate thread.

    This worker runs the search using the UnifiedDatabaseSearchEngine and emits
    signals to communicate results, errors, or cancellation back to the main UI thread.

    Signals:
        search_complete: Emitted with results and search time (List[SearchResult], float)
        search_error: Emitted with an error message (str)
        search_cancelled: Emitted when the search is successfully cancelled
        progress_update: Emitted with progress message (str)
    """
    search_complete = pyqtSignal(list, float)
    search_error = pyqtSignal(str)
    search_cancelled = pyqtSignal()
    progress_update = pyqtSignal(str)

    def __init__(
        self,
        search_engine: UnifiedDatabaseSearchEngine,
        search_term: str,
        databases: List[str],
        tables: Dict[str, List[str]],
        case_sensitive: bool,
        exact_match: bool,
        use_regex: bool,
        max_results_per_table: int,
        start_time: Optional[object] = None,
        end_time: Optional[object] = None,
        timeout_seconds: float = 60.0
    ):
        """
        Initializes the search worker.

        Args:
            search_engine: An instance of the UnifiedDatabaseSearchEngine.
            search_term: The term or pattern to search for.
            databases: A list of database names to search within.
            tables: A dictionary mapping database names to lists of table names.
            case_sensitive: Flag for case-sensitive matching.
            exact_match: Flag for exact value matching.
            use_regex: Flag to interpret the search term as a regular expression.
            max_results_per_table: The maximum number of results to return per table.
            start_time: Optional start datetime for time filtering.
            end_time: Optional end datetime for time filtering.
            timeout_seconds: Maximum time allowed for search operation.
        """
        super().__init__()
        self.search_engine = search_engine
        self.search_term = search_term
        self.databases = databases
        self.tables = tables
        self.case_sensitive = case_sensitive
        self.exact_match = exact_match
        self.use_regex = use_regex
        self.max_results_per_table = max_results_per_table
        self.start_time = start_time
        self.end_time = end_time
        self.timeout_seconds = timeout_seconds
        self.logger = logging.getLogger(self.__class__.__name__)

    def run(self):
        """
        Executes the search operation.

        This method is called when the worker's thread is started. It performs
        the search and emits signals based on the outcome.
        
        Requirements: 14.3 - Display progress indicators during search
        """
        try:
            self.logger.info(f"Starting search for term: '{self.search_term}' (time_filter: {self.start_time is not None or self.end_time is not None})")
            start_search_time = time.time()

            # Define progress callback to emit progress updates
            def progress_callback(message: str):
                try:
                    self.progress_update.emit(message)
                except RuntimeError:
                    # Signal disconnected or object deleted
                    pass
            
            results = self.search_engine.search(
                search_term=self.search_term,
                databases=self.databases,
                tables=self.tables,
                case_sensitive=self.case_sensitive,
                exact_match=self.exact_match,
                use_regex=self.use_regex,
                max_results_per_table=self.max_results_per_table,
                start_time=self.start_time,
                end_time=self.end_time,
                timeout_seconds=self.timeout_seconds,
                progress_callback=progress_callback
            )

            print(f"[WORKER] Received {len(results) if results else 0} SearchResults objects from search engine")
            if results:
                for idx, sr in enumerate(results[:3]):  # Log first 3
                    print(f"[WORKER]   Result {idx}: {type(sr)} - {getattr(sr, 'total_matches', '?')} matches")

            search_time = time.time() - start_search_time

            if self.search_engine.is_search_cancelled():
                self.logger.info("Search was cancelled")
                try:
                    self.search_cancelled.emit()
                except RuntimeError:
                    pass  # Object deleted
                return

            self.logger.info(f"Search completed: {len(results)} results in {search_time:.2f}s")
            print(f"[WORKER] Emitting search_complete signal with {len(results)} SearchResults objects")
            try:
                self.search_complete.emit(results, search_time)
            except RuntimeError:
                self.logger.warning("Could not emit search_complete - object deleted")

        except ValueError as ve:
            print(f"[WORKER] ValueError: {ve}")
            self.logger.warning(f"Search validation error: {ve}")
            try:
                self.search_error.emit(str(ve))
            except RuntimeError:
                print(f"[WORKER] Could not emit error signal - object deleted")
        except Exception as e:
            print(f"[WORKER] Exception: {e}")
            import traceback
            traceback.print_exc()
            self.logger.error(f"Unexpected search thread error: {e}", exc_info=True)
            try:
                self.search_error.emit(f"Unexpected error: {str(e)}")
            except RuntimeError:
                print(f"[WORKER] Could not emit error signal - object deleted")



class UISearchResult:
    """
    Static class to hold search result data for the UI.
    Replaces dynamic type creation to avoid potential crashes.
    """
    def __init__(self, database, table, row_id, matched_columns, row_data, match_preview, matched_timestamps):
        self.database = database
        self.table = table
        self.row_id = row_id
        self.matched_columns = matched_columns
        self.row_data = row_data
        self.match_preview = match_preview
        self.matched_timestamps = matched_timestamps


class DatabaseSearchDialog(QtWidgets.QDialog):
    """
    Unified Database Search Dialog for Crow Eye.
    
    Provides comprehensive search functionality across all forensic artifact
    databases with advanced options, result navigation, and export capabilities.
    
    Signals:
        navigate_to_result: Emitted when user wants to navigate to a result
                           (database, table, row_id)
    """
    
    # Signal for result navigation
    navigate_to_result = pyqtSignal(str, str, object, object)  # database, table, row_id, timestamp_info
    
    # Database categories for organization
    DATABASE_CATEGORIES = {
        "Execution Evidence": [
            "prefetch_data.db",
            "amcache_data.db",
            "amcache.db",  # Alternative name
            "shimcache_data.db",
            "shimcache.db",  # Alternative name
            "lnk_data.db",
            "LnkDB.db",  # Alternative name
            "jumplist_data.db",
            "userassist_data.db",
            "bam_dam_data.db"
        ],
        "Registry Evidence": [
            "registry_data.db",
            "muicache_data.db"
        ],
        "File System Evidence": [
            "mft_data.db",
            "mft_claw_analysis.db",  # Alternative name
            "usn_data.db",
            "USN_journal.db",  # Alternative name
            "mft_usn_correlated_analysis.db",  # Correlated data
            "recyclebin_data.db",
            "recyclebin_analysis.db",  # Alternative name
            "shellbags_data.db"
        ],
        "System Information": [
            "eventlog_data.db",
            "Log_Claw.db"  # Alternative name
        ],
        "System Resource Usage": [
            "srum_data.db"
        ]
    }
    
    def __init__(
        self,
        parent: Optional[QtWidgets.QWidget] = None,
        search_engine: Optional[UnifiedDatabaseSearchEngine] = None
    ):
        """
        Initialize the database search dialog.
        
        Args:
            parent: Parent widget
            search_engine: An instance of UnifiedDatabaseSearchEngine.
        """
        super().__init__(parent)
        
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Use the provided search engine
        self.search_engine = search_engine
        if not self.search_engine:
            self.logger.error("No search engine was provided to the search dialog.")
        
        # Search state
        self.current_results: List[SearchResult] = []
        self.search_in_progress = False
        self.discovered_databases: List[DatabaseInfo] = []
        self.thread: Optional[QThread] = None
        self.worker: Optional[SearchWorker] = None
        
        # Worker thread for background searches
        
        
        # Debounce timer for real-time search
        self.debounce_timer = QTimer()
        self.debounce_timer.setSingleShot(True)
        self.debounce_timer.setInterval(300)  # 300ms debounce
        self.debounce_timer.timeout.connect(self._perform_search)
        
        # Settings for persistence
        self.settings = QtCore.QSettings("CrowEye", "DatabaseSearch")
        
        # UI Components (will be created in _setup_ui)
        self.search_input: Optional[QtWidgets.QLineEdit] = None
        self.history_combo: Optional[QtWidgets.QComboBox] = None
        self.case_sensitive_checkbox: Optional[QtWidgets.QCheckBox] = None
        self.exact_match_checkbox: Optional[QtWidgets.QCheckBox] = None
        self.regex_checkbox: Optional[QtWidgets.QCheckBox] = None
        # Note: search_as_type_checkbox removed - search only on button/Enter
        self.database_tree: Optional[QtWidgets.QTreeWidget] = None
        self.search_button: Optional[QtWidgets.QPushButton] = None
        self.cancel_button: Optional[QtWidgets.QPushButton] = None
        self.progress_bar: Optional[QtWidgets.QProgressBar] = None
        self.results_table: Optional[QtWidgets.QTableWidget] = None
        
        # Setup UI
        self._setup_ui()
        self._connect_signals()
        self._apply_styles()
        
        # Load settings
        self._load_settings()
        
        # Load available databases
        if self.search_engine:
            self._load_available_databases()
        
        # Load search history
        self._load_search_history()
    
    def closeEvent(self, event):
        """
        Handle dialog close event to ensure proper cleanup.
        
        This method ensures that any ongoing search is cancelled and
        threads are properly cleaned up before the dialog closes.
        
        Args:
            event: QCloseEvent object
        
        Requirements: 7.5
        """
        try:
            # Cancel any ongoing search
            if self.search_in_progress:
                self.logger.info("Cancelling search before closing dialog")
                self._cancel_search()
                
                # Wait briefly for thread to finish
                if self.thread and self.thread.isRunning():
                    self.thread.quit()
                    self.thread.wait(1000)  # Wait up to 1 second
            
            # Clean up thread and worker
            self._cleanup_search_thread()
            
            # Save settings (including window state)
            self._save_settings()
            
            self.logger.info("Database search dialog closed")
            
        except Exception as e:
            self.logger.error(f"Error during dialog close: {e}", exc_info=True)
        
        # Accept the close event
        event.accept()
    
    def resizeEvent(self, event):
        """
        Handle window resize events to maintain responsive layout.
        
        Ensures proper proportions and prevents UI element overlap during resize.
        
        Args:
            event: QResizeEvent object
        
        Requirements: 11.7, 11.8
        """
        try:
            super().resizeEvent(event)
            
            # Get new size
            new_size = event.size()
            width = new_size.width()
            height = new_size.height()
            
            # Adjust database tree height based on window height
            # Keep it proportional but within reasonable bounds
            if hasattr(self, 'database_tree'):
                min_tree_height = 150
                max_tree_height = 300
                proportional_height = int(height * 0.15)  # 15% of window height
                tree_height = max(min_tree_height, min(max_tree_height, proportional_height))
                self.database_tree.setMaximumHeight(tree_height)
            
            # Ensure results table gets most of the space
            # The stretch factor in the layout handles this, but we can adjust if needed
            
            self.logger.debug(f"Window resized to {width}x{height}")
            
        except Exception as e:
            self.logger.warning(f"Error handling resize event: {e}")

    def _setup_ui(self):
        """
        Set up the user interface following the spec requirements.
        
        Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 11.6, 11.7, 11.8, 13.1, 13.2, 13.3, 13.5, 13.6, 13.8, 13.9
        """
        self.setWindowTitle("⚡ CROW EYE - DATABASE SEARCH ⚡")
        self.setMinimumSize(1000, 600)
        self.resize(1200, 800)  # More compact default size
        
        # Enable window controls: minimize, maximize, restore buttons
        # Requirements: 7.1, 7.2, 7.3, 7.4
        window_flags = Qt.Window | Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint | Qt.WindowCloseButtonHint
        self.setWindowFlags(window_flags)
        
        # Restore window geometry from settings
        # Requirements: 7.5
        self._restore_window_state()
        
        # Main layout - ultra compact spacing for more data visibility
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(2)
        
        # Time filter widget - show date/time inputs but hide preset buttons
        self.time_filter_widget = TimePeriodFilterWidget(self)
        main_layout.addWidget(self.time_filter_widget)
        
        # Search input section
        search_layout = self._create_search_controls()
        main_layout.addLayout(search_layout)
        
        # Filter summary bar (below search input)
        # Requirements: 13.1, 13.2, 13.5, 13.6
        self.filter_summary_bar = self._create_filter_summary_bar()
        main_layout.addWidget(self.filter_summary_bar)
        
        # Options section (checkboxes)
        options_layout = self._create_options_controls()
        main_layout.addLayout(options_layout)
        
        # Database/table selection tree
        database_group = self._create_database_tree()
        main_layout.addWidget(database_group)
        
        # Progress bar (initially hidden)
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(0)  # Indeterminate
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("Searching databases...")
        self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)
        
        # Results table
        results_group = self._create_results_table()
        main_layout.addWidget(results_group, stretch=1)
        
        # Button section
        button_layout = self._create_buttons()
        main_layout.addLayout(button_layout)
    
    def _create_filter_summary_bar(self) -> QtWidgets.QWidget:
        """
        Create the filter summary bar displaying active filters.
        
        Shows badge count for number of active filters and provides a "Clear All Filters" button.
        
        Requirements: 13.1, 13.2, 13.3, 13.5, 13.6
        """
        # Container widget
        container = QtWidgets.QWidget()
        container.setVisible(False)  # Initially hidden until filters are active
        
        layout = QtWidgets.QHBoxLayout(container)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(10)
        
        # Active filters label with badge
        self.filter_summary_label = QtWidgets.QLabel("Active Filters:")
        self.filter_summary_label.setStyleSheet(f"""
            QLabel {{
                color: {Colors.ACCENT_CYAN};
                font-weight: bold;
                font-size: 9pt;
                padding: 4px 8px;
            }}
        """)
        layout.addWidget(self.filter_summary_label)
        
        # Filter details label
        self.filter_details_label = QtWidgets.QLabel("")
        self.filter_details_label.setStyleSheet(f"""
            QLabel {{
                color: {Colors.TEXT_PRIMARY};
                font-size: 9pt;
                padding: 4px;
            }}
        """)
        layout.addWidget(self.filter_details_label, stretch=1)
        
        # Clear all filters button
        self.clear_all_filters_button = QtWidgets.QPushButton("Clear All Filters")
        self.clear_all_filters_button.setMinimumHeight(24)
        self.clear_all_filters_button.setToolTip("Reset all search filters to default values")
        self.clear_all_filters_button.clicked.connect(self._on_clear_all_filters)
        layout.addWidget(self.clear_all_filters_button)
        
        # Apply styling to container
        container.setStyleSheet(f"""
            QWidget {{
                background-color: {Colors.BG_PANELS};
                border: 2px solid {Colors.ACCENT_BLUE};
                border-radius: 4px;
            }}
        """)
        
        return container
    
    def _create_search_controls(self) -> QtWidgets.QVBoxLayout:
        """Create the search input controls section."""
        main_layout = QtWidgets.QVBoxLayout()
        main_layout.setSpacing(6)
        
        # Combined search and recent row
        search_layout = QtWidgets.QHBoxLayout()
        search_layout.setSpacing(6)
        
        # Recent label and combo (smaller)
        recent_label = QtWidgets.QLabel("Recent:")
        recent_label.setMinimumWidth(50)
        search_layout.addWidget(recent_label)
        
        # History combo box (smaller)
        self.history_combo = QtWidgets.QComboBox()
        self.history_combo.setMinimumHeight(20)
        self.history_combo.setMaximumWidth(200)
        self.history_combo.setPlaceholderText("Select recent...")
        self.history_combo.addItem("-- Select recent --")
        self.history_combo.setToolTip("Select from your recent searches to quickly repeat them")
        search_layout.addWidget(self.history_combo)
        
        # Search label
        search_label = QtWidgets.QLabel("Search:")
        search_label.setMinimumWidth(50)
        search_layout.addWidget(search_label)
        
        # Search input with placeholder
        self.search_input = QtWidgets.QLineEdit()
        self.search_input.setPlaceholderText("Enter search term and press Enter to search across all databases...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMinimumHeight(20)
        search_layout.addWidget(self.search_input, stretch=1)
        
        # Search button
        self.search_button = QtWidgets.QPushButton("Search")
        self.search_button.setMinimumWidth(60)
        self.search_button.setMinimumHeight(20)
        self.search_button.setDefault(True)
        self.search_button.setToolTip("Click to search or press Enter in the search box")
        search_layout.addWidget(self.search_button)
        
        # Cancel button (initially hidden)
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.cancel_button.setMinimumWidth(60)
        self.cancel_button.setMinimumHeight(20)
        self.cancel_button.setVisible(False)
        search_layout.addWidget(self.cancel_button)
        
        main_layout.addLayout(search_layout)
        
        return main_layout
    
    def _create_options_controls(self) -> QtWidgets.QHBoxLayout:
        """
        Create the search options checkboxes section with visual separators.
        
        Requirements: 13.1, 13.8
        """
        layout = QtWidgets.QHBoxLayout()
        layout.setSpacing(12)
        
        # Options label
        options_label = QtWidgets.QLabel("Options:")
        options_label.setMinimumWidth(60)
        options_label.setToolTip("Configure search behavior with these options")
        layout.addWidget(options_label)
        
        # Case sensitive checkbox
        self.case_sensitive_checkbox = QtWidgets.QCheckBox("Case Sensitive")
        self.case_sensitive_checkbox.setChecked(False)
        self.case_sensitive_checkbox.setToolTip("Distinguish between uppercase and lowercase characters in search results")
        layout.addWidget(self.case_sensitive_checkbox)
        
        # Visual separator
        separator1 = QtWidgets.QFrame()
        separator1.setFrameShape(QtWidgets.QFrame.VLine)
        separator1.setFrameShadow(QtWidgets.QFrame.Sunken)
        separator1.setStyleSheet(f"color: {Colors.BORDER_SUBTLE};")
        layout.addWidget(separator1)
        
        # Exact match checkbox
        self.exact_match_checkbox = QtWidgets.QCheckBox("Exact Match")
        self.exact_match_checkbox.setChecked(False)
        self.exact_match_checkbox.setToolTip("Match entire field value exactly (no partial matches)")
        layout.addWidget(self.exact_match_checkbox)
        
        # Visual separator
        separator2 = QtWidgets.QFrame()
        separator2.setFrameShape(QtWidgets.QFrame.VLine)
        separator2.setFrameShadow(QtWidgets.QFrame.Sunken)
        separator2.setStyleSheet(f"color: {Colors.BORDER_SUBTLE};")
        layout.addWidget(separator2)
        
        # Regex checkbox
        self.regex_checkbox = QtWidgets.QCheckBox("Use Regex")
        self.regex_checkbox.setChecked(False)
        self.regex_checkbox.setToolTip("Interpret search term as a regular expression pattern for advanced matching")
        layout.addWidget(self.regex_checkbox)
        
        # Visual separator
        separator3 = QtWidgets.QFrame()
        separator3.setFrameShape(QtWidgets.QFrame.VLine)
        separator3.setFrameShadow(QtWidgets.QFrame.Sunken)
        separator3.setStyleSheet(f"color: {Colors.BORDER_SUBTLE};")
        layout.addWidget(separator3)
        
        
        layout.addStretch()
        
        return layout
    
    def _create_database_tree(self) -> QtWidgets.QGroupBox:
        """
        Create the database/table selection tree widget with categories.
        
        Includes enhanced controls for selecting databases based on load status.
        
        Requirements: 10.8
        """
        group = QtWidgets.QGroupBox("Select Databases to Search:")
        layout = QtWidgets.QVBoxLayout()
        
        # Create horizontal layout for tree and buttons side by side
        main_layout = QtWidgets.QHBoxLayout()
        
        # Database tree widget - increased height for better visibility
        self.database_tree = QtWidgets.QTreeWidget()
        self.database_tree.setHeaderLabels(["Database / Table", "Status"])
        self.database_tree.setAlternatingRowColors(True)
        self.database_tree.setRootIsDecorated(True)
        self.database_tree.setColumnWidth(0, 280)
        self.database_tree.setColumnWidth(1, 220)
        self.database_tree.setMinimumHeight(200)  # Increased from 100
        self.database_tree.setMaximumHeight(500)  # Increased from 350 for more space
        self.database_tree.setIndentation(20)
        
        # Set header background color programmatically
        tree_header = self.database_tree.header()
        tree_header.setStyleSheet(f"""
            QHeaderView::section {{
                background-color: #1E293B;
                color: #00FFFF;
                border: none;
                border-right: 1px solid #334155;
                border-bottom: 2px solid #00FFFF;
                padding: 4px 8px;
                font-weight: 700;
                font-size: 10px;
                font-family: 'Segoe UI', sans-serif;
            }}
        """)
        
        main_layout.addWidget(self.database_tree)
        
        # Selection controls - vertical layout on the right side
        controls_layout = QtWidgets.QVBoxLayout()
        
        select_all_btn = QtWidgets.QPushButton("Select All")
        select_all_btn.setMinimumWidth(100)
        select_all_btn.setMaximumWidth(100)
        select_all_btn.setToolTip("Select all available databases and tables")
        select_all_btn.clicked.connect(self._select_all_databases)
        controls_layout.addWidget(select_all_btn)
        
        deselect_all_btn = QtWidgets.QPushButton("Deselect All")
        deselect_all_btn.setMinimumWidth(100)
        deselect_all_btn.setMaximumWidth(100)
        deselect_all_btn.setToolTip("Deselect all databases and tables")
        deselect_all_btn.clicked.connect(self._deselect_all_databases)
        controls_layout.addWidget(deselect_all_btn)
        
        # Add "Select Loaded Only" button
        select_loaded_btn = QtWidgets.QPushButton("Select Loaded")
        select_loaded_btn.setMinimumWidth(100)
        select_loaded_btn.setMaximumWidth(100)
        select_loaded_btn.setToolTip("Select only databases with loaded GUI tabs")
        select_loaded_btn.clicked.connect(self._select_loaded_only)
        controls_layout.addWidget(select_loaded_btn)
        
        main_layout.addLayout(controls_layout)
        
        layout.addLayout(main_layout)
        
        group.setLayout(layout)
        return group
    
    def _create_results_table(self) -> QtWidgets.QGroupBox:
        """
        Create the results display table widget with timestamp column support.
        
        Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.7, 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7, 12.8, 12.10
        """
        group = QtWidgets.QGroupBox("Search Results")
        layout = QtWidgets.QVBoxLayout()
        
        # Results info label - smaller
        self.results_info_label = QtWidgets.QLabel("No search performed yet")
        self.results_info_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 8pt;")
        layout.addWidget(self.results_info_label)
        
        # Results table widget
        self.results_table = QtWidgets.QTableWidget()
        # Start with 5 columns (including Timestamp column, excluding Row ID)
        self.results_table.setColumnCount(5)
        self.results_table.setHorizontalHeaderLabels([
            "Database",
            "Table",
            "Matched Columns",
            "Timestamp",
            "Preview"
        ])
        
        # Configure table properties
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.results_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.results_table.setSortingEnabled(True)
        self.results_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        
        # Enable hover effects
        self.results_table.setMouseTracking(True)
        
        # Set column widths - optimized for more data
        header = self.results_table.horizontalHeader()
        header.setStretchLastSection(False)
        # Enable column resizing by dragging borders
        header.setSectionsMovable(False)
        header.setSectionResizeMode(QtWidgets.QHeaderView.Interactive)
        
        self.results_table.setColumnWidth(0, 120)  # Database
        self.results_table.setColumnWidth(1, 120)  # Table
        self.results_table.setColumnWidth(2, 200)  # Matched Columns - slightly wider
        self.results_table.setColumnWidth(3, 180)  # Timestamp
        self.results_table.setColumnWidth(4, 500)  # Preview - wider for more data
        header.setSectionResizeMode(4, QtWidgets.QHeaderView.Stretch)  # Preview stretches
        
        # Set row height to be very compact for more data visibility
        self.results_table.verticalHeader().setDefaultSectionSize(18)
        
        # Set header background color programmatically (stylesheet sometimes doesn't apply)
        header.setStyleSheet(f"""
            QHeaderView::section {{
                background-color: #1E293B;
                color: #00FFFF;
                border: none;
                border-right: 1px solid #334155;
                border-bottom: 2px solid #00FFFF;
                padding: 4px 8px;
                font-weight: 700;
                font-size: 10px;
                font-family: 'Segoe UI', sans-serif;
            }}
        """)
        
        # Initially hide timestamp column (shown only when time filtering is active)
        self.results_table.setColumnHidden(3, True)
        
        layout.addWidget(self.results_table)
        
        group.setLayout(layout)
        return group
    
    def _create_buttons(self) -> QtWidgets.QHBoxLayout:
        """Create the bottom button section."""
        layout = QtWidgets.QHBoxLayout()
        
        # Export button (disabled until results available)
        self.export_button = QtWidgets.QPushButton("Export")
        self.export_button.setMinimumWidth(80)
        self.export_button.setMinimumHeight(24)
        self.export_button.setEnabled(False)
        layout.addWidget(self.export_button)
        
        # Clear button
        self.clear_button = QtWidgets.QPushButton("Clear")
        self.clear_button.setMinimumWidth(80)
        self.clear_button.setMinimumHeight(24)
        layout.addWidget(self.clear_button)
        
        layout.addStretch()
        
        # Close button
        self.close_button = QtWidgets.QPushButton("Close")
        self.close_button.setMinimumWidth(80)
        self.close_button.setMinimumHeight(24)
        layout.addWidget(self.close_button)
        
        return layout
    
    def _connect_signals(self):
        """Connect widget signals to handlers."""
        # Search controls
        self.search_button.clicked.connect(self._on_search_clicked)
        self.search_input.returnPressed.connect(self._on_search_clicked)
        self.search_input.textChanged.connect(self._on_search_text_changed)
        self.cancel_button.clicked.connect(self._cancel_search)
        
        # History
        self.history_combo.currentIndexChanged.connect(self._on_history_selected)
        
        # Note: Search-as-type feature removed
        
        # Filter change signals for updating summary AND auto-triggering search
        # Requirements: 13.6
        self.case_sensitive_checkbox.stateChanged.connect(self._on_filter_changed)
        self.exact_match_checkbox.stateChanged.connect(self._on_filter_changed)
        self.regex_checkbox.stateChanged.connect(self._on_filter_changed)
        if hasattr(self, 'time_filter_widget'):
            self.time_filter_widget.filter_enabled_changed.connect(self._on_filter_changed)
            self.time_filter_widget.time_filter_changed.connect(self._on_filter_changed)
        
        # Results table
        self.results_table.itemDoubleClicked.connect(self._on_result_double_clicked)
        
        # Buttons
        self.export_button.clicked.connect(self._on_export_clicked)
        self.clear_button.clicked.connect(self._on_clear_clicked)
        self.close_button.clicked.connect(self.reject)
    
    def _restore_window_state(self):
        """
        Restore window size and position from QSettings.
        
        Requirements: 7.5
        """
        try:
            # Restore window geometry (size and position)
            geometry = self.settings.value("window_geometry")
            if geometry:
                self.restoreGeometry(geometry)
                self.logger.debug("Restored window geometry from settings")
            
            # Restore window state (maximized, etc.)
            window_state = self.settings.value("window_state")
            if window_state:
                self.restoreState(window_state)
                self.logger.debug("Restored window state from settings")
                
        except Exception as e:
            self.logger.warning(f"Failed to restore window state: {e}")
    
    def _save_window_state(self):
        """
        Save window size and position to QSettings.
        
        Requirements: 7.5
        """
        try:
            # Save window geometry (size and position)
            self.settings.setValue("window_geometry", self.saveGeometry())
            
            # Save window state (maximized, etc.)
            self.settings.setValue("window_state", self.saveState())
            
            self.logger.debug("Saved window state to settings")
            
        except Exception as e:
            self.logger.warning(f"Failed to save window state: {e}")
    
    def _load_settings(self):
        """
        Load user preferences from QSettings.
        """
        # Note: Search-as-type feature removed
        self.logger.debug("Settings loaded")
    
    def _save_settings(self):
        """
        Save user preferences to QSettings.
        
        Saves window state.
        
        Requirements: 7.5
        """
        self._save_window_state()
        self.logger.debug("Settings saved")
    

    
    def _apply_styles(self):
        """Apply enhanced cyberpunk styles to the dialog - futuristic and professional."""
        self.setStyleSheet(f"""
            /* Main Dialog - Futuristic Dark Theme with Glow */
            QDialog {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #0A0E1A, stop:0.5 #0F172A, stop:1 #0A0E1A);
                border: 3px solid #00FFFF;
                border-radius: 12px;
            }}
            
            /* Labels - Neon Cyan Text */
            QLabel {{
                color: #00FFFF;
                font-size: 8pt;
                font-family: 'Segoe UI', sans-serif;
                font-weight: 600;
            }}
            
            /* Search Input - Futuristic with Glow Effect */
            QLineEdit {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1A1F2E, stop:1 #0F1419);
                color: #FFFFFF;
                border: 2px solid #334155;
                border-radius: 10px;
                padding: 10px 16px;
                font-size: 14px;
                font-family: 'Segoe UI', sans-serif;
                selection-background-color: #00FFFF;
                selection-color: #000000;
            }}
            QLineEdit:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1F2937, stop:1 #111827);
                border: 2px solid #475569;
            }}
            QLineEdit:focus {{
                border: 2px solid #00FFFF;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1F2937, stop:1 #111827);
            }}
            
            /* Group Boxes - Futuristic Panels */
            QGroupBox {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(30, 41, 59, 0.8), stop:1 rgba(15, 23, 42, 0.9));
                color: #00FFFF;
                border: 2px solid #00FFFF;
                border-radius: 10px;
                margin-top: 12px;
                padding: 6px;
                font-weight: 700;
                font-size: 9pt;
                font-family: 'Segoe UI', sans-serif;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 3px 8px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #0F172A, stop:0.5 #1E293B, stop:1 #0F172A);
                color: #00FFFF;
                border: 2px solid #00FFFF;
                border-radius: 6px;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 1px;
            }}
            
            /* Checkboxes - Futuristic Glowing Style */
            QCheckBox {{
                color: #E0E7FF;
                spacing: 8px;
                font-size: 10pt;
                font-family: 'Segoe UI', sans-serif;
                font-weight: 500;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border: 2px solid #00FFFF;
                border-radius: 4px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1A1F2E, stop:1 #0F1419);
            }}
            QCheckBox::indicator:checked {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #00FFFF, stop:1 #00BFFF);
                border-color: #00FFFF;
                image: none;
            }}
            QCheckBox::indicator:hover {{
                border-color: #00FF7F;
                background-color: rgba(0, 255, 127, 0.15);
            }}
            
            /* ComboBox - Futuristic Dropdown */
            QComboBox {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1A1F2E, stop:1 #0F1419);
                color: #FFFFFF;
                border: 2px solid #334155;
                border-radius: 8px;
                padding: 6px 12px;
                font-size: 10pt;
                font-family: 'Segoe UI', sans-serif;
                min-height: 24px;
            }}
            QComboBox:hover {{
                border: 2px solid #00FFFF;
            }}
            QComboBox:focus {{
                border: 2px solid #00FFFF;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1F2937, stop:1 #111827);
            }}
            QComboBox::drop-down {{
                border: none;
                width: 30px;
                background: transparent;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 6px solid transparent;
                border-right: 6px solid transparent;
                border-top: 6px solid #00FFFF;
                margin-right: 10px;
            }}
            QComboBox QAbstractItemView {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1A1F2E, stop:1 #0F1419);
                color: #FFFFFF;
                border: 2px solid #00FFFF;
                selection-background-color: #00FFFF;
                selection-color: #000000;
                padding: 6px;
                font-size: 10pt;
                outline: none;
            }}
            
            /* Buttons - Futuristic Glowing Style */
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #00BFFF, stop:1 #0080FF);
                color: #000000;
                border: 2px solid #00FFFF;
                border-radius: 6px;
                padding: 4px 10px;
                font-weight: 600;
                font-size: 9px;
                font-family: 'Segoe UI', sans-serif;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                min-width: 60px;
                min-height: 24px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #00FFFF, stop:1 #00BFFF);
                border: 2px solid #00FF7F;
                color: #000000;
            }}
            QPushButton:pressed {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #0080FF, stop:1 #0060BF);
                border: 2px solid #00BFFF;
            }}
            QPushButton:disabled {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #334155, stop:1 #1E293B);
                color: #64748B;
                border: 2px solid #334155;
            }}
        """)
        
        # Tree widget style - Futuristic Database Tree with Glow
        self.database_tree.setStyleSheet(f"""
            QTreeWidget {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(10, 14, 26, 0.98), stop:1 rgba(5, 7, 13, 0.98));
                color: #E0E7FF;
                border: 2px solid #00FFFF;
                border-radius: 10px;
                alternate-background-color: rgba(30, 41, 59, 0.3);
                font-size: 9pt;
                font-family: 'Segoe UI', sans-serif;
                padding: 6px;
                outline: none;
            }}
            QTreeWidget::item {{
                padding: 6px 8px;
                min-height: 24px;
                border-bottom: 1px solid rgba(0, 255, 255, 0.1);
                border-left: 3px solid transparent;
            }}
            QTreeWidget::item:selected {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 rgba(0, 255, 255, 0.4), stop:1 rgba(0, 191, 255, 0.2));
                color: #FFFFFF;
                border-left: 4px solid #00FFFF;
                font-weight: 600;
            }}
            QTreeWidget::item:selected:active {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 rgba(0, 255, 255, 0.5), stop:1 rgba(0, 255, 127, 0.3));
                color: #FFFFFF;
                border-left: 4px solid #00FF7F;
            }}
            QTreeWidget::item:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 rgba(0, 255, 255, 0.2), stop:1 rgba(0, 255, 255, 0.1));
                border-left: 3px solid #00FFFF;
            }}
            QTreeView::branch:closed:has-children {{
                image: none;
            }}
            QTreeView::branch:open:has-children {{
                image: none;
            }}
            QTreeWidget::indicator {{
                width: 18px;
                height: 18px;
                border: 2px solid #00FFFF;
                border-radius: 4px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1A1F2E, stop:1 #0F1419);
            }}
            QTreeWidget::indicator:hover {{
                border-color: #00FF7F;
                background-color: rgba(0, 255, 127, 0.15);
            }}
            QTreeWidget::indicator:checked {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #00FFFF, stop:1 #00BFFF);
                border-color: #00FFFF;
            }}
            QHeaderView::section {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #1E293B, stop:1 #0F172A);
                color: #00FFFF;
                border: none;
                border-right: 1px solid #334155;
                border-bottom: 2px solid #00FFFF;
                padding: 8px 10px;
                font-weight: 700;
                font-size: 10px;
                font-family: 'Segoe UI', sans-serif;
                text-transform: uppercase;
                letter-spacing: 1px;
            }}
            QHeaderView::section:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #334155, stop:1 #1E293B);
                color: #FFFFFF;
                border-bottom: 2px solid #00FF7F;
            }}
        """)
        
        # Results table style - Futuristic Data Grid with Glow
        # Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7, 12.8, 12.10
        self.results_table.setStyleSheet(f"""
            QTableWidget {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(10, 14, 26, 0.98), stop:1 rgba(5, 7, 13, 0.98));
                color: #E0E7FF;
                border: 2px solid #00FFFF;
                border-radius: 10px;
                gridline-color: rgba(0, 255, 255, 0.15);
                alternate-background-color: rgba(30, 41, 59, 0.2);
                font-size: 9pt;
                font-family: 'Segoe UI', sans-serif;
                selection-background-color: rgba(0, 255, 255, 0.4);
                selection-color: #FFFFFF;
                outline: none;
            }}
            QTableWidget::item {{
                padding: 4px 8px;
                color: #E0E7FF;
                border: none;
            }}
            QTableWidget::item:selected {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 rgba(0, 255, 255, 0.5), stop:1 rgba(0, 191, 255, 0.3));
                color: #FFFFFF;
                border-left: 4px solid #00FFFF;
                font-weight: 600;
            }}
            QTableWidget::item:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 rgba(0, 255, 255, 0.2), stop:1 rgba(0, 255, 255, 0.1));
            }}
            QTableWidget::item:selected:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 rgba(0, 255, 127, 0.4), stop:1 rgba(0, 255, 255, 0.4));
                color: #FFFFFF;
                border-left: 4px solid #00FF7F;
            }}
            QHeaderView::section {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #1E293B, stop:1 #0F172A);
                color: #00FFFF;
                border: none;
                border-right: 1px solid #334155;
                border-bottom: 2px solid #00FFFF;
                padding: 8px 10px;
                font-weight: 700;
                font-size: 10px;
                font-family: 'Segoe UI', sans-serif;
                text-transform: uppercase;
                letter-spacing: 1px;
            }}
            QHeaderView::section:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #334155, stop:1 #1E293B);
                color: #FFFFFF;
                border-bottom: 2px solid #00FF7F;
            }}
            QHeaderView::down-arrow {{
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid {Colors.ACCENT_CYAN};
                margin-right: 8px;
            }}
            QHeaderView::up-arrow {{
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-bottom: 5px solid {Colors.ACCENT_CYAN};
                margin-right: 8px;
            }}
            QHeaderView::up-arrow {{
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-bottom: 4px solid {Colors.ACCENT_CYAN};
                margin-right: 6px;
            }}
        """)
        
        # Progress bar style - Cyberpunk Loading Animation
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 rgba(18, 18, 24, 0.9), stop:1 rgba(26, 26, 46, 0.9));
                border: 2px solid {Colors.ACCENT_BLUE};
                border-radius: 6px;
                text-align: center;
                color: {Colors.ACCENT_CYAN};
                font-size: 9pt;
                font-weight: bold;
                font-family: 'Consolas', 'Courier New', monospace;
                min-height: 24px;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 {Colors.ACCENT_CYAN},
                    stop:0.5 {Colors.SUCCESS},
                    stop:1 {Colors.ACCENT_CYAN}
                );
                border-radius: 4px;
                margin: 2px;
            }}
        """)
    
    # ========================================================================
    # Database Tree Population (Task 4.2)
    # ========================================================================
    
    def _load_available_databases(self):
        """
        Load and populate the database tree with discovered databases using enhanced metadata.
        Displays GUI tab names, load status indicators, and timestamp support badges.
        
        Requirements: 2.4, 2.5, 3.3, 5.2, 5.7, 6.4, 10.1, 10.2, 10.3, 10.4, 10.5, 10.7, 10.8, 10.9, 10.10
        """
        if not self.search_engine:
            self.logger.warning("Cannot load databases - search engine not initialized")
            return
        
        try:
            # Import DatabaseDiscoveryManager
            from data.database_discovery_manager import DatabaseDiscoveryManager
            
            # Get case directory from search engine
            case_directory = self.search_engine.case_directory
            
            # Create discovery manager
            discovery_manager = DatabaseDiscoveryManager(case_directory)
            
            # Discover databases with enhanced metadata
            self.logger.info("Discovering databases with enhanced metadata...")
            enhanced_databases = discovery_manager.discover_databases_with_metadata(
                verify_timestamps=True,
                sample_size=50  # Smaller sample for faster discovery
            )
            
            self.logger.info(f"Discovered {len(enhanced_databases)} databases with metadata")
            
            # Check if any databases are available
            available_count = len([db for db in enhanced_databases if db.exists and db.accessible])
            
            if available_count == 0:
                self.logger.warning("No databases available in case directory")
                self.results_info_label.setText(
                    "⚠️ No databases available. Please load forensic data first."
                )
                self.results_info_label.setStyleSheet(
                    f"color: {Colors.ERROR}; font-size: 11pt; font-weight: bold;"
                )
            
            # Clear existing tree
            self.database_tree.clear()
            
            # Group databases by GUI tab name
            grouped_by_tab = discovery_manager.get_databases_by_gui_tab()
            
            # Organize by category
            category_items: Dict[str, QtWidgets.QTreeWidgetItem] = {}
            
            for category, db_names in self.DATABASE_CATEGORIES.items():
                # Create category item
                category_item = QtWidgets.QTreeWidgetItem(self.database_tree)
                category_item.setText(0, category)
                category_item.setFlags(category_item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsTristate)
                category_item.setCheckState(0, Qt.Checked)
                category_item.setExpanded(True)
                
                # Style category item
                font = category_item.font(0)
                font.setBold(True)
                font.setPointSize(9)
                category_item.setFont(0, font)
                category_item.setForeground(0, QtGui.QBrush(QtGui.QColor(Colors.ACCENT_CYAN)))
                
                category_items[category] = category_item
                
                # Track which GUI tabs we've added to avoid duplicates
                added_gui_tabs = set()
                
                # Add databases in this category
                for db_name in db_names:
                    # Find enhanced database info
                    db_info = next((db for db in enhanced_databases if db.name == db_name), None)
                    
                    if db_info:
                        # Check if we've already added this GUI tab
                        if db_info.gui_tab_name not in added_gui_tabs:
                            # Get all databases that map to this GUI tab in this category
                            tab_databases = [
                                db for db in enhanced_databases 
                                if db.gui_tab_name == db_info.gui_tab_name and db.name in db_names
                            ]
                            
                            self._add_enhanced_database_item(category_item, tab_databases)
                            added_gui_tabs.add(db_info.gui_tab_name)
            
            # Expand all categories
            self.database_tree.expandAll()
            
            # Show warning if no databases available
            if available_count == 0:
                QtWidgets.QMessageBox.warning(
                    self,
                    "No Databases Available",
                    "No forensic artifact databases were found in the case directory.\n\n"
                    "Please ensure you have:\n"
                    "1. Loaded a case directory\n"
                    "2. Collected forensic artifacts\n"
                    "3. Parsed the artifacts into databases"
                )
            
            self.logger.info("Database tree populated with enhanced metadata")
            
        except Exception as e:
            self.logger.error(f"Failed to load databases: {e}", exc_info=True)
            QtWidgets.QMessageBox.warning(
                self,
                "Database Loading Error",
                f"Failed to load databases:\n{str(e)}"
            )
    
    def _add_enhanced_database_item(
        self,
        parent_item: QtWidgets.QTreeWidgetItem,
        databases: List
    ):
        """
        Add an enhanced database item to the tree with GUI name mapping and status indicators.
        
        Consolidates multiple database files that map to the same GUI tab.
        Shows load status, timestamp support, and enhanced tooltips.
        
        Args:
            parent_item: Parent category item
            databases: List of EnhancedDatabaseInfo objects that map to the same GUI tab
            
        Requirements: 2.4, 2.5, 3.3, 5.2, 5.7, 6.4, 10.1, 10.2, 10.3, 10.4, 10.5, 10.7, 10.8, 10.9, 10.10
        """
        if not databases:
            return
        
        # Use the first database's GUI tab name
        gui_tab_name = databases[0].gui_tab_name
        
        # Check if any database is accessible
        accessible_dbs = [db for db in databases if db.accessible and db.exists]
        has_accessible = len(accessible_dbs) > 0
        
        # Check if any database supports time filtering
        supports_time_filter = any(db.supports_time_filtering() for db in accessible_dbs)
        
        # Check if GUI tab is loaded (query from integration if available)
        is_loaded = self._is_gui_tab_loaded(gui_tab_name)
        
        # Create database item with GUI tab name
        db_item = QtWidgets.QTreeWidgetItem(parent_item)
        db_item.setText(0, gui_tab_name)
        db_item.setFlags(db_item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsTristate)
        
        # Build status text with indicators
        status_parts = []
        
        if has_accessible:
            if is_loaded:
                status_parts.append("✓ Loaded")
                db_item.setForeground(0, QtGui.QBrush(QtGui.QColor(Colors.SUCCESS)))
            else:
                status_parts.append("○ Not Loaded")
                db_item.setForeground(0, QtGui.QBrush(QtGui.QColor(Colors.TEXT_MUTED)))
            
            if supports_time_filter:
                status_parts.append("🕐 Time Filter")
            
            # Count total tables
            total_tables = sum(len(db.tables) for db in accessible_dbs)
            status_parts.append(f"{total_tables} tables")
            
            db_item.setCheckState(0, Qt.Checked)
        else:
            status_parts.append("⚠️ Not Available")
            db_item.setCheckState(0, Qt.Unchecked)
            db_item.setFlags(db_item.flags() & ~Qt.ItemIsEnabled)
            db_item.setForeground(0, QtGui.QBrush(QtGui.QColor(Colors.TEXT_MUTED)))
        
        db_item.setText(1, " | ".join(status_parts))
        
        # Build enhanced tooltip
        tooltip_lines = [f"GUI Tab: {gui_tab_name}"]
        tooltip_lines.append("")
        tooltip_lines.append("Database Files:")
        for db in databases:
            if db.exists:
                tooltip_lines.append(f"  • {db.name}")
            else:
                tooltip_lines.append(f"  • {db.name} (missing)")
        
        tooltip_lines.append("")
        tooltip_lines.append(f"Load Status: {'Loaded in GUI' if is_loaded else 'Not loaded in GUI'}")
        
        if has_accessible:
            tooltip_lines.append(f"Timestamp Support: {'Yes' if supports_time_filter else 'No'}")
            tooltip_lines.append(f"Total Tables: {total_tables}")
            
            # Show row counts if available
            total_rows = sum(
                sum(table.row_count or 0 for table in db.tables.values())
                for db in accessible_dbs
            )
            if total_rows > 0:
                tooltip_lines.append(f"Total Rows: {total_rows:,}")
        
        if not has_accessible:
            tooltip_lines.append("")
            tooltip_lines.append("⚠️ Database files not found or not accessible")
        
        tooltip_text = "\n".join(tooltip_lines)
        db_item.setToolTip(0, tooltip_text)
        db_item.setToolTip(1, tooltip_text)
        
        # Store all database infos
        db_item.setData(0, Qt.UserRole, databases)
        
        # Add table items if accessible
        if has_accessible:
            # Collect all unique tables across all databases
            all_tables = {}
            for db in accessible_dbs:
                for table_name, table_info in db.tables.items():
                    if table_name not in all_tables:
                        all_tables[table_name] = table_info
            
            # Add table items
            for table_name, table_info in sorted(all_tables.items()):
                table_item = QtWidgets.QTreeWidgetItem(db_item)
                
                # Simplify table name for display
                display_name = table_name.replace('_', ' ').title()
                if display_name.endswith(' Table'):
                    display_name = display_name[:-6]
                
                table_item.setText(0, display_name)
                table_item.setFlags(table_item.flags() | Qt.ItemIsUserCheckable)
                table_item.setCheckState(0, Qt.Checked)
                
                # Add timestamp indicator if table supports time filtering
                if table_info.supports_time_filtering:
                    table_item.setText(1, "🕐")
                
                # Build table tooltip
                table_tooltip_lines = [f"Table: {table_name}"]
                if table_info.row_count is not None:
                    table_tooltip_lines.append(f"Rows: {table_info.row_count:,}")
                if table_info.timestamp_columns:
                    table_tooltip_lines.append(f"Timestamp Columns: {len(table_info.timestamp_columns)}")
                    for ts_col in table_info.timestamp_columns[:3]:  # Show first 3
                        table_tooltip_lines.append(f"  • {ts_col.name} ({ts_col.format})")
                
                table_item.setToolTip(0, "\n".join(table_tooltip_lines))
                
                # Store table info
                table_item.setData(0, Qt.UserRole, (table_name, table_info))
    
    def _is_gui_tab_loaded(self, gui_tab_name: str) -> bool:
        """
        Check if a GUI tab has loaded data.
        
        Queries the DatabaseSearchIntegration if available to determine
        if the specified GUI tab currently has data loaded.
        
        Args:
            gui_tab_name: Name of the GUI tab to check
            
        Returns:
            True if tab is loaded, False otherwise
            
        Requirements: 6.4, 10.7
        """
        # Try multiple ways to get the integration
        integration = None
        
        # Method 1: Check if parent has search_integration attribute
        if hasattr(self.parent(), 'search_integration'):
            integration = self.parent().search_integration
        
        # Method 2: Check if parent has main_window with search_integration
        elif hasattr(self.parent(), 'main_window'):
            main_window = self.parent().main_window
            if hasattr(main_window, 'search_integration'):
                integration = main_window.search_integration
        
        # Method 3: Try to import and get global instance
        if not integration:
            try:
                from ui.database_search_integration import DatabaseSearchIntegration
                # Check if there's a global instance or singleton
                # For now, we'll assume tabs are loaded if we can't determine
                # This prevents false "Not Loaded" indicators
                self.logger.debug(f"Cannot determine load status for {gui_tab_name}, assuming loaded")
                return True
            except Exception:
                pass
        
        # If we have integration, check if tab is loaded
        if integration and hasattr(integration, 'is_tab_loaded'):
            is_loaded = integration.is_tab_loaded(gui_tab_name)
            self.logger.debug(f"Tab '{gui_tab_name}' load status: {is_loaded}")
            return is_loaded
        
        # Default to True (assume loaded) if we can't determine
        # This prevents false "Not Loaded" indicators when integration isn't available
        return True
    
    def update_database_tree_indicators(self):
        """
        Update database tree indicators to reflect current GUI tab load states.
        
        This method updates the status indicators (✓ Loaded / ○ Not Loaded) for
        all database items in the tree without reloading the entire tree structure.
        Called when tabs load/unload data to keep the tree in sync.
        
        Requirements: 10.7
        """
        try:
            if not self.database_tree:
                return
            
            self.logger.debug("Updating database tree indicators")
            
            # Iterate through all database items in the tree
            root = self.database_tree.invisibleRootItem()
            for i in range(root.childCount()):
                category_item = root.child(i)
                for j in range(category_item.childCount()):
                    db_item = category_item.child(j)
                    
                    # Get the GUI tab name
                    gui_tab_name = db_item.text(0)
                    
                    # Check if database is accessible
                    db_data = db_item.data(0, Qt.UserRole)
                    if not db_data:
                        continue
                    
                    # Handle enhanced database info (list of EnhancedDatabaseInfo)
                    accessible_dbs = []
                    if isinstance(db_data, list):
                        accessible_dbs = [db for db in db_data if db.accessible and db.exists]
                    
                    if not accessible_dbs:
                        continue
                    
                    # Check if GUI tab is loaded
                    is_loaded = self._is_gui_tab_loaded(gui_tab_name)
                    
                    # Check if supports time filtering
                    supports_time_filter = any(db.supports_time_filtering() for db in accessible_dbs)
                    
                    # Update status text
                    status_parts = []
                    
                    if is_loaded:
                        status_parts.append("✓ Loaded")
                        db_item.setForeground(0, QtGui.QBrush(QtGui.QColor(Colors.SUCCESS)))
                    else:
                        status_parts.append("○ Not Loaded")
                        db_item.setForeground(0, QtGui.QBrush(QtGui.QColor(Colors.TEXT_MUTED)))
                    
                    if supports_time_filter:
                        status_parts.append("🕐 Time Filter")
                    
                    # Count total tables
                    total_tables = sum(len(db.tables) for db in accessible_dbs)
                    status_parts.append(f"{total_tables} tables")
                    
                    db_item.setText(1, " | ".join(status_parts))
                    
                    # Update tooltip
                    tooltip_lines = [f"GUI Tab: {gui_tab_name}"]
                    tooltip_lines.append("")
                    tooltip_lines.append("Database Files:")
                    for db in db_data if isinstance(db_data, list) else [db_data]:
                        if hasattr(db, 'name'):
                            if hasattr(db, 'exists') and db.exists:
                                tooltip_lines.append(f"  • {db.name}")
                            else:
                                tooltip_lines.append(f"  • {db.name} (missing)")
                    
                    tooltip_lines.append("")
                    tooltip_lines.append(f"Load Status: {'Loaded in GUI' if is_loaded else 'Not loaded in GUI'}")
                    tooltip_lines.append(f"Timestamp Support: {'Yes' if supports_time_filter else 'No'}")
                    tooltip_lines.append(f"Total Tables: {total_tables}")
                    
                    # Show row counts if available
                    total_rows = sum(
                        sum(table.row_count or 0 for table in db.tables.values())
                        for db in accessible_dbs
                    )
                    if total_rows > 0:
                        tooltip_lines.append(f"Total Rows: {total_rows:,}")
                    
                    tooltip_text = "\n".join(tooltip_lines)
                    db_item.setToolTip(0, tooltip_text)
                    db_item.setToolTip(1, tooltip_text)
            
            self.logger.debug("Database tree indicators updated successfully")
            
        except Exception as e:
            self.logger.warning(f"Error updating database tree indicators: {e}")
    
    def _add_database_item(self, parent_item: QtWidgets.QTreeWidgetItem, db_info: DatabaseInfo):
        """
        Add a database item to the tree with status indicators.
        
        DEPRECATED: Use _add_enhanced_database_item instead for new implementations.
        This method is kept for backward compatibility.
        
        Args:
            parent_item: Parent category item
            db_info: Database information object
        """
        # Create database item
        db_item = QtWidgets.QTreeWidgetItem(parent_item)
        db_item.setText(0, db_info.display_name)
        db_item.setFlags(db_item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsTristate)
        
        # Set status and icon with warning indicators
        if not db_info.exists:
            db_item.setCheckState(0, Qt.Unchecked)
            db_item.setText(1, "⚠️ Missing")
            db_item.setForeground(1, QtGui.QBrush(QtGui.QColor(Colors.TEXT_MUTED)))
            db_item.setToolTip(0, f"Database file not found: {db_info.name}")
            db_item.setToolTip(1, f"Database file not found: {db_info.name}")
            db_item.setFlags(db_item.flags() & ~Qt.ItemIsEnabled)
        elif not db_info.accessible:
            db_item.setCheckState(0, Qt.Unchecked)
            db_item.setText(1, "⚠️ Error")
            db_item.setForeground(1, QtGui.QBrush(QtGui.QColor(Colors.ERROR)))
            error_msg = db_info.error or "Database cannot be accessed"
            db_item.setToolTip(0, f"Database error: {error_msg}")
            db_item.setToolTip(1, f"Database error: {error_msg}")
            db_item.setFlags(db_item.flags() & ~Qt.ItemIsEnabled)
            self.logger.warning(f"Database {db_info.name} is not accessible: {error_msg}")
        else:
            db_item.setCheckState(0, Qt.Checked)
            db_item.setText(1, f"✓ Available ({len(db_info.tables)} tables)")
            db_item.setForeground(1, QtGui.QBrush(QtGui.QColor(Colors.SUCCESS)))
            db_item.setToolTip(0, f"Database ready: {len(db_info.tables)} tables available")
            db_item.setToolTip(1, f"Database ready: {len(db_info.tables)} tables available")
        
        # Store database info
        db_item.setData(0, Qt.UserRole, db_info)
        
        # Add table items if accessible
        if db_info.accessible and db_info.tables:
            for table_name in db_info.tables:
                table_item = QtWidgets.QTreeWidgetItem(db_item)
                table_item.setText(0, table_name)
                table_item.setFlags(table_item.flags() | Qt.ItemIsUserCheckable)
                table_item.setCheckState(0, Qt.Checked)
                table_item.setData(0, Qt.UserRole, table_name)
    
    def _select_all_databases(self):
        """Select all available databases and tables."""
        root = self.database_tree.invisibleRootItem()
        for i in range(root.childCount()):
            category_item = root.child(i)
            category_item.setCheckState(0, Qt.Checked)
            for j in range(category_item.childCount()):
                db_item = category_item.child(j)
                if db_item.flags() & Qt.ItemIsEnabled:
                    db_item.setCheckState(0, Qt.Checked)
    
    def _deselect_all_databases(self):
        """Deselect all databases and tables."""
        root = self.database_tree.invisibleRootItem()
        for i in range(root.childCount()):
            category_item = root.child(i)
            category_item.setCheckState(0, Qt.Unchecked)
            for j in range(category_item.childCount()):
                db_item = category_item.child(j)
                db_item.setCheckState(0, Qt.Unchecked)
    
    def _select_loaded_only(self):
        """
        Select only databases with loaded GUI tabs.
        
        Queries GUI tab state from DatabaseSearchIntegration and checks
        only those databases that have corresponding loaded tabs.
        
        Requirements: 10.8
        """
        # First deselect all
        self._deselect_all_databases()
        
        # Iterate through tree and select only loaded databases
        root = self.database_tree.invisibleRootItem()
        for i in range(root.childCount()):
            category_item = root.child(i)
            for j in range(category_item.childCount()):
                db_item = category_item.child(j)
                
                # Check if this database is enabled
                if not (db_item.flags() & Qt.ItemIsEnabled):
                    continue
                
                # Get the GUI tab name from the item text
                gui_tab_name = db_item.text(0)
                
                # Check if this tab is loaded
                if self._is_gui_tab_loaded(gui_tab_name):
                    db_item.setCheckState(0, Qt.Checked)
                    self.logger.debug(f"Selected loaded database: {gui_tab_name}")
        
        self.logger.info("Selected only databases with loaded GUI tabs")
    
    def _get_selected_databases_and_tables(self) -> Dict[str, List[str]]:
        """
        Get selected databases and their tables.
        
        Works with both legacy DatabaseInfo and enhanced EnhancedDatabaseInfo structures.
        
        Returns:
            Dictionary mapping database names to lists of selected table names
        """
        selected: Dict[str, List[str]] = {}
        
        root = self.database_tree.invisibleRootItem()
        for i in range(root.childCount()):
            category_item = root.child(i)
            for j in range(category_item.childCount()):
                db_item = category_item.child(j)
                
                # Check if database is selected
                if db_item.checkState(0) == Qt.Checked or db_item.checkState(0) == Qt.PartiallyChecked:
                    db_data = db_item.data(0, Qt.UserRole)
                    
                    # Handle enhanced database info (list of EnhancedDatabaseInfo)
                    if isinstance(db_data, list):
                        # Multiple databases map to same GUI tab
                        for db_info in db_data:
                            if hasattr(db_info, 'name') and hasattr(db_info, 'accessible'):
                                if db_info.accessible:
                                    db_name = db_info.name
                                    selected[db_name] = []
                                    
                                    # Get selected tables
                                    for k in range(db_item.childCount()):
                                        table_item = db_item.child(k)
                                        if table_item.checkState(0) == Qt.Checked:
                                            table_data = table_item.data(0, Qt.UserRole)
                                            # Table data is (table_name, table_info) tuple
                                            if isinstance(table_data, tuple) and len(table_data) >= 1:
                                                table_name = table_data[0]
                                                # Only add if this table exists in this database
                                                if hasattr(db_info, 'tables') and table_name in db_info.tables:
                                                    selected[db_name].append(table_name)
                                            elif isinstance(table_data, str):
                                                # Legacy format
                                                selected[db_name].append(table_data)
                    
                    # Handle legacy database info (single DatabaseInfo)
                    elif hasattr(db_data, 'name'):
                        db_name = db_data.name
                        selected[db_name] = []
                        
                        # Get selected tables
                        for k in range(db_item.childCount()):
                            table_item = db_item.child(k)
                            if table_item.checkState(0) == Qt.Checked:
                                table_data = table_item.data(0, Qt.UserRole)
                                if isinstance(table_data, tuple) and len(table_data) >= 1:
                                    table_name = table_data[0]
                                    selected[db_name].append(table_name)
                                elif isinstance(table_data, str):
                                    selected[db_name].append(table_data)
        
        return selected
    
    # ========================================================================
    # Search History UI (Task 8.1, 8.2)
    # ========================================================================
    
    def _load_search_history(self):
        """
        Load search history and populate the history combo box.
        
        Retrieves recent searches from the search engine and displays them
        in the history dropdown with search term, timestamp, and time filter info.
        
        Requirements: 7.2, 11.2
        """
        if not self.search_engine:
            self.logger.debug("Cannot load search history - search engine not initialized")
            return
        
        try:
            # Block signals while populating to avoid triggering handlers during init
            self.history_combo.blockSignals(True)
            
            # Clear existing items (except the placeholder)
            self.history_combo.clear()
            self.history_combo.addItem("-- Select a recent search --")
            
            # Get search history from engine
            history = self.search_engine.get_search_history()
            
            if not history:
                self.logger.debug("No search history available")
                return
            
            # Populate combo box with history entries
            for entry in history:
                # Format display text: "search_term (timestamp) [time_filter]"
                # Parse timestamp to make it more readable
                try:
                    from datetime import datetime
                    timestamp = datetime.fromisoformat(entry.timestamp)
                    time_str = timestamp.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    time_str = entry.timestamp[:16]  # Fallback to first 16 chars
                
                # Truncate long search terms
                term = entry.term
                if len(term) > 40:
                    term = term[:37] + "..."
                
                display_text = f"{term} ({time_str})"
                
                # Add time filter indicator if present
                if hasattr(entry, 'start_time') and (entry.start_time or entry.end_time):
                    if hasattr(entry, 'time_preset') and entry.time_preset and entry.time_preset != 'custom':
                        # Show preset name
                        preset_display = entry.time_preset.replace('_', ' ').title()
                        display_text += f" [🕐 {preset_display}]"
                    else:
                        # Show custom time range indicator
                        display_text += " [🕐 Custom]"
                
                # Add item with entry data stored in UserRole
                self.history_combo.addItem(display_text)
                self.history_combo.setItemData(
                    self.history_combo.count() - 1,
                    entry,
                    Qt.UserRole
                )
            
            self.logger.info(f"Loaded {len(history)} search history entries")
            
        except Exception as e:
            self.logger.error(f"Error loading search history: {e}", exc_info=True)
        finally:
            # Re-enable signals after populating
            self.history_combo.blockSignals(False)
    
    def _on_history_selected(self, index: int):
        """
        Handle selection of a history item from the combo box.
        
        Populates search fields with the selected history entry's parameters,
        including search term, options, selected databases/tables, and time filter state.
        
        Args:
            index: Index of selected item in combo box
        
        Requirements: 7.3, 11.2
        """
        # Ignore the placeholder item (index 0)
        if index <= 0:
            return
        
        try:
            # Get the history entry from item data
            entry = self.history_combo.itemData(index, Qt.UserRole)
            
            if not entry:
                self.logger.warning(f"No history entry data for index {index}")
                return
            
            self.logger.info(f"Loading history entry: '{entry.term}'")
            
            # Populate search term
            self.search_input.setText(entry.term)
            
            # Set search options
            self.case_sensitive_checkbox.setChecked(entry.case_sensitive)
            self.exact_match_checkbox.setChecked(entry.exact_match)
            self.regex_checkbox.setChecked(entry.use_regex)
            
            # Restore database and table selections
            self._restore_database_selection(entry.databases, entry.tables)
            
            # Restore time filter state
            if hasattr(self, 'time_filter_widget'):
                if hasattr(entry, 'start_time') and (entry.start_time or entry.end_time):
                    from datetime import datetime
                    start_dt = None
                    end_dt = None
                    
                    if entry.start_time:
                        try:
                            start_dt = datetime.fromisoformat(entry.start_time)
                        except Exception as e:
                            self.logger.warning(f"Failed to parse start_time from history: {e}")
                    
                    if entry.end_time:
                        try:
                            end_dt = datetime.fromisoformat(entry.end_time)
                        except Exception as e:
                            self.logger.warning(f"Failed to parse end_time from history: {e}")
                    
                    if start_dt or end_dt:
                        self.time_filter_widget.set_time_range(start_dt, end_dt)
                        self.logger.debug(f"Restored time filter: {start_dt} to {end_dt}")
                else:
                    # No time filter in history, disable filter
                    self.time_filter_widget.group_box.setChecked(False)
            
            # Reset combo box to placeholder
            self.history_combo.setCurrentIndex(0)
            
            self.logger.debug("Successfully restored search parameters from history")
            
        except Exception as e:
            self.logger.error(f"Error loading history entry: {e}", exc_info=True)
            QtWidgets.QMessageBox.warning(
                self,
                "History Load Error",
                f"Failed to load search from history:\n{str(e)}"
            )
    
    def _restore_database_selection(
        self,
        databases: List[str],
        tables: Dict[str, List[str]]
    ):
        """
        Restore database and table selections from history or saved search.
        
        Args:
            databases: List of database names that were selected
            tables: Dictionary mapping database names to selected table lists
        """
        # First, deselect all
        self._deselect_all_databases()
        
        # Iterate through tree and select matching databases/tables
        root = self.database_tree.invisibleRootItem()
        for i in range(root.childCount()):
            category_item = root.child(i)
            for j in range(category_item.childCount()):
                db_item = category_item.child(j)
                db_info = db_item.data(0, Qt.UserRole)
                
                if isinstance(db_info, DatabaseInfo) and db_info.name in databases:
                    # Get tables for this database
                    db_tables = tables.get(db_info.name, [])
                    
                    if not db_tables:
                        # If no specific tables, select all
                        db_item.setCheckState(0, Qt.Checked)
                    else:
                        # Select specific tables
                        for k in range(db_item.childCount()):
                            table_item = db_item.child(k)
                            table_name = table_item.data(0, Qt.UserRole)
                            
                            if isinstance(table_name, str) and table_name in db_tables:
                                table_item.setCheckState(0, Qt.Checked)
                            else:
                                table_item.setCheckState(0, Qt.Unchecked)
    
    # ========================================================================
    # Results Display (Task 4.3)
    # ========================================================================
    
    def _populate_results_table(self, results: List[SearchResult], search_time: float, truncated: bool = False, time_filter_active: bool = False, start_time=None, end_time=None):
        """
        Populate the results table with search results, including timestamp display when time filtering is active.
        
        Args:
            results: List of SearchResult objects
            search_time: Time taken for search in seconds
            truncated: Whether results were truncated
            time_filter_active: Whether time filtering was used
            start_time: Start datetime for time filter (if active)
            end_time: End datetime for time filter (if active)
            
        Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.7, 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7, 12.8, 12.10
        """
        try:
            self.logger.info(f"Populating results table with {len(results)} results (time_filter_active={time_filter_active})")
            
            # Clear existing results
            self.results_table.setRowCount(0)
            self.results_table.setSortingEnabled(False)
            
            # Show/hide timestamp column based on time filter state
            self.results_table.setColumnHidden(3, not time_filter_active)
            
            # Update info label with time filter info
            info_text = f"Found {len(results)} results in {search_time:.2f}s"
            
            # Add time filter parameters to summary if active
            if time_filter_active and (start_time or end_time):
                filter_parts = []
                if start_time:
                    filter_parts.append(f"from {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
                if end_time:
                    filter_parts.append(f"to {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
                
                if filter_parts:
                    info_text += f" (Filtered by time: {' '.join(filter_parts)})"
            
            self.results_info_label.setText(info_text)
            
            # Populate table
            for idx, result in enumerate(results):
                self.logger.debug(f"Processing result {idx}: {type(result)}")
                try:
                    row = self.results_table.rowCount()
                    self.results_table.insertRow(row)
                    self.logger.debug(f"Inserted row {row}")
                    
                    # Database column - with defensive checks
                    db_name = str(result.database) if hasattr(result, 'database') and result.database else "Unknown"
                    db_item = QtWidgets.QTableWidgetItem(db_name)
                    db_item.setData(Qt.UserRole, result)  # Store full result object
                    self.results_table.setItem(row, 0, db_item)
                    self.logger.debug(f"Set database: {db_name}")
                    
                    # Table column - with defensive checks
                    table_name = str(result.table) if hasattr(result, 'table') and result.table else "Unknown"
                    table_item = QtWidgets.QTableWidgetItem(table_name)
                    self.results_table.setItem(row, 1, table_item)
                    self.logger.debug(f"Set table: {table_name}")
                    
                    # Matched columns - with defensive checks
                    if hasattr(result, 'matched_columns') and result.matched_columns and isinstance(result.matched_columns, list):
                        matched_cols = ", ".join(str(col) for col in result.matched_columns[:3])
                        if len(result.matched_columns) > 3:
                            matched_cols += f" (+{len(result.matched_columns) - 3} more)"
                    else:
                        matched_cols = "N/A"
                    matched_item = QtWidgets.QTableWidgetItem(matched_cols)
                    self.results_table.setItem(row, 2, matched_item)
                    self.logger.debug(f"Set matched columns: {matched_cols}")
                    
                    # Timestamp column - only populate if time filtering is active
                    if time_filter_active:
                        timestamp_item = self._create_timestamp_item(result)
                        self.results_table.setItem(row, 3, timestamp_item)
                        self.logger.debug(f"Set timestamp: {timestamp_item.text()}")
                    
                    # Preview - with defensive checks
                    try:
                        preview = ""
                        if hasattr(result, 'match_preview') and result.match_preview:
                            preview = str(result.match_preview)
                        else:
                            # If no preview, create one from row_data
                            if hasattr(result, 'row_data') and result.row_data:
                                matched_cols = getattr(result, 'matched_columns', [])
                                preview = self._create_preview_from_data(result.row_data, matched_cols)
                        
                        # Don't truncate preview in table - let it show full text
                        preview_item = QtWidgets.QTableWidgetItem(preview)
                        
                        # Set full preview as tooltip
                        if preview:
                            preview_item.setToolTip(preview)
                        
                        # Column index is always 4 for Preview
                        # Even if timestamp column (3) is hidden, the model index remains 4
                        preview_col = 4
                        self.results_table.setItem(row, preview_col, preview_item)
                        self.logger.debug(f"Set preview: {preview[:50] if preview else '(empty)'}...")
                    except Exception as preview_error:
                        self.logger.error(f"Error setting preview: {preview_error}")
                        # Set empty preview on error
                        preview_col = 4
                        self.results_table.setItem(row, preview_col, QtWidgets.QTableWidgetItem(""))
                    
                    self.logger.info(f"Successfully added result {idx} to row {row}")
                    
                except Exception as e:
                    self.logger.error(f"Error adding result {idx} to table: {e}", exc_info=True)
                    # Continue with next result instead of crashing
                    continue
            
            # Enable sorting
            self.results_table.setSortingEnabled(True)
            
            # Enable export button if we have results
            self.export_button.setEnabled(len(results) > 0)
            
            final_row_count = self.results_table.rowCount()
            self.logger.info(f"Results table populated: {final_row_count} rows added out of {len(results)} results")
            
            if final_row_count == 0 and len(results) > 0:
                self.logger.warning("No rows were added to table despite having results!")
            
        except Exception as e:
            self.logger.error(f"Error populating results table: {e}", exc_info=True)
            self.results_info_label.setText(f"Error displaying results: {str(e)}")
            QtWidgets.QMessageBox.critical(
                self,
                "Display Error",
                f"Failed to display search results:\n{str(e)}\n\nCheck the log for details."
            )
    
    def _create_timestamp_item(self, result: SearchResult) -> QtWidgets.QTableWidgetItem:
        """
        Create a table item for displaying timestamp information.
        
        Formats timestamps in human-readable format and adds tooltips showing
        both formatted display value and original database value.
        
        Args:
            result: SearchResult object with potential matched_timestamps
            
        Returns:
            QTableWidgetItem with formatted timestamp display
            
        Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.7
        """
        timestamp_item = QtWidgets.QTableWidgetItem()
        
        # Use monospace font for timestamps
        font = timestamp_item.font()
        font.setFamily("Courier New")
        timestamp_item.setFont(font)
        
        # Check if result has matched timestamps
        if hasattr(result, 'matched_timestamps') and result.matched_timestamps:
            # Display all matching timestamps (up to 3)
            display_timestamps = []
            tooltip_lines = []
            
            for ts_match in result.matched_timestamps[:3]:
                # Format timestamp for display
                display_timestamps.append(ts_match.formatted_display)
                
                # Build tooltip showing column name, formatted value, and original value
                tooltip_lines.append(f"Column: {ts_match.column_name}")
                tooltip_lines.append(f"Formatted: {ts_match.formatted_display}")
                tooltip_lines.append(f"Original: {ts_match.original_value}")
                tooltip_lines.append(f"Format: {ts_match.format_type}")
                tooltip_lines.append("")  # Blank line between timestamps
            
            # If more than 3 timestamps matched, indicate that
            if len(result.matched_timestamps) > 3:
                display_timestamps.append(f"(+{len(result.matched_timestamps) - 3} more)")
                tooltip_lines.append(f"... and {len(result.matched_timestamps) - 3} more timestamp(s)")
            
            # Set display text
            timestamp_item.setText("\n".join(display_timestamps))
            
            # Set tooltip
            tooltip_text = "\n".join(tooltip_lines).strip()
            timestamp_item.setToolTip(tooltip_text)
            
        else:
            # No timestamp matches
            timestamp_item.setText("N/A")
            timestamp_item.setToolTip("No timestamp columns matched the filter")
        
        return timestamp_item
    
    # ========================================================================
    # Event Handlers
    # ========================================================================
    
    def _on_search_text_changed(self, text: str):
        """
        Handle search text changes.
        
        Note: Auto-search on typing is disabled. Search only triggers when
        user clicks Search button or presses Enter.
        
        Args:
            text: Current text in the search input
        """
        # No auto-search functionality - user must explicitly trigger search
        pass
    
    def _on_search_clicked(self):
        """Handle search button click."""
        # Cancel any ongoing search
        if self.search_in_progress:
            self._cancel_search()
            return
        
        # Cancel debounce timer if running
        self.debounce_timer.stop()
        self._perform_search()
    
    def _validate_search_input(self, search_term: str, use_regex: bool) -> Optional[str]:
        """
        Validate and sanitize search input to prevent SQL injection and regex errors.
        
        Args:
            search_term: The search term to validate
            use_regex: Whether regex mode is enabled
            
        Returns:
            Error message if validation fails, None if valid
        """
        # Check for empty or whitespace-only input
        if not search_term or not search_term.strip():
            return "Search term cannot be empty"
        
        # Check for excessively long search terms (potential DoS)
        if len(search_term) > 1000:
            return "Search term is too long (maximum 1000 characters)"
        
        # Validate regex pattern if regex mode is enabled
        if use_regex:
            try:
                # Try to compile the regex pattern
                re.compile(search_term)
            except re.error as e:
                # Return helpful error message
                error_msg = str(e)
                return (
                    f"Invalid regular expression pattern:\n\n{error_msg}\n\n"
                    "Please check your regex syntax or disable regex mode."
                )
            except Exception as e:
                return f"Error validating regex pattern: {str(e)}"
        
        # SQL injection prevention is handled by parameterized queries,
        # but we can check for suspicious patterns
        suspicious_patterns = [
            ';--',  # SQL comment
            'DROP TABLE',
            'DELETE FROM',
            'INSERT INTO',
            'UPDATE ',
            'CREATE TABLE',
            'ALTER TABLE',
        ]
        
        search_upper = search_term.upper()
        for pattern in suspicious_patterns:
            if pattern in search_upper:
                self.logger.warning(
                    f"Suspicious SQL pattern detected in search term: {pattern}"
                )
                # Don't block it, just log - parameterized queries will protect us
                break
        
        return None
    
    def _perform_search(self):
        """
        Perform the actual search operation using a worker thread.
        
        This method gathers search parameters, creates a worker thread,
        and starts the search execution in the background.
        
        Requirements: 1.1, 1.2, 4.5, 8.1, 8.2, 8.5, 9.1, 9.2, 9.3, 11.1, 11.2, 11.3
        """
        search_term = self.search_input.text().strip()
        
        if not search_term:
            QtWidgets.QMessageBox.warning(
                self,
                "Empty Search",
                "Please enter a search term."
            )
            return
        
        if self.search_engine is None:
            QtWidgets.QMessageBox.critical(
                self,
                "Search Engine Not Available",
                "Database search engine is not initialized.\nPlease ensure a case directory is loaded."
            )
            return
        
        # Get selected databases and tables
        selected = self._get_selected_databases_and_tables()
        
        if not selected:
            QtWidgets.QMessageBox.warning(
                self,
                "No Databases Selected",
                "Please select at least one database and table to search."
            )
            return
        
        # Get search options
        case_sensitive = self.case_sensitive_checkbox.isChecked()
        exact_match = self.exact_match_checkbox.isChecked()
        use_regex = self.regex_checkbox.isChecked()
        
        # Validate search input
        validation_error = self._validate_search_input(search_term, use_regex)
        if validation_error:
            QtWidgets.QMessageBox.warning(
                self,
                "Invalid Search Input",
                validation_error
            )
            self.logger.warning(f"Search validation failed: {validation_error}")
            return
        
        # Extract time range from time filter widget
        start_time = None
        end_time = None
        time_filter_enabled = False
        
        if hasattr(self, 'time_filter_widget'):
            time_filter_enabled = self.time_filter_widget.is_enabled()
            self.logger.info(f"Time filter widget exists, enabled={time_filter_enabled}")
            
            if time_filter_enabled:
                # Validate time filter
                is_valid, error_message = self.time_filter_widget.validate_range()
                self.logger.info(f"Time filter validation: valid={is_valid}, message='{error_message}'")
                
                if not is_valid and "error" in error_message.lower():
                    # Show validation error
                    QtWidgets.QMessageBox.warning(
                        self,
                        "Invalid Time Range",
                        error_message
                    )
                    self.logger.warning(f"Time filter validation failed: {error_message}")
                    return
                
                # Get time range
                start_time, end_time = self.time_filter_widget.get_time_range()
                
                # Debug: Read directly from widgets to verify
                widget_start = self.time_filter_widget.start_datetime.dateTime().toPyDateTime()
                widget_end = self.time_filter_widget.end_datetime.dateTime().toPyDateTime()
                
                self.logger.info(f"Time filtering enabled:")
                self.logger.info(f"  From get_time_range(): start={start_time}, end={end_time}")
                self.logger.info(f"  From widgets directly: start={widget_start}, end={widget_end}")
                self.logger.info(f"  Widget enabled state: {self.time_filter_widget.is_filter_enabled}")
                
                # Debug: Verify time values are not None
                if start_time is None or end_time is None:
                    self.logger.error(f"Time filter enabled but got None values: start={start_time}, end={end_time}")
                    QtWidgets.QMessageBox.warning(
                        self,
                        "Time Filter Error",
                        "Time filter is enabled but time values are invalid. Please check your time range settings."
                    )
                    return
            else:
                self.logger.info("Time filter is disabled, searching without time constraints")
        
        # Cancel any existing search and clean up before starting new one
        if self.search_in_progress:
            self.logger.info("Cancelling previous search before starting new one")
            self._cancel_search()
            
            # Wait for previous thread to finish
            if hasattr(self, 'thread') and self.thread is not None and self.thread.isRunning():
                self.thread.quit()
                self.thread.wait(1000)  # Wait up to 1 second
            
            # Clean up previous thread and worker
            self._cleanup_search_thread()
        
        # CRITICAL: Reset the search engine's cancellation flag before starting new search
        # Without this, if a previous search was cancelled, the new search will immediately abort
        if self.search_engine and hasattr(self.search_engine, 'reset_cancellation'):
            self.search_engine.reset_cancellation()
            self.logger.info("Reset search engine cancellation flag")
        elif self.search_engine and hasattr(self.search_engine, '_cancelled'):
            # Fallback: directly reset the flag if reset method doesn't exist
            self.search_engine._cancelled = False
            self.logger.info("Reset search engine cancellation flag (direct)")
        
        # Update UI state - show progress
        self.search_in_progress = True
        self.search_button.setVisible(False)
        self.cancel_button.setVisible(True)
        self.search_input.setEnabled(False)
        self.progress_bar.setVisible(True)
        
        # Update progress message based on time filtering
        if time_filter_enabled:
            self.progress_bar.setFormat(f"Searching for '{search_term}' with time filter...")
        else:
            self.progress_bar.setFormat(f"Searching for '{search_term}'...")
        
        # Create a new thread and worker for the search
        self.thread = QThread()
        self.worker = SearchWorker(
            search_engine=self.search_engine,
            search_term=search_term,
            databases=list(selected.keys()),
            tables=selected,
            case_sensitive=case_sensitive,
            exact_match=exact_match,
            use_regex=use_regex,
            max_results_per_table=999999,  # Effectively unlimited
            start_time=start_time,
            end_time=end_time,
            timeout_seconds=60.0
        )
        self.worker.moveToThread(self.thread)

        # Connect signals
        self.thread.started.connect(self.worker.run)
        self.worker.search_complete.connect(self._on_search_complete)
        self.worker.search_error.connect(self._on_search_error)
        self.worker.search_cancelled.connect(self._on_search_cancelled)
        self.worker.progress_update.connect(self._on_search_progress)  # Requirements: 14.3
        
        # Connect cleanup signals - thread quits after any completion signal
        self.worker.search_complete.connect(self.thread.quit)
        self.worker.search_error.connect(self.thread.quit)
        self.worker.search_cancelled.connect(self.thread.quit)
        
        # Clean up thread and worker after thread finishes
        self.thread.finished.connect(self._cleanup_search_thread)

        # Start the search
        self.thread.start()
    
    def _on_search_progress(self, message: str):
        """
        Handle progress updates from the search worker.
        
        Args:
            message: Progress message to display
        """
        self.progress_bar.setFormat(message)
        self.logger.debug(f"Search progress: {message}")
    
    def _create_preview_from_data(self, row_data: dict, matched_columns: list) -> str:
        """
        Create a preview string from row data and matched columns.
        
        Args:
            row_data: Dictionary of row data
            matched_columns: List of column names that matched
            
        Returns:
            Preview string showing matched column values or column names
        """
        try:
            if not row_data:
                if matched_columns:
                    # Show column names if no data available
                    cols = ", ".join(str(col) for col in matched_columns[:3])
                    if len(matched_columns) > 3:
                        cols += f" (+{len(matched_columns) - 3} more)"
                    return f"Matched in: {cols}"
                return "No data available"
            
            # If matched_columns is empty, show first few columns with data
            columns_to_show = matched_columns if matched_columns else list(row_data.keys())
            
            # Create preview from first few columns with data
            preview_parts = []
            for col in columns_to_show[:3]:  # Limit to first 3 columns
                if col in row_data and row_data[col] is not None:
                    value = str(row_data[col])
                    # Truncate long values
                    if len(value) > 100:
                        value = value[:97] + "..."
                    preview_parts.append(f"{col}: {value}")
            
            if preview_parts:
                return " | ".join(preview_parts)
            else:
                # Data exists but no values in columns
                if matched_columns:
                    cols = ", ".join(str(col) for col in matched_columns[:3])
                    if len(matched_columns) > 3:
                        cols += f" (+{len(matched_columns) - 3} more)"
                    return f"Matched in: {cols}"
                return "No preview available"
            
        except Exception as e:
            self.logger.error(f"Error creating preview from data: {e}")
            return "Preview unavailable"
    
    def _create_preview(self, result) -> str:
        """
        Create a preview string from a search result.
        
        Args:
            result: SearchResult object
            
        Returns:
            Preview string showing matched column values or column names
        """
        try:
            matched_columns = getattr(result, 'matched_columns', [])
            
            # Try multiple data attributes (record_data or row_data)
            record_data = getattr(result, 'record_data', None)
            if not record_data:
                record_data = getattr(result, 'row_data', {})
            
            return self._create_preview_from_data(record_data, matched_columns)
            
        except Exception as e:
            self.logger.error(f"Error creating preview: {e}")
            return "Preview unavailable"
    
    def _on_search_complete(self, results, search_time: float):
        """
        Handle search completion from the worker thread.
        
        Args:
            results: List of SearchResults objects (one per database)
            search_time: Time taken for search in seconds
        """
        try:
            self.logger.info(f"Search completed: {len(results)} SearchResults objects in {search_time:.2f}s")
            
            # Flatten results from List[SearchResults] to List[SearchResult]
            # and convert to the format expected by the UI
            flat_results = []
            for idx, search_results in enumerate(results):
                # Get database name from the SearchResults container
                database_name = getattr(search_results, 'database_name', 'Unknown')
                
                # Get all individual results
                individual_results = []
                if hasattr(search_results, 'get_all_results'):
                    individual_results = search_results.get_all_results()
                elif hasattr(search_results, 'results'):
                    # Fallback: manually flatten the results dict
                    for table_name, table_results in search_results.results.items():
                        individual_results.extend(table_results)
                
                # Convert each result to include database info and create preview
                for result_idx, result in enumerate(individual_results):
                    # Get row data from result
                    row_data = getattr(result, 'record_data', None)
                    if not row_data:
                        row_data = getattr(result, 'row_data', {})
                    
                    # Try to extract row_id if not already set
                    row_id = getattr(result, 'row_id', None)
                    if row_id is None and row_data:
                        # Try common ID column names
                        for id_col in ['id', 'ID', 'rowid', 'ROWID', '_rowid_', 'Id', 'row_id', 'ROW_ID']:
                            if id_col in row_data and row_data[id_col] is not None:
                                row_id = row_data[id_col]
                                break
                    
                    # Get matched columns
                    matched_columns = getattr(result, 'matched_columns', [])
                    
                    # Create preview from row_data and matched_columns
                    preview = self._create_preview_from_data(row_data, matched_columns)
                    
                    # Get table name - handle both 'table' and 'table_name' attributes
                    table_name = getattr(result, 'table', None)
                    if not table_name:
                        table_name = getattr(result, 'table_name', 'Unknown')
                    
                    # Get matched timestamps
                    matched_timestamps = getattr(result, 'matched_timestamps', None)
                    
                    if result_idx < 3:  # Log first 3 results for debugging
                        print(f"[UI]   Converting result {result_idx}: table={table_name}, row_id={row_id}, "
                              f"matched_cols={len(matched_columns)}, timestamps={len(matched_timestamps) if matched_timestamps else 0}")
                    
                    # Create a converted result with the expected structure using static class
                    converted_result = UISearchResult(
                        database=database_name,
                        table=table_name,
                        row_id=row_id,
                        matched_columns=matched_columns,
                        row_data=row_data,
                        match_preview=preview,
                        matched_timestamps=matched_timestamps
                    )
                    flat_results.append(converted_result)
            
            print(f"[UI] Flattened to {len(flat_results)} individual results")
            self.logger.info(f"Flattened to {len(flat_results)} individual results")
            
            # Store and display results
            self.current_results = flat_results
            truncated = len(flat_results) >= 1000  # Simple truncation check
            
            # Check if time filtering was active
            time_filter_active = False
            start_time = None
            end_time = None
            
            try:
                if hasattr(self, 'time_filter_widget') and self.time_filter_widget:
                    time_filter_active = self.time_filter_widget.is_enabled()
                    if time_filter_active:
                        start_time, end_time = self.time_filter_widget.get_time_range()
            except Exception as e:
                self.logger.warning(f"Error checking time filter status: {e}")
                time_filter_active = False
            
            self._populate_results_table(
                flat_results, 
                search_time, 
                truncated,
                time_filter_active=time_filter_active,
                start_time=start_time,
                end_time=end_time
            )
            
            # Add search to history
            if self.search_engine:
                try:
                    search_term = self.search_input.text().strip()
                    selected = self._get_selected_databases_and_tables()
                    
                    # Get time filter parameters
                    start_time_str = None
                    end_time_str = None
                    time_preset = None
                    
                    if hasattr(self, 'time_filter_widget') and self.time_filter_widget.is_enabled():
                        start_time, end_time = self.time_filter_widget.get_time_range()
                        if start_time:
                            start_time_str = start_time.isoformat()
                        if end_time:
                            end_time_str = end_time.isoformat()
                        time_preset = self.time_filter_widget.current_preset
                    
                    self.search_engine.history_manager.save_history(
                        term=search_term,
                        databases=list(selected.keys()),
                        tables=selected,
                        case_sensitive=self.case_sensitive_checkbox.isChecked(),
                        exact_match=self.exact_match_checkbox.isChecked(),
                        use_regex=self.regex_checkbox.isChecked(),
                        start_time=start_time_str,
                        end_time=end_time_str,
                        time_preset=time_preset
                    )
                    
                    # Reload history dropdown
                    self._load_search_history()
                    
                except Exception as e:
                    self.logger.error(f"Failed to save search to history: {e}", exc_info=True)

            # Restore UI state
            self.search_in_progress = False
            self.search_button.setVisible(True)
            self.cancel_button.setVisible(False)
            self.search_input.setEnabled(True)
            self.progress_bar.setVisible(False)
            
        except BaseException as e:
            self.logger.error(f"Error in _on_search_complete: {e}", exc_info=True)
            print(f"[UI] Critical error in _on_search_complete: {e}")
            import traceback
            traceback.print_exc()
            self._on_search_error(f"Error processing results: {str(e)}")
    
    def _on_search_error(self, error_message: str):
        """
        Handle search errors from the worker thread.
        
        Args:
            error_message: Error message to display
        """
        self.logger.error(f"Search error: {error_message}")
        self.results_info_label.setText(f"Error: {error_message}")

        # Restore UI state
        self.search_in_progress = False
        self.search_button.setVisible(True)
        self.cancel_button.setVisible(False)
        self.search_input.setEnabled(True)
        self.progress_bar.setVisible(False)
        
        # Show error dialog
        QtWidgets.QMessageBox.critical(
            self,
            "Search Error",
            f"An error occurred during search:\n{error_message}"
        )
        
        self.results_info_label.setText(f"Search failed: {error_message}")
    
    def _on_search_cancelled(self):
        """Handle search cancellation from the worker thread."""
        self.logger.info("Search was cancelled")
        self.results_info_label.setText("Search cancelled")

        # Restore UI state
        self.search_in_progress = False
        self.search_button.setVisible(True)
        self.cancel_button.setVisible(False)
        self.search_input.setEnabled(True)
        self.progress_bar.setVisible(False)
    
    def _cleanup_search_thread(self):
        """
        Clean up the search thread and worker after search completes.
        
        This method is called when the thread finishes to properly clean up
        resources and prevent crashes from accessing deleted objects.
        """
        try:
            # Disconnect all signals first to prevent callbacks during cleanup
            if hasattr(self, 'worker') and self.worker is not None:
                try:
                    self.worker.search_complete.disconnect()
                    self.worker.search_error.disconnect()
                    self.worker.search_cancelled.disconnect()
                    self.worker.progress_update.disconnect()
                except (TypeError, RuntimeError):
                    pass  # Signals already disconnected or object deleted
                
                self.worker.deleteLater()
                self.worker = None
            
            if hasattr(self, 'thread') and self.thread is not None:
                try:
                    self.thread.started.disconnect()
                    self.thread.finished.disconnect()
                except (TypeError, RuntimeError):
                    pass  # Signals already disconnected or object deleted
                
                self.thread.deleteLater()
                self.thread = None
                
            self.logger.debug("Search thread and worker cleaned up successfully")
        except Exception as e:
            self.logger.error(f"Error during thread cleanup: {e}", exc_info=True)
    
    def _cancel_search(self):
        """
        Cancel the current search operation.
        
        This method cancels the worker thread and updates the UI state.
        The worker thread will stop at the next checkpoint.
        """
        if self.search_in_progress and self.search_engine:
            self.logger.info("Cancelling search operation")
            
            # Request cancellation from search engine
            self.search_engine.cancel_search()
            
            # Update progress bar
            self.progress_bar.setFormat("Cancelling search...")
    
    def _on_result_double_clicked(self, item: QtWidgets.QTableWidgetItem):
        """Handle double-click on a result item to show detailed information dialog."""
        # Get the result object from the first column
        row = item.row()
        db_item = self.results_table.item(row, 0)
        
        if db_item:
            result = db_item.data(Qt.UserRole)
            if result:
                # Show detail dialog with all row data
                self._show_result_detail_dialog(result)
    
    def _show_result_detail_dialog(self, result):
        """
        Show a detailed information dialog for a search result.
        
        Args:
            result: SearchResult object with row data
        """
        try:
            # Import the detail dialog
            from ui.row_detail_dialog import RowDetailDialog
            
            # Get row data
            row_data = {}
            if hasattr(result, 'row_data') and result.row_data:
                row_data = result.row_data
            elif hasattr(result, 'record_data') and result.record_data:
                row_data = result.record_data
            
            if not row_data:
                QtWidgets.QMessageBox.information(
                    self,
                    "No Data Available",
                    "No detailed data is available for this result."
                )
                return
            
            # Add metadata to row data
            enhanced_data = dict(row_data)
            enhanced_data['_Database'] = getattr(result, 'database', 'Unknown')
            enhanced_data['_Table'] = getattr(result, 'table', 'Unknown')
            enhanced_data['_Row_ID'] = getattr(result, 'row_id', 'N/A')
            
            # Add matched columns info
            if hasattr(result, 'matched_columns') and result.matched_columns:
                enhanced_data['_Matched_Columns'] = ', '.join(str(col) for col in result.matched_columns)
            
            # Add timestamp info if available
            if hasattr(result, 'matched_timestamps') and result.matched_timestamps:
                timestamp_info = []
                for ts in result.matched_timestamps:
                    timestamp_info.append(
                        f"{ts.column_name}: {ts.formatted_display} ({ts.format_type})"
                    )
                enhanced_data['_Matched_Timestamps'] = '\n'.join(timestamp_info)
            
            # Create dialog title
            db_name = getattr(result, 'database', 'Unknown')
            table_name = getattr(result, 'table', 'Unknown')
            row_id = getattr(result, 'row_id', 'N/A')
            title = f"{db_name} / {table_name}"
            
            # Determine row name from common identifying columns
            row_name = "Unknown"
            name_keys = ["Name", "name", "Filename", "filename", "Process Name", "process_name", "Executable", "executable"]
            
            for key in name_keys:
                if key in enhanced_data and enhanced_data[key]:
                    row_name = str(enhanced_data[key])
                    break
            
            # If still unknown, try the first few keys that might be relevant
            if row_name == "Unknown":
                for key, value in enhanced_data.items():
                    if key.lower() in ["id", "uuid", "guid", "hash", "sha256", "md5"]:
                        row_name = str(value)
                        break
            
            # Extract row number
            try:
                row_number = int(row_id)
            except (ValueError, TypeError):
                row_number = 0
            
            # Show the detail dialog
            detail_dialog = RowDetailDialog(enhanced_data, title, row_name, row_number, self)
            detail_dialog.show()
            
            self.logger.info(f"Opened detail dialog for: {title}")
            
        except Exception as e:
            self.logger.error(f"Error showing detail dialog: {e}", exc_info=True)
            QtWidgets.QMessageBox.critical(
                self,
                "Error",
                f"Failed to show detail dialog:\n{str(e)}"
            )
    
    def _on_filter_changed(self, *args):
        """
        Handle filter changes - update summary only.
        
        When filters change (case sensitive, exact match, regex, time range), this method
        updates the filter summary bar. The user must manually trigger a new search by
        clicking the Search button or pressing Enter.
        
        Requirements: 13.1, 13.2, 13.3, 13.5, 13.6
        """
        try:
            # Update the filter summary display
            self._update_filter_summary()
            
        except Exception as e:
            self.logger.warning(f"Error handling filter change: {e}")
    
    def _update_filter_summary(self):
        """
        Update the filter summary bar to show active filters.
        
        Displays a summary of all active filters with badge count and shows/hides
        the summary bar based on whether any filters are active.
        
        Requirements: 13.1, 13.2, 13.3, 13.5, 13.6
        """
        try:
            active_filters = []
            
            # Check search options
            if self.case_sensitive_checkbox.isChecked():
                active_filters.append("Case Sensitive")
            
            if self.exact_match_checkbox.isChecked():
                active_filters.append("Exact Match")
            
            if self.regex_checkbox.isChecked():
                active_filters.append("Regex")
            
            # Check time filter
            if hasattr(self, 'time_filter_widget') and self.time_filter_widget.is_enabled():
                start_time, end_time = self.time_filter_widget.get_time_range()
                if start_time and end_time:
                    # Format time range for display
                    start_str = start_time.strftime("%Y-%m-%d %H:%M")
                    end_str = end_time.strftime("%Y-%m-%d %H:%M")
                    active_filters.append(f"Time: {start_str} to {end_str}")
            
            # Update summary bar visibility and content
            if active_filters:
                # Show summary bar
                self.filter_summary_bar.setVisible(True)
                
                # Update badge count
                count = len(active_filters)
                self.filter_summary_label.setText(f"Active Filters ({count}):")
                
                # Update filter details
                filter_text = " • ".join(active_filters)
                self.filter_details_label.setText(filter_text)
                
                self.logger.debug(f"Filter summary updated: {count} active filters")
            else:
                # Hide summary bar when no filters are active
                self.filter_summary_bar.setVisible(False)
                self.logger.debug("Filter summary hidden: no active filters")
                
        except Exception as e:
            self.logger.warning(f"Error updating filter summary: {e}")
    
    def _on_clear_all_filters(self):
        """
        Clear all active filters and reset to default values.
        
        Resets search options, time filter, and updates the UI accordingly.
        
        Requirements: 13.3
        """
        try:
            self.logger.info("Clearing all filters")
            
            # Clear search options
            self.case_sensitive_checkbox.setChecked(False)
            self.exact_match_checkbox.setChecked(False)
            self.regex_checkbox.setChecked(False)
            
            # Clear time filter
            if hasattr(self, 'time_filter_widget'):
                self.time_filter_widget.group_box.setChecked(False)
            
            # Update filter summary (will hide the bar)
            self._update_filter_summary()
            
            self.logger.debug("All filters cleared successfully")
            
        except Exception as e:
            self.logger.error(f"Error clearing filters: {e}", exc_info=True)
    
    def _on_clear_clicked(self):
        """
        Clear search results and reset the results table.
        
        This is different from clearing filters - it clears the results display.
        """
        try:
            self.logger.info("Clearing search results")
            
            # Clear results
            self.current_results = []
            self.results_table.setRowCount(0)
            self.results_info_label.setText("No search performed yet")
            self.results_info_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 8pt;")
            
            # Disable export button
            self.export_button.setEnabled(False)
            
            self.logger.debug("Search results cleared")
            
        except Exception as e:
            self.logger.error(f"Error clearing results: {e}", exc_info=True)
    
    def _on_export_clicked(self):
        """
        Handle export button click.
        
        Shows a format selection dialog and exports results to the chosen format.
        Supports CSV, JSON, and HTML export formats.
        """
        if not self.current_results or len(self.current_results) == 0:
            QtWidgets.QMessageBox.warning(
                self,
                "No Results",
                "No search results to export."
            )
            return
        
        # Show export format dialog
        format_dialog = QtWidgets.QDialog(self)
        format_dialog.setWindowTitle("Export Format Selection")
        format_dialog.setModal(True)
        format_dialog.setMinimumWidth(400)
        
        layout = QtWidgets.QVBoxLayout(format_dialog)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Title label
        title_label = QtWidgets.QLabel("Select Export Format:")
        title_font = title_label.font()
        title_font.setPointSize(11)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)
        
        # Format descriptions
        desc_label = QtWidgets.QLabel(
            "CSV: Spreadsheet format for Excel/analysis tools\n"
            "JSON: Structured data format for programmatic access\n"
            "HTML: Formatted report for viewing in web browsers"
        )
        desc_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 9pt;")
        layout.addWidget(desc_label)
        
        layout.addSpacing(10)
        
        # Format buttons
        csv_button = QtWidgets.QPushButton("Export as CSV")
        csv_button.setMinimumHeight(40)
        csv_button.setToolTip("Export results to CSV format with all fields and proper escaping")
        
        json_button = QtWidgets.QPushButton("Export as JSON")
        json_button.setMinimumHeight(40)
        json_button.setToolTip("Export results to JSON format with database and table structure")
        
        html_button = QtWidgets.QPushButton("Export as HTML")
        html_button.setMinimumHeight(40)
        html_button.setToolTip("Export results to HTML report with search parameters and styling")
        
        cancel_button = QtWidgets.QPushButton("Cancel")
        cancel_button.setMinimumHeight(40)
        
        layout.addWidget(csv_button)
        layout.addWidget(json_button)
        layout.addWidget(html_button)
        layout.addSpacing(10)
        layout.addWidget(cancel_button)
        
        export_format = [None]
        
        def on_csv():
            export_format[0] = 'csv'
            format_dialog.accept()
        
        def on_json():
            export_format[0] = 'json'
            format_dialog.accept()
        
        def on_html():
            export_format[0] = 'html'
            format_dialog.accept()
        
        csv_button.clicked.connect(on_csv)
        json_button.clicked.connect(on_json)
        html_button.clicked.connect(on_html)
        cancel_button.clicked.connect(format_dialog.reject)
        
        if format_dialog.exec_() != QtWidgets.QDialog.Accepted:
            return
        
        # Get file path based on format
        if export_format[0] == 'csv':
            file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self,
                "Export Search Results as CSV",
                f"search_results_{int(time.time())}.csv",
                "CSV Files (*.csv)"
            )
        elif export_format[0] == 'json':
            file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self,
                "Export Search Results as JSON",
                f"search_results_{int(time.time())}.json",
                "JSON Files (*.json)"
            )
        else:  # html
            file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self,
                "Export Search Results as HTML",
                f"search_results_{int(time.time())}.html",
                "HTML Files (*.html)"
            )
        
        if not file_path:
            return
        
        # Export results
        try:
            if export_format[0] == 'csv':
                self._export_to_csv(file_path)
            elif export_format[0] == 'json':
                self._export_to_json(file_path)
            else:  # html
                self._export_to_html(file_path)
            
            QtWidgets.QMessageBox.information(
                self,
                "Export Successful",
                f"Results exported successfully to:\n{file_path}"
            )
        
        except Exception as e:
            self.logger.error(f"Export error: {e}", exc_info=True)
            QtWidgets.QMessageBox.critical(
                self,
                "Export Error",
                f"Failed to export results:\n{str(e)}"
            )
    
    def _export_to_csv(self, file_path: str):
        """
        Export results to CSV format.
        
        Includes all result fields with proper column headers and handles
        special characters and escaping automatically via csv module.
        Includes time filter parameters in header comments and timestamp columns.
        
        Args:
            file_path: Path to save the CSV file
        
        Requirements: 6.3, 8.6
        """
        self.logger.info(f"Exporting {len(self.current_results)} results to CSV: {file_path}")
        
        try:
            with open(file_path, 'w', newline='', encoding='utf-8') as f:
                # Write header comments with search parameters including time filter
                f.write(f"# Crow Eye Database Search Results\n")
                f.write(f"# Search Term: {self.search_input.text().strip()}\n")
                f.write(f"# Case Sensitive: {self.case_sensitive_checkbox.isChecked()}\n")
                f.write(f"# Exact Match: {self.exact_match_checkbox.isChecked()}\n")
                f.write(f"# Use Regex: {self.regex_checkbox.isChecked()}\n")
                
                # Add time filter parameters if enabled
                if hasattr(self, 'time_filter_widget') and self.time_filter_widget.is_enabled():
                    start_time, end_time = self.time_filter_widget.get_time_range()
                    if start_time:
                        f.write(f"# Time Filter Start: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                    if end_time:
                        f.write(f"# Time Filter End: {end_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(f"# Time Filter Preset: {self.time_filter_widget.current_preset}\n")
                else:
                    f.write(f"# Time Filter: Disabled\n")
                
                f.write(f"# Export Time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"# Total Results: {len(self.current_results)}\n")
                f.write("#\n")
                
                # Define column headers
                fieldnames = [
                    'Database',
                    'Table',
                    'Row_ID',
                    'Matched_Columns',
                    'Match_Preview'
                ]
                
                # Add timestamp columns if time filtering was used
                has_timestamps = any(result.matched_timestamps for result in self.current_results)
                if has_timestamps:
                    fieldnames.append('Matched_Timestamps')
                
                # Collect all unique column names from row_data across all results
                data_columns = set()
                for result in self.current_results:
                    data_columns.update(result.row_data.keys())
                
                # Add data columns to fieldnames (sorted for consistency)
                fieldnames.extend(sorted(data_columns))
                
                # Create CSV writer with proper escaping
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
                writer.writeheader()
                
                # Write each result as a row
                for result in self.current_results:
                    # Build row dictionary
                    row = {
                        'Database': result.database,
                        'Table': result.table,
                        'Row_ID': result.row_id if result.row_id is not None else '',
                        'Matched_Columns': ', '.join(result.matched_columns),
                        'Match_Preview': result.match_preview
                    }
                    
                    # Add matched timestamps if present (preserve original format from database)
                    if has_timestamps:
                        if result.matched_timestamps:
                            timestamp_strs = []
                            for ts_match in result.matched_timestamps:
                                # Use original value from database to preserve format
                                timestamp_strs.append(f"{ts_match.column_name}={ts_match.original_value}")
                            row['Matched_Timestamps'] = '; '.join(timestamp_strs)
                        else:
                            row['Matched_Timestamps'] = ''
                    
                    # Add all row_data fields
                    for key, value in result.row_data.items():
                        # Convert None to empty string, everything else to string
                        row[key] = '' if value is None else str(value)
                    
                    # Write row (csv module handles escaping automatically)
                    writer.writerow(row)
                
                self.logger.info(f"Successfully exported {len(self.current_results)} results to CSV")
                
        except Exception as e:
            self.logger.error(f"CSV export failed: {e}", exc_info=True)
            raise
    
    def _export_to_json(self, file_path: str):
        """
        Export results to JSON format.
        
        Structures data with database name, table name, and record data.
        Formats JSON with proper indentation for readability.
        Includes time filter parameters in metadata and matched timestamps in results.
        
        Args:
            file_path: Path to save the JSON file
        
        Requirements: 6.4, 8.6
        """
        self.logger.info(f"Exporting {len(self.current_results)} results to JSON: {file_path}")
        
        try:
            # Build export data structure organized by database and table
            export_data = {
                'search_metadata': {
                    'search_term': self.search_input.text().strip(),
                    'case_sensitive': self.case_sensitive_checkbox.isChecked(),
                    'exact_match': self.exact_match_checkbox.isChecked(),
                    'use_regex': self.regex_checkbox.isChecked(),
                    'total_results': len(self.current_results),
                    'export_timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
                },
                'results_by_database': {}
            }
            
            # Add time filter information to metadata
            if hasattr(self, 'time_filter_widget') and self.time_filter_widget.is_enabled():
                start_time, end_time = self.time_filter_widget.get_time_range()
                export_data['search_metadata']['time_filter'] = {
                    'enabled': True,
                    'start_time': start_time.isoformat() if start_time else None,
                    'end_time': end_time.isoformat() if end_time else None,
                    'preset': self.time_filter_widget.current_preset
                }
            else:
                export_data['search_metadata']['time_filter'] = {
                    'enabled': False
                }
            
            # Organize results by database and table
            for result in self.current_results:
                # Initialize database entry if not exists
                if result.database not in export_data['results_by_database']:
                    export_data['results_by_database'][result.database] = {}
                
                # Initialize table entry if not exists
                if result.table not in export_data['results_by_database'][result.database]:
                    export_data['results_by_database'][result.database][result.table] = []
                
                # Add result to appropriate database/table
                result_entry = {
                    'row_id': result.row_id,
                    'matched_columns': result.matched_columns,
                    'match_preview': result.match_preview,
                    'record_data': result.row_data
                }
                
                # Add matched timestamps if present
                if result.matched_timestamps:
                    result_entry['matched_timestamps'] = [
                        {
                            'column_name': ts.column_name,
                            'original_value': str(ts.original_value),
                            'formatted_display': ts.formatted_display,
                            'format_type': ts.format_type
                        }
                        for ts in result.matched_timestamps
                    ]
                
                export_data['results_by_database'][result.database][result.table].append(result_entry)
            
            # Write to file with proper indentation
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, default=str, ensure_ascii=False)
            
            self.logger.info(f"Successfully exported {len(self.current_results)} results to JSON")
            
        except Exception as e:
            self.logger.error(f"JSON export failed: {e}", exc_info=True)
            raise
    
    def _export_to_html(self, file_path: str):
        """
        Export results to HTML format.
        
        Creates a formatted report with search parameters section and results
        organized by database and table with professional styling.
        
        Args:
            file_path: Path to save the HTML file
        
        Requirements: 6.5
        """
        self.logger.info(f"Exporting {len(self.current_results)} results to HTML: {file_path}")
        
        try:
            # Gather search parameters
            search_term = self.search_input.text().strip()
            case_sensitive = self.case_sensitive_checkbox.isChecked()
            exact_match = self.exact_match_checkbox.isChecked()
            use_regex = self.regex_checkbox.isChecked()
            export_time = time.strftime('%Y-%m-%d %H:%M:%S')
            
            # Get time filter parameters
            time_filter_enabled = False
            time_filter_start = None
            time_filter_end = None
            time_filter_preset = None
            
            if hasattr(self, 'time_filter_widget') and self.time_filter_widget.is_enabled():
                time_filter_enabled = True
                start_time, end_time = self.time_filter_widget.get_time_range()
                if start_time:
                    time_filter_start = start_time.strftime('%Y-%m-%d %H:%M:%S')
                if end_time:
                    time_filter_end = end_time.strftime('%Y-%m-%d %H:%M:%S')
                time_filter_preset = self.time_filter_widget.current_preset
            
            # Organize results by database and table
            results_by_db = {}
            for result in self.current_results:
                if result.database not in results_by_db:
                    results_by_db[result.database] = {}
                if result.table not in results_by_db[result.database]:
                    results_by_db[result.database][result.table] = []
                results_by_db[result.database][result.table].append(result)
            
            # Build HTML content
            html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Crow Eye Database Search Results</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #e0e0e0;
            padding: 20px;
            line-height: 1.6;
        }}
        
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            background: #0f3460;
            border-radius: 12px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
            overflow: hidden;
        }}
        
        .header {{
            background: linear-gradient(135deg, #00d4ff 0%, #0099cc 100%);
            color: #1a1a2e;
            padding: 30px;
            text-align: center;
        }}
        
        .header h1 {{
            font-size: 2.5em;
            margin-bottom: 10px;
            font-weight: 700;
            text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.2);
        }}
        
        .header .subtitle {{
            font-size: 1.1em;
            opacity: 0.9;
        }}
        
        .search-params {{
            background: #16213e;
            padding: 25px;
            margin: 20px;
            border-radius: 8px;
            border-left: 4px solid #00d4ff;
        }}
        
        .search-params h2 {{
            color: #00d4ff;
            margin-bottom: 15px;
            font-size: 1.5em;
        }}
        
        .param-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 15px;
            margin-top: 15px;
        }}
        
        .param-item {{
            background: #0f3460;
            padding: 12px;
            border-radius: 6px;
            border: 1px solid #1e4976;
        }}
        
        .param-label {{
            color: #00d4ff;
            font-weight: 600;
            font-size: 0.9em;
            margin-bottom: 5px;
        }}
        
        .param-value {{
            color: #e0e0e0;
            font-size: 1.1em;
            word-break: break-word;
        }}
        
        .results-section {{
            padding: 20px;
        }}
        
        .database-section {{
            margin-bottom: 30px;
            background: #16213e;
            border-radius: 8px;
            overflow: hidden;
        }}
        
        .database-header {{
            background: linear-gradient(135deg, #533483 0%, #7b2cbf 100%);
            color: white;
            padding: 15px 20px;
            font-size: 1.3em;
            font-weight: 600;
        }}
        
        .table-section {{
            margin: 15px;
        }}
        
        .table-header {{
            background: #0f3460;
            color: #00d4ff;
            padding: 12px 15px;
            font-size: 1.1em;
            font-weight: 600;
            border-radius: 6px;
            margin-bottom: 10px;
            border-left: 3px solid #00d4ff;
        }}
        
        .result-card {{
            background: #0f3460;
            border: 1px solid #1e4976;
            border-radius: 6px;
            padding: 15px;
            margin-bottom: 12px;
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        
        .result-card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0, 212, 255, 0.2);
            border-color: #00d4ff;
        }}
        
        .result-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
            padding-bottom: 10px;
            border-bottom: 1px solid #1e4976;
        }}
        
        .row-id {{
            background: #00d4ff;
            color: #1a1a2e;
            padding: 4px 12px;
            border-radius: 4px;
            font-weight: 600;
            font-size: 0.9em;
        }}
        
        .matched-columns {{
            color: #7b2cbf;
            font-size: 0.9em;
            font-weight: 600;
        }}
        
        .match-preview {{
            background: #16213e;
            padding: 10px;
            border-radius: 4px;
            margin: 10px 0;
            font-family: 'Courier New', monospace;
            font-size: 0.9em;
            color: #00d4ff;
            border-left: 3px solid #7b2cbf;
        }}
        
        .record-data {{
            margin-top: 10px;
        }}
        
        .data-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.9em;
        }}
        
        .data-table td {{
            padding: 6px 10px;
            border-bottom: 1px solid #1e4976;
        }}
        
        .data-table td:first-child {{
            color: #00d4ff;
            font-weight: 600;
            width: 200px;
            vertical-align: top;
        }}
        
        .data-table td:last-child {{
            color: #e0e0e0;
            word-break: break-word;
        }}
        
        .footer {{
            background: #16213e;
            padding: 20px;
            text-align: center;
            color: #888;
            font-size: 0.9em;
            margin-top: 20px;
        }}
        
        .summary-stats {{
            display: flex;
            justify-content: space-around;
            padding: 20px;
            background: #16213e;
            margin: 20px;
            border-radius: 8px;
        }}
        
        .stat-item {{
            text-align: center;
        }}
        
        .stat-value {{
            font-size: 2em;
            color: #00d4ff;
            font-weight: 700;
        }}
        
        .stat-label {{
            color: #888;
            font-size: 0.9em;
            margin-top: 5px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔍 Crow Eye Database Search Results</h1>
            <div class="subtitle">Forensic Artifact Database Search Report</div>
        </div>
        
        <div class="search-params">
            <h2>Search Parameters</h2>
            <div class="param-grid">
                <div class="param-item">
                    <div class="param-label">Search Term</div>
                    <div class="param-value">"{self._html_escape(search_term)}"</div>
                </div>
                <div class="param-item">
                    <div class="param-label">Case Sensitive</div>
                    <div class="param-value">{"Yes" if case_sensitive else "No"}</div>
                </div>
                <div class="param-item">
                    <div class="param-label">Exact Match</div>
                    <div class="param-value">{"Yes" if exact_match else "No"}</div>
                </div>
                <div class="param-item">
                    <div class="param-label">Regular Expression</div>
                    <div class="param-value">{"Yes" if use_regex else "No"}</div>
                </div>
                <div class="param-item">
                    <div class="param-label">Time Filter</div>
                    <div class="param-value">{"Enabled" if time_filter_enabled else "Disabled"}</div>
                </div>
                {"" if not time_filter_enabled else f'''
                <div class="param-item">
                    <div class="param-label">Time Filter Start</div>
                    <div class="param-value">{self._html_escape(time_filter_start) if time_filter_start else "N/A"}</div>
                </div>
                <div class="param-item">
                    <div class="param-label">Time Filter End</div>
                    <div class="param-value">{self._html_escape(time_filter_end) if time_filter_end else "N/A"}</div>
                </div>
                <div class="param-item">
                    <div class="param-label">Time Filter Preset</div>
                    <div class="param-value">{self._html_escape(time_filter_preset) if time_filter_preset else "N/A"}</div>
                </div>
                '''}
                <div class="param-item">
                    <div class="param-label">Export Time</div>
                    <div class="param-value">{export_time}</div>
                </div>
                <div class="param-item">
                    <div class="param-label">Total Results</div>
                    <div class="param-value">{len(self.current_results)}</div>
                </div>
            </div>
        </div>
        
        <div class="summary-stats">
            <div class="stat-item">
                <div class="stat-value">{len(self.current_results)}</div>
                <div class="stat-label">Total Results</div>
            </div>
            <div class="stat-item">
                <div class="stat-value">{len(results_by_db)}</div>
                <div class="stat-label">Databases</div>
            </div>
            <div class="stat-item">
                <div class="stat-value">{sum(len(tables) for tables in results_by_db.values())}</div>
                <div class="stat-label">Tables</div>
            </div>
        </div>
        
        <div class="results-section">
"""
            
            # Add results organized by database and table
            for database, tables in sorted(results_by_db.items()):
                html_content += f"""
            <div class="database-section">
                <div class="database-header">📁 {self._html_escape(database)}</div>
"""
                
                for table, results in sorted(tables.items()):
                    html_content += f"""
                <div class="table-section">
                    <div class="table-header">📊 {self._html_escape(table)} ({len(results)} results)</div>
"""
                    
                    for result in results:
                        html_content += f"""
                    <div class="result-card">
                        <div class="result-header">
                            <span class="row-id">Row ID: {result.row_id if result.row_id is not None else 'N/A'}</span>
                            <span class="matched-columns">Matched: {self._html_escape(', '.join(result.matched_columns))}</span>
                        </div>
                        <div class="match-preview">{self._html_escape(result.match_preview)}</div>
"""
                        
                        # Add matched timestamps if present
                        if result.matched_timestamps:
                            html_content += """
                        <div class="match-preview" style="border-left-color: #00d4ff;">
                            <strong>🕐 Matched Timestamps:</strong><br>
"""
                            for ts_match in result.matched_timestamps:
                                html_content += f"""
                            {self._html_escape(ts_match.column_name)}: {self._html_escape(ts_match.formatted_display)}<br>
"""
                            html_content += """
                        </div>
"""
                        
                        html_content += """
                        <div class="record-data">
                            <table class="data-table">
"""
                        
                        # Add record data fields
                        for key, value in sorted(result.row_data.items()):
                            value_str = '' if value is None else str(value)
                            # Truncate very long values
                            if len(value_str) > 500:
                                value_str = value_str[:497] + '...'
                            
                            html_content += f"""
                                <tr>
                                    <td>{self._html_escape(key)}</td>
                                    <td>{self._html_escape(value_str)}</td>
                                </tr>
"""
                        
                        html_content += """
                            </table>
                        </div>
                    </div>
"""
                    
                    html_content += """
                </div>
"""
                
                html_content += """
            </div>
"""
            
            # Add footer
            html_content += f"""
        </div>
        
        <div class="footer">
            <p>Generated by Crow Eye Forensic Analysis Tool</p>
            <p>Report generated on {export_time}</p>
        </div>
    </div>
</body>
</html>
"""
            
            # Write to file
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            self.logger.info(f"Successfully exported {len(self.current_results)} results to HTML")
            
        except Exception as e:
            self.logger.error(f"HTML export failed: {e}", exc_info=True)
            raise
    
    def _html_escape(self, text: str) -> str:
        """
        Escape HTML special characters to prevent injection and display issues.
        
        Args:
            text: Text to escape
        
        Returns:
            HTML-escaped text
        """
        if not isinstance(text, str):
            text = str(text)
        
        return (text
                .replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
                .replace('"', '&quot;')
                .replace("'", '&#39;'))
    
    def _on_clear_clicked(self):
        """Handle clear button click."""
        # Cancel any ongoing search
        if self.search_in_progress:
            self._cancel_search()
        
        # Stop debounce timer
        self.debounce_timer.stop()
        
        # Clear UI
        self.search_input.clear()
        self.results_table.setRowCount(0)
        self.current_results = []
        self.results_info_label.setText("No search performed yet")
        self.export_button.setEnabled(False)
    
    # ========================================================================
    # Saved Search Management (Task 8.3)
    # ========================================================================
    
    def _on_save_search_clicked(self):
        """
        Handle save search button click.
        
        Opens a dialog for the user to enter a name for the current search
        parameters, then saves it for future use.
        
        Requirements: 7.4
        """
        # Validate that we have search parameters
        search_term = self.search_input.text().strip()
        if not search_term:
            QtWidgets.QMessageBox.warning(
                self,
                "No Search Term",
                "Please enter a search term before saving."
            )
            return
        
        selected = self._get_selected_databases_and_tables()
        if not selected:
            QtWidgets.QMessageBox.warning(
                self,
                "No Databases Selected",
                "Please select at least one database before saving."
            )
            return
        
        # Prompt for search name
        name, ok = QtWidgets.QInputDialog.getText(
            self,
            "Save Search",
            "Enter a name for this search:",
            QtWidgets.QLineEdit.Normal,
            ""
        )
        
        if not ok or not name.strip():
            return
        
        name = name.strip()
        
        # Check if name already exists
        if self.search_engine:
            existing = self.search_engine.get_saved_search(name)
            if existing:
                reply = QtWidgets.QMessageBox.question(
                    self,
                    "Overwrite Saved Search",
                    f"A saved search named '{name}' already exists.\n\nDo you want to overwrite it?",
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                    QtWidgets.QMessageBox.No
                )
                
                if reply != QtWidgets.QMessageBox.Yes:
                    return
        
        # Save the search
        try:
            if not self.search_engine:
                raise Exception("Search engine not initialized")
            
            # Get time filter parameters
            start_time_str = None
            end_time_str = None
            time_preset = None
            
            if hasattr(self, 'time_filter_widget') and self.time_filter_widget.is_enabled():
                start_time, end_time = self.time_filter_widget.get_time_range()
                if start_time:
                    start_time_str = start_time.isoformat()
                if end_time:
                    end_time_str = end_time.isoformat()
                time_preset = self.time_filter_widget.current_preset
            
            success = self.search_engine.save_search(
                name=name,
                term=search_term,
                databases=list(selected.keys()),
                tables=selected,
                case_sensitive=self.case_sensitive_checkbox.isChecked(),
                exact_match=self.exact_match_checkbox.isChecked(),
                use_regex=self.regex_checkbox.isChecked(),
                start_time=start_time_str,
                end_time=end_time_str,
                time_preset=time_preset
            )
            
            if success:
                QtWidgets.QMessageBox.information(
                    self,
                    "Search Saved",
                    f"Search '{name}' has been saved successfully."
                )
                self.logger.info(f"Saved search: '{name}'")
            else:
                raise Exception("Save operation returned False")
                
        except Exception as e:
            self.logger.error(f"Failed to save search: {e}", exc_info=True)
            QtWidgets.QMessageBox.critical(
                self,
                "Save Error",
                f"Failed to save search:\n{str(e)}"
            )
    
    def _on_saved_searches_clicked(self):
        """
        Handle saved searches button click.
        
        Opens a dialog showing all saved searches with options to load or delete them.
        
        Requirements: 7.4
        """
        if not self.search_engine:
            QtWidgets.QMessageBox.warning(
                self,
                "Search Engine Not Available",
                "Search engine is not initialized."
            )
            return
        
        # Load saved searches
        try:
            saved_searches = self.search_engine.get_saved_searches()
            
            if not saved_searches:
                QtWidgets.QMessageBox.information(
                    self,
                    "No Saved Searches",
                    "You don't have any saved searches yet.\n\nUse the 'Save Search' button to save your current search parameters."
                )
                return
            
            # Create saved searches dialog
            dialog = SavedSearchesDialog(self, saved_searches, self.search_engine)
            
            if dialog.exec_() == QtWidgets.QDialog.Accepted:
                # User selected a search to load
                selected_search = dialog.get_selected_search()
                
                if selected_search:
                    self._load_saved_search(selected_search)
                    
        except Exception as e:
            self.logger.error(f"Error opening saved searches: {e}", exc_info=True)
            QtWidgets.QMessageBox.critical(
                self,
                "Error",
                f"Failed to load saved searches:\n{str(e)}"
            )
    
    def _load_saved_search(self, saved_search):
        """
        Load a saved search into the dialog.
        
        Restores all search parameters including time filter state.
        
        Args:
            saved_search: SavedSearch object to load
            
        Requirements: 11.3
        """
        try:
            self.logger.info(f"Loading saved search: '{saved_search.name}'")
            
            # Populate search term
            self.search_input.setText(saved_search.term)
            
            # Set search options
            self.case_sensitive_checkbox.setChecked(saved_search.case_sensitive)
            self.exact_match_checkbox.setChecked(saved_search.exact_match)
            self.regex_checkbox.setChecked(saved_search.use_regex)
            
            # Restore database and table selections
            self._restore_database_selection(saved_search.databases, saved_search.tables)
            
            # Restore time filter state
            if hasattr(self, 'time_filter_widget'):
                if hasattr(saved_search, 'start_time') and (saved_search.start_time or saved_search.end_time):
                    from datetime import datetime
                    start_dt = None
                    end_dt = None
                    
                    if saved_search.start_time:
                        try:
                            start_dt = datetime.fromisoformat(saved_search.start_time)
                        except Exception as e:
                            self.logger.warning(f"Failed to parse start_time from saved search: {e}")
                    
                    if saved_search.end_time:
                        try:
                            end_dt = datetime.fromisoformat(saved_search.end_time)
                        except Exception as e:
                            self.logger.warning(f"Failed to parse end_time from saved search: {e}")
                    
                    if start_dt or end_dt:
                        self.time_filter_widget.set_time_range(start_dt, end_dt)
                        self.logger.debug(f"Restored time filter: {start_dt} to {end_dt}")
                else:
                    # No time filter in saved search, disable filter
                    self.time_filter_widget.group_box.setChecked(False)
            
            # Update last used timestamp
            if self.search_engine:
                self.search_engine.update_saved_search_last_used(saved_search.name)
            
            self.logger.debug("Successfully loaded saved search")
            
        except Exception as e:
            self.logger.error(f"Error loading saved search: {e}", exc_info=True)
            QtWidgets.QMessageBox.warning(
                self,
                "Load Error",
                f"Failed to load saved search:\n{str(e)}"
            )
    
    def _navigate_to_result(self, result: SearchResult) -> bool:
        """
        Navigate to a search result by switching tabs and highlighting the row.
        
        Args:
            result: SearchResult to navigate to
            
        Returns:
            bool: True if navigation was successful, False otherwise
        """
        try:
            # Map table names to tab indices and table widgets
            table_tab_mapping = {
                'mft_records': ('MFT', 0),
                'mft_file_names': ('MFT', 0),
                'mft_standard_info': ('MFT', 0),
                'mft_data_attributes': ('MFT', 0),
                'journal_events': ('USN', 1),
                'usn_journal': ('USN', 1),
                'mft_usn_correlated': ('Correlated', 2),
                'correlated_data': ('Correlated', 2),
            }
            
            # Get tab info for this table
            tab_info = table_tab_mapping.get(result.table_name.lower())
            
            if not tab_info:
                self.logger.warning(f"No tab mapping found for table: {result.table_name}")
                self.results_info_label.setText(
                    f"Cannot navigate to {result.table_name} - tab not found"
                )
                return False
            
            tab_name, tab_index = tab_info
            
            # Get the table widget for this tab
            table_widget = self.table_widgets.get(tab_name)
            
            if not table_widget:
                self.logger.warning(f"No table widget found for tab: {tab_name}")
                self.results_info_label.setText(
                    f"Cannot navigate to {tab_name} - table widget not found"
                )
                return False
            
            # Find the row index by record ID
            row_index = self.search_utils.find_row_by_record_id(
                table_widget=table_widget,
                record_id=result.row_id,
                id_column_index=0  # Assume first column contains record ID
            )
            
            if row_index is None:
                self.logger.warning(f"Record ID {result.row_id} not found in table")
                self.results_info_label.setText(
                    f"Record not found in {tab_name} table - may need to reload data"
                )
                return False
            
            # Navigate to the result
            success = self.search_utils.navigate_to_result(
                tab_widget=self.tab_widget,
                table_widget=table_widget,
                tab_index=tab_index,
                row_index=row_index,
                matched_columns=result.matched_columns,
                highlight_duration_ms=3000
            )
            
            if success:
                self.results_info_label.setText(
                    f"Navigated to {tab_name} tab, row {row_index + 1}"
                )
                self.logger.info(f"Successfully navigated to {tab_name}, row {row_index}")
            else:
                self.results_info_label.setText(
                    f"Failed to navigate to {tab_name}"
                )
            
            return success
            
        except Exception as e:
            self.logger.error(f"Error navigating to result: {e}", exc_info=True)
            self.results_info_label.setText(f"Navigation error: {str(e)}")
            return False
    
    def set_navigation_components(
        self,
        tab_widget: QtWidgets.QTabWidget,
        table_widgets: Dict[str, QtWidgets.QTableWidget]
    ):
        """
        Set the navigation components for result navigation.
        
        Args:
            tab_widget: Main tab widget
            table_widgets: Dictionary mapping tab names to table widgets
        """
        self.tab_widget = tab_widget
        self.table_widgets = table_widgets
        self.logger.info("Navigation components configured")


class SavedSearchesDialog(QtWidgets.QDialog):
    """
    Dialog for managing saved searches.
    
    Displays a list of saved searches with options to load or delete them.
    Shows search details including name, term, and last used timestamp.
    """
    
    def __init__(
        self,
        parent: Optional[QtWidgets.QWidget],
        saved_searches: List,
        search_engine
    ):
        """
        Initialize the saved searches dialog.
        
        Args:
            parent: Parent widget
            saved_searches: List of SavedSearch objects
            search_engine: UnifiedDatabaseSearchEngine instance
        """
        super().__init__(parent)
        
        self.saved_searches = saved_searches
        self.search_engine = search_engine
        self.selected_search = None
        self.logger = logging.getLogger(self.__class__.__name__)
        
        self._setup_ui()
        self._populate_searches()
        self._apply_styles()
    
    def _setup_ui(self):
        """Set up the user interface."""
        self.setWindowTitle("Saved Searches")
        self.setMinimumSize(700, 500)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # Title
        title_label = QtWidgets.QLabel("Manage Saved Searches")
        title_font = title_label.font()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)
        
        # Info label
        info_label = QtWidgets.QLabel(
            "Select a saved search to load it, or delete searches you no longer need."
        )
        info_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 10pt;")
        layout.addWidget(info_label)
        
        # Searches table
        self.searches_table = QtWidgets.QTableWidget()
        self.searches_table.setColumnCount(4)
        self.searches_table.setHorizontalHeaderLabels([
            "Name",
            "Search Term",
            "Created",
            "Last Used"
        ])
        
        # Configure table
        self.searches_table.setAlternatingRowColors(True)
        self.searches_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.searches_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.searches_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.searches_table.setSortingEnabled(True)
        
        # Set column widths
        header = self.searches_table.horizontalHeader()
        self.searches_table.setColumnWidth(0, 150)
        self.searches_table.setColumnWidth(1, 250)
        self.searches_table.setColumnWidth(2, 130)
        self.searches_table.setColumnWidth(3, 130)
        header.setStretchLastSection(True)
        
        # Double-click to load
        self.searches_table.itemDoubleClicked.connect(self._on_load_clicked)
        
        layout.addWidget(self.searches_table, stretch=1)
        
        # Buttons
        button_layout = QtWidgets.QHBoxLayout()
        
        self.load_button = QtWidgets.QPushButton("Load Search")
        self.load_button.setMinimumWidth(120)
        self.load_button.setMinimumHeight(35)
        self.load_button.setEnabled(False)
        button_layout.addWidget(self.load_button)
        
        self.delete_button = QtWidgets.QPushButton("Delete Search")
        self.delete_button.setMinimumWidth(120)
        self.delete_button.setMinimumHeight(35)
        self.delete_button.setEnabled(False)
        button_layout.addWidget(self.delete_button)
        
        button_layout.addStretch()
        
        self.close_button = QtWidgets.QPushButton("Close")
        self.close_button.setMinimumWidth(100)
        self.close_button.setMinimumHeight(35)
        button_layout.addWidget(self.close_button)
        
        layout.addLayout(button_layout)
        
        # Connect signals
        self.searches_table.itemSelectionChanged.connect(self._on_selection_changed)
        self.load_button.clicked.connect(self._on_load_clicked)
        self.delete_button.clicked.connect(self._on_delete_clicked)
        self.close_button.clicked.connect(self.reject)
    
    def _populate_searches(self):
        """Populate the table with saved searches."""
        self.searches_table.setRowCount(0)
        self.searches_table.setSortingEnabled(False)
        
        for search in self.saved_searches:
            row = self.searches_table.rowCount()
            self.searches_table.insertRow(row)
            
            # Name
            name_item = QtWidgets.QTableWidgetItem(search.name)
            name_item.setData(Qt.UserRole, search)
            self.searches_table.setItem(row, 0, name_item)
            
            # Search term (truncate if too long)
            term = search.term
            if len(term) > 50:
                term = term[:47] + "..."
            term_item = QtWidgets.QTableWidgetItem(term)
            term_item.setToolTip(search.term)
            self.searches_table.setItem(row, 1, term_item)
            
            # Created timestamp
            try:
                from datetime import datetime
                created = datetime.fromisoformat(search.created)
                created_str = created.strftime("%Y-%m-%d %H:%M")
            except Exception:
                created_str = search.created[:16]
            created_item = QtWidgets.QTableWidgetItem(created_str)
            self.searches_table.setItem(row, 2, created_item)
            
            # Last used timestamp
            if search.last_used:
                try:
                    last_used = datetime.fromisoformat(search.last_used)
                    last_used_str = last_used.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    last_used_str = search.last_used[:16]
            else:
                last_used_str = "Never"
            last_used_item = QtWidgets.QTableWidgetItem(last_used_str)
            self.searches_table.setItem(row, 3, last_used_item)
        
        self.searches_table.setSortingEnabled(True)
    
    def _on_selection_changed(self):
        """Handle selection changes in the table."""
        has_selection = len(self.searches_table.selectedItems()) > 0
        self.load_button.setEnabled(has_selection)
        self.delete_button.setEnabled(has_selection)
    
    def _on_load_clicked(self):
        """Handle load button click."""
        selected_rows = self.searches_table.selectionModel().selectedRows()
        
        if not selected_rows:
            return
        
        row = selected_rows[0].row()
        name_item = self.searches_table.item(row, 0)
        
        if name_item:
            self.selected_search = name_item.data(Qt.UserRole)
            self.accept()
    
    def _on_delete_clicked(self):
        """Handle delete button click."""
        selected_rows = self.searches_table.selectionModel().selectedRows()
        
        if not selected_rows:
            return
        
        row = selected_rows[0].row()
        name_item = self.searches_table.item(row, 0)
        
        if not name_item:
            return
        
        search = name_item.data(Qt.UserRole)
        
        # Confirm deletion
        reply = QtWidgets.QMessageBox.question(
            self,
            "Delete Saved Search",
            f"Are you sure you want to delete the saved search '{search.name}'?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No
        )
        
        if reply != QtWidgets.QMessageBox.Yes:
            return
        
        # Delete the search
        try:
            success = self.search_engine.delete_saved_search(search.name)
            
            if success:
                # Remove from table
                self.searches_table.removeRow(row)
                
                # Remove from list
                self.saved_searches = [s for s in self.saved_searches if s.name != search.name]
                
                QtWidgets.QMessageBox.information(
                    self,
                    "Search Deleted",
                    f"Saved search '{search.name}' has been deleted."
                )
                
                self.logger.info(f"Deleted saved search: '{search.name}'")
            else:
                raise Exception("Delete operation returned False")
                
        except Exception as e:
            self.logger.error(f"Failed to delete saved search: {e}", exc_info=True)
            QtWidgets.QMessageBox.critical(
                self,
                "Delete Error",
                f"Failed to delete saved search:\n{str(e)}"
            )
    
    def _apply_styles(self):
        """Apply cyberpunk styles to the dialog."""
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {Colors.BG_PRIMARY};
                border: 2px solid {Colors.ACCENT_CYAN};
                border-radius: 8px;
            }}
            QLabel {{
                color: {Colors.TEXT_PRIMARY};
            }}
            QTableWidget {{
                background-color: {Colors.BG_TABLES};
                color: {Colors.TEXT_PRIMARY};
                border: 2px solid {Colors.BORDER_SUBTLE};
                border-radius: 6px;
                gridline-color: {Colors.BORDER_SUBTLE};
                alternate-background-color: {Colors.BG_PANELS};
                font-size: 10pt;
            }}
            QTableWidget::item:selected {{
                background-color: {Colors.ACCENT_BLUE};
                color: {Colors.TEXT_PRIMARY};
            }}
            QHeaderView::section {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #2563EB, stop:1 #1E40AF);
                color: #FFFFFF;
                border: none;
                border-right: 1px solid #334155;
                padding: 6px 10px;
                font-weight: 600;
                font-size: 11px;
                font-family: 'Segoe UI', sans-serif;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }}
            QPushButton {{
                background-color: {Colors.ACCENT_BLUE};
                color: {Colors.TEXT_PRIMARY};
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 10pt;
            }}
            QPushButton:hover {{
                background-color: {Colors.ACCENT_CYAN};
                color: {Colors.BG_PRIMARY};
            }}
            QPushButton:disabled {{
                background-color: {Colors.BORDER_SUBTLE};
                color: {Colors.TEXT_MUTED};
            }}
        """)
    
    def get_selected_search(self):
        """
        Get the selected search.
        
        Returns:
            SavedSearch object if one was selected, None otherwise
        """
        return self.selected_search


if __name__ == "__main__":
    # Test the dialog
    app = QtWidgets.QApplication(sys.argv)
    dialog = DatabaseSearchDialog()
    dialog.show()
    sys.exit(app.exec_())
