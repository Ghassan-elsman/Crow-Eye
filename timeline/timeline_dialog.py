"""
Timeline Dialog - Main window for forensic timeline visualization.

This module provides the main dialog window for the timeline visualization feature,
integrating all timeline components and coordinating data loading and user interactions.
"""

import os
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget, QLabel, 
    QMessageBox, QSplitter, QProgressDialog
)
from PyQt5.QtCore import Qt, pyqtSignal, QThread
from PyQt5.QtGui import QFont, QKeySequence
from timeline.timeline_canvas import TimelineCanvas
from timeline.filter_bar import FilterBar
from timeline.data.timeline_data_manager import TimelineDataManager
from timeline.data.query_worker import QueryWorker, AggregationWorker, IndexingWorker
from timeline.event_details_panel import EventDetailsPanel
from timeline.utils.error_handler import ErrorHandler, create_recovery_options


class TimelineDialog(QDialog):
    """
    Main timeline visualization dialog window.
    
    This dialog provides an interactive timeline view of all forensic artifacts
    collected by Crow Eye, with filtering, zooming, and correlation capabilities.
    
    Signals:
        event_double_clicked: Emitted when an event is double-clicked (for navigation to main GUI)
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
        self.case_paths = None
        self.data_manager = None
        self.timeline_canvas = None
        self.filter_bar = None
        self.event_details_panel = None
        
        # Initialize error handler
        self.error_handler = ErrorHandler(self)
        
        # Current state
        self.current_events = []  # All loaded events
        self.filtered_events = []  # Events after filtering
        self.current_time_range = (None, None)  # Current time range (start, end)
        
        # Context query caching
        self._context_cache = {}  # Cache for nearby/related events: {event_id: {'nearby': [...], 'related': [...]}}
        self._events_by_time_index = {}  # Time-based index for faster nearby event lookup
        self._events_by_path_index = {}  # Path-based index for faster related event lookup
        
        # Background worker threads
        self.query_worker = None  # Current query worker thread
        self.aggregation_worker = None  # Current aggregation worker thread
        self.indexing_worker = None  # Current indexing worker thread
        
        # Initialize UI
        self._init_ui()
        
        # Load case paths and initialize data manager
        try:
            self.case_paths = self._get_case_paths()
            # Initialize data manager with error handler
            self.data_manager = TimelineDataManager(self.case_paths, self.error_handler)
            
            # Load initial data
            self._load_initial_data()
        except ValueError as e:
            # User-friendly message for missing case
            self.error_handler.handle_error(
                e,
                "loading case",
                show_dialog=True
            )
        except Exception as e:
            # Unexpected initialization error
            self.error_handler.handle_error(
                e,
                "initializing timeline",
                show_dialog=True,
                recovery_options=create_recovery_options(
                    retry_func=lambda: self._retry_initialization()
                )
            )
    
    def showEvent(self, event):
        """
        Handle dialog show event to ensure proper rendering.
        
        Args:
            event: QShowEvent
        """
        super().showEvent(event)
        
        # Force update of timeline canvas after window is shown
        if self.timeline_canvas:
            # Trigger a repaint to ensure time axis is visible
            self.timeline_canvas.viewport().update()
            # Force scene update
            if self.timeline_canvas.scene:
                self.timeline_canvas.scene.update()
    
    def _init_ui(self):
        """Initialize the user interface components."""
        # Set window properties
        self.setWindowTitle("Forensic Timeline Visualization")
        self.setMinimumSize(1024, 768)
        
        # Open maximized to show full screen
        self.showMaximized()
        
        # Apply dark theme styling
        self.setStyleSheet("""
            QDialog {
                background-color: #0F172A;
                color: #E2E8F0;
            }
            QLabel {
                color: #E2E8F0;
                font-family: 'Segoe UI', sans-serif;
            }
        """)
        
        # Create main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # Create header
        header = self._create_header()
        main_layout.addWidget(header)
        
        # Create main content area with splitter
        content_splitter = self._create_content_area()
        main_layout.addWidget(content_splitter, stretch=1)
        
        # Set the layout
        self.setLayout(main_layout)
        
        # Track initial size for responsive adjustments
        self._last_width = self.width()
        self._last_height = self.height()
        
        # Setup keyboard shortcuts
        self._setup_keyboard_shortcuts()
    
    def _setup_keyboard_shortcuts(self):
        """
        Setup keyboard shortcuts for timeline navigation and interaction.
        """
        from PyQt5.QtWidgets import QShortcut
        from PyQt5.QtGui import QKeySequence
        from PyQt5.QtCore import Qt
        
        # Zoom shortcuts
        zoom_in_shortcut = QShortcut(QKeySequence(Qt.Key_Plus), self)
        zoom_in_shortcut.activated.connect(lambda: self.timeline_canvas.zoom_in() if self.timeline_canvas else None)
        
        zoom_out_shortcut = QShortcut(QKeySequence(Qt.Key_Minus), self)
        zoom_out_shortcut.activated.connect(lambda: self.timeline_canvas.zoom_out() if self.timeline_canvas else None)
        
        # Reset zoom
        reset_zoom_shortcut = QShortcut(QKeySequence(Qt.Key_0), self)
        reset_zoom_shortcut.activated.connect(lambda: self.timeline_canvas.reset_zoom() if self.timeline_canvas else None)
        
        # Close dialog
        close_shortcut = QShortcut(QKeySequence(Qt.Key_Escape), self)
        close_shortcut.activated.connect(self.close)
        
        # Refresh
        refresh_shortcut = QShortcut(QKeySequence(Qt.Key_F5), self)
        refresh_shortcut.activated.connect(self._refresh_timeline)
    
    def _refresh_timeline(self):
        """Refresh the timeline with current filters"""
        if self.timeline_canvas and self.current_time_range[0] and self.current_time_range[1]:
            self._load_events_for_range(self.current_time_range[0], self.current_time_range[1])
    
    def _create_header(self):
        """
        Create the header section with title and info.
        
        Returns:
            QWidget: Header widget
        """
        header_widget = QWidget()
        header_layout = QVBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(5)
        
        # Title label
        title_label = QLabel("Forensic Timeline Visualization")
        title_font = QFont("Segoe UI", 18, QFont.Bold)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #00FFFF; padding: 10px;")
        header_layout.addWidget(title_label)
        
        # Description label
        desc_label = QLabel("Interactive chronological view of forensic artifacts")
        desc_label.setStyleSheet("color: #94A3B8; font-size: 12px; padding-left: 10px;")
        header_layout.addWidget(desc_label)
        
        return header_widget
    
    def _create_content_area(self):
        """
        Create the main content area with filter bar on top and details panel on bottom.
        
        Returns:
            QWidget: Main content widget
        """
        # Create main container widget
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(5)
        
        # Top: Filter bar (horizontal, compact)
        self.filter_bar = FilterBar(self)
        self.filter_bar.setStyleSheet("""
            QWidget {
                border: 1px solid #334155;
                border-radius: 8px;
            }
        """)
        self.filter_bar.setMaximumHeight(200)
        self.filter_bar.setMinimumHeight(100)
        
        # Connect filter bar signals
        self.filter_bar.filter_changed.connect(self._on_filter_changed)
        self.filter_bar.time_range_changed.connect(self._on_time_range_changed)
        self.filter_bar.zoom_changed.connect(self._on_zoom_changed)
        self.filter_bar.search_requested.connect(self._on_search_requested)
        self.filter_bar.srum_show_ids_changed.connect(self._on_srum_show_ids_changed)
        
        main_layout.addWidget(self.filter_bar)
        
        # Middle: Timeline canvas (takes most space)
        self.timeline_canvas = TimelineCanvas(self)
        self.timeline_canvas.setStyleSheet("""
            QGraphicsView {
                border: 1px solid #334155;
                border-radius: 8px;
            }
        """)
        self.timeline_canvas.setMinimumHeight(300)
        
        # Connect signals
        self.timeline_canvas.event_selected.connect(self._on_events_selected)
        self.timeline_canvas.event_double_clicked.connect(self.on_event_double_click)
        
        main_layout.addWidget(self.timeline_canvas, stretch=1)
        
        # Bottom: Event details panel
        self.event_details_panel = EventDetailsPanel(self)
        self.event_details_panel.setStyleSheet("""
            QWidget {
                border: 1px solid #334155;
                border-radius: 8px;
            }
        """)
        self.event_details_panel.setMaximumHeight(200)
        self.event_details_panel.setMinimumHeight(100)
        self.event_details_panel.jump_to_event_requested.connect(self.on_event_double_click)
        main_layout.addWidget(self.event_details_panel)
        
        return main_widget
    


    
    def _retry_initialization(self):
        """Retry timeline initialization after an error."""
        try:
            self.case_paths = self._get_case_paths()
            self.data_manager = TimelineDataManager(self.case_paths, self.error_handler)
            self._load_initial_data()
        except Exception as e:
            self.error_handler.handle_error(
                e,
                "retrying initialization",
                show_dialog=True
            )
    
    def _get_case_paths(self):
        """
        Extract case paths from the main Crow Eye window.
        
        Returns:
            dict: Dictionary containing all relevant paths
            
        Raises:
            ValueError: If no active case is found
        """
        if not self.main_window:
            raise ValueError("No main window reference available")
        
        # Check if main_window has a ui attribute (Ui_Crow_Eye object)
        ui_object = getattr(self.main_window, 'ui', self.main_window)
        
        if not hasattr(ui_object, 'case_paths') or not ui_object.case_paths:
            raise ValueError("No active case found. Please load a case first.")
        
        case_root = ui_object.case_paths.get('case_root')
        if not case_root:
            raise ValueError("Case root path not found")
        
        artifacts_dir = ui_object.case_paths.get('artifacts_dir', 
                                                 os.path.join(case_root, 'artifacts'))
        
        # Build comprehensive case paths dictionary
        case_paths = {
            'case_root': case_root,
            'artifacts_dir': artifacts_dir,
            'timeline_dir': os.path.join(case_root, 'timeline'),
            'registry_db': os.path.join(artifacts_dir, 'registry_data.db'),
            'prefetch_db': os.path.join(artifacts_dir, 'prefetch_data.db'),
            'lnk_db': os.path.join(artifacts_dir, 'lnk_data.db'),
            'bam_db': os.path.join(artifacts_dir, 'bam_data.db'),
            'srum_db': os.path.join(artifacts_dir, 'srum_data.db'),
            'usn_db': os.path.join(artifacts_dir, 'usn_data.db'),
            'mft_db': os.path.join(artifacts_dir, 'mft_data.db'),
            'shellbags_db': os.path.join(artifacts_dir, 'shellbags_data.db'),
            'logs_db': os.path.join(artifacts_dir, 'logs_data.db')
        }
        
        return case_paths
    
    def load_artifacts(self):
        """
        Load all artifacts from currently loaded tabs in main GUI.
        
        This method will be implemented in future tasks when the data manager
        and timeline canvas are ready.
        """
        # TODO: Implement in future tasks
        # if self.data_manager:
        #     self.data_manager.load_all_artifacts()
        pass
    
    def on_event_double_click(self, event_data):
        """
        Handle double-click on timeline event to navigate to main GUI.
        
        Args:
            event_data (dict): Event data containing artifact type and row information
        """
        # TODO: Implement navigation to main GUI in future tasks
        # This will map artifact types to tabs and select the corresponding row
        pass
    
    def export_timeline(self, format_type):
        """
        Export timeline to specified format.
        
        Args:
            format_type (str): Export format ('csv', 'json', or 'png')
        """
        # TODO: Implement in future tasks
        pass
    
    def save_bookmark(self, name, description):
        """
        Save current timeline state as a bookmark.
        
        Args:
            name (str): Bookmark name
            description (str): Bookmark description
        """
        # TODO: Implement in future tasks
        pass
    
    def _on_events_selected(self, selected_events):
        """
        Handle event selection from timeline canvas.
        
        Args:
            selected_events (list): List of selected event data dictionaries
        """
        if not selected_events:
            # Clear details panel
            if self.event_details_panel:
                self.event_details_panel.clear()
            return
        
        # For single selection, show context information
        if len(selected_events) == 1 and self.event_details_panel:
            event = selected_events[0]
            
            # Find nearby events (within 5 minutes before/after)
            nearby_events = self._find_nearby_events(event, minutes=5)
            
            # Find related events (same file/app)
            related_events = self._find_related_events(event)
            
            # Display with context
            self.event_details_panel.display_event_context(event, nearby_events, related_events)
        
        # For multi-selection, just display the events
        elif self.event_details_panel:
            self.event_details_panel.display_events(selected_events)
    
    def _on_filter_changed(self, filter_config):
        """
        Handle filter changes from filter bar.
        
        Args:
            filter_config (dict): Filter configuration
        """
        artifact_types = filter_config.get('artifact_types', [])
        print(f"Filter changed: {len(artifact_types)} artifact types selected")
        
        # Apply filters to current events
        self._apply_filters()
    
    def _on_time_range_changed(self, start_time, end_time):
        """
        Handle time range changes from filter bar.
        
        Args:
            start_time: Start time of range (None for all time)
            end_time: End time of range (None for all time)
        """
        print(f"Time range changed: {start_time} to {end_time}")
        
        # Store current time range
        self.current_time_range = (start_time, end_time)
        
        # Reload data with new time range
        self._load_timeline_data()
    
    def _on_zoom_changed(self, zoom_level):
        """
        Handle zoom level changes from filter bar.
        
        Args:
            zoom_level (int): New zoom level
        """
        print(f"Zoom level changed: {zoom_level}")
        
        # Update timeline canvas zoom level
        if self.timeline_canvas:
            self.timeline_canvas.set_zoom_level(zoom_level)
    
    def _on_search_requested(self, search_term):
        """
        Handle search requests from filter bar.
        
        Args:
            search_term (str): Search term
        """
        print(f"Search requested: {search_term}")
        # TODO: Implement search functionality in Phase 4
        pass
    
    def _on_srum_show_ids_changed(self, show_ids):
        """
        Handle SRUM show IDs option change from filter bar.
        
        Args:
            show_ids (bool): Whether to show IDs alongside names
        """
        print(f"SRUM show IDs changed: {show_ids}")
        
        # Update data manager setting
        if self.data_manager:
            self.data_manager.set_srum_show_ids(show_ids)
            
            # Reload timeline data to apply the change
            self._load_timeline_data()
    
    def _load_initial_data(self):
        """
        Load initial timeline data when dialog opens.
        
        This method:
        1. Gets time bounds from all databases
        2. Sets the timeline canvas time range
        3. Loads events for the initial view
        """
        if not self.data_manager:
            return
        
        progress = None
        try:
            # Show progress dialog
            progress = QProgressDialog("Loading timeline data...", "Cancel", 0, 100, self)
            progress.setWindowTitle("Timeline Loading")
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(0)
            progress.setValue(10)
            
            # Get time bounds from all databases
            progress.setLabelText("Finding time bounds...")
            progress.setValue(20)
            
            try:
                start_time, end_time = self.data_manager.get_all_time_bounds()
            except Exception as e:
                progress.close()
                
                # Create detailed error message
                from timeline.utils.error_handler import TimelineError
                
                if not isinstance(e, TimelineError):
                    # Wrap generic exception with better message
                    error = TimelineError(
                        message="Unable to find timeline data in case databases",
                        details=f"Error while scanning databases for time bounds:\n{str(e)}\n\n"
                                f"Possible causes:\n"
                                f"1. No artifacts have been collected yet\n"
                                f"2. Database files are missing or corrupted\n"
                                f"3. Database files are in an incompatible format\n"
                                f"4. Insufficient permissions to read database files"
                    )
                else:
                    error = e
                
                # Offer recovery options
                selected = self.error_handler.handle_error(
                    error,
                    "finding time bounds in databases",
                    show_dialog=True,
                    recovery_options=create_recovery_options(
                        retry_func=lambda: self._load_initial_data(),
                        skip_func=lambda: None
                    )
                )
                
                if selected == "Retry":
                    return self._load_initial_data()
                return
            
            if not start_time or not end_time:
                progress.close()
                
                from timeline.utils.error_handler import TimelineError
                
                error = TimelineError(
                    message="No timeline data found in case databases",
                    details="The timeline could not find any events in the case databases.\n\n"
                            "Possible causes:\n"
                            "1. No artifacts have been collected yet - run artifact collection first\n"
                            "2. All database files are empty\n"
                            "3. Database files contain no valid timestamps\n"
                            "4. All timestamps were filtered out as invalid (before year 2000)\n\n"
                            "Suggested actions:\n"
                            "1. Verify artifact collection has been run for this case\n"
                            "2. Check that artifact databases exist in the case directory\n"
                            "3. Review artifact collection logs for errors\n"
                            f"4. Case directory: {self.case_paths.get('case_root', 'Unknown')}"
                )
                
                self.error_handler.handle_error(
                    error,
                    "loading timeline data",
                    show_dialog=True
                )
                return
            
            progress.setValue(40)
            
            # Set time range on canvas
            progress.setLabelText("Initializing timeline canvas...")
            try:
                if self.timeline_canvas:
                    self.timeline_canvas.set_time_range(start_time, end_time)
            except Exception as e:
                progress.close()
                self.error_handler.handle_error(
                    e,
                    "initializing timeline canvas",
                    show_dialog=True
                )
                return
            
            progress.setValue(60)
            
            # Store time range
            self.current_time_range = (None, None)  # All time mode
            
            # Load events
            progress.setLabelText("Loading events...")
            self._load_timeline_data()
            
            progress.setValue(100)
            progress.close()
            
            print(f"Timeline initialized: {start_time} to {end_time}")
            print(f"Loaded {len(self.current_events)} events")
        
        except Exception as e:
            if progress:
                progress.close()
            
            self.error_handler.handle_error(
                e,
                "loading initial timeline data",
                show_dialog=True,
                recovery_options=create_recovery_options(
                    retry_func=lambda: self._load_initial_data()
                )
            )
    
    def _check_query_performance_warnings(self):
        """
        Check if the current query configuration might have performance issues
        and warn the user with suggestions for improvement.
        
        Returns:
            bool: True if query should proceed, False if user cancelled
        """
        from datetime import timedelta
        from PyQt5.QtWidgets import QMessageBox, QPushButton
        
        # Get current query parameters
        start_time, end_time = self.current_time_range
        
        # If in "all time" mode, use canvas time range
        if start_time is None and end_time is None:
            if self.timeline_canvas and self.timeline_canvas.start_time and self.timeline_canvas.end_time:
                start_time = self.timeline_canvas.start_time
                end_time = self.timeline_canvas.end_time
        
        if not start_time or not end_time:
            return True  # Can't estimate, proceed
        
        # Get active artifact types
        artifact_types = self.filter_bar.get_active_artifact_types() if self.filter_bar else []
        
        # Calculate time range duration
        time_range = end_time - start_time
        
        # Get database sizes and estimate query time
        db_info = self._get_database_info()
        estimated_time, warning_level = self._estimate_query_time(time_range, artifact_types, db_info)
        
        # Only show warning if there's a potential performance issue
        if warning_level == "none":
            return True
        
        # Build warning message
        warning_msg = self._build_performance_warning_message(
            time_range, artifact_types, db_info, estimated_time, warning_level
        )
        
        # Show warning dialog with options
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Query Performance Warning")
        msg_box.setIcon(QMessageBox.Warning)
        msg_box.setText(warning_msg)
        
        # Add custom buttons
        continue_btn = msg_box.addButton("Continue Anyway", QMessageBox.AcceptRole)
        optimize_btn = msg_box.addButton("Optimize Query", QMessageBox.RejectRole)
        cancel_btn = msg_box.addButton("Cancel", QMessageBox.RejectRole)
        
        msg_box.setDefaultButton(optimize_btn)
        msg_box.exec_()
        
        clicked_button = msg_box.clickedButton()
        
        if clicked_button == continue_btn:
            return True  # Proceed with query
        elif clicked_button == optimize_btn:
            # Show optimization suggestions
            self._show_optimization_suggestions(time_range, artifact_types)
            return False  # Don't proceed, let user adjust
        else:
            return False  # User cancelled
    
    def _get_database_info(self):
        """
        Get information about database sizes and record counts.
        
        Returns:
            dict: Database information including sizes and estimated record counts
        """
        import os
        
        db_info = {
            'total_size_mb': 0,
            'databases': {},
            'total_estimated_records': 0
        }
        
        if not self.data_manager or not self.case_paths:
            return db_info
        
        # Check each database file
        db_paths = {
            'Prefetch': self.case_paths.get('prefetch_db'),
            'LNK': self.case_paths.get('lnk_db'),
            'Registry': self.case_paths.get('registry_db'),
            'BAM': self.case_paths.get('bam_db'),
            'ShellBag': self.case_paths.get('shellbags_db'),
            'SRUM': self.case_paths.get('srum_db'),
            'USN': self.case_paths.get('usn_db'),
            'MFT': self.case_paths.get('mft_db'),
            'Logs': self.case_paths.get('logs_db')
        }
        
        for artifact_type, db_path in db_paths.items():
            if not db_path or not os.path.exists(db_path):
                continue
            
            try:
                # Get file size in MB
                size_bytes = os.path.getsize(db_path)
                size_mb = size_bytes / (1024 * 1024)
                
                # Estimate record count (rough estimate: ~1KB per record average)
                estimated_records = int(size_bytes / 1024)
                
                db_info['databases'][artifact_type] = {
                    'size_mb': size_mb,
                    'estimated_records': estimated_records,
                    'path': db_path
                }
                
                db_info['total_size_mb'] += size_mb
                db_info['total_estimated_records'] += estimated_records
            
            except Exception as e:
                print(f"Error getting info for {artifact_type} database: {e}")
                continue
        
        return db_info
    
    def _estimate_query_time(self, time_range, artifact_types, db_info):
        """
        Estimate query execution time based on time range, filters, and database size.
        
        Args:
            time_range: timedelta object representing the query time range
            artifact_types: List of artifact types to query
            db_info: Database information from _get_database_info()
        
        Returns:
            tuple: (estimated_seconds, warning_level)
                - estimated_seconds: Estimated query time in seconds
                - warning_level: "none", "low", "medium", or "high"
        """
        from datetime import timedelta
        
        # Base query time per 10,000 records (with indexes): ~0.1 seconds
        # Without filters on large time range: multiply by time range factor
        
        # Calculate time range factor (days)
        days = time_range.days + (time_range.seconds / 86400)
        
        # Estimate records to scan based on time range and artifact types
        if not artifact_types:
            # No filters - will query all types
            estimated_records = db_info['total_estimated_records']
            type_count = len(db_info['databases'])
        else:
            # Filtered - only selected types
            estimated_records = sum(
                db_info['databases'].get(atype, {}).get('estimated_records', 0)
                for atype in artifact_types
            )
            type_count = len(artifact_types)
        
        # Time range factor: larger ranges take longer
        # Full timeline (>365 days) = 1.0x, 30 days = 0.5x, 7 days = 0.3x, 1 day = 0.1x
        if days > 365:
            time_factor = 1.0
        elif days > 90:
            time_factor = 0.8
        elif days > 30:
            time_factor = 0.5
        elif days > 7:
            time_factor = 0.3
        else:
            time_factor = 0.1
        
        # Estimate query time
        # Base: 0.1 seconds per 10,000 records
        # Multiply by time factor and number of databases
        base_time = (estimated_records / 10000) * 0.1
        estimated_time = base_time * time_factor * type_count
        
        # Determine warning level
        if estimated_time < 2:
            warning_level = "none"
        elif estimated_time < 5:
            warning_level = "low"
        elif estimated_time < 15:
            warning_level = "medium"
        else:
            warning_level = "high"
        
        # Additional factors that increase warning level
        # Large time range with no filters
        if days > 180 and not artifact_types:
            if warning_level == "none":
                warning_level = "low"
            elif warning_level == "low":
                warning_level = "medium"
        
        # Very large databases
        if db_info['total_size_mb'] > 500:
            if warning_level == "low":
                warning_level = "medium"
            elif warning_level == "medium":
                warning_level = "high"
        
        return estimated_time, warning_level
    
    def _build_performance_warning_message(self, time_range, artifact_types, db_info, estimated_time, warning_level):
        """
        Build a detailed performance warning message with suggestions.
        
        Args:
            time_range: timedelta object
            artifact_types: List of artifact types
            db_info: Database information
            estimated_time: Estimated query time in seconds
            warning_level: Warning level string
        
        Returns:
            str: Formatted warning message
        """
        days = time_range.days + (time_range.seconds / 86400)
        
        # Build main warning
        if warning_level == "high":
            severity = "⚠️ High Performance Impact"
        elif warning_level == "medium":
            severity = "⚠️ Moderate Performance Impact"
        else:
            severity = "ℹ️ Performance Notice"
        
        msg = f"<h3>{severity}</h3>"
        msg += f"<p>This query may take <b>{estimated_time:.1f} seconds</b> to complete.</p>"
        
        # Add query details
        msg += "<p><b>Query Details:</b></p>"
        msg += "<ul>"
        msg += f"<li>Time Range: <b>{days:.1f} days</b></li>"
        
        if not artifact_types:
            msg += f"<li>Artifact Types: <b>All types</b> ({len(db_info['databases'])} databases)</li>"
        else:
            msg += f"<li>Artifact Types: <b>{len(artifact_types)} selected</b></li>"
        
        msg += f"<li>Total Database Size: <b>{db_info['total_size_mb']:.1f} MB</b></li>"
        msg += f"<li>Estimated Records: <b>{db_info['total_estimated_records']:,}</b></li>"
        msg += "</ul>"
        
        # Add suggestions
        msg += "<p><b>Suggestions for Better Performance:</b></p>"
        msg += "<ul>"
        
        if days > 30:
            msg += "<li>✓ <b>Reduce time range</b> - Use custom time range to focus on specific periods</li>"
        
        if not artifact_types or len(artifact_types) > 5:
            msg += "<li>✓ <b>Select specific artifact types</b> - Uncheck types you don't need</li>"
        
        if db_info['total_size_mb'] > 200:
            msg += "<li>✓ <b>Use filters</b> - Apply filters after loading to narrow results</li>"
        
        msg += "<li>✓ <b>Zoom in</b> - Load a smaller time window first, then zoom to see details</li>"
        msg += "</ul>"
        
        msg += "<p><i>You can continue anyway if you need all this data.</i></p>"
        
        return msg
    
    def _show_optimization_suggestions(self, time_range, artifact_types):
        """
        Show a dialog with specific optimization suggestions.
        
        Args:
            time_range: timedelta object
            artifact_types: List of artifact types
        """
        from PyQt5.QtWidgets import QMessageBox
        
        days = time_range.days + (time_range.seconds / 86400)
        
        msg = "<h3>Query Optimization Suggestions</h3>"
        msg += "<p>Here are specific ways to improve query performance:</p>"
        
        msg += "<h4>1. Reduce Time Range</h4>"
        msg += "<ul>"
        if days > 365:
            msg += "<li>Current range: <b>Full timeline</b></li>"
            msg += "<li>Suggestion: Start with <b>last 30 days</b> or a specific month</li>"
        elif days > 90:
            msg += f"<li>Current range: <b>{days:.0f} days</b></li>"
            msg += "<li>Suggestion: Reduce to <b>30 days</b> or less</li>"
        else:
            msg += f"<li>Current range: <b>{days:.0f} days</b></li>"
            msg += "<li>Suggestion: Focus on <b>specific days</b> of interest</li>"
        msg += "</ul>"
        
        msg += "<h4>2. Select Specific Artifact Types</h4>"
        msg += "<ul>"
        if not artifact_types:
            msg += "<li>Current: <b>All artifact types</b> selected</li>"
            msg += "<li>Suggestion: Select only the types you need:</li>"
            msg += "<li>&nbsp;&nbsp;• <b>Prefetch</b> - Application execution</li>"
            msg += "<li>&nbsp;&nbsp;• <b>LNK</b> - File access shortcuts</li>"
            msg += "<li>&nbsp;&nbsp;• <b>Registry</b> - System configuration changes</li>"
            msg += "<li>&nbsp;&nbsp;• <b>USN</b> - File system changes</li>"
        else:
            msg += f"<li>Current: <b>{len(artifact_types)} types</b> selected</li>"
            msg += "<li>Suggestion: Further reduce if possible</li>"
        msg += "</ul>"
        
        msg += "<h4>3. Use Progressive Loading</h4>"
        msg += "<ul>"
        msg += "<li>Load a <b>smaller time window</b> first</li>"
        msg += "<li>Use <b>zoom and pan</b> to explore the timeline</li>"
        msg += "<li>Apply <b>additional filters</b> after initial load</li>"
        msg += "</ul>"
        
        msg += "<p><i>Adjust your filters and try again.</i></p>"
        
        QMessageBox.information(self, "Optimization Suggestions", msg)
    
    def _load_timeline_data(self, max_events=20000):
        """
        Load timeline data based on current time range and filters.
        
        This method starts a background query worker thread to query the data
        manager for events within the current time range without blocking the UI.
        
        Progressive loading: Initially loads up to max_events (default 20,000) for
        better performance. More events can be loaded on demand when scrolling.
        
        Args:
            max_events (int): Maximum number of events to load initially (default: 20,000)
        """
        if not self.data_manager:
            return
        
        try:
            # Check for performance warnings before executing query
            should_continue = self._check_query_performance_warnings()
            if not should_continue:
                return
            # Cancel any existing query
            if self.query_worker and self.query_worker.isRunning():
                print("Cancelling previous query...")
                self.query_worker.cancel()
                self.query_worker.wait(1000)  # Wait up to 1 second for cancellation
                if self.query_worker.isRunning():
                    self.query_worker.terminate()  # Force terminate if still running
            
            # Show loading indicator on canvas with progress bar
            if self.timeline_canvas:
                self.timeline_canvas.loading_overlay.show_loading_with_progress(
                    message=f"Loading timeline data (up to {max_events:,} events)...",
                    current=0,
                    total=1,
                    artifact_type="",
                    event_count=0
                )
            
            # Get active artifact types from filter bar
            artifact_types = self.filter_bar.get_active_artifact_types() if self.filter_bar else None
            
            # Get time range
            start_time, end_time = self.current_time_range
            
            # If in "all time" mode, use canvas time range
            if start_time is None and end_time is None:
                if self.timeline_canvas and self.timeline_canvas.start_time and self.timeline_canvas.end_time:
                    start_time = self.timeline_canvas.start_time
                    end_time = self.timeline_canvas.end_time
            
            print(f"Starting background query: {start_time} to {end_time}, types: {artifact_types}, max: {max_events}")
            
            # Create and configure query worker with limit
            self.query_worker = QueryWorker(
                self.data_manager,
                start_time=start_time,
                end_time=end_time,
                artifact_types=artifact_types,
                max_events=max_events  # Add limit for progressive loading
            )
            
            # Connect signals
            self.query_worker.progress.connect(self._on_query_progress)
            self.query_worker.finished.connect(self._on_query_finished)
            self.query_worker.error.connect(self._on_query_error)
            self.query_worker.cancelled.connect(self._on_query_cancelled)
            
            # Start the worker thread
            self.query_worker.start()
        
        except Exception as e:
            # Hide loading indicator on error
            if self.timeline_canvas:
                self.timeline_canvas.loading_overlay.hide_loading()
            
            # Handle unexpected error
            self.error_handler.handle_error(
                e,
                "starting timeline query",
                show_dialog=True,
                recovery_options=create_recovery_options(
                    retry_func=lambda: self._load_timeline_data()
                )
            )
    
    def _on_query_progress(self, current, total, artifact_type, message):
        """
        Handle query progress updates from worker thread.
        
        Args:
            current: Current artifact type index
            total: Total number of artifact types
            artifact_type: Name of artifact type being queried
            message: Progress message (contains event count)
        """
        # Extract event count from message
        # Message format: "Querying {artifact_type}... ({count} events loaded)"
        # or "Loaded {count} events from {artifact_type} (total: {total_count})"
        import re
        event_count = 0
        
        # Try to extract event count from message
        match = re.search(r'\((\d+(?:,\d+)*)\s+events loaded\)', message)
        if not match:
            match = re.search(r'total:\s+(\d+(?:,\d+)*)', message)
        
        if match:
            # Remove commas and convert to int
            event_count_str = match.group(1).replace(',', '')
            try:
                event_count = int(event_count_str)
            except ValueError:
                event_count = 0
        
        # Update loading indicator with per-artifact progress
        if self.timeline_canvas:
            self.timeline_canvas.loading_overlay.update_progress(
                current=current,
                total=total,
                artifact_type=artifact_type,
                event_count=event_count
            )
        
        print(f"Query progress: {current}/{total} - {artifact_type} - {event_count:,} events")
    
    def _on_query_finished(self, all_events):
        """
        Handle query completion from worker thread.
        
        This method is called in the main thread when the query worker finishes.
        
        Args:
            all_events: List of event dictionaries returned by the query
        """
        print(f"Query finished: {len(all_events)} events loaded")
        
        try:
            # Limit events for performance (sample if too many)
            MAX_EVENTS = 5000
            if len(all_events) > MAX_EVENTS:
                print(f"Too many events ({len(all_events)}), sampling to {MAX_EVENTS}")
                
                # Use time-based sampling for even distribution
                self.current_events, sampling_metadata = self._sample_events_by_time(all_events, MAX_EVENTS)
                print(f"Sampled {len(self.current_events)} events using time-based distribution")
                
                # Update filter bar sampling indicator with metadata
                if self.filter_bar:
                    self.filter_bar.update_sampling_indicator(
                        is_sampled=True,
                        sample_count=len(self.current_events),
                        total_available=len(all_events)
                    )
                
                # Hide loading indicator before showing message
                if self.timeline_canvas:
                    self.timeline_canvas.loading_overlay.hide_loading()
                
                # Show info message with sampling metadata
                QMessageBox.information(
                    self, 
                    "Large Dataset", 
                    f"Loaded {len(all_events):,} events.\n\n"
                    f"Displaying a sample of {len(self.current_events):,} events for performance.\n\n"
                    f"Sampling method: Time-based distribution\n"
                    f"Time buckets: {sampling_metadata['num_buckets']}\n"
                    f"Events per bucket: ~{sampling_metadata['avg_per_bucket']}\n\n"
                    f"Use time range filtering or zoom in to see more detail."
                )
            else:
                self.current_events = all_events
                
                # Update filter bar to show no sampling
                if self.filter_bar:
                    self.filter_bar.update_sampling_indicator(
                        is_sampled=False,
                        sample_count=len(all_events),
                        total_available=len(all_events)
                    )
            
            # Apply filters and render
            self._apply_filters()
            
            # Hide loading indicator
            if self.timeline_canvas:
                self.timeline_canvas.loading_overlay.hide_loading()
        
        except Exception as e:
            # Hide loading indicator on error
            if self.timeline_canvas:
                self.timeline_canvas.loading_overlay.hide_loading()
            
            # Handle error processing results
            self.error_handler.handle_error(
                e,
                "processing query results",
                show_dialog=True
            )
    
    def _sample_events_by_time(self, events, max_events):
        """
        Sample events using time-based distribution for even representation.
        
        This method divides the time range into buckets and samples events
        proportionally from each bucket to ensure even distribution across
        the entire timeline, avoiding over-representation of dense periods.
        
        Args:
            events: List of all events to sample from
            max_events: Maximum number of events to return
        
        Returns:
            tuple: (sampled_events, metadata_dict)
                - sampled_events: List of sampled events
                - metadata_dict: Dictionary with sampling statistics
        """
        from datetime import datetime, timedelta
        
        if not events:
            return [], {'num_buckets': 0, 'avg_per_bucket': 0}
        
        # Sort events by timestamp
        sorted_events = sorted(events, key=lambda e: e.get('timestamp', datetime.min))
        
        # Get time range
        start_time = sorted_events[0].get('timestamp')
        end_time = sorted_events[-1].get('timestamp')
        
        if not start_time or not end_time or start_time == end_time:
            # Fallback to simple sampling if time range is invalid
            step = max(1, len(events) // max_events)
            return sorted_events[::step][:max_events], {'num_buckets': 1, 'avg_per_bucket': max_events}
        
        # Calculate time range duration
        time_range = end_time - start_time
        
        # Determine number of time buckets (aim for ~50-100 events per bucket)
        target_events_per_bucket = 75
        num_buckets = max(10, min(200, max_events // target_events_per_bucket))
        
        # Calculate bucket duration
        bucket_duration = time_range / num_buckets
        
        # Create buckets
        buckets = [[] for _ in range(num_buckets)]
        
        # Distribute events into buckets
        for event in sorted_events:
            event_time = event.get('timestamp')
            if not event_time:
                continue
            
            # Calculate which bucket this event belongs to
            time_offset = event_time - start_time
            bucket_index = int((time_offset / time_range) * num_buckets)
            
            # Clamp to valid bucket range
            bucket_index = max(0, min(num_buckets - 1, bucket_index))
            
            buckets[bucket_index].append(event)
        
        # Calculate events to sample from each bucket
        # Distribute max_events proportionally based on bucket sizes
        total_events = len(sorted_events)
        sampled_events = []
        
        for bucket in buckets:
            if not bucket:
                continue
            
            # Calculate proportional sample size for this bucket
            bucket_proportion = len(bucket) / total_events
            bucket_sample_size = max(1, int(max_events * bucket_proportion))
            
            # Sample from this bucket
            if len(bucket) <= bucket_sample_size:
                # Take all events if bucket is small
                sampled_events.extend(bucket)
            else:
                # Sample evenly from bucket
                step = len(bucket) / bucket_sample_size
                indices = [int(i * step) for i in range(bucket_sample_size)]
                sampled_events.extend([bucket[i] for i in indices if i < len(bucket)])
        
        # Ensure we don't exceed max_events
        if len(sampled_events) > max_events:
            # Final trim if we slightly exceeded
            step = len(sampled_events) / max_events
            indices = [int(i * step) for i in range(max_events)]
            sampled_events = [sampled_events[i] for i in indices if i < len(sampled_events)]
        
        # Calculate metadata
        non_empty_buckets = sum(1 for b in buckets if b)
        avg_per_bucket = len(sampled_events) // non_empty_buckets if non_empty_buckets > 0 else 0
        
        metadata = {
            'num_buckets': num_buckets,
            'non_empty_buckets': non_empty_buckets,
            'avg_per_bucket': avg_per_bucket,
            'total_events': total_events,
            'sampled_events': len(sampled_events),
            'time_range': str(time_range),
            'bucket_duration': str(bucket_duration)
        }
        
        print(f"Time-based sampling: {len(sampled_events)} events from {num_buckets} buckets "
              f"({non_empty_buckets} non-empty), avg {avg_per_bucket} per bucket")
        
        return sampled_events, metadata
    
    def _on_query_error(self, exception, error_message):
        """
        Handle query error from worker thread.
        
        Args:
            exception: The exception that occurred
            error_message: Error message string
        """
        print(f"Query error: {error_message}")
        
        # Hide loading indicator
        if self.timeline_canvas:
            self.timeline_canvas.loading_overlay.hide_loading()
        
        # Handle query error with recovery options
        selected = self.error_handler.handle_error(
            exception,
            "querying timeline data",
            show_dialog=True,
            recovery_options=create_recovery_options(
                retry_func=lambda: self._load_timeline_data(),
                skip_func=lambda: None
            )
        )
        
        if selected == "Retry":
            self._load_timeline_data()
    
    def _on_query_cancelled(self):
        """Handle query cancellation from worker thread."""
        print("Query cancelled")
        
        # Hide loading indicator
        if self.timeline_canvas:
            self.timeline_canvas.loading_overlay.hide_loading()
    
    def _apply_filters(self):
        """
        Apply current filters to loaded events and update canvas.
        
        This method filters the current_events based on active artifact types
        and updates the timeline canvas with the filtered results.
        """
        if not self.current_events:
            # No events loaded, clear canvas
            if self.timeline_canvas:
                self.timeline_canvas.clear_timeline()
            return
        
        # Get active artifact types from filter bar
        active_types = self.filter_bar.get_active_artifact_types() if self.filter_bar else []
        
        if not active_types:
            # No types selected, show nothing
            self.filtered_events = []
        else:
            # Filter events by artifact type
            self.filtered_events = [
                event for event in self.current_events
                if event.get('artifact_type') in active_types
            ]
        
        print(f"Filtered to {len(self.filtered_events)} events (from {len(self.current_events)} total)")
        
        # Clear context cache and rebuild indexes when filters change
        self._clear_context_cache()
        self._build_event_indexes()
        
        # Update canvas with filtered events
        self._render_timeline()
    
    def _render_timeline(self):
        """
        Render the filtered events on the timeline canvas.
        
        This method updates the timeline canvas with the current filtered events.
        """
        if not self.timeline_canvas:
            return
        
        try:
            # Render events on canvas
            self.timeline_canvas.render_events(self.filtered_events)
            
            print(f"Rendered {len(self.filtered_events)} events on timeline")
        
        except Exception as e:
            # Handle rendering error with recovery options
            selected = self.error_handler.handle_error(
                e,
                "rendering timeline",
                show_dialog=True,
                recovery_options=create_recovery_options(
                    retry_func=lambda: self._render_timeline(),
                    skip_func=lambda: None
                )
            )
            
            if selected == "Retry":
                self._render_timeline()
    
    def _clear_context_cache(self):
        """
        Clear the context query cache.
        
        This should be called when filtered_events changes to ensure
        cache consistency.
        """
        self._context_cache.clear()
        self._events_by_time_index.clear()
        self._events_by_path_index.clear()
    
    def _build_event_indexes(self):
        """
        Build indexes for fast context query lookups.
        
        Creates:
        - Time-based index: Groups events by time buckets for nearby event lookup
        - Path-based index: Groups events by (artifact_type, display_name, path) for related event lookup
        """
        from datetime import timedelta
        
        if not self.filtered_events:
            return
        
        # Build time-based index (5-minute buckets)
        # This allows O(1) lookup of events in a time range
        for event in self.filtered_events:
            event_time = event.get('timestamp')
            if not event_time:
                continue
            
            # Create bucket key (rounded to 5-minute intervals)
            # This groups events that are within 5 minutes of each other
            bucket_minutes = (event_time.hour * 60 + event_time.minute) // 5
            bucket_key = (event_time.year, event_time.month, event_time.day, bucket_minutes)
            
            if bucket_key not in self._events_by_time_index:
                self._events_by_time_index[bucket_key] = []
            
            self._events_by_time_index[bucket_key].append(event)
        
        # Build path-based index for related events
        # Groups events by (artifact_type, normalized_display_name, normalized_path)
        for event in self.filtered_events:
            artifact_type = event.get('artifact_type')
            display_name = event.get('display_name', '').lower().strip()
            full_path = event.get('full_path', '').lower().strip()
            
            if not artifact_type:
                continue
            
            # Index by display name if available
            if display_name:
                key = (artifact_type, 'name', display_name)
                if key not in self._events_by_path_index:
                    self._events_by_path_index[key] = []
                self._events_by_path_index[key].append(event)
            
            # Index by full path if available
            if full_path:
                key = (artifact_type, 'path', full_path)
                if key not in self._events_by_path_index:
                    self._events_by_path_index[key] = []
                self._events_by_path_index[key].append(event)
    
    def _get_time_buckets_for_range(self, start_time, end_time):
        """
        Get all time bucket keys that overlap with the given time range.
        
        Args:
            start_time: Start of time range
            end_time: End of time range
        
        Returns:
            List of bucket keys that overlap with the range
        """
        from datetime import timedelta
        
        bucket_keys = []
        current_time = start_time
        
        # Iterate through time range in 5-minute increments
        while current_time <= end_time:
            bucket_minutes = (current_time.hour * 60 + current_time.minute) // 5
            bucket_key = (current_time.year, current_time.month, current_time.day, bucket_minutes)
            
            if bucket_key not in bucket_keys:
                bucket_keys.append(bucket_key)
            
            # Move to next 5-minute bucket
            current_time += timedelta(minutes=5)
        
        return bucket_keys
    
    def _find_nearby_events(self, event, minutes=5):
        """
        Find events that occurred near the given event in time.
        
        Uses time-based indexing and caching for O(1) average case performance
        instead of O(n) linear search.
        
        Args:
            event: The reference event
            minutes: Time window in minutes (before and after)
        
        Returns:
            List[Dict]: List of nearby events
        """
        from datetime import timedelta
        
        event_id = event.get('id')
        event_time = event.get('timestamp')
        
        if not event_time:
            return []
        
        # Check cache first
        cache_key = f"nearby_{event_id}_{minutes}"
        if cache_key in self._context_cache:
            return self._context_cache[cache_key]
        
        # Calculate time window
        time_before = event_time - timedelta(minutes=minutes)
        time_after = event_time + timedelta(minutes=minutes)
        
        # Get relevant time buckets
        bucket_keys = self._get_time_buckets_for_range(time_before, time_after)
        
        # Collect events from relevant buckets
        nearby = []
        seen_ids = set()
        
        for bucket_key in bucket_keys:
            bucket_events = self._events_by_time_index.get(bucket_key, [])
            
            for e in bucket_events:
                e_id = e.get('id')
                e_time = e.get('timestamp')
                
                # Skip if already seen or is the event itself
                if e_id in seen_ids or e_id == event_id:
                    continue
                
                # Check if within time window
                if e_time and time_before <= e_time <= time_after:
                    nearby.append(e)
                    seen_ids.add(e_id)
        
        # Sort by timestamp
        nearby.sort(key=lambda e: e.get('timestamp'))
        
        # Cache the result
        self._context_cache[cache_key] = nearby
        
        return nearby
    
    def _find_related_events(self, event):
        """
        Find events related to the given event (same file/application).
        
        Uses path-based indexing and caching for O(1) average case performance
        instead of O(n) linear search with string comparisons.
        
        Args:
            event: The reference event
        
        Returns:
            List[Dict]: List of related events
        """
        event_id = event.get('id')
        artifact_type = event.get('artifact_type')
        display_name = event.get('display_name', '').lower().strip()
        full_path = event.get('full_path', '').lower().strip()
        
        if not artifact_type or (not display_name and not full_path):
            return []
        
        # Check cache first
        cache_key = f"related_{event_id}"
        if cache_key in self._context_cache:
            return self._context_cache[cache_key]
        
        # Collect related events using indexes
        related = []
        seen_ids = set()
        
        # Find by display name
        if display_name:
            name_key = (artifact_type, 'name', display_name)
            name_events = self._events_by_path_index.get(name_key, [])
            
            for e in name_events:
                e_id = e.get('id')
                if e_id != event_id and e_id not in seen_ids:
                    related.append(e)
                    seen_ids.add(e_id)
        
        # Find by full path
        if full_path:
            path_key = (artifact_type, 'path', full_path)
            path_events = self._events_by_path_index.get(path_key, [])
            
            for e in path_events:
                e_id = e.get('id')
                if e_id != event_id and e_id not in seen_ids:
                    related.append(e)
                    seen_ids.add(e_id)
        
        # Sort by timestamp
        related.sort(key=lambda e: e.get('timestamp'))
        
        # Cache the result
        self._context_cache[cache_key] = related
        
        return related

    def resizeEvent(self, event):
        """
        Handle window resize events to adjust layout responsively.
        
        This method implements responsive layout adjustments:
        - Adjusts filter bar and details panel heights based on window size
        - Ensures timeline canvas maintains minimum readable size
        - Maintains aspect ratio and readability of timeline elements
        
        Args:
            event: QResizeEvent
        """
        super().resizeEvent(event)
        
        # Get new window dimensions
        new_width = event.size().width()
        new_height = event.size().height()
        
        # Calculate responsive heights based on window size
        # Filter bar: 15-20% of height, capped at 200px
        filter_bar_height = min(200, max(100, int(new_height * 0.15)))
        
        # Event details panel: 15-20% of height, capped at 200px
        details_panel_height = min(200, max(100, int(new_height * 0.15)))
        
        # Apply responsive sizing
        if self.filter_bar:
            self.filter_bar.setMaximumHeight(filter_bar_height)
            
            # Adjust filter bar layout for narrow windows
            if new_width < 1200:
                # Compact mode for narrow windows
                self.filter_bar.setMaximumHeight(min(250, filter_bar_height + 50))
        
        if self.event_details_panel:
            self.event_details_panel.setMaximumHeight(details_panel_height)
            
            # Make details panel scrollable for narrow windows
            if new_width < 1200:
                # Ensure scroll area is enabled
                if hasattr(self.event_details_panel, 'scroll_area'):
                    self.event_details_panel.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        # Ensure timeline canvas maintains minimum readable size
        if self.timeline_canvas:
            # Calculate available height for canvas
            available_height = new_height - filter_bar_height - details_panel_height - 100  # 100px for margins/spacing
            min_canvas_height = 300
            
            if available_height < min_canvas_height:
                # Reduce details panel height to maintain canvas size
                adjusted_details_height = max(80, details_panel_height - (min_canvas_height - available_height))
                if self.event_details_panel:
                    self.event_details_panel.setMaximumHeight(adjusted_details_height)
        
        # Update last size tracking
        self._last_width = new_width
        self._last_height = new_height
    
    def closeEvent(self, event):
        """
        Handle dialog close event to clean up resources.
        
        This method ensures that all background worker threads are properly
        stopped and database connections are closed before the dialog closes.
        
        Args:
            event: QCloseEvent
        """
        print("Timeline dialog closing, cleaning up resources...")
        
        try:
            # Cancel and wait for query worker
            if self.query_worker and self.query_worker.isRunning():
                print("Stopping query worker...")
                self.query_worker.cancel()
                self.query_worker.wait(2000)  # Wait up to 2 seconds
                if self.query_worker.isRunning():
                    print("Force terminating query worker...")
                    self.query_worker.terminate()
                    self.query_worker.wait(1000)
            
            # Cancel and wait for aggregation worker
            if self.aggregation_worker and self.aggregation_worker.isRunning():
                print("Stopping aggregation worker...")
                self.aggregation_worker.cancel()
                self.aggregation_worker.wait(2000)
                if self.aggregation_worker.isRunning():
                    print("Force terminating aggregation worker...")
                    self.aggregation_worker.terminate()
                    self.aggregation_worker.wait(1000)
            
            # Wait for indexing worker (no cancel method, just wait)
            if self.indexing_worker and self.indexing_worker.isRunning():
                print("Waiting for indexing worker...")
                self.indexing_worker.wait(2000)
                if self.indexing_worker.isRunning():
                    print("Force terminating indexing worker...")
                    self.indexing_worker.terminate()
                    self.indexing_worker.wait(1000)
            
            # Close database connections
            if self.data_manager:
                print("Closing database connections...")
                self.data_manager.close_connections()
            
            print("Timeline dialog cleanup complete")
        
        except Exception as e:
            print(f"Error during timeline dialog cleanup: {e}")
            # Continue with close even if cleanup fails
        
        # Accept the close event
        event.accept()
