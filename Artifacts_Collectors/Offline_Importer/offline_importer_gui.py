"""
Offline Artifact Importer GUI

This module provides the main GUI application for the Offline Artifact Importer feature.
It enables forensic investigators to collect Windows artifacts from external sources
(forensic images, network shares, USB drives) and organize them into the case directory structure.

Architecture:
    - Three-panel layout: Selection Panel, Progress Panel, Results Panel
    - State management: Idle → Collecting → Complete
    - Background threading for collection operations to keep GUI responsive
    - Integration with existing case management and artifact collection components

Author: Crow-eye Forensics
License: MIT
"""

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QMessageBox, QTableWidget, QProgressBar, QComboBox,
    QCheckBox, QApplication, QSplitter, QFrame, QTableWidgetItem,
    QHeaderView, QMenuBar, QMenu, QAction, QStatusBar, QGridLayout
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QFont, QColor
from typing import Optional, Callable, List
from dataclasses import dataclass
from datetime import datetime
import sys
import os
import time
import logging
import traceback
import types
import hashlib
import json

# Import collection components
from .collection_coordinator import CollectionCoordinator, CollectionSummary, ProgressUpdate
from .artifact_collector import CollectedArtifactInfo

# Import resources (Task 14.4)
from .resources.icons import (
    get_artifact_icon, get_status_icon, get_artifact_color, get_status_color,
    APP_ICON, STATUS_ICONS
)

# Import case management components
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
try:
    from config.case_history_manager import CaseHistoryManager
    from config.data_models import CaseMetadata
    from correlation_engine.config.case_configuration_manager import CaseConfigurationManager
    CASE_MANAGER_AVAILABLE = True
except ImportError:
    print("Warning: Could not import CaseHistoryManager or CaseConfigurationManager. Case management features will be limited.")
    CASE_MANAGER_AVAILABLE = False
    CaseHistoryManager = None
    CaseMetadata = None
    CaseConfigurationManager = None

# Import Crow-eye styles for consistent appearance
try:
    from styles import CrowEyeStyles, Colors
    STYLES_AVAILABLE = True
except ImportError:
    print("Warning: Could not import CrowEyeStyles. Using default styling.")
    STYLES_AVAILABLE = False
    # Fallback color definitions
    class Colors:
        BG_PRIMARY = "#0F172A"
        BG_PANELS = "#1E293B"
        TEXT_PRIMARY = "#E2E8F0"
        ACCENT_BLUE = "#3B82F6"


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class GUIState:
    """Represents the current state of the GUI"""
    state: str  # 'idle', 'collecting', 'complete'
    source_directory: Optional[str] = None
    artifact_type_filter: str = "All Types"
    include_subdirs: bool = True
    verify_hashes: bool = True
    incremental_scan: bool = False  # Task 28.1: Preserve existing scan index when enabled
    # Removed strict_validation - validation is no longer used


# ============================================================================
# Background Collection Worker Thread (Task 11.1)
# ============================================================================

class CollectionWorker(QThread):
    """
    Background worker thread for artifact collection operations.
    
    This QThread-based worker runs the collection process in the background
    to keep the GUI responsive during long-running operations. It emits
    signals for progress updates, completion, and errors.
    
    Signals:
        progress_update: Emitted periodically with ProgressUpdate information
        collection_complete: Emitted when collection finishes successfully
        collection_error: Emitted when collection fails with error message
        collection_cancelled: Emitted when collection is cancelled by user
    """
    
    # Define signals for thread-safe communication with GUI (Task 11.2)
    progress_update = pyqtSignal(object)  # ProgressUpdate object
    artifact_found = pyqtSignal(object)   # Single CollectedArtifactInfo object
    collection_complete = pyqtSignal(object)  # CollectionSummary object
    collection_error = pyqtSignal(str)  # Error message string
    collection_cancelled = pyqtSignal()  # No parameters
    
    def __init__(self, case_root: str, source_dir: str, 
                 artifact_type_filter: Optional[str] = None,
                 include_subdirs: bool = True,
                 verify_hashes: bool = True,
                 scan_only: bool = False,
                 specific_files: Optional[List[str]] = None,
                 strict_validation: bool = False):
        """
        Initialize the collection worker thread.
        """
        super().__init__()
        
        self.case_root = case_root
        self.source_dir = source_dir
        self.artifact_type_filter = artifact_type_filter
        self.include_subdirs = include_subdirs
        self.verify_hashes = verify_hashes
        self.scan_only = scan_only
        self.specific_files = specific_files
        self.strict_validation = strict_validation
        
        # Cancellation flag (Task 11.4)
        self._cancelled = False
        
        # Coordinator reference (will be created in run())
        self.coordinator = None
    
    def run(self):
        """
        Execute the collection or scan process in the background thread.
        """
        try:
            # Create collection coordinator with scan_only mode
            self.coordinator = CollectionCoordinator(
                case_root=self.case_root,
                calculate_hashes=self.verify_hashes,
                validate_artifacts=self.strict_validation,
                scan_only=self.scan_only  # Pass scan_only to coordinator
            )
            
            # Set up progress callback that emits signals (Task 11.2)
            def progress_callback(progress: ProgressUpdate):
                # Check for cancellation (Task 11.4)
                if self._cancelled:
                    # Cancel the coordinator
                    self.coordinator.cancel()
                
                # Emit progress update signal (thread-safe)
                self.progress_update.emit(progress)
            
            self.coordinator.set_progress_callback(progress_callback)
            
            # If scan_only, we modify the collector to NOT copy files
            # For now, let's use the standard collect_artifacts and we'll
            # implement a dedicated scan method in coordinator if needed.
            # But we want real-time updates for the table.
            
            # We'll hook into the collector's internal processing to emit artifact_found
            # Store reference to the original bound method
            artifact_collector = self.coordinator.artifact_collector
            original_process = artifact_collector._process_single_artifact
            
            # Create a wrapper that properly calls the bound method
            def hooked_process(file_path, filter):
                # Call the original bound method (it already has self bound to it)
                result = original_process(file_path, filter)
                if result:
                    self.artifact_found.emit(result)
                return result
            
            # Replace the method with our hooked version using types.MethodType to bind it
            artifact_collector._process_single_artifact = types.MethodType(
                lambda self, file_path, filter: hooked_process(file_path, filter),
                artifact_collector
            )
            
            # Execute collection or scan
            summary = self.coordinator.collect_artifacts(
                source_dir=self.source_dir,
                artifact_type_filter=self.artifact_type_filter,
                include_subdirs=self.include_subdirs
            )
            
            # Check for cancellation one final time
            if self._cancelled:
                self.collection_cancelled.emit()
                return
            
            # Emit completion signal with summary (thread-safe)
            self.collection_complete.emit(summary)
            
        except InterruptedError as e:
            # Collection was cancelled
            self.collection_cancelled.emit()
            
        except Exception as e:
            # Emit error signal (thread-safe) (Task 11.3)
            import traceback
            error_traceback = traceback.format_exc()
            error_msg = f"Collection failed: {str(e)}\n\nFull traceback:\n{error_traceback}"
            print(f"[ERROR] {error_msg}")  # Also print to console for debugging
            self.collection_error.emit(error_msg)
    
    def cancel(self):
        """
        Request cancellation of the collection process (Task 11.4).
        
        This method is thread-safe and can be called from the GUI thread.
        The collection will stop at the next safe checkpoint.
        """
        self._cancelled = True
        # Also cancel the coordinator if it exists
        if self.coordinator:
            self.coordinator.cancel()


# ============================================================================
# Main Application Window
# ============================================================================

class OfflineImporterGUI(QMainWindow):
    """
    Main GUI application for the Offline Artifact Importer.
    
    This class manages the user interface for artifact collection, including:
    - Source directory selection
    - Artifact type filtering
    - Real-time progress tracking
    - Results display and filtering
    
    Attributes:
        state: Current GUI state (idle, collecting, complete)
        collection_thread: Background thread for collection operations
    """
    
    def __init__(self, default_scan_path: Optional[str] = None):
        """
        Initialize the Offline Importer GUI.
        
        Args:
            default_scan_path: Optional default directory for scanning artifacts
        """
        try:
            super().__init__()
            self.state = GUIState(state='idle')
            self.collection_thread: Optional[QThread] = None
            self.current_case_path: Optional[str] = None
            self.case_root: Optional[str] = None
            self.current_case_metadata: Optional[CaseMetadata] = None
            self.logger: Optional[logging.Logger] = None
            self.error_log: List[dict] = []  # Store errors for display (Task 13.3)
            self.selected_files: Optional[List[str]] = None  # Store individually selected files
            self.default_scan_path: Optional[str] = default_scan_path  # Default path for scanning
            
            # Set initial source directory to default scan path if provided
            if default_scan_path:
                self.state.source_directory = default_scan_path
                print(f"[Info] Offline Importer initialized with default scan path: {default_scan_path}")
            
            # Initialize case history manager (Task 12.1)
            if CASE_MANAGER_AVAILABLE:
                self.case_manager = CaseHistoryManager()
            else:
                self.case_manager = None
            
            # Setup logging (Task 13.1)
            self._setup_logging()
            
            # Configure main window
            self.setWindowTitle(f"{APP_ICON} Crow-eye Offline - Artifact Collector")
            
            # Set window size to be responsive to screen size
            from PyQt5.QtWidgets import QDesktopWidget
            screen = QDesktopWidget().screenGeometry()
            # Use 85% of screen width and 90% of screen height for better visibility
            window_width = int(screen.width() * 0.85)
            window_height = int(screen.height() * 0.90)
            self.resize(window_width, window_height)
            
            # Set minimum size to ensure usability
            self.setMinimumSize(1100, 800)
            
            # Center window on screen
            self.move(
                (screen.width() - window_width) // 2,
                (screen.height() - window_height) // 2
            )
            
            # Apply comprehensive Crow-eye styling
            if STYLES_AVAILABLE:
                self.setStyleSheet(CrowEyeStyles.MAIN_WINDOW)
            
            # Initialize GUI components (to be implemented in subsequent tasks)
            self._setup_menu_bar()
            self._setup_main_layout()
            self._setup_selection_panel()
            self._setup_progress_panel()
            self._setup_results_panel()
            self._setup_status_bar()
            
            # Setup GUI logging handler after log_text_area is created
            self._setup_gui_logging_handler()
            
            # Update button states if default scan path was provided
            if default_scan_path:
                self._update_start_button_state()
                print(f"[Info] Scan button enabled for default path: {default_scan_path}")
            
            if self.logger:
                self.logger.info("Offline Importer GUI initialized successfully")
                
        except Exception as e:
            # Log the error
            error_msg = f"Failed to initialize Offline Importer GUI: {str(e)}"
            print(f"[ERROR] {error_msg}")
            traceback.print_exc()
            
            # Show error dialog
            QMessageBox.critical(
                None,
                "Initialization Error",
                f"{error_msg}\n\nPlease check the console for details."
            )
            raise
    
    def _setup_menu_bar(self):
        """Setup the menu bar (File, Case, Help)"""
        menubar = self.menuBar()
        
        # Apply comprehensive Crow-eye styling
        if STYLES_AVAILABLE:
            menubar.setStyleSheet(f"""
                QMenuBar {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                        stop:0 {Colors.BG_PANELS}, stop:1 {Colors.BG_PRIMARY});
                    color: {Colors.TEXT_PRIMARY};
                    border: none;
                    border-bottom: 1px solid {Colors.BORDER_SUBTLE};
                    padding: 6px;
                    font-weight: 600;
                    font-size: 11px;
                    font-family: 'Segoe UI', sans-serif;
                }}
                QMenuBar::item {{
                    background-color: transparent;
                    padding: 6px 12px;
                    border-radius: 4px;
                }}
                QMenuBar::item:selected {{
                    background-color: {Colors.ACCENT_BLUE};
                    color: #FFFFFF;
                }}
                QMenuBar::item:pressed {{
                    background-color: #2563EB;
                }}
                QMenu {{
                    background-color: {Colors.BG_PANELS};
                    color: {Colors.TEXT_PRIMARY};
                    border: 1px solid {Colors.BORDER_ACCENT};
                    border-radius: 6px;
                    padding: 4px;
                }}
                QMenu::item {{
                    padding: 8px 24px;
                    border-radius: 4px;
                }}
                QMenu::item:selected {{
                    background-color: {Colors.ACCENT_BLUE};
                    color: #FFFFFF;
                }}
                QMenu::separator {{
                    height: 1px;
                    background-color: {Colors.BORDER_SUBTLE};
                    margin: 4px 8px;
                }}
            """)
        
        # File Menu
        file_menu = menubar.addMenu("&File")
        
        new_case_action = QAction("&New Case...", self)
        new_case_action.setShortcut("Ctrl+N")
        new_case_action.setStatusTip("Create a new case for artifact collection")
        new_case_action.triggered.connect(self._on_new_case)
        file_menu.addAction(new_case_action)
        
        open_case_action = QAction("&Open Case...", self)
        open_case_action.setShortcut("Ctrl+O")
        open_case_action.setStatusTip("Open an existing case")
        open_case_action.triggered.connect(self._on_open_case)
        file_menu.addAction(open_case_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("E&xit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.setStatusTip("Exit the application")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Case Menu
        case_menu = menubar.addMenu("&Case")
        
        export_case_action = QAction("&Export Case...", self)
        export_case_action.setShortcut("Ctrl+E")
        export_case_action.setStatusTip("Export the current case for archival or sharing")
        export_case_action.triggered.connect(self._on_export_case)
        case_menu.addAction(export_case_action)
        
        case_menu.addSeparator()
        
        case_info_action = QAction("Case &Information", self)
        case_info_action.setStatusTip("View current case information")
        case_info_action.triggered.connect(self._on_case_info)
        case_menu.addAction(case_info_action)
        
        # View Menu (Task 13.3)
        view_menu = menubar.addMenu("&View")
        
        error_log_action = QAction("&Error Log", self)
        error_log_action.setShortcut("Ctrl+L")
        error_log_action.setStatusTip("View error log")
        error_log_action.triggered.connect(self._show_error_log)
        view_menu.addAction(error_log_action)
        
        # Help Menu
        help_menu = menubar.addMenu("&Help")
        
        documentation_action = QAction("&Documentation", self)
        documentation_action.setShortcut("F1")
        documentation_action.setStatusTip("View user documentation")
        documentation_action.triggered.connect(self._on_documentation)
        help_menu.addAction(documentation_action)
        
        help_menu.addSeparator()
        
        about_action = QAction("&About", self)
        about_action.setStatusTip("About Crow-eye Offline Artifact Importer")
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)
    
    def _setup_main_layout(self):
        """
        Setup the three-panel layout using QSplitter.
        
        Creates a vertical three-panel layout:
        1. Selection Panel (top) - for source directory and options
        2. Progress Panel (middle) - for progress tracking during collection
        3. Results Panel (bottom) - for displaying collection results
        
        Uses QSplitter to allow users to resize panels dynamically.
        """
        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Create main vertical layout
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(0)
        
        # Create vertical splitter for three panels
        self.main_splitter = QSplitter(Qt.Vertical)
        self.main_splitter.setChildrenCollapsible(False)  # Prevent panels from collapsing completely
        
        # Set size policy for splitter to expand with window
        from PyQt5.QtWidgets import QSizePolicy
        self.main_splitter.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        # Create the three panel containers
        self.selection_panel = self._create_panel_container("Selection Panel")
        self.progress_panel = self._create_panel_container("Progress Panel")
        self.results_panel = self._create_panel_container("Results Panel")
        
        # Set size policies for proper scaling
        from PyQt5.QtWidgets import QSizePolicy
        self.selection_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.progress_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.results_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        # Set minimum heights for panels to prevent collapsing
        self.selection_panel.setMinimumHeight(200)  # More vertical space for better layout
        self.progress_panel.setMinimumHeight(300)   # More space for statistics and log
        self.results_panel.setMinimumHeight(400)    # More space for results table
        
        # Add panels to splitter
        self.main_splitter.addWidget(self.selection_panel)
        self.main_splitter.addWidget(self.progress_panel)
        self.main_splitter.addWidget(self.results_panel)
        
        # Set stretch factors for proportional resizing
        # Selection: 0 (fixed), Progress: 2, Results: 5 (gives most space to results)
        self.main_splitter.setStretchFactor(0, 0)    # Selection panel (minimal, fixed)
        self.main_splitter.setStretchFactor(1, 2)    # Progress panel
        self.main_splitter.setStretchFactor(2, 5)    # Results panel (biggest)
        
        # Set initial sizes for panels (proportional distribution)
        # Selection: 200px (more vertical space), Progress: 340px, Results: 580px+
        self.main_splitter.setSizes([200, 340, 580])
        
        # Configure splitter appearance
        self.main_splitter.setHandleWidth(2)
        if STYLES_AVAILABLE:
            self.main_splitter.setStyleSheet(f"""
                QSplitter::handle {{
                    background-color: {Colors.ACCENT_BLUE};
                }}
                QSplitter::handle:hover {{
                    background-color: #60A5FA;
                }}
            """)
        
        # Add splitter to main layout
        main_layout.addWidget(self.main_splitter)
    
    def _create_panel_container(self, title: str) -> QFrame:
        """
        Create a styled panel container with a title.
        
        Args:
            title: The title to display at the top of the panel
            
        Returns:
            QFrame configured as a panel container
        """
        # Create frame container
        panel = QFrame()
        panel.setFrameShape(QFrame.StyledPanel)
        panel.setFrameShadow(QFrame.Raised)
        
        # Apply comprehensive Crow-eye styling
        if STYLES_AVAILABLE:
            panel.setStyleSheet(f"""
                QFrame {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                        stop:0 {Colors.BG_PANELS}, stop:0.3 #1E293B, stop:0.7 #1E293B, stop:1 {Colors.BG_PANELS});
                    border: 1px solid {Colors.BORDER_ACCENT};
                    border-radius: 8px;
                    margin: 5px;
                }}
            """)
        
        # Create layout for panel - more vertical space for Selection Panel
        is_selection = "Selection" in title
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(12, 8 if is_selection else 8, 12, 8 if is_selection else 8)
        panel_layout.setSpacing(8 if is_selection else 8)
        
        # Create title label with compact styling for Selection Panel
        title_label = QLabel(title)
        title_font = QFont()
        title_font.setPointSize(10 if is_selection else 12)
        title_font.setBold(True)
        title_font.setFamily('Segoe UI')
        title_label.setFont(title_font)
        
        if STYLES_AVAILABLE:
            title_label.setStyleSheet(f"""
                QLabel {{
                    color: {Colors.TEXT_PRIMARY};
                    padding: {4 if is_selection else 6}px;
                    border-bottom: {1 if is_selection else 2}px solid {Colors.BORDER_ACCENT};
                    font-weight: 700;
                    letter-spacing: 0.5px;
                    background: transparent;
                }}
            """)
        
        # Add title to panel
        panel_layout.addWidget(title_label)
        
        # Store layout reference for later use
        panel.content_layout = panel_layout
        
        return panel
    
    def _setup_selection_panel(self):
        """
        Setup the selection panel (source directory, filters, options).
        
        Enhanced horizontal layout with better spacing and styling.
        """
        layout = self.selection_panel.content_layout
        layout.setSpacing(12)  # Increased from 8 for better breathing room
        layout.setContentsMargins(12, 10, 12, 10)  # Increased margins
        
        # ====================================================================
        # Row 1: Source Directory (full width) - ENHANCED
        # ====================================================================
        source_row = QHBoxLayout()
        source_row.setSpacing(12)  # Increased spacing
        
        source_label = QLabel("📁")
        source_label.setStyleSheet(f"""
            color: {Colors.TEXT_PRIMARY}; 
            font-size: 26px; 
            min-width: 40px;
            padding: 4px;
        """)
        source_label.setToolTip("Source Directory")
        source_row.addWidget(source_label)
        
        # Set initial display text based on default scan path
        initial_text = "No directory selected"
        if self.default_scan_path:
            initial_text = self.default_scan_path
        
        self.source_path_display = QLabel(initial_text)
        self.source_path_display.setMinimumHeight(48)
        self.source_path_display.setMaximumHeight(48)
        if self.default_scan_path:
            self.source_path_display.setToolTip(self.default_scan_path)
        if STYLES_AVAILABLE:
            self.source_path_display.setStyleSheet(f"""
                QLabel {{
                    color: {Colors.TEXT_PRIMARY};
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 {Colors.BG_PRIMARY}, stop:1 #0B1220);
                    border: 1px solid {Colors.BORDER_ACCENT};
                    border-radius: 6px;
                    padding: 10px 14px;
                    font-size: 13px;
                    font-family: 'Consolas', monospace;
                    font-weight: 500;
                }}
            """)
        source_row.addWidget(self.source_path_display, 1)
        
        self.browse_button = QPushButton("Browse")
        self.browse_button.setMinimumWidth(120)
        self.browse_button.setMaximumWidth(120)
        self.browse_button.setMinimumHeight(48)
        self.browse_button.setMaximumHeight(48)
        self.browse_button.setCursor(Qt.PointingHandCursor)
        self.browse_button.setToolTip("Select folder or files to collect artifacts from")
        self.browse_button.clicked.connect(self._on_browse_source)
        if STYLES_AVAILABLE:
            self.browse_button.setStyleSheet(CrowEyeStyles.BUTTON_STYLE)
        source_row.addWidget(self.browse_button)
        
        layout.addLayout(source_row)
        
        # Add small spacing between rows
        layout.addSpacing(6)
        
        # ====================================================================
        # Row 2: Type Filter + Options + Buttons (all in one row) - ENHANCED
        # ====================================================================
        controls_row = QHBoxLayout()
        controls_row.setSpacing(14)  # Increased spacing
        
        # Artifact Type Filter - ENHANCED
        filter_label = QLabel("🔎")
        filter_label.setStyleSheet(f"""
            color: {Colors.TEXT_PRIMARY}; 
            font-size: 26px; 
            min-width: 40px;
            padding: 4px;
        """)
        filter_label.setToolTip("Artifact Type")
        controls_row.addWidget(filter_label)
        
        self.artifact_type_combo = QComboBox()
        self.artifact_type_combo.setMinimumHeight(48)
        self.artifact_type_combo.setMaximumHeight(48)
        self.artifact_type_combo.setMinimumWidth(180)  # Bigger (was 120)
        self.artifact_type_combo.setMaximumWidth(220)
        artifact_types = ["All Types", "Registry Hives", "Prefetch Files", "Jump Lists", "MFT Files", "USN Journal", "Recycle Bin", "AmCache", "ShimCache"]
        self.artifact_type_combo.addItems(artifact_types)
        self.artifact_type_combo.currentTextChanged.connect(self._on_artifact_type_changed)
        self.artifact_type_combo.setCursor(Qt.PointingHandCursor)
        if STYLES_AVAILABLE:
            self.artifact_type_combo.setStyleSheet(f"""
                QComboBox {{
                    color: {Colors.TEXT_PRIMARY};
                    background-color: {Colors.BG_PRIMARY};
                    border: 1px solid {Colors.BORDER_SUBTLE};
                    border-radius: 4px;
                    padding: 8px 10px;
                    font-size: 13px;
                }}
                QComboBox:hover {{ border: 1px solid {Colors.ACCENT_BLUE}; }}
                QComboBox::drop-down {{ width: 30px; border-left: 1px solid {Colors.BORDER_SUBTLE}; }}
                QComboBox QAbstractItemView {{
                    background-color: {Colors.BG_PANELS};
                    color: {Colors.TEXT_PRIMARY};
                    border: 1px solid {Colors.ACCENT_BLUE};
                    selection-background-color: {Colors.ACCENT_BLUE};
                    font-size: 13px;
                }}
            """)
        controls_row.addWidget(self.artifact_type_combo)
        
        # Separator
        controls_row.addSpacing(10)
        separator1 = QFrame()
        separator1.setFrameShape(QFrame.VLine)
        separator1.setStyleSheet(f"color: {Colors.BORDER_SUBTLE};")
        separator1.setMaximumHeight(40)
        controls_row.addWidget(separator1)
        controls_row.addSpacing(10)
        
        # Checkboxes (LARGER icons)
        self.include_subdirs_checkbox = QCheckBox("📂")
        self.include_subdirs_checkbox.setChecked(True)
        self.include_subdirs_checkbox.stateChanged.connect(self._on_include_subdirs_changed)
        self.include_subdirs_checkbox.setCursor(Qt.PointingHandCursor)
        self.include_subdirs_checkbox.setToolTip("Include subdirectories")
        if STYLES_AVAILABLE:
            self.include_subdirs_checkbox.setStyleSheet(CrowEyeStyles.CHECKBOX_STYLE)
        controls_row.addWidget(self.include_subdirs_checkbox)
        
        self.verify_hashes_checkbox = QCheckBox("🔐")
        self.verify_hashes_checkbox.setChecked(True)
        self.verify_hashes_checkbox.stateChanged.connect(self._on_verify_hashes_changed)
        self.verify_hashes_checkbox.setCursor(Qt.PointingHandCursor)
        self.verify_hashes_checkbox.setToolTip("Calculate SHA256 hashes")
        if STYLES_AVAILABLE:
            self.verify_hashes_checkbox.setStyleSheet(CrowEyeStyles.CHECKBOX_STYLE)
        controls_row.addWidget(self.verify_hashes_checkbox)
        
        self.incremental_scan_checkbox = QCheckBox("📊")
        self.incremental_scan_checkbox.setChecked(False)  # Default: unchecked (clear index before scan)
        self.incremental_scan_checkbox.stateChanged.connect(self._on_incremental_scan_changed)
        self.incremental_scan_checkbox.setCursor(Qt.PointingHandCursor)
        self.incremental_scan_checkbox.setToolTip("Incremental scan (preserve existing scan index)")
        if STYLES_AVAILABLE:
            self.incremental_scan_checkbox.setStyleSheet(CrowEyeStyles.CHECKBOX_STYLE)
        controls_row.addWidget(self.incremental_scan_checkbox)
        
        # Removed strict validation checkbox - validation is no longer used
        # Detection is purely based on filename and extension patterns
        
        # Separator
        controls_row.addSpacing(10)
        separator2 = QFrame()
        separator2.setFrameShape(QFrame.VLine)
        separator2.setStyleSheet(f"color: {Colors.BORDER_SUBTLE};")
        separator2.setMaximumHeight(40)
        controls_row.addWidget(separator2)
        controls_row.addSpacing(10)
        
        # Action Buttons - Aligned and sized consistently
        self.scan_artifacts_button = QPushButton("🔍 SCAN")
        self.scan_artifacts_button.setMinimumSize(150, 48)  # Same width as collect button
        self.scan_artifacts_button.setMaximumSize(150, 48)
        self.scan_artifacts_button.setEnabled(False)
        self.scan_artifacts_button.setCursor(Qt.PointingHandCursor)
        self.scan_artifacts_button.clicked.connect(self._on_scan_artifacts)
        self.scan_artifacts_button.setToolTip("Scan for artifacts (preview)")
        if STYLES_AVAILABLE:
            self.scan_artifacts_button.setStyleSheet(CrowEyeStyles.BUTTON_STYLE)
        controls_row.addWidget(self.scan_artifacts_button)
        
        self.start_collection_button = QPushButton("▶️ COLLECT")
        self.start_collection_button.setMinimumSize(150, 48)  # Same width as scan button
        self.start_collection_button.setMaximumSize(150, 48)
        self.start_collection_button.setEnabled(False)
        self.start_collection_button.setCursor(Qt.PointingHandCursor)
        self.start_collection_button.clicked.connect(self._on_start_collection)
        self.start_collection_button.setToolTip("Start collection to case")
        if STYLES_AVAILABLE:
            self.start_collection_button.setStyleSheet(CrowEyeStyles.GREEN_BUTTON)
        controls_row.addWidget(self.start_collection_button)
        
        self.cancel_button = QPushButton("⏹️ CANCEL")
        self.cancel_button.setMinimumSize(150, 48)  # Bigger with text
        self.cancel_button.setMaximumSize(150, 48)
        self.cancel_button.setEnabled(False)
        self.cancel_button.setCursor(Qt.PointingHandCursor)
        self.cancel_button.clicked.connect(self.cancel_collection)
        self.cancel_button.setToolTip("Cancel operation")
        if STYLES_AVAILABLE:
            self.cancel_button.setStyleSheet(CrowEyeStyles.RED_BUTTON)
        controls_row.addWidget(self.cancel_button)
        
        # Task 28.3: Clear Scan Index button
        self.clear_scan_index_button = QPushButton("🗑️ CLEAR INDEX")
        self.clear_scan_index_button.setMinimumSize(150, 48)
        self.clear_scan_index_button.setMaximumSize(150, 48)
        self.clear_scan_index_button.setEnabled(True)  # Always enabled
        self.clear_scan_index_button.setCursor(Qt.PointingHandCursor)
        self.clear_scan_index_button.clicked.connect(self._on_clear_scan_index)
        self.clear_scan_index_button.setToolTip("Clear the artifact scan index")
        if STYLES_AVAILABLE:
            self.clear_scan_index_button.setStyleSheet(CrowEyeStyles.BUTTON_STYLE)
        controls_row.addWidget(self.clear_scan_index_button)
        
        controls_row.addStretch()
        layout.addLayout(controls_row)
        
        # No stretch at the end - keep it compact
        layout.addStretch()
    
    # ========================================================================
    # Selection Panel Event Handlers (Task 8.6 - Input Validation)
    # ========================================================================
    
    def _on_browse_source(self):
        """
        Handle Browse button click - show choice dialog then open appropriate file dialog.
        
        Allows user to choose between:
        1. Selecting a folder to scan for artifacts (recursive)
        2. Selecting individual artifact files
        """
        # Create choice dialog
        choice_dialog = QMessageBox(self)
        choice_dialog.setWindowTitle("Select Source Type")
        choice_dialog.setText("What would you like to select?")
        choice_dialog.setIcon(QMessageBox.Question)
        
        # Add custom buttons
        folder_button = choice_dialog.addButton("📁 Scan Folder", QMessageBox.ActionRole)
        files_button = choice_dialog.addButton("📄 Select Files", QMessageBox.ActionRole)
        cancel_button = choice_dialog.addButton(QMessageBox.Cancel)
        
        # Style the dialog with Crow-eye theme
        if STYLES_AVAILABLE:
            choice_dialog.setStyleSheet(CrowEyeStyles.MESSAGE_BOX_STYLE)
        
        # Show dialog and get choice
        choice_dialog.exec_()
        clicked_button = choice_dialog.clickedButton()
        
        if clicked_button == folder_button:
            self._on_browse_source_directory()
        elif clicked_button == files_button:
            self._on_select_artifact_files()
        # If cancel or closed, do nothing
    
    def _on_browse_source_directory(self):
        """
        Handle folder selection - open directory selection dialog.
        
        Allows selection of a directory to scan for forensic artifacts.
        """
        # Use native directory selection dialog
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Source Directory",
            self.state.source_directory or "",
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )
        
        if directory:
            # Validate directory
            if self._validate_source_directory(directory):
                # Update state
                self.state.source_directory = directory
                
                # Update display
                self.source_path_display.setText(directory)
                self.source_path_display.setToolTip(directory)
                
                # Update Start Collection button state
                self._update_start_button_state()
                
                # Update status bar
                self.statusBar().showMessage(f"Source folder selected: {directory}")
                
                # Log selection
                if self.logger:
                    self.logger.info(f"Source directory selected: {directory}")
            else:
                # Show error message
                QMessageBox.warning(
                    self,
                    "Invalid Selection",
                    f"The directory is not accessible or does not exist:\n{directory}\n\n"
                    "Please select a valid directory."
                )
    
    def _on_select_artifact_files(self):
        """
        Handle file selection - open file selection dialog for individual artifacts.
        
        Allows selection of specific artifact files to collect.
        """
        # Define file filters for common artifact types
        file_filters = (
            "All Artifact Files (*.pf *.lnk *.dat *.db *.log *.evtx *.regtrans-ms $*);;",
            "Prefetch Files (*.pf);;",
            "Jump Lists (*.automaticDestinations-ms *.customDestinations-ms);;",
            "Registry Hives (NTUSER.DAT SAM SYSTEM SOFTWARE SECURITY);;",
            "AmCache (Amcache.hve);;",
            "MFT Files ($MFT);;",
            "USN Journal ($UsnJrnl);;",
            "Recycle Bin ($I* $R*);;",
            "All Files (*.*)"
        )
        
        # Use native file selection dialog (allows multiple selection)
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Artifact Files",
            self.state.source_directory or "",
            "".join(file_filters)
        )
        
        if files:
            # Store selected files
            self.selected_files = files
            
            # Update display with file count
            file_count = len(files)
            if file_count == 1:
                display_text = f"1 file selected: {os.path.basename(files[0])}"
            else:
                display_text = f"{file_count} files selected"
            
            self.source_path_display.setText(display_text)
            self.source_path_display.setToolTip("\n".join(files))
            
            # Set source directory to parent of first file for validation
            self.state.source_directory = os.path.dirname(files[0])
            
            # Update Start Collection button state
            self._update_start_button_state()
            
            # Update status bar
            self.statusBar().showMessage(f"{file_count} artifact file(s) selected")
            
            # Log selection
            if self.logger:
                self.logger.info(f"{file_count} artifact files selected")
                for file in files:
                    self.logger.debug(f"  - {file}")
    
    def _on_artifact_type_changed(self, artifact_type: str):
        """
        Handle artifact type filter change.
        
        Args:
            artifact_type: The newly selected artifact type
        """
        # Update state
        self.state.artifact_type_filter = artifact_type
        
        # Update status bar
        if artifact_type == "All Types":
            self.statusBar().showMessage("Filter: Collecting all artifact types")
        else:
            self.statusBar().showMessage(f"Filter: Collecting only {artifact_type}")
    
    def _on_include_subdirs_changed(self, state: int):
        """
        Handle "Include subdirectories" checkbox state change.
        
        Args:
            state: Qt.Checked (2) or Qt.Unchecked (0)
        """
        # Update state
        self.state.include_subdirs = (state == Qt.Checked)
        
        # Update status bar
        if self.state.include_subdirs:
            self.statusBar().showMessage("Subdirectories will be included in scan")
        else:
            self.statusBar().showMessage("Only the selected directory will be scanned (no subdirectories)")
    
    def _on_verify_hashes_changed(self, state: int):
        """
        Handle "Verify hashes" checkbox state change.
        
        Args:
            state: Qt.Checked (2) or Qt.Unchecked (0)
        """
        # Update state
        self.state.verify_hashes = (state == Qt.Checked)
        
        # Update status bar
        if self.state.verify_hashes:
            self.statusBar().showMessage("File hashes will be calculated for integrity verification")
        else:
            self.statusBar().showMessage("File hash calculation disabled (faster collection)")
    
    def _on_incremental_scan_changed(self, state: int):
        """
        Handle "Incremental scan" checkbox state change (Task 28.1).
        
        Args:
            state: Qt.Checked (2) or Qt.Unchecked (0)
        """
        # Update state
        self.state.incremental_scan = (state == Qt.Checked)
        
        # Update status bar
        if self.state.incremental_scan:
            self.statusBar().showMessage("Incremental scan enabled: new artifacts will be added to existing scan index")
        else:
            self.statusBar().showMessage("Incremental scan disabled: scan index will be cleared before scanning")
    
    def _on_clear_scan_index(self):
        """
        Handle Clear Scan Index button click (Task 28.3).
        
        Clears the artifact scan index after user confirmation.
        Requirement 13.5: Provide a "Clear Scan Index" button to manually reset the artifact index
        """
        # Check if case is loaded
        if not self.case_root:
            QMessageBox.warning(
                self,
                "No Case Loaded",
                "Cannot clear scan index: no case is currently loaded."
            )
            return
        
        # Check if scan index exists and has artifacts
        from .artifact_scan_index import ArtifactScanIndex
        scan_index = ArtifactScanIndex(self.case_root)
        artifact_count = len(scan_index.artifacts)
        
        if artifact_count == 0:
            QMessageBox.information(
                self,
                "Scan Index Empty",
                "The scan index is already empty."
            )
            return
        
        # Confirm with user
        reply = QMessageBox.question(
            self,
            "Clear Scan Index",
            f"Are you sure you want to clear the scan index?\n\n"
            f"This will remove {artifact_count} artifact(s) from the index.\n"
            f"This action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                # Clear the scan index
                scan_index.artifacts = {}
                scan_index.save()
                
                # Clear the results table
                self.results_table.setRowCount(0)
                
                # Update status bar
                self.statusBar().showMessage(f"Scan index cleared ({artifact_count} artifacts removed)")
                
                # Log the action
                if self.logger:
                    self.logger.info(f"Scan index cleared: {artifact_count} artifacts removed")
                
                # Show success message
                QMessageBox.information(
                    self,
                    "Scan Index Cleared",
                    f"Successfully cleared {artifact_count} artifact(s) from the scan index."
                )
                
            except Exception as e:
                error_msg = f"Failed to clear scan index: {str(e)}"
                QMessageBox.critical(
                    self,
                    "Error",
                    error_msg
                )
                if self.logger:
                    self.logger.error(error_msg)
    
    # Removed _on_strict_validation_changed - validation is no longer used
    
    def _on_start_collection(self):
        """
        Handle Start Collection button click.
        
        Validates all inputs and starts the collection process if valid.
        """
        # Final validation before starting (Task 8.6)
        validation_errors = self._validate_collection_inputs()
        
        if validation_errors:
            # Show validation errors
            QMessageBox.warning(
                self,
                "Invalid Input",
                "Cannot start collection due to the following errors:\n\n" +
                "\n".join(f"• {error}" for error in validation_errors)
            )
            return
        
        # All validation passed - start collection
        self.start_collection()
    
    def _validate_source_directory(self, directory: str) -> bool:
        """
        Validate that the source directory exists and is accessible.
        
        Args:
            directory: Path to the directory to validate
            
        Returns:
            True if valid, False otherwise
        """
        # Check if directory exists
        if not os.path.exists(directory):
            return False
        
        # Check if it's actually a directory
        if not os.path.isdir(directory):
            return False
        
        # Check if it's accessible (try to list contents)
        try:
            os.listdir(directory)
            return True
        except PermissionError:
            return False
        except Exception:
            return False
    
    def _validate_collection_inputs(self) -> List[str]:
        """
        Validate all collection inputs before starting.
        
        Returns:
            List of validation error messages (empty if all valid)
        """
        errors = []
        
        # Check if case is loaded
        if not self.current_case_path:
            errors.append("No case is loaded. Please open or create a case first.")
        
        # Check if source directory is selected
        if not self.state.source_directory:
            errors.append("No source directory selected. Please select a source directory.")
        
        # Check if source directory is valid
        elif not self._validate_source_directory(self.state.source_directory):
            errors.append(f"Source directory is not accessible: {self.state.source_directory}")
        
        # Check if source and case directories are the same (prevent overwriting)
        if self.current_case_path and self.state.source_directory:
            if os.path.normpath(self.current_case_path) == os.path.normpath(self.state.source_directory):
                errors.append("Source directory cannot be the same as the case directory.")
        
        return errors
    
    def _update_start_button_state(self):
        """
        Update the Start Collection and Scan button enabled state.
        """
        # Check all conditions
        case_loaded = self.current_case_path is not None
        source_selected = self.state.source_directory is not None
        not_collecting = self.state.state != 'collecting'
        
        # Enable buttons only if conditions are met
        self.scan_artifacts_button.setEnabled(source_selected and not_collecting)
        self.start_collection_button.setEnabled(case_loaded and source_selected and not_collecting)

    def _on_scan_artifacts(self):
        """Handle Scan for Artifacts button click - scan without copying."""
        print("[DEBUG] Scan button clicked")
        print(f"[DEBUG] Source directory: {self.state.source_directory}")
        print(f"[DEBUG] Button enabled: {self.scan_artifacts_button.isEnabled()}")
        
        try:
            self.start_collection(scan_only=True)
        except Exception as e:
            print(f"[ERROR] Exception in _on_scan_artifacts: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(
                self,
                "Scan Error",
                f"An error occurred while starting the scan:\n\n{str(e)}\n\nCheck the console for details."
            )

    def _on_artifact_found(self, artifact_info):
        """Handle real-time artifact discovery from background thread."""
        try:
            # Convert dataclass to dict if needed
            if hasattr(artifact_info, '__dict__'):
                artifact = {
                    'source_path': artifact_info.source_path,
                    'artifact_type': artifact_info.artifact_type,
                    'collection_status': artifact_info.collection_status,
                    'file_size': artifact_info.file_size,
                    'file_hash': artifact_info.file_hash,
                    'timestamp': artifact_info.timestamp
                }
            else:
                artifact = artifact_info
                
            # Add to local list
            self.all_results.append(artifact)
            
            # Update table with proper error handling
            try:
                self._add_result_row(artifact)
            except Exception as e:
                # Log error but don't crash
                if self.logger:
                    self.logger.error(f"Error adding result row: {e}")
                print(f"[GUI] Error adding result row: {e}")
        except Exception as e:
            # Catch any errors to prevent thread crash
            if self.logger:
                self.logger.error(f"Error in _on_artifact_found: {e}")
            print(f"[GUI] Error in _on_artifact_found: {e}")

    def start_collection(self, scan_only=False):
        """
        Start the artifact collection or scan process.
        
        Args:
            scan_only: If True, only scan for artifacts without copying them
        """
        print(f"[DEBUG] start_collection called with scan_only={scan_only}")
        
        # Validate inputs - for scan mode, only source directory is required
        if scan_only:
            print(f"[DEBUG] Scan mode - checking source directory: {self.state.source_directory}")
            if not self.state.source_directory:
                print("[DEBUG] No source directory - showing warning")
                QMessageBox.warning(
                    self,
                    "Invalid Input",
                    "Please select a source directory to scan."
                )
                return
        else:
            print("[DEBUG] Collection mode - validating inputs")
            validation_errors = self._validate_collection_inputs()
            if validation_errors:
                print(f"[DEBUG] Validation errors: {validation_errors}")
                QMessageBox.warning(
                    self,
                    "Invalid Input",
                    "Cannot start collection:\n\n" + "\n".join(f"• {error}" for error in validation_errors)
                )
                return
        
        print("[DEBUG] Validation passed - updating GUI state")
        
        # Update GUI state to collecting
        try:
            self.set_state_collecting()
            print("[DEBUG] State set to collecting")
        except Exception as e:
            print(f"[ERROR] Failed to set state: {e}")
            import traceback
            traceback.print_exc()
            return
        
        # Clear and initialize log
        try:
            self.clear_log()
            print("[DEBUG] Log cleared")
        except Exception as e:
            print(f"[ERROR] Failed to clear log: {e}")
        
        mode_text = "Scan" if scan_only else "Collection"
        try:
            self.append_log(f"{mode_text} started", "INFO")
            self.append_log(f"Source: {self.state.source_directory}", "INFO")
            self.append_log(f"Filter: {self.state.artifact_type_filter}", "INFO")
            self.append_log(f"Include subdirectories: {self.state.include_subdirs}", "INFO")
            self.append_log(f"Verify hashes: {self.state.verify_hashes}", "INFO")
            # Removed strict validation log - validation is no longer used
            print("[DEBUG] Log messages appended")
        except Exception as e:
            print(f"[ERROR] Failed to append log: {e}")
        
        # Reset progress display
        try:
            self.progress_bar.setValue(0)
            self.current_file_value.setText("Initializing..." if not scan_only else "Scanning...")
            self.found_value.setText("0")
            self.copied_value.setText("0")
            # failed_value removed - no longer tracked
            self.time_value.setText("00:00:00")
            print("[DEBUG] Progress display reset")
        except Exception as e:
            print(f"[ERROR] Failed to reset progress: {e}")
            import traceback
            traceback.print_exc()
            return
        
        # Clear previous results
        try:
            self.results_table.setRowCount(0)
            self.all_results = []
            print("[DEBUG] Results cleared")
        except Exception as e:
            print(f"[ERROR] Failed to clear results: {e}")
        
        # Use a temporary case root if scanning without a case
        effective_case_root = self.case_root or os.path.join(os.path.expanduser("~"), ".crow_eye", "tmp", "scan")
        os.makedirs(effective_case_root, exist_ok=True)
        print(f"[DEBUG] Using case root: {effective_case_root}")
        
        # Create and configure collection worker thread
        try:
            print("[DEBUG] Creating collection worker thread")
            
            # Pass selected files if available
            specific_files = self.selected_files if hasattr(self, 'selected_files') and self.selected_files else None
            
            self.collection_thread = CollectionWorker(
                case_root=effective_case_root,
                source_dir=self.state.source_directory,
                artifact_type_filter=self.state.artifact_type_filter if self.state.artifact_type_filter != "All Types" else None,
                include_subdirs=self.state.include_subdirs,
                verify_hashes=self.state.verify_hashes,
                scan_only=scan_only,
                specific_files=specific_files,
                strict_validation=False  # Validation disabled - detection by filename/extension only
            )
            print(f"[DEBUG] Worker thread created (specific_files: {len(specific_files) if specific_files else 0})")
        except Exception as e:
            print(f"[ERROR] Failed to create worker thread: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(
                self,
                "Thread Creation Error",
                f"Failed to create collection worker thread:\n\n{str(e)}"
            )
            return
        
        # Connect signals
        try:
            print("[DEBUG] Connecting signals")
            self.collection_thread.progress_update.connect(self._on_progress_update)
            self.collection_thread.artifact_found.connect(self._on_artifact_found)
            self.collection_thread.collection_complete.connect(self._on_collection_complete)
            self.collection_thread.collection_error.connect(self._on_collection_error)
            self.collection_thread.collection_cancelled.connect(self._on_collection_cancelled)
            print("[DEBUG] Signals connected")
        except Exception as e:
            print(f"[ERROR] Failed to connect signals: {e}")
            import traceback
            traceback.print_exc()
            return
        
        # Start thread
        try:
            print("[DEBUG] Starting worker thread")
            self.collection_thread.start()
            print("[DEBUG] Worker thread started successfully")
        except Exception as e:
            print(f"[ERROR] Failed to start thread: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(
                self,
                "Thread Start Error",
                f"Failed to start collection worker thread:\n\n{str(e)}"
            )
            return
        
        # Update status
        mode = "Scan" if scan_only else "Collection"
        try:
            self.update_status_message(f"{mode} started - searching for artifacts...")
            print(f"[DEBUG] {mode} started successfully")
        except Exception as e:
            print(f"[ERROR] Failed to update status: {e}")

    def _setup_progress_panel(self):
        """Setup the progress panel (progress bar, time, collection log)"""
        # Use the existing panel's content_layout directly
        layout = self.progress_panel.content_layout
        layout.setSpacing(5)  # Tighter spacing
        
        # Current file section
        current_file_label = QLabel("Current File:")
        current_file_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; font-weight: bold; font-size: 11px;")
        layout.addWidget(current_file_label)
        
        self.current_file_value = QLabel("No file being processed")
        self.current_file_value.setStyleSheet(f"""
            color: {Colors.TEXT_PRIMARY}; 
            font-size: 11px;
            padding: 4px 8px;
            background-color: rgba(226, 232, 240, 0.03);
            border-radius: 4px;
            border: 1px solid {Colors.BORDER_SUBTLE};
        """)
        self.current_file_value.setWordWrap(True)
        self.current_file_value.setMinimumHeight(28)
        layout.addWidget(self.current_file_value)
        
        # Combined Progress and Time row
        progress_header_layout = QHBoxLayout()
        progress_label = QLabel("Overall Progress:")
        progress_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; font-weight: bold; font-size: 11px;")
        progress_header_layout.addWidget(progress_label)
        
        progress_header_layout.addStretch()
        
        time_label = QLabel("Elapsed Time:")
        time_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; font-weight: bold; font-size: 11px;")
        progress_header_layout.addWidget(time_label)
        
        self.time_value = QLabel("00:00:00")
        self.time_value.setStyleSheet(f"""
            color: {Colors.TEXT_PRIMARY};
            font-weight: bold;
            font-size: 12px;
            font-family: 'Consolas', 'Courier New', monospace;
            padding: 2px 6px;
            background-color: rgba(226, 232, 240, 0.05);
            border-radius: 3px;
        """)
        progress_header_layout.addWidget(self.time_value)
        layout.addLayout(progress_header_layout)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setMinimumHeight(22)
        
        # Set size policy for progress bar
        from PyQt5.QtWidgets import QSizePolicy
        self.progress_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        # Apply Crow-eye progress bar styling
        if STYLES_AVAILABLE:
            self.progress_bar.setStyleSheet(CrowEyeStyles.LOADING_PROGRESS + " QProgressBar { font-size: 10px; font-weight: bold; }")
        layout.addWidget(self.progress_bar)
        
        # Statistics Section (Found, Copied, Failed)
        stats_layout = QGridLayout()
        stats_layout.setSpacing(10)
        stats_layout.setContentsMargins(0, 10, 0, 10)
        
        # Found artifacts
        found_label = QLabel("Found:")
        found_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; font-weight: bold; font-size: 11px;")
        stats_layout.addWidget(found_label, 0, 0)
        
        self.found_value = QLabel("0")
        self.found_value.setStyleSheet(f"""
            color: {Colors.TEXT_PRIMARY};
            font-weight: bold;
            font-size: 12px;
            padding: 2px 8px;
            background-color: rgba(59, 130, 246, 0.2);
            border-radius: 3px;
            border: 1px solid {Colors.ACCENT_BLUE};
        """)
        stats_layout.addWidget(self.found_value, 0, 1)
        
        # Copied artifacts
        copied_label = QLabel("Collected:")
        copied_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; font-weight: bold; font-size: 11px;")
        stats_layout.addWidget(copied_label, 0, 2)
        
        self.copied_value = QLabel("0")
        self.copied_value.setStyleSheet(f"""
            color: #10B981;
            font-weight: bold;
            font-size: 12px;
            padding: 2px 8px;
            background-color: rgba(16, 185, 129, 0.2);
            border-radius: 3px;
            border: 1px solid #10B981;
        """)
        stats_layout.addWidget(self.copied_value, 0, 3)
        
        # Failed artifacts REMOVED - no longer tracked without validation
        
        # Add stretch to push stats to the left
        stats_layout.setColumnStretch(4, 1)
        
        layout.addLayout(stats_layout)
        
        # Collection Log Section
        log_label = QLabel("Collection Log:")
        log_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; font-weight: bold; margin-top: 5px; font-size: 11px;")
        layout.addWidget(log_label)
        
        # Create log text area
        from PyQt5.QtWidgets import QTextEdit, QSizePolicy
        self.log_text_area = QTextEdit()
        self.log_text_area.setReadOnly(True)
        self.log_text_area.setMinimumHeight(150)
        
        # Set size policy for log area to expand horizontally and vertically
        self.log_text_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.log_text_area.setStyleSheet(f"""
            QTextEdit {{
                background-color: {Colors.BG_PRIMARY};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER_ACCENT};
                border-radius: 6px;
                padding: 8px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 11px;
            }}
            QScrollBar:vertical {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {Colors.BG_PRIMARY}, stop:1 #0B1220);
                width: 14px;
                border-radius: 7px;
                margin: 2px;
            }}
            QScrollBar::handle:vertical {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {Colors.ACCENT_BLUE}, stop:1 #1E40AF);
                border-radius: 6px;
                min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #60A5FA, stop:1 {Colors.ACCENT_BLUE});
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
            QScrollBar:horizontal {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {Colors.BG_PRIMARY}, stop:1 #0B1220);
                height: 14px;
                border-radius: 7px;
                margin: 2px;
            }}
            QScrollBar::handle:horizontal {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {Colors.ACCENT_BLUE}, stop:1 #1E40AF);
                border-radius: 6px;
                min-width: 30px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #60A5FA, stop:1 {Colors.ACCENT_BLUE});
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0px;
            }}
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
                background: none;
            }}
        """)
        
        layout.addWidget(self.log_text_area)
        
        # Ensure log area takes all remaining space
        layout.setStretch(layout.count()-1, 1)
    
    def _setup_results_panel(self):
        """Setup the results panel (table, filters, action buttons)"""
        # Use the existing panel's content_layout instead of creating a new layout
        layout = self.results_panel.content_layout
        
        # Filter controls row with enhanced styling
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(15)
        filter_layout.setContentsMargins(0, 5, 0, 10)
        
        # Artifact type filter
        type_filter_label = QLabel("Filter by Type:")
        type_filter_label.setStyleSheet(f"""
            color: {Colors.TEXT_PRIMARY};
            font-size: 14px;
            font-weight: 600;
        """)
        filter_layout.addWidget(type_filter_label)
        
        self.results_type_filter = QComboBox()
        self.results_type_filter.setMinimumWidth(180)
        self.results_type_filter.setMinimumHeight(38)
        self.results_type_filter.addItems([
            "All Types",
            "Registry",
            "Prefetch",
            "JumpLists",
            "MFT",
            "USN",
            "RecycleBin",
            "AmCache",
            "ShimCache",
            "Unknown"
        ])
        self.results_type_filter.currentTextChanged.connect(self._apply_results_filters)
        if STYLES_AVAILABLE:
            self.results_type_filter.setStyleSheet(f"""
                QComboBox {{
                    color: {Colors.TEXT_PRIMARY};
                    background-color: {Colors.BG_PANELS};
                    border: 1px solid {Colors.BORDER_SUBTLE};
                    border-radius: 6px;
                    padding: 8px 12px;
                    font-size: 14px;
                    font-weight: 600;
                }}
                QComboBox:hover {{
                    border: 1px solid {Colors.ACCENT_BLUE};
                }}
                QComboBox::drop-down {{
                    border-left: 1px solid {Colors.BORDER_SUBTLE};
                    width: 30px;
                }}
                QComboBox QAbstractItemView {{
                    background-color: {Colors.BG_PANELS};
                    color: {Colors.TEXT_PRIMARY};
                    selection-background-color: {Colors.ACCENT_BLUE};
                    font-size: 14px;
                }}
            """)
        filter_layout.addWidget(self.results_type_filter)
        
        # Status filter REMOVED - no longer needed without validation
        
        filter_layout.addStretch()
        layout.addLayout(filter_layout)
        
        # Results table with enhanced styling (Status column removed)
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(5)  # Type, Source Path, Status, Size, Hash
        self.results_table.setHorizontalHeaderLabels([
            "Type", "Source Path", "Status", "Size", "Hash"
        ])
        
        # Set size policy for table to expand with panel
        from PyQt5.QtWidgets import QSizePolicy
        self.results_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        # Configure table appearance
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results_table.setSortingEnabled(True)
        
        # Set minimum row height for better readability
        self.results_table.verticalHeader().setDefaultSectionSize(40)
        
        # Enhanced table styling for better visibility
        if STYLES_AVAILABLE:
            self.results_table.setStyleSheet(CrowEyeStyles.UNIFIED_TABLE_STYLE)
        
        # Configure column widths for better scalability (4 columns after Status removal)
        header = self.results_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)  # Type
        header.setSectionResizeMode(1, QHeaderView.Stretch)  # Source Path - stretches
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Size
        header.setSectionResizeMode(3, QHeaderView.Interactive)  # Hash - user resizable
        header.setStretchLastSection(False)
        
        # Set minimum column widths (5 columns: Type, Source Path, Status, Size, Hash)
        self.results_table.setColumnWidth(0, 150)  # Type - wider for artifact names
        self.results_table.setColumnWidth(2, 120)  # Status - collection status indicator
        self.results_table.setColumnWidth(3, 100)  # Size - compact
        self.results_table.setColumnWidth(4, 280)  # Hash - wider for better visibility
        
        # Enable sorting by clicking column headers
        header.setSortIndicatorShown(True)
        header.sectionClicked.connect(self._on_results_column_clicked)
        
        layout.addWidget(self.results_table)
        
        # Action buttons row
        button_layout = QHBoxLayout()
        button_layout.setSpacing(15)
        
        # Collect Artifacts button (Task 6.1)
        self.collect_artifacts_button = QPushButton("📦 Collect Artifacts")
        self.collect_artifacts_button.setMinimumHeight(40)
        self.collect_artifacts_button.setMinimumWidth(180)
        self.collect_artifacts_button.clicked.connect(self._on_collect_artifacts_clicked)
        self.collect_artifacts_button.setEnabled(False)  # Enabled when artifacts are scanned
        self.collect_artifacts_button.setToolTip("Copy scanned artifacts to case directory organized by category")
        
        # Apply Crow-eye button styling
        if STYLES_AVAILABLE:
            self.collect_artifacts_button.setStyleSheet(CrowEyeStyles.BUTTON_STYLE + " QPushButton { font-size: 14px; }")
        
        button_layout.addWidget(self.collect_artifacts_button)
        
        # Parse Artifacts button (Task 8.1)
        self.parse_artifacts_button = QPushButton("🔍 Parse Artifacts")
        self.parse_artifacts_button.setMinimumHeight(40)
        self.parse_artifacts_button.setMinimumWidth(180)
        self.parse_artifacts_button.clicked.connect(self._on_parse_artifacts_clicked)
        self.parse_artifacts_button.setEnabled(False)  # Enabled when artifacts are imported (Task 8.3)
        self.parse_artifacts_button.setToolTip("Open dialog to select and parse artifacts")
        
        # Apply Crow-eye button styling (Task 8.1) - override min-width to respect setMinimumWidth
        if STYLES_AVAILABLE:
            self.parse_artifacts_button.setStyleSheet(
                CrowEyeStyles.GREEN_BUTTON + 
                " QPushButton { font-size: 14px; min-width: 180px; }"
            )
        
        button_layout.addWidget(self.parse_artifacts_button)
        
        self.export_case_button = QPushButton("Export Case")
        self.export_case_button.setMinimumHeight(40)
        self.export_case_button.clicked.connect(self._on_export_case)
        self.export_case_button.setEnabled(False)
        
        # Apply Crow-eye export button styling
        if STYLES_AVAILABLE:
            self.export_case_button.setStyleSheet(CrowEyeStyles.EXPORT_BUTTON + " QPushButton { font-size: 14px; font-weight: bold; }")
        
        button_layout.addWidget(self.export_case_button)
        
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        # Initialize storage for all results (unfiltered)
        self.all_results = []
        self.current_sort_column = -1
        self.current_sort_order = Qt.AscendingOrder
    
    def _on_results_column_clicked(self, column: int):
        """Handle column header click for sorting"""
        # Toggle sort order if clicking the same column
        if self.current_sort_column == column:
            self.current_sort_order = (
                Qt.DescendingOrder if self.current_sort_order == Qt.AscendingOrder
                else Qt.AscendingOrder
            )
        else:
            self.current_sort_column = column
            self.current_sort_order = Qt.AscendingOrder
        
        # Sort the table
        self.results_table.sortItems(column, self.current_sort_order)
    
    def _apply_results_filters(self):
        """Apply type filter to results table (status filter removed)"""
        type_filter = self.results_type_filter.currentText()
        
        # Clear current table
        self.results_table.setRowCount(0)
        
        # Filter and display results
        for artifact in self.all_results:
            # Skip Unknown artifacts - they should not appear in the Result panel table
            artifact_type = artifact.get('artifact_type', 'Unknown')
            if artifact_type == "Unknown":
                continue
                
            # Apply type filter
            if type_filter != "All Types":
                if artifact_type != type_filter:
                    continue
            
            # Status filter REMOVED - no longer needed
            
            # Add row to table
            self._add_result_row(artifact)
    
    def _add_result_row(self, artifact: dict):
        """Add a single result row to the table with collection status indicator"""
        try:
            # Disable sorting during insert for performance
            self.results_table.setSortingEnabled(False)
            
            row = self.results_table.rowCount()
            self.results_table.insertRow(row)
            
            # Type column
            type_item = QTableWidgetItem(artifact.get('artifact_type', 'Unknown'))
            self.results_table.setItem(row, 0, type_item)
            
            # Source Path column
            source_item = QTableWidgetItem(artifact.get('source_path', ''))
            self.results_table.setItem(row, 1, source_item)
            
            # Status column - show collection status
            destination_path = artifact.get('destination_path')
            if destination_path:
                status_text = "📦 Collected"
                status_tooltip = f"Copied to: {destination_path}"
            else:
                status_text = "🔍 Scanned"
                status_tooltip = "Not yet collected to case directory"
            
            status_item = QTableWidgetItem(status_text)
            status_item.setToolTip(status_tooltip)
            self.results_table.setItem(row, 2, status_item)
            
            # Size column (formatted) - now column 3
            size_bytes = artifact.get('file_size', 0)
            size_text = self._format_file_size(size_bytes)
            size_item = QTableWidgetItem(size_text)
            size_item.setData(Qt.UserRole, size_bytes)  # Store raw value for sorting
            self.results_table.setItem(row, 3, size_item)
            
            # Hash column (truncated) - now column 4
            file_hash = artifact.get('file_hash', '')
            hash_text = file_hash[:16] + "..." if len(file_hash) > 16 else file_hash
            hash_item = QTableWidgetItem(hash_text)
            hash_item.setToolTip(file_hash)  # Full hash in tooltip
            self.results_table.setItem(row, 4, hash_item)
            
            # Re-enable sorting
            self.results_table.setSortingEnabled(True)
            
        except Exception as e:
            # Log error but don't crash
            if hasattr(self, 'logger') and self.logger:
                self.logger.error(f"Error in _add_result_row: {e}")
            print(f"[GUI] Error in _add_result_row: {e}")
            # Re-enable sorting even on error
            try:
                self.results_table.setSortingEnabled(True)
            except:
                pass
    
    def _format_file_size(self, size_bytes: int) -> str:
        """Format file size in human-readable format"""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"
    
    def _save_results_to_case(self):
        """Save collection results to case directory"""
        if not hasattr(self, 'case_root') or not self.case_root:
            return
        
        import json
        results_file = os.path.join(self.case_root, 'import_results.json')
        
        try:
            # Convert results to serializable format
            serializable_results = []
            for artifact in self.all_results:
                result_dict = {
                    'source_path': artifact.get('source_path', ''),
                    'destination_path': artifact.get('destination_path', ''),
                    'artifact_type': artifact.get('artifact_type', 'Unknown'),
                    'file_size': artifact.get('file_size', 0),
                    'file_hash': artifact.get('file_hash', ''),
                    'collection_status': artifact.get('collection_status', 'failed'),
                    'error_message': artifact.get('error_message'),
                    'timestamp': artifact.get('timestamp', datetime.now().isoformat())
                }
                serializable_results.append(result_dict)
            
            # Save to file
            with open(results_file, 'w') as f:
                json.dump({
                    'collection_date': datetime.now().isoformat(),
                    'total_artifacts': len(self.all_results),
                    'successful': sum(1 for a in self.all_results if a.get('collection_status') == 'success'),
                    'failed': sum(1 for a in self.all_results if a.get('collection_status') != 'success'),
                    'artifacts': serializable_results
                }, f, indent=2)
            
            print(f"Results saved to {results_file}")
        except Exception as e:
            print(f"Error saving results: {e}")
    
    def _load_results_from_case(self):
        """Load collection results from case directory"""
        if not hasattr(self, 'case_root') or not self.case_root:
            return
        
        import json
        results_file = os.path.join(self.case_root, 'import_results.json')
        
        if not os.path.exists(results_file):
            return
        
        try:
            with open(results_file, 'r') as f:
                data = json.load(f)
            
            # Load artifacts
            self.all_results = data.get('artifacts', [])
            
            # Display in table
            self._apply_results_filters()
            
            # Update status
            total = data.get('total_artifacts', 0)
            successful = data.get('successful', 0)
            failed = data.get('failed', 0)
            self.update_status_message(
                f"Loaded previous results: {successful} successful, {failed} failed out of {total} total"
            )
            
            print(f"Results loaded from {results_file}")
        except Exception as e:
            print(f"Error loading results: {e}")
    
    def _setup_status_bar(self):
        """Setup the status bar at the bottom of the window"""
        statusbar = self.statusBar()
        
        # Apply enhanced Crow-eye styling
        if STYLES_AVAILABLE:
            statusbar.setStyleSheet(f"""
                QStatusBar {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                        stop:0 {Colors.BG_PANELS}, stop:1 {Colors.BG_PRIMARY});
                    color: {Colors.TEXT_PRIMARY};
                    border-top: 2px solid {Colors.ACCENT_BLUE};
                    padding: 6px;
                    font-weight: 600;
                    font-size: 11px;
                    font-family: 'Segoe UI', sans-serif;
                }}
                QStatusBar::item {{
                    border: none;
                }}
            """)
        
        # Set initial status message
        statusbar.showMessage("Ready - No case loaded")

    # ========================================================================
    # Logging and Error Handling Methods (Task 13)
    # ========================================================================
    
    def _setup_logging(self):
        """
        Setup comprehensive logging (Task 13.1).
        
        Creates a logger that writes to:
        - Console (INFO level and above)
        - File log in case directory when available (DEBUG level and above)
        - GUI log viewer (INFO level and above)
        """
        # Create logger
        self.logger = logging.getLogger('OfflineImporter')
        self.logger.setLevel(logging.DEBUG)
        
        # Remove existing handlers to avoid duplicates
        self.logger.handlers.clear()
        
        # Console handler (INFO and above)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter(
            '[%(asctime)s] %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)
        
        # GUI handler (INFO and above) - will be added after GUI is initialized
        # This is done in a separate method after log_text_area is created
        
        self.logger.info("Offline Importer GUI initialized")
    
    def _setup_gui_logging_handler(self):
        """Setup GUI logging handler to display logs in the log text area."""
        if not hasattr(self, 'log_text_area') or not self.logger:
            return
        
        # Create custom handler for GUI
        class GUILogHandler(logging.Handler):
            def __init__(self, text_widget):
                super().__init__()
                self.text_widget = text_widget
            
            def emit(self, record):
                try:
                    msg = self.format(record)
                    # Append to text widget (thread-safe via Qt signal/slot)
                    self.text_widget.append(msg)
                    # Auto-scroll to bottom
                    self.text_widget.verticalScrollBar().setValue(
                        self.text_widget.verticalScrollBar().maximum()
                    )
                except Exception:
                    pass  # Silently ignore GUI logging errors
        
        # Add GUI handler
        gui_handler = GUILogHandler(self.log_text_area)
        gui_handler.setLevel(logging.INFO)
        gui_formatter = logging.Formatter(
            '[%(asctime)s] %(levelname)s - %(message)s',
            datefmt='%H:%M:%S'
        )
        gui_handler.setFormatter(gui_formatter)
        self.logger.addHandler(gui_handler)
        
        self.logger.info("GUI logging handler initialized")
    
    def append_log(self, message: str, level: str = "INFO"):
        """
        Append a log message to the GUI log viewer.
        
        Args:
            message: Log message to display
            level: Log level (INFO, WARNING, ERROR, DEBUG)
        """
        if not hasattr(self, 'log_text_area'):
            return
        
        # Format message with timestamp and level
        timestamp = datetime.now().strftime('%H:%M:%S')
        formatted_msg = f"[{timestamp}] {level} - {message}"
        
        # Append to log text area
        self.log_text_area.append(formatted_msg)
        
        # Auto-scroll to bottom
        self.log_text_area.verticalScrollBar().setValue(
            self.log_text_area.verticalScrollBar().maximum()
        )
    
    def clear_log(self):
        """Clear the GUI log viewer."""
        if hasattr(self, 'log_text_area'):
            self.log_text_area.clear()
    
    def _setup_file_logging(self, case_path: str):
        """
        Setup file logging for a specific case (Task 13.4).
        
        Args:
            case_path: Path to case directory
        """
        if not self.logger:
            return
        
        # Create logs directory if it doesn't exist
        logs_dir = os.path.join(case_path, 'logs')
        os.makedirs(logs_dir, exist_ok=True)
        
        # Create log file with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_file = os.path.join(logs_dir, f'import_{timestamp}.log')
        
        # Remove old file handlers
        for handler in self.logger.handlers[:]:
            if isinstance(handler, logging.FileHandler):
                handler.close()
                self.logger.removeHandler(handler)
        
        # Add new file handler (DEBUG and above)
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            '[%(asctime)s] %(levelname)s - %(message)s\n%(pathname)s:%(lineno)d',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)
        self.logger.addHandler(file_handler)
        
        self.logger.info(f"File logging enabled: {log_file}")
    
    def _log_error(self, error_type: str, message: str, exception: Optional[Exception] = None):
        """
        Log an error and add it to the error log (Task 13.1, 13.3).
        
        Args:
            error_type: Type of error (e.g., 'File Access', 'Parser', 'Validation')
            message: Error message
            exception: Optional exception object
        """
        # Create error entry
        error_entry = {
            'timestamp': datetime.now(),
            'type': error_type,
            'message': message,
            'exception': str(exception) if exception else None,
            'traceback': traceback.format_exc() if exception else None
        }
        
        # Add to error log
        self.error_log.append(error_entry)
        
        # Log to logger
        if self.logger:
            if exception:
                self.logger.error(f"{error_type}: {message}", exc_info=True)
            else:
                self.logger.error(f"{error_type}: {message}")
    
    def _group_errors(self) -> dict:
        """
        Group errors by message for display (Task 13.2).
        
        Returns:
            Dictionary mapping error messages to lists of error entries
        """
        grouped = {}
        for error in self.error_log:
            key = f"{error['type']}: {error['message']}"
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(error)
        return grouped
    
    def _show_error_log(self):
        """
        Display error log in a dialog (Task 13.3).
        """
        if not self.error_log:
            QMessageBox.information(
                self,
                "Error Log",
                "No errors have been logged in this session."
            )
            return
        
        # Group errors
        grouped_errors = self._group_errors()
        
        # Create error message
        error_text = f"Total Errors: {len(self.error_log)}\n"
        error_text += f"Unique Error Types: {len(grouped_errors)}\n\n"
        
        for error_msg, errors in grouped_errors.items():
            count = len(errors)
            error_text += f"[{count}x] {error_msg}\n"
            # Show first occurrence timestamp
            error_text += f"  First: {errors[0]['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}\n"
            if count > 1:
                error_text += f"  Last: {errors[-1]['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}\n"
            error_text += "\n"
        
        # Show in message box
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Error Log")
        msg_box.setText("Errors encountered during collection:")
        msg_box.setDetailedText(error_text)
        msg_box.setIcon(QMessageBox.Warning)
        msg_box.exec_()
    
    def _format_user_friendly_error(self, error_type: str, message: str) -> str:
        """
        Format error message for user display (Task 13.5).
        
        Args:
            error_type: Type of error
            message: Technical error message
            
        Returns:
            User-friendly error message
        """
        # Map technical errors to user-friendly messages
        friendly_messages = {
            'File Access': "Unable to access the file. It may be locked, missing, or you may not have permission.",
            'Parser': "Failed to parse the artifact. The file may be corrupted or in an unexpected format.",
            'Validation': "The artifact failed validation checks. It may be corrupted or not a valid artifact.",
            'Path': "Invalid file path. Please ensure the path is correct and accessible.",
            'Case Management': "Case management operation failed. Please check the case directory.",
            'Memory': "Insufficient memory to process this file. Try closing other applications."
        }
        
        base_message = friendly_messages.get(error_type, "An unexpected error occurred.")
        return f"{base_message}\n\nDetails: {message}"

    # ========================================================================
    # State Management Methods
    # ========================================================================

    def set_state_idle(self):
        """
        Set the GUI to Idle state.

        Idle state characteristics:
        - Ready to start a new collection
        - Selection panel controls are enabled
        - Progress panel shows no activity
        - Results panel may show previous results
        - Status bar shows "Ready" message
        """
        self.state.state = 'idle'

        # Update status bar
        if self.current_case_path:
            case_name = os.path.basename(self.current_case_path)
            self.statusBar().showMessage(f"Ready - Case: {case_name}")
        else:
            self.statusBar().showMessage("Ready - No case loaded")

        # Enable/disable controls based on state
        self._update_controls_for_state()

    def set_state_collecting(self):
        """
        Set the GUI to Collecting state.

        Collecting state characteristics:
        - Collection is in progress
        - Selection panel controls are disabled (except Cancel button)
        - Progress panel shows active progress
        - Results panel is disabled during collection
        - Status bar shows "Collecting artifacts..." message
        """
        self.state.state = 'collecting'

        # Update status bar
        self.statusBar().showMessage("Collecting artifacts...")

        # Enable/disable controls based on state
        self._update_controls_for_state()

    def set_state_complete(self):
        """
        Set the GUI to Complete state.

        Complete state characteristics:
        - Collection has finished (successfully or with errors)
        - Selection panel controls are re-enabled for new collection
        - Progress panel shows final statistics
        - Results panel displays collection results
        - Status bar shows completion message with summary
        """
        self.state.state = 'complete'

        # Update status bar with completion message
        # This will be updated with actual statistics when collection completes
        self.statusBar().showMessage("Collection complete")

        # Enable/disable controls based on state
        self._update_controls_for_state()

    def _update_controls_for_state(self):
        """
        Update control states (enabled/disabled) based on current GUI state.

        This method is called whenever the state changes to ensure that
        only appropriate controls are enabled for the current state.

        State-specific control behavior:
        - Idle: Enable selection controls, disable cancel button
        - Collecting: Disable selection controls, enable cancel button
        - Complete: Enable selection controls, disable cancel button
        """
        is_idle = self.state.state == 'idle'
        is_collecting = self.state.state == 'collecting'
        is_complete = self.state.state == 'complete'

        # Selection Panel Controls (Task 8)
        # - Source directory browser: enabled in idle/complete, disabled in collecting
        # - Artifact type filter: enabled in idle/complete, disabled in collecting
        # - Options checkboxes: enabled in idle/complete, disabled in collecting
        # - Start Collection button: enabled in idle/complete (if case loaded), disabled in collecting
        
        if hasattr(self, 'browse_button'):
            self.browse_button.setEnabled(not is_collecting)
        
        if hasattr(self, 'artifact_type_combo'):
            self.artifact_type_combo.setEnabled(not is_collecting)
        
        if hasattr(self, 'include_subdirs_checkbox'):
            self.include_subdirs_checkbox.setEnabled(not is_collecting)
        
        if hasattr(self, 'verify_hashes_checkbox'):
            self.verify_hashes_checkbox.setEnabled(not is_collecting)
        
        if hasattr(self, 'start_collection_button'):
            if is_collecting:
                self.start_collection_button.setEnabled(False)
            else:
                # Update based on validation
                self._update_start_button_state()

        # Progress Panel Controls (Task 9)
        # - Cancel Collection button: disabled in idle/complete, enabled in collecting
        if hasattr(self, 'cancel_button'):
            self.cancel_button.setEnabled(is_collecting)

        # Results Panel Controls (to be implemented in Task 10)
        # - Results table: always enabled (read-only)
        # - Filter dropdowns: always enabled
        # - Export Case button: enabled if case loaded, disabled otherwise

        # Menu actions
        # File > New Case: always enabled
        # File > Open Case: enabled in idle/complete, disabled in collecting
        # Case > Export Case: enabled if case loaded and not collecting

    def get_current_state(self) -> str:
        """
        Get the current GUI state.

        Returns:
            Current state as string: 'idle', 'collecting', or 'complete'
        """
        return self.state.state

    def update_status_message(self, message: str):
        """
        Update the status bar message.

        Args:
            message: The message to display in the status bar
        """
        self.statusBar().showMessage(message)
    
    def cancel_collection(self):
        """
        Cancel the ongoing collection process (Task 11.4).
        
        This method signals the collection thread to stop and updates the GUI state.
        The cancellation is thread-safe and will stop at the next safe checkpoint.
        """
        if self.collection_thread and self.collection_thread.isRunning():
            # Request cancellation (thread-safe)
            self.collection_thread.cancel()
            
            # Disable cancel button to prevent multiple clicks
            self.cancel_button.setEnabled(False)
            self.cancel_button.setText("Cancelling...")
            
            # Update status
            self.update_status_message("Cancelling collection - please wait...")
    
    # ========================================================================
    # Thread Signal Handlers (Task 11.2 - Thread-safe progress updates)
    # ========================================================================
    
    def _on_progress_update(self, progress: ProgressUpdate):
        """
        Handle progress update from collection thread (Task 11.2).
        
        This slot is called from the background thread via Qt signals,
        which ensures thread-safe GUI updates.
        
        Args:
            progress: ProgressUpdate object with current status
        """
        # Calculate progress percentage
        if progress.total_count > 0:
            progress_percent = (progress.processed_count / progress.total_count) * 100
        else:
            progress_percent = 0
        
        # Log progress every 10% or every 10 files
        if progress.processed_count % 10 == 0 or progress_percent % 10 < 1:
            self.append_log(
                f"Progress: {progress.processed_count}/{progress.total_count} files processed "
                f"({progress_percent:.1f}%) - {progress.artifacts_collected} collected, "
                f"{progress.artifacts_failed} failed",
                "INFO"
            )
        
        # Update GUI using the existing update_progress method
        self.update_progress(
            current_file=progress.current_file,
            progress_percent=progress_percent,
            found=progress.artifacts_found,
            copied=progress.artifacts_collected,
            failed=progress.artifacts_failed,
            elapsed_time=progress.elapsed_time
        )
    
    def _on_collection_complete(self, summary: CollectionSummary):
        """
        Handle collection completion from thread (Task 11.2).
        
        This slot is called when collection finishes successfully.
        
        Args:
            summary: CollectionSummary with complete results
        """
        print(f"[DEBUG] _on_collection_complete called with {len(summary.artifacts)} artifacts")
        
        # Log completion
        self.append_log("Collection completed successfully!", "INFO")
        self.append_log(
            f"Results: {summary.total_collected} collected, {summary.failed} failed "
            f"out of {summary.total_found} found",
            "INFO"
        )
        self.append_log(f"Time taken: {summary.collection_time:.1f} seconds", "INFO")
        
        # Update GUI state
        self.set_state_complete()
        
        # Reset cancel button
        self.cancel_button.setEnabled(False)
        self.cancel_button.setText("⏹️ CANCEL")
        
        # Ensure case_root is set if we're scanning from default_scan_path
        if not self.case_root and self.default_scan_path:
            # Set case_root from default_scan_path (parent directory)
            self.case_root = os.path.dirname(self.default_scan_path)
            self.current_case_path = self.case_root
            print(f"[DEBUG] Set case_root from default_scan_path: {self.case_root}")
        
        # Add artifacts to scan index for parsing BEFORE displaying results
        print(f"[DEBUG] About to add artifacts to scan index...")
        self._add_artifacts_to_scan_index(summary.artifacts)
        print(f"[DEBUG] Finished adding artifacts to scan index")
        
        # Display results
        self.display_results(summary.artifacts)
        
        # Update Parse Artifacts button state after scan/collection completes
        print(f"[DEBUG] About to update parse button state...")
        if hasattr(self, 'parse_artifacts_button'):
            self._update_parse_button_state()
            # Force GUI update to ensure button state is visible
            self.parse_artifacts_button.repaint()
            QApplication.processEvents()
        else:
            print("[DEBUG] parse_artifacts_button not found!")
        
        # Show completion message
        QMessageBox.information(
            self,
            "Collection Complete",
            f"Artifact collection completed successfully!\n\n"
            f"Total found: {summary.total_found}\n"
            f"Successfully collected: {summary.total_collected}\n"
            f"Failed: {summary.failed}\n"
            f"Time taken: {summary.collection_time:.1f} seconds"
        )
        
        # Clean up thread
        self.collection_thread = None
    
    def _on_collection_error(self, error_message: str):
        """
        Handle collection error from thread (Task 11.3).
        
        This slot is called when collection fails with an error.
        
        Args:
            error_message: Error message string
        """
        # Log error
        self.append_log(f"Collection failed: {error_message}", "ERROR")
        
        # Update GUI state
        self.set_state_complete()
        
        # Reset cancel button
        self.cancel_button.setEnabled(False)
        self.cancel_button.setText("Cancel Collection")
        
        # Show error message
        QMessageBox.critical(
            self,
            "Collection Error",
            f"An error occurred during collection:\n\n{error_message}\n\n"
            "Please check the logs for more details."
        )
        
        # Update status
        self.update_status_message(f"Collection failed: {error_message}")
        
        # Clean up thread
        self.collection_thread = None
    
    def _on_collection_cancelled(self):
        """
        Handle collection cancellation from thread (Task 11.4).
        
        This slot is called when collection is cancelled by the user.
        """
        # Update GUI state
        self.set_state_complete()
        
        # Reset cancel button
        self.cancel_button.setEnabled(False)
        self.cancel_button.setText("Cancel Collection")
        
        # Update status
        self.update_status_message("Collection cancelled by user")
        
        # Show cancellation message
        QMessageBox.information(
            self,
            "Collection Cancelled",
            "Artifact collection was cancelled.\n\n"
            "Partial results have been preserved."
        )
        
        # Clean up thread
        self.collection_thread = None
    
    def update_progress(self, current_file: str, progress_percent: float, 
                       found: int, copied: int, failed: int, elapsed_time: float):
        """
        Update the progress panel with current collection status.
        
        Args:
            current_file: Path of the file currently being processed
            progress_percent: Overall progress percentage (0.0 to 100.0)
            found: Number of artifacts found
            copied: Number of artifacts successfully copied
            failed: Number of failed copies
            elapsed_time: Elapsed time in seconds
        """
        # Update current file label (truncate long paths)
        if len(current_file) > 80:
            display_file = "..." + current_file[-77:]
        else:
            display_file = current_file
        self.current_file_value.setText(display_file)
        self.current_file_value.setToolTip(current_file)  # Full path in tooltip
        
        # Update progress bar
        self.progress_bar.setValue(int(progress_percent))
        
        # Update statistics (failed count removed)
        self.found_value.setText(str(found))
        self.copied_value.setText(str(copied))
        # failed_value removed - no longer tracked
        
        # Format elapsed time as HH:MM:SS
        hours = int(elapsed_time // 3600)
        minutes = int((elapsed_time % 3600) // 60)
        seconds = int(elapsed_time % 60)
        time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        self.time_value.setText(time_str)
        
        # Update status bar (removed failed count)
        status_msg = f"Processing: {found} found, {copied} collected"
        self.update_status_message(status_msg)
    
    def display_results(self, results: List):
        """
        Display collection results in the results table.
        
        Args:
            results: List of CollectedArtifactInfo objects or dictionaries
        """
        # Convert results to dictionaries if they're dataclass objects
        self.all_results = []
        for result in results:
            if hasattr(result, '__dict__'):
                # It's a dataclass, convert to dict
                result_dict = {
                    'source_path': result.source_path,
                    'destination_path': result.destination_path,
                    'artifact_type': result.artifact_type,
                    'file_size': result.file_size,
                    'file_hash': result.file_hash,
                    'collection_status': result.collection_status,
                    'error_message': result.error_message,
                    'timestamp': result.timestamp.isoformat() if hasattr(result.timestamp, 'isoformat') else str(result.timestamp)
                }
            else:
                # Already a dict
                result_dict = result
            
            self.all_results.append(result_dict)
        
        # Apply filters and display
        self._apply_results_filters()
        
        # Enable export button
        self.export_case_button.setEnabled(True)
        
        # Enable collect artifacts button if artifacts were scanned (Task 6.1)
        self.collect_artifacts_button.setEnabled(len(self.all_results) > 0)
        
        # Enable parse artifacts button if artifacts are available (Task 8.3)
        self._update_parse_button_state()
        
        # Save results to case directory
        self._save_results_to_case()
        
        # Update status message
        successful = sum(1 for r in self.all_results if r.get('collection_status') == 'success')
        failed = len(self.all_results) - successful
        self.update_status_message(
            f"Collection complete: {successful} successful, {failed} failed out of {len(self.all_results)} total"
        )
    
    # ========================================================================
    # Menu Action Handlers
    # ========================================================================
    
    def _on_new_case(self):
        """Handle File > New Case menu action (Task 12.2)"""
        if not CASE_MANAGER_AVAILABLE:
            QMessageBox.warning(
                self,
                "Case Manager Unavailable",
                "Case management features are not available. Please check your installation."
            )
            return
        
        # Create a dialog for case creation
        from PyQt5.QtWidgets import QDialog, QLineEdit, QTextEdit, QDialogButtonBox
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Create New Case")
        dialog.setMinimumWidth(500)
        
        layout = QVBoxLayout()
        
        # Case name
        layout.addWidget(QLabel("Case Name:"))
        name_edit = QLineEdit()
        name_edit.setPlaceholderText("Enter case name (e.g., Investigation_2024)")
        layout.addWidget(name_edit)
        
        # Case description
        layout.addWidget(QLabel("Description:"))
        desc_edit = QTextEdit()
        desc_edit.setPlaceholderText("Enter case description...")
        desc_edit.setMaximumHeight(100)
        layout.addWidget(desc_edit)
        
        # Case directory
        layout.addWidget(QLabel("Case Directory:"))
        dir_layout = QHBoxLayout()
        dir_edit = QLineEdit()
        dir_edit.setPlaceholderText("Select directory for case...")
        dir_button = QPushButton("Browse...")
        
        def browse_directory():
            directory = QFileDialog.getExistingDirectory(
                dialog,
                "Select Case Directory",
                os.path.expanduser("~")
            )
            if directory:
                # Append case name to directory if name is provided
                if name_edit.text():
                    directory = os.path.join(directory, name_edit.text())
                dir_edit.setText(directory)
        
        dir_button.clicked.connect(browse_directory)
        dir_layout.addWidget(dir_edit)
        dir_layout.addWidget(dir_button)
        layout.addLayout(dir_layout)
        
        # Dialog buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)
        
        dialog.setLayout(layout)
        
        # Show dialog and process result
        if dialog.exec_() == QDialog.Accepted:
            case_name = name_edit.text().strip()
            case_desc = desc_edit.toPlainText().strip()
            case_path = dir_edit.text().strip()
            
            # Validate inputs
            if not case_name:
                QMessageBox.warning(self, "Invalid Input", "Please enter a case name.")
                return
            
            if not case_path:
                QMessageBox.warning(self, "Invalid Input", "Please select a case directory.")
                return
            
            # Create case directory structure (Task 12.5)
            try:
                self._create_case_directory_structure(case_path)
                
                # Add case to case manager
                case_info = {
                    'name': case_name,
                    'path': case_path,
                    'description': case_desc or "No description provided"
                }
                
                case_metadata = self.case_manager.add_case(case_info)
                
                # Set as current case
                self.current_case_path = case_path
                self.case_root = case_path
                self.current_case_metadata = case_metadata
                
                # Setup file logging for this case (Task 13.4)
                self._setup_file_logging(case_path)
                
                # Update status bar
                self.statusBar().showMessage(f"Case created: {case_name}")
                
                # Update window title
                self.setWindowTitle(f"Crow-eye Offline - Artifact Collector - {case_name}")
                
                # Update Parse Artifacts button state (Task 8.3)
                if hasattr(self, 'parse_artifacts_button'):
                    self._update_parse_button_state()
                
                QMessageBox.information(
                    self,
                    "Case Created",
                    f"Case '{case_name}' has been created successfully.\n\n"
                    f"Location: {case_path}"
                )
                
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Case Creation Failed",
                    f"Failed to create case: {str(e)}"
                )
    
    def _on_open_case(self):
        """Handle File > Open Case menu action (Task 12.3)"""
        if not CASE_MANAGER_AVAILABLE:
            QMessageBox.warning(
                self,
                "Case Manager Unavailable",
                "Case management features are not available. Please check your installation."
            )
            return
        
        # Show dialog to select case directory
        case_dir = QFileDialog.getExistingDirectory(
            self,
            "Select Case Directory",
            "",
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )
        
        if not case_dir:
            return
        
        # Validate case directory (Task 12.4)
        validation_result = self._validate_case_directory(case_dir)
        
        if not validation_result['valid']:
            # Ask user if they want to create the structure
            reply = QMessageBox.question(
                self,
                "Invalid Case Structure",
                f"The selected directory does not have a valid case structure:\n\n"
                f"{validation_result['message']}\n\n"
                "Would you like to create the required structure?",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                try:
                    self._create_case_directory_structure(case_dir)
                except Exception as e:
                    QMessageBox.critical(
                        self,
                        "Structure Creation Failed",
                        f"Failed to create case structure: {str(e)}"
                    )
                    return
            else:
                return
        
        # Try to get case metadata from case manager
        case_metadata = self.case_manager.get_case_by_path(case_dir)
        
        if not case_metadata:
            # Case not in history, ask if user wants to add it
            reply = QMessageBox.question(
                self,
                "Case Not in History",
                "This case is not in the case history. Would you like to add it?",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                # Get case name from user
                from PyQt5.QtWidgets import QInputDialog
                case_name, ok = QInputDialog.getText(
                    self,
                    "Case Name",
                    "Enter a name for this case:",
                    text=os.path.basename(case_dir)
                )
                
                if ok and case_name:
                    case_info = {
                        'name': case_name,
                        'path': case_dir,
                        'description': "Imported case"
                    }
                    case_metadata = self.case_manager.add_case(case_info)
        else:
            # Update last accessed time
            self.case_manager.update_case_access(case_dir)
        
        # Set as current case
        self.current_case_path = case_dir
        self.case_root = case_dir
        self.current_case_metadata = case_metadata
        
        # Setup file logging for this case (Task 13.4)
        self._setup_file_logging(case_dir)
        
        # Update status bar
        case_name = case_metadata.name if case_metadata else os.path.basename(case_dir)
        self.statusBar().showMessage(f"Case opened: {case_name}")
        
        # Update window title
        self.setWindowTitle(f"Crow-eye Offline - Artifact Collector - {case_name}")
        
        # Load previous results if they exist
        self._load_results_from_case()
        
        # Update Start Collection button state now that case is loaded
        if hasattr(self, 'start_collection_button'):
            self._update_start_button_state()
        
        # Update Parse Artifacts button state (Task 8.3)
        if hasattr(self, 'parse_artifacts_button'):
            self._update_parse_button_state()
        
        QMessageBox.information(
            self,
            "Case Opened",
            f"Case '{case_name}' has been opened successfully.\n\n"
            f"Location: {case_dir}"
        )
    
    # ========================================================================
    # Artifact Collection Methods (Task 6)
    # ========================================================================
    
    def _on_collect_artifacts_clicked(self):
        """
        Handle Collect Artifacts button click (Task 6.1).
        
        Copies scanned artifacts to the case directory organized by category.
        """
        try:
            # Validate that we have artifacts to collect
            if not self.all_results:
                QMessageBox.warning(
                    self,
                    "No Artifacts",
                    "No artifacts have been scanned yet. Please scan for artifacts first."
                )
                return
            
            # Validate that case is loaded
            if not self.case_root:
                QMessageBox.warning(
                    self,
                    "No Case Loaded",
                    "Please open or create a case before collecting artifacts."
                )
                return
            
            # Check disk space before collecting (Task 6.3)
            total_size = sum(artifact.get('file_size', 0) for artifact in self.all_results)
            if not self._check_disk_space(self.case_root, total_size):
                return
            
            # Confirm with user
            reply = QMessageBox.question(
                self,
                "Collect Artifacts",
                f"This will copy {len(self.all_results)} artifact(s) to the case directory.\n\n"
                f"Total size: {self._format_file_size(total_size)}\n\n"
                "Do you want to continue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply != QMessageBox.Yes:
                return
            
            # Perform collection
            self.collect_artifacts_to_case()
            
        except Exception as e:
            error_msg = f"Failed to collect artifacts: {str(e)}"
            if self.logger:
                self.logger.error(error_msg)
            QMessageBox.critical(
                self,
                "Collection Error",
                error_msg
            )
    
    def collect_artifacts_to_case(self):
        """
        Copy artifacts to case directory and update ArtifactScanIndex (Task 6.2).
        
        Organizes artifacts by category subdirectories and updates paths in the index.
        """
        try:
            # Import required modules
            from .artifact_scan_index import ArtifactScanIndex, ScannedArtifact
            import shutil
            import hashlib
            from datetime import datetime
            
            # Check disk space before collection (Task 13.4)
            total_size = sum(artifact.get('file_size', 0) for artifact in self.all_results)
            available_space = shutil.disk_usage(self.case_root).free
            
            # Add 10% buffer for safety
            required_space = int(total_size * 1.1)
            
            if available_space < required_space:
                QMessageBox.warning(
                    self,
                    "Insufficient Disk Space",
                    f"Not enough disk space to collect artifacts.\n\n"
                    f"Required: {self._format_file_size(required_space)}\n"
                    f"Available: {self._format_file_size(available_space)}\n\n"
                    f"Please free up disk space and try again."
                )
                if self.logger:
                    self.logger.warning(f"Insufficient disk space: need {required_space}, have {available_space}")
                return
            
            # Initialize artifact scan index
            scan_index = ArtifactScanIndex(self.case_root)
            
            # Create live_acquisition directory if it doesn't exist
            live_acq_dir = os.path.join(self.case_root, "live_acquisition")
            os.makedirs(live_acq_dir, exist_ok=True)
            
            # Track collection progress
            collected_count = 0
            failed_count = 0
            errors = []
            
            # Process each artifact
            for artifact in self.all_results:
                try:
                    source_path = artifact.get('source_path', '')
                    artifact_type = artifact.get('artifact_type', 'Unknown')
                    
                    if not source_path or not os.path.exists(source_path):
                        failed_count += 1
                        errors.append(f"Source file not found: {source_path}")
                        continue
                    
                    # Create category subdirectory (Task 6.2)
                    category_dir = os.path.join(live_acq_dir, artifact_type)
                    os.makedirs(category_dir, exist_ok=True)
                    
                    # Determine destination filename
                    filename = os.path.basename(source_path)
                    dest_path = os.path.join(category_dir, filename)
                    
                    # Handle filename conflicts
                    counter = 1
                    base_name, ext = os.path.splitext(filename)
                    while os.path.exists(dest_path):
                        filename = f"{base_name}_{counter}{ext}"
                        dest_path = os.path.join(category_dir, filename)
                        counter += 1
                    
                    # Copy file (Task 6.2)
                    shutil.copy2(source_path, dest_path)
                    
                    # Calculate hash if not already present
                    file_hash = artifact.get('file_hash')
                    if not file_hash:
                        file_hash = self._calculate_file_hash(dest_path)
                    
                    # Create ScannedArtifact entry
                    scanned_artifact = ScannedArtifact(
                        artifact_id=f"{artifact_type}_{os.path.basename(dest_path)}_{datetime.now().timestamp()}",
                        artifact_type=artifact_type,
                        original_path=source_path,
                        current_path=dest_path,
                        file_size=os.path.getsize(dest_path),
                        file_hash=file_hash,
                        scan_timestamp=datetime.now().isoformat(),
                        collected=True,
                        parsed=False
                    )
                    
                    # Add to index (Task 6.2)
                    scan_index.add_artifact(scanned_artifact)
                    
                    collected_count += 1
                    
                except PermissionError as e:
                    # Handle permission errors (Task 6.3)
                    failed_count += 1
                    error_msg = f"Permission denied: {source_path}"
                    errors.append(error_msg)
                    if self.logger:
                        self.logger.error(error_msg)
                    
                except Exception as e:
                    # Handle other errors (Task 6.3)
                    failed_count += 1
                    error_msg = f"Failed to collect {source_path}: {str(e)}"
                    errors.append(error_msg)
                    if self.logger:
                        self.logger.error(error_msg)
            
            # Save index (Task 6.2)
            scan_index.save()
            
            # Show results
            if collected_count > 0:
                message = f"Successfully collected {collected_count} artifact(s) to:\n{live_acq_dir}"
                if failed_count > 0:
                    message += f"\n\n{failed_count} artifact(s) failed to collect."
                    if errors:
                        message += "\n\nErrors:\n" + "\n".join(errors[:5])  # Show first 5 errors
                        if len(errors) > 5:
                            message += f"\n... and {len(errors) - 5} more errors"
                
                QMessageBox.information(
                    self,
                    "Collection Complete",
                    message
                )
                
                if self.logger:
                    self.logger.info(f"Collected {collected_count} artifacts to {live_acq_dir}")
            else:
                QMessageBox.warning(
                    self,
                    "Collection Failed",
                    f"Failed to collect any artifacts.\n\n" +
                    "\n".join(errors[:10])  # Show first 10 errors
                )
            
        except Exception as e:
            error_msg = f"Collection process failed: {str(e)}"
            if self.logger:
                self.logger.error(error_msg)
            QMessageBox.critical(
                self,
                "Collection Error",
                error_msg
            )
    
    def _on_parse_artifacts_clicked(self):
        """
        Handle Parse Artifacts button click (Task 8.2).
        
        Opens the ParseArtifactsDialog to allow user to select and parse artifacts.
        Auto-scans the live_acquisition directory if no artifacts are in the index.
        """
        try:
            # Validate that case is loaded
            if not self.case_root:
                QMessageBox.warning(
                    self,
                    "No Case Loaded",
                    "Please open or create a case before parsing artifacts."
                )
                return
            
            # Import ParseArtifactsDialog
            from .parse_artifacts_dialog import ParseArtifactsDialog
            from .artifact_scan_index import ArtifactScanIndex
            
            # Check if artifacts are available in the index
            scan_index = ArtifactScanIndex(self.case_root)
            all_artifacts = scan_index.get_all_artifacts()
            
            # If no artifacts in index, try to auto-scan live_acquisition directory
            if not all_artifacts:
                live_acq_path = os.path.join(self.case_root, "live_acquisition")
                
                # Check if live_acquisition directory exists and has files
                if os.path.exists(live_acq_path) and os.path.isdir(live_acq_path):
                    # Check if directory has any files
                    has_files = False
                    for root, dirs, files in os.walk(live_acq_path):
                        if files:
                            has_files = True
                            break
                    
                    if has_files:
                        # Auto-scan the live_acquisition directory
                        print(f"[INFO] Auto-scanning live_acquisition directory: {live_acq_path}")
                        if self.logger:
                            self.logger.info(f"Auto-scanning live_acquisition directory: {live_acq_path}")
                        
                        # Set source directory and trigger scan
                        self.state.source_directory = live_acq_path
                        self.source_path_display.setText(live_acq_path)
                        self.source_path_display.setToolTip(live_acq_path)
                        
                        # Start scan in background
                        self.start_collection(scan_only=True)
                        
                        # Show message that scan is in progress
                        QMessageBox.information(
                            self,
                            "Scanning Artifacts",
                            f"Scanning artifacts from live_acquisition directory...\n\n"
                            f"Please wait for the scan to complete, then click Parse Artifacts again."
                        )
                        return
                
                # No artifacts and no live_acquisition data
                QMessageBox.information(
                    self,
                    "No Artifacts Available",
                    "No artifacts have been scanned or imported yet.\n\n"
                    "Please scan for artifacts first using the Scan button."
                )
                return
            
            # Open ParseArtifactsDialog (Task 8.2)
            dialog = ParseArtifactsDialog(self.case_root, parent=self)
            
            # Connect signal to refresh display after parsing (Task 8.4)
            dialog.artifacts_selected.connect(self._on_artifacts_parsed)
            
            # Show dialog
            result = dialog.exec_()
            
            if result == dialog.Accepted:
                if self.logger:
                    self.logger.info("Parsing completed successfully")
                
                # Refresh the display (Task 8.4)
                self._refresh_after_parsing()
            
        except Exception as e:
            error_msg = f"Failed to open parse dialog: {str(e)}"
            if self.logger:
                self.logger.error(error_msg)
            print(f"[ERROR] {error_msg}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(
                self,
                "Parse Dialog Error",
                error_msg
            )
    
    def _on_artifacts_parsed(self, artifact_ids: list):
        """
        Handle artifacts parsed signal from ParseArtifactsDialog.
        
        This method is called when ParseArtifactsDialog is opened from the Offline Importer
        window (not directly from main Crow Eye). It serves as a bridge to refresh both
        the Offline Importer display AND the main Crow Eye GUI tabs.
        
        Signal Flow Architecture:
        -------------------------
        SCENARIO 1: Parse from Offline Importer (this path)
          User clicks "Parse Artifacts" in Offline Importer window
          → ParseArtifactsDialog opens with parent=OfflineImporterGUI
          → Signal connects to: offline_importer_gui._on_artifacts_parsed() [THIS METHOD]
          → This method calls: crow_eye_main_window.refresh_gui_tabs_after_parsing()
          → Result: Both Offline Importer AND main Crow Eye GUI are refreshed
        
        SCENARIO 2: Parse from main Crow Eye (direct path)
          User clicks "Parse Offline Artifacts" in main Crow Eye menu
          → ParseArtifactsDialog opens with parent=Crow Eye main_window
          → Signal connects to: Crow Eye.refresh_gui_tabs_after_parsing() [DIRECT]
          → Result: Main Crow Eye GUI is refreshed directly
        
        Args:
            artifact_ids: List of artifact type strings that were parsed
                         (e.g., ['Registry', 'Prefetch', 'AmCache'])
        """
        if self.logger:
            self.logger.info(f"Received notification that {len(artifact_ids)} artifacts were parsed")
        
        # CRITICAL FIX: Also refresh the main Crow Eye GUI tabs if we have a reference
        # This ensures that when parsing from Offline Importer, the main GUI tabs are updated
        if hasattr(self, 'crow_eye_main_window') and self.crow_eye_main_window:
            try:
                print(f"[DEBUG] Triggering main Crow Eye GUI refresh for artifact types: {artifact_ids}")
                self.crow_eye_main_window.refresh_gui_tabs_after_parsing(artifact_ids)
                print(f"[DEBUG] Main Crow Eye GUI refresh completed")
            except Exception as e:
                print(f"[ERROR] Failed to refresh main Crow Eye GUI: {e}")
                import traceback
                traceback.print_exc()
    
    def _refresh_after_parsing(self):
        """
        Refresh the Offline Importer display after parsing completes (Task 8.4).
        
        Reloads the artifact scan index to show updated parsing status.
        """
        try:
            # Reload artifacts from index to show updated status
            from .artifact_scan_index import ArtifactScanIndex
            
            scan_index = ArtifactScanIndex(self.case_root)
            all_artifacts = scan_index.get_all_artifacts()
            
            # Update status message
            parsed_count = sum(1 for a in all_artifacts if a.parsed)
            total_count = len(all_artifacts)
            
            self.update_status_message(
                f"Artifacts: {total_count} total, {parsed_count} parsed"
            )
            
            if self.logger:
                self.logger.info(f"Display refreshed: {parsed_count}/{total_count} artifacts parsed")
                
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to refresh display: {e}")
    
    def _add_artifacts_to_scan_index(self, artifacts: List[CollectedArtifactInfo]):
        """
        Add collected/scanned artifacts to the ArtifactScanIndex.
        
        This method populates the scan index with artifacts that were found during
        scanning or collection, making them available for parsing in the Parse Artifacts dialog.
        
        IMPORTANT: This method CLEARS the existing index before adding new artifacts
        UNLESS incremental_scan mode is enabled (Task 28.2).
        
        Args:
            artifacts: List of CollectedArtifactInfo objects from collection
        """
        try:
            from .artifact_scan_index import ArtifactScanIndex, ScannedArtifact
            import hashlib
            
            print(f"[DEBUG] _add_artifacts_to_scan_index called with {len(artifacts)} artifacts")
            
            if not self.case_root:
                print("[DEBUG] No case_root - cannot add to index")
                if self.logger:
                    self.logger.warning("Cannot add artifacts to index: no case loaded")
                return
            
            print(f"[DEBUG] Case root: {self.case_root}")
            
            # Initialize scan index
            scan_index = ArtifactScanIndex(self.case_root)
            
            # Task 28.2: Skip clearing if incremental scan is enabled
            if self.state.incremental_scan:
                print(f"[DEBUG] Incremental scan mode: preserving existing {len(scan_index.artifacts)} artifacts")
                if self.logger:
                    self.logger.info(f"Incremental scan: preserving {len(scan_index.artifacts)} existing artifacts")
            else:
                # CRITICAL: Clear existing artifacts to ensure rescan updates properly
                print(f"[DEBUG] Clearing existing scan index (had {len(scan_index.artifacts)} artifacts)")
                scan_index.artifacts = {}
            
            # Save each artifact to the index and collect for case_config
            added_count = 0
            skipped_unknown = 0
            skipped_duplicates = 0  # Task 28.2: Track duplicates
            scanned_artifacts_for_config = []
            
            # Task 28.2: Build hash lookup for duplicate detection in incremental mode
            existing_hashes = {}
            if self.state.incremental_scan:
                for artifact_id, artifact in scan_index.artifacts.items():
                    if artifact.file_hash:
                        existing_hashes[artifact.file_hash] = artifact_id
                print(f"[DEBUG] Built hash lookup with {len(existing_hashes)} existing artifacts")
            
            for artifact_info in artifacts:
                # Skip failed artifacts
                if artifact_info.collection_status != "success":
                    print(f"[DEBUG] Skipping failed artifact: {artifact_info.source_path}")
                    continue
                
                # Skip Unknown artifacts (they can't be parsed)
                if artifact_info.artifact_type == "Unknown":
                    print(f"[DEBUG] Skipping Unknown artifact: {artifact_info.source_path}")
                    skipped_unknown += 1
                    continue
                
                # Task 28.2: Check for duplicates based on file hash in incremental mode
                if self.state.incremental_scan and artifact_info.file_hash:
                    if artifact_info.file_hash in existing_hashes:
                        existing_id = existing_hashes[artifact_info.file_hash]
                        print(f"[DEBUG] Skipping duplicate artifact (hash match): {artifact_info.source_path} (matches {existing_id})")
                        skipped_duplicates += 1
                        continue
                
                # Generate artifact ID from file path
                artifact_id = hashlib.md5(artifact_info.source_path.encode()).hexdigest()[:16]
                
                # Determine the current path (destination if collected, source if scan-only)
                current_path = artifact_info.destination_path if artifact_info.destination_path else artifact_info.source_path
                
                print(f"[DEBUG] Adding artifact: {artifact_info.artifact_type} - {current_path}")
                
                # Create ScannedArtifact object
                scanned_artifact = ScannedArtifact(
                    artifact_id=artifact_id,
                    artifact_type=artifact_info.artifact_type,
                    original_path=artifact_info.source_path,
                    current_path=current_path,
                    file_size=artifact_info.file_size,
                    file_hash=artifact_info.file_hash,
                    scan_timestamp=artifact_info.timestamp.isoformat() if hasattr(artifact_info.timestamp, 'isoformat') else str(artifact_info.timestamp),
                    collected=bool(artifact_info.destination_path),  # True if copied to case
                    parsed=False
                )
                
                # Add to index
                scan_index.add_artifact(scanned_artifact)
                
                # Add to case_config list
                scanned_artifacts_for_config.append({
                    'type': artifact_info.artifact_type,
                    'name': os.path.basename(current_path),
                    'path': current_path
                })
                
                added_count += 1
            
            # Save the index
            scan_index.save()
            print(f"[DEBUG] Saved scan index with {added_count} artifacts to {scan_index.index_path}")
            
            # Save to case_config.json if available
            if CASE_MANAGER_AVAILABLE and self.current_case_metadata:
                try:
                    config_manager = CaseConfigurationManager()
                    case_id = self.current_case_metadata.name
                    config_manager.set_scanned_artifacts(case_id, scanned_artifacts_for_config)
                    print(f"[DEBUG] Saved {len(scanned_artifacts_for_config)} artifacts to case_config.json")
                except Exception as e:
                    print(f"[ERROR] Failed to save to case_config.json: {e}")
            
            if skipped_unknown > 0:
                print(f"[DEBUG] Skipped {skipped_unknown} Unknown artifacts (not parseable)")
            
            # Task 28.2: Log duplicate skips in incremental mode
            if skipped_duplicates > 0:
                print(f"[DEBUG] Skipped {skipped_duplicates} duplicate artifacts (already in index)")
                if self.logger:
                    self.logger.info(f"Skipped {skipped_duplicates} duplicate artifacts based on file hash")
            
            if self.logger:
                self.logger.info(f"Added {added_count} artifacts to scan index (skipped {skipped_unknown} Unknown, {skipped_duplicates} duplicates)")
            
        except Exception as e:
            print(f"[ERROR] Failed to add artifacts to scan index: {e}")
            import traceback
            traceback.print_exc()
            if self.logger:
                self.logger.error(f"Failed to add artifacts to scan index: {e}")
    
    def _update_parse_button_state(self):
        """
        Update the Parse Artifacts button enabled state (Task 8.3).
        
        Button is enabled only when:
        - A case is loaded
        - Artifacts have been imported/scanned
        """
        try:
            print(f"[DEBUG] _update_parse_button_state called")
            print(f"[DEBUG] case_root: {self.case_root}")
            
            # Check if case is loaded
            if not self.case_root:
                print("[DEBUG] No case_root - disabling parse button")
                self.parse_artifacts_button.setEnabled(False)
                return
            
            # Check if artifacts are available in the index
            from .artifact_scan_index import ArtifactScanIndex
            
            scan_index = ArtifactScanIndex(self.case_root)
            all_artifacts = scan_index.get_all_artifacts()
            
            print(f"[DEBUG] Found {len(all_artifacts)} artifacts in scan index")
            
            # Enable button if artifacts are available
            has_artifacts = len(all_artifacts) > 0
            self.parse_artifacts_button.setEnabled(has_artifacts)
            
            print(f"[DEBUG] Parse button enabled: {has_artifacts}")
            
            if self.logger:
                self.logger.debug(f"Parse button state updated: enabled={has_artifacts}")
                
        except Exception as e:
            # If there's an error checking, disable the button
            print(f"[ERROR] Exception in _update_parse_button_state: {e}")
            import traceback
            traceback.print_exc()
            self.parse_artifacts_button.setEnabled(False)
            if self.logger:
                self.logger.error(f"Failed to update parse button state: {e}")
    
    def _check_disk_space(self, directory: str, required_bytes: int) -> bool:
        """
        Check if there's sufficient disk space for collection (Task 6.3).
        
        Args:
            directory: Target directory path
            required_bytes: Required space in bytes
            
        Returns:
            True if sufficient space, False otherwise
        """
        try:
            import shutil
            
            # Get disk usage statistics
            stat = shutil.disk_usage(directory)
            available_bytes = stat.free
            
            # Add 10% buffer for safety
            required_with_buffer = required_bytes * 1.1
            
            if available_bytes < required_with_buffer:
                QMessageBox.warning(
                    self,
                    "Insufficient Disk Space",
                    f"Not enough disk space to collect artifacts.\n\n"
                    f"Required: {self._format_file_size(required_with_buffer)}\n"
                    f"Available: {self._format_file_size(available_bytes)}\n\n"
                    "Please free up disk space and try again."
                )
                return False
            
            return True
            
        except Exception as e:
            # If we can't check disk space, warn but allow to proceed
            if self.logger:
                self.logger.warning(f"Could not check disk space: {e}")
            return True
    
    def _calculate_file_hash(self, file_path: str) -> str:
        """
        Calculate SHA256 hash of a file.
        
        Args:
            file_path: Path to file
            
        Returns:
            SHA256 hash as hex string
        """
        try:
            import hashlib
            
            sha256_hash = hashlib.sha256()
            with open(file_path, "rb") as f:
                # Read in chunks to handle large files
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)
            
            return sha256_hash.hexdigest()
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to calculate hash for {file_path}: {e}")
            return ""
    
    def _format_file_size(self, size_bytes: int) -> str:
        """
        Format file size in human-readable format.
        
        Args:
            size_bytes: Size in bytes
            
        Returns:
            Formatted size string
        """
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} PB"
    
    def _on_export_case(self):
        """Handle Case > Export Case menu action"""
        # Placeholder for case export functionality
        # Will be implemented in Phase 4
        if not self.current_case_path:
            QMessageBox.warning(
                self,
                "No Case Loaded",
                "Please open a case before attempting to export."
            )
            return
        
        QMessageBox.information(
            self,
            "Export Case",
            "Case export functionality will be implemented in Phase 4.\n\n"
            "This will create an archive of the case directory for sharing or archival."
        )
    
    def _on_case_info(self):
        """Handle Case > Case Information menu action"""
        # Placeholder for case information display
        if not self.current_case_path:
            QMessageBox.warning(
                self,
                "No Case Loaded",
                "Please open a case to view its information."
            )
            return
        
        QMessageBox.information(
            self,
            "Case Information",
            f"Case Directory: {self.current_case_path}\n\n"
            "Detailed case information will be implemented in Phase 4."
        )
    
    # ========================================================================
    # Case Management Helper Methods (Task 12.4, 12.5)
    # ========================================================================
    
    def _validate_case_directory(self, case_path: str) -> dict:
        """
        Validate case directory structure (Task 12.4).
        
        Args:
            case_path: Path to case directory
            
        Returns:
            Dictionary with 'valid' (bool) and 'message' (str) keys
        """
        if not os.path.exists(case_path):
            return {
                'valid': False,
                'message': 'Directory does not exist'
            }
        
        if not os.path.isdir(case_path):
            return {
                'valid': False,
                'message': 'Path is not a directory'
            }
        
        # Check for live_acquisition directory
        live_acquisition = os.path.join(case_path, 'live_acquisition')
        if not os.path.exists(live_acquisition):
            return {
                'valid': False,
                'message': 'Missing live_acquisition directory'
            }
        
        # Check for required subdirectories
        required_subdirs = [
            'Registry_Hives',
            'Prefetch',
            'C_AJL_Lnk',
            'MFT_USN',
            'AmCache',
            'RecycleBin'
        ]
        
        missing_subdirs = []
        for subdir in required_subdirs:
            subdir_path = os.path.join(live_acquisition, subdir)
            if not os.path.exists(subdir_path):
                missing_subdirs.append(subdir)
        
        if missing_subdirs:
            return {
                'valid': False,
                'message': f"Missing subdirectories: {', '.join(missing_subdirs)}"
            }
        
        return {
            'valid': True,
            'message': 'Case directory structure is valid'
        }
    
    def _create_case_directory_structure(self, case_path: str):
        """
        Create case directory structure (Task 12.5).
        
        Args:
            case_path: Path to case directory
            
        Raises:
            OSError: If directory creation fails
        """
        # Create main case directory if it doesn't exist
        os.makedirs(case_path, exist_ok=True)
        
        # Create live_acquisition directory
        live_acquisition = os.path.join(case_path, 'live_acquisition')
        os.makedirs(live_acquisition, exist_ok=True)
        
        # Create artifact type subdirectories
        artifact_subdirs = [
            'Registry_Hives',
            'Prefetch',
            'C_AJL_Lnk',
            'MFT_USN',
            'AmCache',
            'RecycleBin'
        ]
        
        for subdir in artifact_subdirs:
            subdir_path = os.path.join(live_acquisition, subdir)
            os.makedirs(subdir_path, exist_ok=True)
        
        # Create logs directory
        logs_dir = os.path.join(case_path, 'logs')
        os.makedirs(logs_dir, exist_ok=True)
        
        # Create case_info.json if it doesn't exist
        case_info_path = os.path.join(case_path, 'case_info.json')
        if not os.path.exists(case_info_path):
            import json
            case_info = {
                'version': '1.0',
                'created_date': datetime.now().isoformat(),
                'last_modified': datetime.now().isoformat()
            }
            with open(case_info_path, 'w') as f:
                json.dump(case_info, f, indent=2)
    
    # ========================================================================
    # Help Menu Actions
    # ========================================================================
    
    def _on_documentation(self):
        """Handle Help > Documentation menu action"""
        # Placeholder for documentation viewer
        QMessageBox.information(
            self,
            "Documentation",
            "Crow-eye Offline Artifact Importer\n\n"
            "This tool enables forensic investigators to collect Windows artifacts\n"
            "from external sources and organize them into case directories.\n\n"
            "Supported Artifact Types:\n"
            "• Registry Hives\n"
            "• Prefetch Files\n"
            "• Jump Lists\n"
            "• MFT Files\n"
            "• USN Journal\n"
            "• Recycle Bin\n"
            "• AmCache\n\n"
            "Full documentation will be available in Phase 6."
        )
    
    def _on_about(self):
        """Handle Help > About menu action"""
        QMessageBox.about(
            self,
            "About Crow-eye Offline Artifact Importer",
            "<h3>Crow-eye Offline Artifact Importer</h3>"
            "<p>Version 1.0.0</p>"
            "<p>A forensic artifact collection tool for Windows artifacts.</p>"
            "<p>Part of the Crow-eye Forensic Application Suite.</p>"
            "<p><b>Author:</b> Crow-eye Forensics</p>"
            "<p><b>License:</b> MIT</p>"
        )
    
    def show(self):
        """Show the GUI window"""
        super().show()


# ============================================================================
# Entry Point
# ============================================================================

def launch_gui():
    """
    Launch the Offline Importer GUI application.
    
    This is the main entry point for the standalone application.
    """
    # Install global exception handler
    def exception_hook(exctype, value, tb):
        """Handle uncaught exceptions."""
        error_msg = ''.join(traceback.format_exception(exctype, value, tb))
        
        # Log to console with full details for debugging
        print(f"[UNHANDLED EXCEPTION]\n{error_msg}")
        
        # Check if this is a known Qt threading issue that can be safely ignored
        error_str = str(value).lower()
        if 'qtimer' in error_str or 'killtimer' in error_str:
            print("[INFO] Qt threading warning detected - this can be safely ignored")
            return
        
        # Show error dialog for genuine unexpected errors
        QMessageBox.critical(
            None,
            "Unhandled Exception",
            f"An unexpected error occurred:\n\n{exctype.__name__}: {value}\n\n"
            f"Please check the console for full details."
        )
    
    sys.excepthook = exception_hook
    
    try:
        app = QApplication(sys.argv)
        
        # Apply Crow-eye dark theme if available
        if STYLES_AVAILABLE:
            app.setStyle('Fusion')  # Use Fusion style for better dark theme support
        
        window = OfflineImporterGUI()
        window.show()
        sys.exit(app.exec_())
        
    except Exception as e:
        print(f"[FATAL ERROR] Failed to launch GUI: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    # Allow running the GUI directly for testing
    launch_gui()
