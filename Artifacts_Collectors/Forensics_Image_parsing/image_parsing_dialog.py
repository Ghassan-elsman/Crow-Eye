"""
Image Parsing Dialog - Complete Three-Panel GUI for Forensic Image Parsing

This module provides the main GUI for forensic image parsing, following the
Offline Importer three-panel pattern (Selection, Progress, Results).

Architecture:
- Three-panel layout using QStackedWidget
- Background threading for extraction operations
- Integration with ImageParser, CollectionCoordinator, ArtifactCollector
- Seamless handoff to ParseArtifactsDialog for parsing

Author: Crow-eye Forensics
License: MIT
"""

import os
import sys
import time

# Ensure proper package resolution for local and parent dependencies
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, '..'))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from typing import Optional, List, Union
from datetime import datetime

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QMessageBox, QTableWidget, QProgressBar, QComboBox,
    QCheckBox, QSplitter, QFrame, QTableWidgetItem, QHeaderView,
    QTextEdit, QGridLayout, QListWidget, QListWidgetItem, QDialog, QGroupBox
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QFont

# Import image parsing components
try:
    if __package__ or "." in __name__:
        from .image_parser import ImageParser
        from .data_models import PartitionInfo, ImageInfo, ExtractionOptions
        from .image_collection_wrapper import ImageCollectionCoordinator
    else:
        from image_parser import ImageParser
        from data_models import PartitionInfo, ImageInfo, ExtractionOptions
        from image_collection_wrapper import ImageCollectionCoordinator
except (ImportError, ValueError):
    from image_parser import ImageParser
    from data_models import PartitionInfo, ImageInfo, ExtractionOptions
    from image_collection_wrapper import ImageCollectionCoordinator

# Import collection components from Offline Importer
try:
    from Offline_Importer.collection_coordinator import (
        CollectionCoordinator, CollectionSummary, ProgressUpdate
    )
    from Offline_Importer.artifact_collector import CollectedArtifactInfo
    from Offline_Importer.parse_artifacts_dialog import ParseArtifactsDialog
except ImportError:
    # Fallback for direct execution/different sys.path
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    from Offline_Importer.collection_coordinator import (
        CollectionCoordinator, CollectionSummary, ProgressUpdate
    )
    from Offline_Importer.artifact_collector import CollectedArtifactInfo
    from Offline_Importer.parse_artifacts_dialog import ParseArtifactsDialog

# Import Crow-eye styles
try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from styles import CrowEyeStyles, Colors
    STYLES_AVAILABLE = True
except ImportError:
    print("Warning: Could not import CrowEyeStyles. Using default styling.")
    STYLES_AVAILABLE = False
    class Colors:
        BG_PRIMARY = "#0F172A"
        BG_PANELS = "#1E293B"
        TEXT_PRIMARY = "#E2E8F0"
        ACCENT_BLUE = "#3B82F6"
        BORDER_SUBTLE = "#334155"
        BORDER_ACCENT = "#3B82F6"


# ============================================================================
# Background Collection Worker Thread
# ============================================================================

class CollectionWorker(QThread):
    """
    Background worker thread for artifact extraction from forensic images.
    
    Signals:
        progress_update: Emitted periodically with ProgressUpdate information
        artifact_found: Emitted when an artifact is discovered
        collection_complete: Emitted when extraction finishes successfully
        collection_error: Emitted when extraction fails with error message
        collection_cancelled: Emitted when extraction is cancelled by user
    """
    
    progress_update = pyqtSignal(object)  # ProgressUpdate object
    artifact_found = pyqtSignal(object)   # CollectedArtifactInfo object
    collection_complete = pyqtSignal(object)  # CollectionSummary object
    collection_error = pyqtSignal(str)  # Error message string
    collection_cancelled = pyqtSignal()  # No parameters
    
    def __init__(self, case_root: str, image_source: Union[str, List[str]], 
                 selected_partitions: List[int],
                 artifact_type_filter: Optional[str] = None,
                 calculate_hashes: bool = True):
        """
        Initialize the collection worker thread.
        
        Args:
            case_root: Root directory of the case
            image_source: Path to the forensic image file or list of paths for segments
            selected_partitions: List of partition numbers to process
            artifact_type_filter: Optional filter for artifact types
            calculate_hashes: Whether to calculate SHA256 hashes
        """
        super().__init__()
        
        self.case_root = case_root
        self.image_source = image_source
        self.selected_partitions = selected_partitions
        self.artifact_type_filter = artifact_type_filter
        self.calculate_hashes = calculate_hashes
        
        # Cancellation flag
        self._cancelled = False
        
        # Coordinator reference
        self.coordinator = None
    
    def run(self):
        """Execute the extraction process in the background thread."""
        try:
            # Create forensic-aware collection coordinator wrapper
            self.coordinator = ImageCollectionCoordinator(
                case_root=self.case_root,
                calculate_hashes=self.calculate_hashes,
                validate_artifacts=False,
                scan_only=False
            )
            
            # Set up progress callback
            def progress_callback(progress: ProgressUpdate):
                if self._cancelled:
                    self.coordinator.cancel()
                self.progress_update.emit(progress)
            
            self.coordinator.set_progress_callback(progress_callback)
            
            # Hook into artifact collector for real-time updates
            artifact_collector = self.coordinator.artifact_collector
            original_process = getattr(artifact_collector, '_process_image_entry_by_path', None)
            
            if original_process:
                def hooked_process(accessor, entry_path, artifact_type):
                    result = original_process(accessor, entry_path, artifact_type)
                    if result:
                        self.artifact_found.emit(result)
                    return result
                
                import types
                artifact_collector._process_image_entry_by_path = types.MethodType(
                    lambda self, accessor, entry_path, artifact_type: hooked_process(accessor, entry_path, artifact_type),
                    artifact_collector
                )
            
            # Execute native collection from image directly to the case directory
            try:
                self.progress_update.emit(ProgressUpdate("Initializing native extraction engine...", 0, 0, 0, 0, 0, 0.0))
                summary = self.coordinator.collect_from_image(
                    image_path=self.image_source,
                    selected_partitions=self.selected_partitions,
                    artifact_type_filter=self.artifact_type_filter if self.artifact_type_filter != "All Types" else None
                )
            except Exception as e:
                import traceback
                error_msg = f"Native Extraction Failed: {e}\n{traceback.format_exc()}"
                print(f"[ERROR] {error_msg}")
                raise RuntimeError(error_msg)
            
            # Check for cancellation
            if self._cancelled:
                self.collection_cancelled.emit()
                return
            
            # Emit completion signal
            self.collection_complete.emit(summary)
            
        except InterruptedError:
            self.collection_cancelled.emit()
            
        except Exception as e:
            import traceback
            error_traceback = traceback.format_exc()
            error_msg = f"Extraction failed: {str(e)}\n\nFull traceback:\n{error_traceback}"
            print(f"[ERROR] {error_msg}")
            self.collection_error.emit(error_msg)
    
    def cancel(self):
        """Request cancellation of the extraction process."""
        self._cancelled = True
        if self.coordinator:
            self.coordinator.cancel()


class ScanWorker(QThread):
    """Background worker for scanning image to avoid freezing the UI."""
    scan_complete = pyqtSignal(object, str)  # image_info, detected_format
    scan_error = pyqtSignal(str)

    def __init__(self, parser, file_paths):
        super().__init__()
        self.parser = parser
        self.file_paths = file_paths

    def run(self):
        try:
            detected_format = self.parser.detect_format(self.file_paths)
            image_info = self.parser.get_image_info(self.file_paths)
            self.scan_complete.emit(image_info, detected_format)
        except Exception as e:
            import traceback
            self.scan_error.emit(f"{str(e)}\n{traceback.format_exc()}")

# ============================================================================
# Main Image Parsing Dialog
# ============================================================================

class ImageParsingDialog(QMainWindow):
    """
    Main GUI for forensic image parsing.
    
    Three-Panel Layout:
    1. Selection Panel: Image selection, format detection, partition selection, options
    2. Progress Panel: Real-time progress, statistics, log
    3. Results Panel: Extracted artifacts table, filtering, actions
    
    Reuses:
    - CollectionCoordinator for orchestration
    - ArtifactCollector for organizing artifacts
    - CollectionWorker QThread pattern for background processing
    - ParseArtifactsDialog for artifact parsing
    """
    
    def __init__(self, case_root: str, parent=None):
        """
        Initialize the Image Parsing Dialog.
        
        Args:
            case_root: Root directory of the case
            parent: Parent widget (optional)
        """
        super().__init__(parent)
        
        self.case_root = case_root
        self.image_path = None
        self.image_info = None
        self.selected_partitions = []
        self.collection_thread = None
        self.all_results = []
        
        # Initialize ImageParser
        self.image_parser = ImageParser()
        
        # Configure main window
        self.setWindowTitle("🔍 Forensic Image Parsing - Crow-eye")
        self.resize(1400, 900)
        self.setMinimumSize(1100, 800)
        
        # Apply Crow-eye styling
        if STYLES_AVAILABLE:
            self.setStyleSheet(CrowEyeStyles.MAIN_WINDOW)
        
        # Setup GUI components
        self._setup_main_layout()
        self._setup_selection_panel()
        self._setup_progress_panel()
        self._setup_results_panel()
    
    def _setup_main_layout(self):
        """Setup the two-column layout using QSplitter."""
        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Create main vertical layout
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(0)
        
        # Create horizontal splitter for two columns
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        
        # Left column container
        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 5, 0)
        left_layout.setSpacing(10)
        
        # Right column container
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(5, 0, 0, 0)
        right_layout.setSpacing(10)
        
        # Create the three panel containers
        self.selection_panel = self._create_panel_container("Selection Panel")
        self.progress_panel = self._create_panel_container("Progress Panel")
        self.results_panel = self._create_panel_container("Results Panel")
        
        # Add panels to left column
        left_layout.addWidget(self.selection_panel, 3)  # 3 stretch: gets 60% of vertical space
        left_layout.addWidget(self.progress_panel, 2)   # 2 stretch: gets 40% of vertical space
        
        # Add panel to right column
        right_layout.addWidget(self.results_panel, 1)   # 1 stretch: takes full vertical space
        
        # Add columns to splitter
        self.main_splitter.addWidget(left_container)
        self.main_splitter.addWidget(right_container)
        
        # Set stretch factors (Right side gets more horizontal space for the table)
        self.main_splitter.setStretchFactor(0, 4)  # Left column width ratio 40%
        self.main_splitter.setStretchFactor(1, 6)  # Right column width ratio 60%
        
        # Give initial generous sizes based on normal 1400 width
        self.main_splitter.setSizes([500, 900])
        
        # Configure splitter appearance
        self.main_splitter.setHandleWidth(4)
        if STYLES_AVAILABLE:
            self.main_splitter.setStyleSheet(f"""
                QSplitter::handle {{
                    background-color: {Colors.BORDER_SUBTLE};
                    border-radius: 2px;
                }}
                QSplitter::handle:hover {{
                    background-color: {Colors.ACCENT_BLUE};
                }}
            """)
        
        # Add splitter to main layout
        main_layout.addWidget(self.main_splitter)
    
    def _create_panel_container(self, title: str) -> QFrame:
        """Create a styled panel container with a title."""
        panel = QFrame()
        panel.setFrameShape(QFrame.StyledPanel)
        panel.setFrameShadow(QFrame.Raised)
        
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
        
        # Create layout for panel
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(12, 8, 12, 8)
        panel_layout.setSpacing(8)
        
        # Create title label
        title_label = QLabel(title)
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        title_font.setFamily('Segoe UI')
        title_label.setFont(title_font)
        
        if STYLES_AVAILABLE:
            title_label.setStyleSheet(f"""
                QLabel {{
                    color: {Colors.TEXT_PRIMARY};
                    padding: 6px;
                    border-bottom: 2px solid {Colors.BORDER_ACCENT};
                    font-weight: 700;
                    letter-spacing: 0.5px;
                    background: transparent;
                }}
            """)
        
        panel_layout.addWidget(title_label)
        panel.content_layout = panel_layout
        
        return panel
    
    def _setup_selection_panel(self):
        """Setup the selection panel with image browser, format display, partition list, options."""
        layout = self.selection_panel.content_layout
        layout.setSpacing(15)
        
        # 1. Image Source Group
        source_group = QGroupBox("1. Image Source")
        if STYLES_AVAILABLE:
            source_group.setStyleSheet(f"""
                QGroupBox {{
                    color: {Colors.ACCENT_BLUE};
                    font-weight: bold;
                    font-size: 12px;
                    border: 1px solid {Colors.BORDER_SUBTLE};
                    border-radius: 6px;
                    margin-top: 10px;
                    padding-top: 15px;
                }}
                QGroupBox::title {{
                    subcontrol-origin: margin;
                    subcontrol-position: top left;
                    left: 10px;
                    padding: 0 5px;
                }}
            """)
        source_layout = QHBoxLayout(source_group)
        source_layout.setSpacing(12)
        
        image_label = QLabel("💿 File:")
        image_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; font-weight: bold; font-size: 11px;")
        source_layout.addWidget(image_label)
        
        self.image_path_display = QLabel("No image selected")
        self.image_path_display.setMinimumHeight(32)
        if STYLES_AVAILABLE:
            self.image_path_display.setStyleSheet(f"""
                QLabel {{
                    color: {Colors.TEXT_PRIMARY};
                    background: {Colors.BG_PRIMARY};
                    border: 1px solid {Colors.BORDER_SUBTLE};
                    border-radius: 4px;
                    padding: 4px 10px;
                    font-size: 11px;
                    font-family: 'Consolas', monospace;
                }}
            """)
        source_layout.addWidget(self.image_path_display, 1)
        
        self.browse_image_button = QPushButton("Browse")
        self.browse_image_button.setMinimumWidth(100)
        self.browse_image_button.setMinimumHeight(32)
        self.browse_image_button.clicked.connect(self._on_browse_image)
        if STYLES_AVAILABLE:
            self.browse_image_button.setStyleSheet(CrowEyeStyles.BUTTON_STYLE)
        source_layout.addWidget(self.browse_image_button)
        
        layout.addWidget(source_group)
        
        # 2. Partitions Group
        partitions_group = QGroupBox("2. Partitions & Format")
        if STYLES_AVAILABLE:
            partitions_group.setStyleSheet(source_group.styleSheet())
        partitions_layout = QVBoxLayout(partitions_group)
        partitions_layout.setSpacing(10)
        
        format_row = QHBoxLayout()
        format_label = QLabel("📋 Detected Format:")
        format_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; font-weight: bold; font-size: 11px;")
        format_row.addWidget(format_label)
        
        self.format_display = QLabel("Unknown")
        if STYLES_AVAILABLE:
            self.format_display.setStyleSheet(f"color: {Colors.ACCENT_BLUE}; font-weight: bold; font-size: 12px;")
        format_row.addWidget(self.format_display)
        format_row.addStretch()
        partitions_layout.addLayout(format_row)
        
        partition_header = QHBoxLayout()
        partition_label = QLabel("Partitions:")
        partition_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; font-weight: bold; font-size: 11px;")
        partition_header.addWidget(partition_label)
        partition_header.addStretch()
        
        self.check_all_btn = QPushButton("Check All")
        self.check_all_btn.setCursor(Qt.PointingHandCursor)
        if STYLES_AVAILABLE:
            self.check_all_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {Colors.BG_PANELS};
                    color: {Colors.TEXT_PRIMARY};
                    border: 1px solid {Colors.BORDER_SUBTLE};
                    border-radius: 4px;
                    padding: 4px 8px;
                    font-size: 10px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    border: 1px solid {Colors.ACCENT_BLUE};
                    background-color: rgba(59, 130, 246, 0.1);
                }}
            """)
        self.check_all_btn.clicked.connect(self._on_check_all_partitions)
        partition_header.addWidget(self.check_all_btn)
        
        self.uncheck_all_btn = QPushButton("Uncheck All")
        self.uncheck_all_btn.setCursor(Qt.PointingHandCursor)
        if STYLES_AVAILABLE:
            self.uncheck_all_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {Colors.BG_PANELS};
                    color: {Colors.TEXT_PRIMARY};
                    border: 1px solid {Colors.BORDER_SUBTLE};
                    border-radius: 4px;
                    padding: 4px 8px;
                    font-size: 10px;
                }}
                QPushButton:hover {{
                    border: 1px solid {Colors.ACCENT_BLUE};
                    background-color: rgba(59, 130, 246, 0.1);
                }}
            """)
        self.uncheck_all_btn.clicked.connect(self._on_uncheck_all_partitions)
        partition_header.addWidget(self.uncheck_all_btn)
        partitions_layout.addLayout(partition_header)
        
        self.partition_list = QListWidget()
        self.partition_list.setMinimumHeight(100)
        if STYLES_AVAILABLE:
            self.partition_list.setStyleSheet(f"""
                QListWidget {{
                    background: {Colors.BG_PRIMARY};
                    color: {Colors.TEXT_PRIMARY};
                    border: 1px solid {Colors.BORDER_SUBTLE};
                    border-radius: 4px;
                    padding: 4px;
                    font-size: 11px;
                }}
                QListWidget::item {{
                    padding: 4px;
                    border-radius: 2px;
                    color: {Colors.TEXT_PRIMARY};
                }}
                QListWidget::item:hover {{
                    background: {Colors.BG_PANELS};
                    color: {Colors.ACCENT_BLUE};
                }}
                QListWidget::item:selected {{
                    background: rgba(59, 130, 246, 0.2);
                    border: 1px solid {Colors.ACCENT_BLUE};
                    color: {Colors.TEXT_PRIMARY};
                }}
                QListWidget::indicator {{
                    width: 14px;
                    height: 14px;
                    border: 1px solid {Colors.BORDER_SUBTLE};
                    border-radius: 3px;
                    background-color: {Colors.BG_PRIMARY};
                }}
                QListWidget::indicator:checked {{
                    background-color: {Colors.ACCENT_BLUE};
                    border: 1px solid {Colors.ACCENT_BLUE};
                    image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'><polyline points='20 6 9 17 4 12'></polyline></svg>");
                }}
                QListWidget::indicator:unchecked:hover {{
                    border: 1px solid {Colors.ACCENT_BLUE};
                }}
            """)
        partitions_layout.addWidget(self.partition_list, 1)
        layout.addWidget(partitions_group, 1)
        
        # 3. Settings & Actions Group
        settings_group = QGroupBox("3. Extraction Settings")
        if STYLES_AVAILABLE:
            settings_group.setStyleSheet(source_group.styleSheet())
        settings_layout = QVBoxLayout(settings_group)
        settings_layout.setSpacing(12)
        
        type_row = QHBoxLayout()
        filter_label = QLabel("🔎 Type:")
        filter_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; font-weight: bold; font-size: 11px;")
        type_row.addWidget(filter_label)
        
        self.artifact_type_combo = QComboBox()
        self.artifact_type_combo.setMinimumHeight(32)
        artifact_types = ["All Types", "Registry Hives", "Prefetch Files", "Jump Lists", 
                         "MFT Files", "USN Journal", "Recycle Bin", "Event Logs", "AmCache", "ShimCache", "SRUM"]
        self.artifact_type_combo.addItems(artifact_types)
        if STYLES_AVAILABLE:
            self.artifact_type_combo.setStyleSheet(f"""
                QComboBox {{
                    color: {Colors.TEXT_PRIMARY};
                    background: {Colors.BG_PRIMARY};
                    border: 1px solid {Colors.BORDER_SUBTLE};
                    border-radius: 4px;
                    padding: 4px 10px;
                    font-size: 11px;
                }}
                QComboBox:hover {{ border: 1px solid {Colors.ACCENT_BLUE}; }}
                QComboBox::drop-down {{ width: 30px; }}
                QComboBox QAbstractItemView {{
                    background: {Colors.BG_PANELS};
                    color: {Colors.TEXT_PRIMARY};
                    selection-background-color: {Colors.ACCENT_BLUE};
                }}
            """)
        type_row.addWidget(self.artifact_type_combo, 1)
        settings_layout.addLayout(type_row)
        
        self.calculate_hashes_checkbox = QCheckBox("🔐 Calculate Hashes")
        self.calculate_hashes_checkbox.setChecked(True)
        self.calculate_hashes_checkbox.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; font-size: 11px;")
        settings_layout.addWidget(self.calculate_hashes_checkbox)
        
        self.auto_parse_checkbox = QCheckBox("⚡ Auto-parse after extraction")
        self.auto_parse_checkbox.setChecked(True)
        self.auto_parse_checkbox.setStyleSheet(f"color: {Colors.ACCENT_BLUE}; font-size: 11px; font-weight: bold;")
        self.auto_parse_checkbox.setToolTip("Automatically run artifact parsers after extraction completes")
        settings_layout.addWidget(self.auto_parse_checkbox)
        
        settings_layout.addStretch()
        
        # Action Buttons
        btn_layout = QHBoxLayout()
        self.start_extraction_button = QPushButton("▶️ Start Analysis")
        self.start_extraction_button.setMinimumHeight(36)
        self.start_extraction_button.setEnabled(False)
        self.start_extraction_button.clicked.connect(self._on_start_extraction)
        if STYLES_AVAILABLE:
            self.start_extraction_button.setStyleSheet(CrowEyeStyles.GREEN_BUTTON + " QPushButton { font-size: 12px; font-weight: bold; }")
        btn_layout.addWidget(self.start_extraction_button, 2)
        
        self.cancel_button = QPushButton("⏹️ Cancel")
        self.cancel_button.setMinimumHeight(36)
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._on_cancel)
        if STYLES_AVAILABLE:
            self.cancel_button.setStyleSheet(CrowEyeStyles.BUTTON_STYLE + " QPushButton { font-size: 12px; font-weight: bold; }")
        btn_layout.addWidget(self.cancel_button, 1)
        
        settings_layout.addLayout(btn_layout)
        layout.addWidget(settings_group)
        
        layout.addStretch()
    
    def _setup_progress_panel(self):
        """Setup the progress panel with progress bar, statistics, log."""
        layout = self.progress_panel.content_layout
        layout.setSpacing(15)
        
        # 4. Status & Progress Group
        status_group = QGroupBox("4. Execution Status")
        if STYLES_AVAILABLE:
            status_group.setStyleSheet(f"""
                QGroupBox {{
                    color: {Colors.ACCENT_BLUE};
                    font-weight: bold;
                    font-size: 12px;
                    border: 1px solid {Colors.BORDER_SUBTLE};
                    border-radius: 6px;
                    margin-top: 10px;
                    padding-top: 15px;
                }}
                QGroupBox::title {{
                    subcontrol-origin: margin;
                    subcontrol-position: top left;
                    left: 10px;
                    padding: 0 5px;
                }}
            """)
        status_layout = QVBoxLayout(status_group)
        status_layout.setSpacing(8)
        
        # Current operation label
        operation_label = QLabel("Current Operation:")
        operation_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; font-weight: bold; font-size: 11px;")
        status_layout.addWidget(operation_label)
        
        self.operation_value = QLabel("Idle")
        self.operation_value.setStyleSheet(f"""
            color: {Colors.TEXT_PRIMARY};
            font-size: 11px;
            padding: 4px 8px;
            background-color: rgba(226, 232, 240, 0.03);
            border-radius: 4px;
            border: 1px solid {Colors.BORDER_SUBTLE};
        """)
        self.operation_value.setWordWrap(True)
        self.operation_value.setMinimumHeight(28)
        status_layout.addWidget(self.operation_value)
        
        # Progress bar with time
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
        status_layout.addLayout(progress_header_layout)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setMinimumHeight(22)
        
        if STYLES_AVAILABLE:
            self.progress_bar.setStyleSheet(f"""
                QProgressBar {{
                    border: 1px solid {Colors.BORDER_SUBTLE};
                    border-radius: 4px;
                    text-align: center;
                    background: {Colors.BG_PRIMARY};
                    color: {Colors.TEXT_PRIMARY};
                    font-weight: bold;
                    font-size: 10px;
                }}
                QProgressBar::chunk {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 {Colors.ACCENT_BLUE}, stop:1 #60A5FA);
                    border-radius: 3px;
                }}
            """)
        status_layout.addWidget(self.progress_bar)
        
        # Statistics
        stats_layout = QGridLayout()
        stats_layout.setSpacing(10)
        stats_layout.setContentsMargins(0, 10, 0, 0)
        
        # Artifacts found
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
        
        # Artifacts extracted
        extracted_label = QLabel("Extracted:")
        extracted_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; font-weight: bold; font-size: 11px;")
        stats_layout.addWidget(extracted_label, 0, 2)
        
        self.extracted_value = QLabel("0")
        self.extracted_value.setStyleSheet(f"""
            color: #10B981;
            font-weight: bold;
            font-size: 12px;
            padding: 2px 8px;
            background-color: rgba(16, 185, 129, 0.2);
            border-radius: 3px;
            border: 1px solid #10B981;
        """)
        stats_layout.addWidget(self.extracted_value, 0, 3)
        
        stats_layout.setColumnStretch(4, 1)
        status_layout.addLayout(stats_layout)
        layout.addWidget(status_group)
        
        # 5. Real-Time Log Group
        log_group = QGroupBox("5. Real-Time Log")
        if STYLES_AVAILABLE:
            log_group.setStyleSheet(status_group.styleSheet())
        log_layout = QVBoxLayout(log_group)
        log_layout.setSpacing(5)
        
        self.log_text_area = QTextEdit()
        self.log_text_area.setReadOnly(True)
        self.log_text_area.setMinimumHeight(150)
        if STYLES_AVAILABLE:
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
            """)
        log_layout.addWidget(self.log_text_area)
        layout.addWidget(log_group, 1)
    
    def _setup_results_panel(self):
        """Setup the results panel with artifacts table, filters, actions."""
        layout = self.results_panel.content_layout
        layout.setSpacing(15)
        
        # 6. Extracted Data Group
        data_group = QGroupBox("6. Extracted Data & Actions")
        if STYLES_AVAILABLE:
            data_group.setStyleSheet(f"""
                QGroupBox {{
                    color: {Colors.ACCENT_BLUE};
                    font-weight: bold;
                    font-size: 12px;
                    border: 1px solid {Colors.BORDER_SUBTLE};
                    border-radius: 6px;
                    margin-top: 10px;
                    padding-top: 15px;
                }}
                QGroupBox::title {{
                    subcontrol-origin: margin;
                    subcontrol-position: top left;
                    left: 10px;
                    padding: 0 5px;
                }}
            """)
        data_layout = QVBoxLayout(data_group)
        data_layout.setSpacing(15)
        
        # Filter controls
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(15)
        filter_layout.setContentsMargins(0, 5, 0, 10)
        
        type_filter_label = QLabel("Filter by Type:")
        type_filter_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; font-size: 12px; font-weight: 600;")
        filter_layout.addWidget(type_filter_label)
        
        self.results_type_filter = QComboBox()
        self.results_type_filter.setMinimumWidth(180)
        self.results_type_filter.setMinimumHeight(36)
        self.results_type_filter.addItems([
            "All Types", "Registry", "Prefetch", "JumpLists", "MFT", "USN",
            "RecycleBin", "AmCache", "ShimCache", "EVTX", "SRUM", "Unknown"
        ])
        self.results_type_filter.currentTextChanged.connect(self._apply_results_filters)
        if STYLES_AVAILABLE:
            self.results_type_filter.setStyleSheet(f"""
                QComboBox {{
                    color: {Colors.TEXT_PRIMARY};
                    background: {Colors.BG_PANELS};
                    border: 1px solid {Colors.BORDER_SUBTLE};
                    border-radius: 6px;
                    padding: 8px 12px;
                    font-size: 12px;
                    font-weight: 600;
                }}
                QComboBox:hover {{ border: 1px solid {Colors.ACCENT_BLUE}; }}
                QComboBox QAbstractItemView {{
                    background: {Colors.BG_PANELS};
                    color: {Colors.TEXT_PRIMARY};
                    selection-background-color: {Colors.ACCENT_BLUE};
                }}
            """)
        filter_layout.addWidget(self.results_type_filter)
        filter_layout.addStretch()
        data_layout.addLayout(filter_layout)
        
        # Results table
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(5)
        self.results_table.setHorizontalHeaderLabels([
            "Type", "Source Path", "Status", "Size", "Hash"
        ])
        
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results_table.setSortingEnabled(True)
        self.results_table.verticalHeader().setDefaultSectionSize(40)
        
        if STYLES_AVAILABLE:
            self.results_table.setStyleSheet(f"""
                QTableWidget {{
                    background: {Colors.BG_PRIMARY};
                    alternate-background-color: {Colors.BG_PANELS};
                    color: {Colors.TEXT_PRIMARY};
                    border: 1px solid {Colors.BORDER_SUBTLE};
                    border-radius: 4px;
                    gridline-color: {Colors.BORDER_SUBTLE};
                }}
                QTableWidget::item {{
                    padding: 8px;
                }}
                QTableWidget::item:alternate {{
                    background: {Colors.BG_PANELS};
                }}
                QTableWidget::item:selected {{
                    background: {Colors.ACCENT_BLUE};
                    color: white;
                }}
                QHeaderView::section {{
                    background: {Colors.BG_PANELS};
                    color: {Colors.TEXT_PRIMARY};
                    padding: 8px;
                    border: 1px solid {Colors.BORDER_SUBTLE};
                    font-weight: bold;
                }}
            """)
        
        # Configure column widths
        header = self.results_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)  # Type
        header.setSectionResizeMode(1, QHeaderView.Stretch)  # Source Path
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Status
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)  # Size
        header.setSectionResizeMode(4, QHeaderView.Interactive)  # Hash
        
        self.results_table.setColumnWidth(0, 150)
        self.results_table.setColumnWidth(2, 120)
        self.results_table.setColumnWidth(3, 100)
        self.results_table.setColumnWidth(4, 280)
        
        data_layout.addWidget(self.results_table, 1)
        
        # Action buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(15)
        
        self.parse_artifacts_button = QPushButton("🔍 Parse Artifacts")
        self.parse_artifacts_button.setMinimumHeight(40)
        self.parse_artifacts_button.setMinimumWidth(180)
        self.parse_artifacts_button.clicked.connect(self._on_parse_artifacts)
        self.parse_artifacts_button.setEnabled(False)
        if STYLES_AVAILABLE:
            self.parse_artifacts_button.setStyleSheet(CrowEyeStyles.GREEN_BUTTON + " QPushButton { font-size: 14px; }")
        button_layout.addWidget(self.parse_artifacts_button)
        
        self.export_results_button = QPushButton("📤 Export Results")
        self.export_results_button.setMinimumHeight(40)
        self.export_results_button.clicked.connect(self._on_export_results)
        self.export_results_button.setEnabled(False)
        if STYLES_AVAILABLE:
            self.export_results_button.setStyleSheet(CrowEyeStyles.BUTTON_STYLE + " QPushButton { font-size: 14px; }")
        button_layout.addWidget(self.export_results_button)
        
        button_layout.addStretch()
        data_layout.addLayout(button_layout)
        
        layout.addWidget(data_group, 1)
    
    # ========================================================================
    # Event Handlers - Selection Panel
    # ========================================================================
    
    def _on_check_all_partitions(self):
        """Check all items in the partition list."""
        for i in range(self.partition_list.count()):
            self.partition_list.item(i).setCheckState(Qt.Checked)

    def _on_uncheck_all_partitions(self):
        """Uncheck all items in the partition list."""
        for i in range(self.partition_list.count()):
            self.partition_list.item(i).setCheckState(Qt.Unchecked)

    def _on_browse_image(self):
        """Handle image file selection (supports multiple segments)."""
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Forensic Image Segment(s)",
            "",
            "Forensic Images (*.E* *.e* *.0* *.vhdx *.vhd *.vmdk *.iso *.dd *.raw *.img *.bin);;All Files (*.*)"
        )
        
        if file_paths:
            # Sort paths to ensure segments are in correct order (e.g., .001, .002)
            file_paths.sort()
            self.image_paths = file_paths
            
            # Update display
            main_file = os.path.basename(file_paths[0])
            if len(file_paths) == 1:
                display_text = f"Forensic Image: {main_file}"
            else:
                display_text = f"Forensic Image: {main_file} (+{len(file_paths)-1} segments)"
                
            self.image_path_display.setText(display_text)
            self.image_path_display.setToolTip("\n".join(file_paths))
            
            # --- Show loading indication ---
            self.format_display.setText("⏳ Scanning image.")
            if STYLES_AVAILABLE:
                self.format_display.setStyleSheet(f"color: #F59E0B; font-weight: bold; font-size: 12px;") # Yellow/Warning color
            
            self.partition_list.clear()
            loading_item = QListWidgetItem("⏳ Loading partitions, please wait...")
            loading_item.setFlags(Qt.NoItemFlags) # Make it unselectable
            self.partition_list.addItem(loading_item)
            
            # Disable buttons while scanning
            self.browse_image_button.setEnabled(False)
            self.start_extraction_button.setEnabled(False)
            
            # Start animation timer
            self.scan_dots = 1
            self.scan_timer = QTimer(self)
            self.scan_timer.timeout.connect(self._update_scan_animation)
            self.scan_timer.start(500)  # Update every 500ms
            
            # Start background worker
            self.scan_worker = ScanWorker(self.image_parser, file_paths)
            self.scan_worker.scan_complete.connect(self._on_scan_complete)
            self.scan_worker.scan_error.connect(self._on_scan_error)
            self.scan_worker.start()
            
    def _update_scan_animation(self):
        """Update the scanning animation dots."""
        self.scan_dots = (self.scan_dots % 3) + 1
        dots = "." * self.scan_dots
        self.format_display.setText(f"⏳ Scanning image{dots}")

    def _on_scan_complete(self, image_info, detected_format):
        """Handle successful completion of the background scan."""
        if hasattr(self, 'scan_timer'):
            self.scan_timer.stop()
        self.browse_image_button.setEnabled(True)
        
        self.format_display.setText(detected_format)
        if STYLES_AVAILABLE:
            self.format_display.setStyleSheet(f"color: {Colors.ACCENT_BLUE}; font-weight: bold; font-size: 12px;") # Reset to blue
        
        self.image_info = image_info
        
        if self.image_info and self.image_info.partitions:
            # Populate partition list
            self.partition_list.clear()
            for partition in self.image_info.partitions:
                item = QListWidgetItem(str(partition))
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked)
                item.setData(Qt.UserRole, partition.partition_number)
                self.partition_list.addItem(item)
            
            # Enable start button
            self.start_extraction_button.setEnabled(True)
            
            # Log
            file_paths = self.image_paths
            main_file = os.path.basename(file_paths[0])
            self._append_log(f"Image(s) loaded: {main_file} ({len(file_paths)} segments)", "INFO")
            self._append_log(f"Format: {detected_format}", "INFO")
            self._append_log(f"Partitions: {len(self.image_info.partitions)}", "INFO")
        else:
            self.partition_list.clear()
            QMessageBox.warning(
                self,
                "Image Error",
                f"Could not open image or no partitions found:\n{self.image_paths[0]}"
            )

    def _on_scan_error(self, error_msg):
        """Handle an error during the background scan."""
        if hasattr(self, 'scan_timer'):
            self.scan_timer.stop()
        self.browse_image_button.setEnabled(True)
        self.format_display.setText("Error")
        if STYLES_AVAILABLE:
            self.format_display.setStyleSheet(f"color: #EF4444; font-weight: bold; font-size: 12px;")
            
        self.partition_list.clear()
        QMessageBox.critical(
            self,
            "Scan Error",
            f"An error occurred while scanning the image:\n\n{error_msg}"
        )
    
    def _on_start_extraction(self):
        """Handle start extraction button click."""
        if not self.image_path and not hasattr(self, 'image_paths'):
            QMessageBox.warning(self, "No Image", "Please select a forensic image first.")
            return
        
        # Get checked partitions
        self.selected_partitions = []
        for i in range(self.partition_list.count()):
            item = self.partition_list.item(i)
            if item.checkState() == Qt.Checked:
                self.selected_partitions.append(item.data(Qt.UserRole))
        
        if not self.selected_partitions:
            QMessageBox.warning(self, "No Partitions", "Please select at least one partition to extract.")
            return
        
        # Update UI state
        self.start_extraction_button.setEnabled(False)
        self.browse_image_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        
        # Clear previous results
        self.results_table.setRowCount(0)
        self.all_results = []
        self.log_text_area.clear()
        
        # Reset progress
        self.progress_bar.setValue(0)
        self.operation_value.setText("Starting extraction...")
        self.found_value.setText("0")
        self.extracted_value.setText("0")
        self.time_value.setText("00:00:00")
        
        # Log start
        self._append_log("Extraction started", "INFO")
        
        main_path = getattr(self, 'image_paths', [getattr(self, 'image_path', '')])[0]
        num_segments = len(getattr(self, 'image_paths', [self.image_path]))
        
        if num_segments > 1:
            self._append_log(f"Forensic Image: {os.path.basename(main_path)} (Total {num_segments} segments)", "INFO")
        else:
            self._append_log(f"Forensic Image: {main_path}", "INFO")
            
        self._append_log(f"Partitions: {len(self.selected_partitions)}", "INFO")
        
        # Get options
        ui_filter = self.artifact_type_combo.currentText()
        filter_map = {
            "All Types": None,
            "Registry Hives": "Registry",
            "Prefetch Files": "Prefetch",
            "Jump Lists": "JumpLists",
            "MFT Files": "MFT",
            "USN Journal": "USN",
            "Recycle Bin": "RecycleBin",
            "AmCache": "AmCache",
            "ShimCache": "ShimCache",
            "Event Logs": "EVTX",
            "SRUM": "SRUM"
        }
        artifact_filter = filter_map.get(ui_filter, None)
        calculate_hashes = self.calculate_hashes_checkbox.isChecked()
        
        # Create and start worker thread
        self.collection_thread = CollectionWorker(
            case_root=self.case_root,
            image_source=getattr(self, 'image_paths', self.image_path),
            selected_partitions=self.selected_partitions,
            artifact_type_filter=artifact_filter,
            calculate_hashes=calculate_hashes
        )
        
        # Connect signals
        self.collection_thread.progress_update.connect(self._on_progress_update)
        self.collection_thread.artifact_found.connect(self._on_artifact_found)
        self.collection_thread.collection_complete.connect(self._on_collection_complete)
        self.collection_thread.collection_error.connect(self._on_collection_error)
        self.collection_thread.collection_cancelled.connect(self._on_collection_cancelled)
        
        # Start thread
        self.collection_thread.start()
    
    def _on_cancel(self):
        """Handle cancel button click."""
        if self.collection_thread and self.collection_thread.isRunning():
            reply = QMessageBox.question(
                self,
                "Cancel Extraction",
                "Are you sure you want to cancel the extraction?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                self._append_log("Cancelling extraction...", "WARNING")
                self.collection_thread.cancel()
    
    # ========================================================================
    # Event Handlers - Progress Updates
    # ========================================================================
    
    def _on_progress_update(self, progress: ProgressUpdate):
        """Handle progress updates from worker thread."""
        # Update progress bar
        if progress.total_count > 0:
            percentage = int((progress.processed_count / progress.total_count) * 100)
            self.progress_bar.setValue(percentage)
        
        # Update current operation
        self.operation_value.setText(progress.current_file)
        
        # Update statistics
        self.found_value.setText(str(progress.artifacts_found))
        self.extracted_value.setText(str(progress.artifacts_collected))
        
        # Update elapsed time
        hours = int(progress.elapsed_time // 3600)
        minutes = int((progress.elapsed_time % 3600) // 60)
        seconds = int(progress.elapsed_time % 60)
        self.time_value.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
    
    def _on_artifact_found(self, artifact_info: CollectedArtifactInfo):
        """Handle real-time artifact discovery."""
        # Add to results list
        artifact = {
            'source_path': artifact_info.source_path,
            'artifact_type': artifact_info.artifact_type,
            'collection_status': artifact_info.collection_status,
            'file_size': artifact_info.file_size,
            'file_hash': artifact_info.file_hash,
            'timestamp': artifact_info.timestamp
        }
        self.all_results.append(artifact)
        
        # Add to table
        self._add_result_row(artifact)
        
        # Log
        self._append_log(f"Found: {artifact_info.artifact_type} - {os.path.basename(artifact_info.source_path)}", "INFO")
    
    def _on_collection_complete(self, summary: CollectionSummary):
        """Handle collection completion."""
        # Update UI state
        self.start_extraction_button.setEnabled(True)
        self.browse_image_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        
        # Update progress
        self.progress_bar.setValue(100)
        self.operation_value.setText("Extraction complete")
        
        # Add to ArtifactScanIndex
        if summary.artifacts:
            try:
                from Offline_Importer.artifact_scan_index import ArtifactScanIndex, ScannedArtifact
                import hashlib
                scan_index = ArtifactScanIndex(self.case_root)
                for artifact_info in summary.artifacts:
                    if artifact_info.collection_status not in ("success", "skipped_duplicate"):
                        continue
                    current_path = artifact_info.destination_path if artifact_info.destination_path else artifact_info.source_path
                    artifact_id = hashlib.md5(artifact_info.source_path.encode()).hexdigest()[:16]
                    scanned_artifact = ScannedArtifact(
                        artifact_id=artifact_id,
                        artifact_type=artifact_info.artifact_type,
                        original_path=artifact_info.source_path,
                        current_path=current_path,
                        file_size=artifact_info.file_size,
                        file_hash=artifact_info.file_hash,
                        scan_timestamp=artifact_info.timestamp.isoformat() if hasattr(artifact_info.timestamp, 'isoformat') else str(artifact_info.timestamp),
                        collected=bool(artifact_info.destination_path),
                        parsed=False
                    )
                    scan_index.add_artifact(scanned_artifact)
                scan_index.save()
                self._append_log(f"Added {len(summary.artifacts)} artifacts to the case index.", "SUCCESS")
            except Exception as e:
                self._append_log(f"Failed to update artifact index: {e}", "ERROR")

        # Enable parse button
        if summary.total_collected > 0:
            self.parse_artifacts_button.setEnabled(True)
            self.export_results_button.setEnabled(True)
        
        # Log completion
        self._append_log("=" * 50, "INFO")
        self._append_log("Extraction completed successfully", "SUCCESS")
        self._append_log(f"Total found: {summary.total_found}", "INFO")
        self._append_log(f"Total extracted: {summary.total_collected}", "INFO")
        self._append_log(f"Failed: {summary.failed}", "INFO")
        self._append_log(f"Time: {summary.collection_time:.2f} seconds", "INFO")
        
        # Show completion message if not auto-parsing
        if not self.auto_parse_checkbox.isChecked():
            QMessageBox.information(
                self,
                "Extraction Complete",
                f"Extraction completed successfully!\n\n"
                f"Total found: {summary.total_found}\n"
                f"Total extracted: {summary.total_collected}\n"
                f"Failed: {summary.failed}\n"
                f"Time: {summary.collection_time:.2f} seconds"
            )
        else:
            # Trigger automated parsing
            self._append_log("Auto-parse enabled. Starting artifact parsing pipeline...", "SUCCESS")
            self._on_parse_artifacts(automated=True)
    
    def _on_collection_error(self, error_msg: str):
        """Handle collection error."""
        # Update UI state
        self.start_extraction_button.setEnabled(True)
        self.browse_image_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        
        # Log error
        self._append_log("Extraction failed", "ERROR")
        self._append_log(error_msg, "ERROR")
        
        # Show error message
        QMessageBox.critical(
            self,
            "Extraction Error",
            f"Extraction failed:\n\n{error_msg}"
        )
    
    def _on_collection_cancelled(self):
        """Handle collection cancellation."""
        # Update UI state
        self.start_extraction_button.setEnabled(True)
        self.browse_image_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        
        # Log cancellation
        self._append_log("Extraction cancelled by user", "WARNING")
        
        # Show cancellation message
        QMessageBox.information(
            self,
            "Extraction Cancelled",
            "Extraction was cancelled by user."
        )
    
    # ========================================================================
    # Event Handlers - Results Panel
    # ========================================================================
    
    def _on_parse_artifacts(self, automated: bool = False):
        """
        Handle parse artifacts button click.
        
        Args:
            automated: If True, bypass the selection dialog and parse everything.
        """
        try:
            if not automated:
                # Log the action
                self._append_log("Invoking artifact parser...", "INFO")
                self._append_log("Select artifacts to parse in the dialog", "INFO")
                
                # Create and execute ParseArtifactsDialog
                dialog = ParseArtifactsDialog(self.case_root, self)
                
                # Connect to artifacts_selected signal to show loading status
                dialog.artifacts_selected.connect(self._on_artifacts_parsing_started)
                
                # Execute dialog (blocks until user completes parsing or cancels)
                result = dialog.exec_()
                
                if result == QDialog.Accepted:
                    self._append_log("Artifact parsing completed successfully", "SUCCESS")
                    self._append_log("Parsed databases written to Target_Artifacts/", "INFO")
                    
                    # If we have a reference to main window, trigger refresh
                    if hasattr(self, 'crow_eye_main_window') and self.crow_eye_main_window:
                        self._append_log("Triggering main GUI refresh...", "INFO")
                else:
                    self._append_log("Artifact parsing cancelled by user", "WARNING")
            else:
                # AUTOMATED FLOW
                self._append_log("Running automated parsing for all extracted artifacts...", "INFO")
                self.operation_value.setText("Automated Parsing in progress...")
                
                from Offline_Importer.artifact_scan_index import ArtifactScanIndex
                from Offline_Importer.parser_invoker import ParserInvoker
                
                artifact_index = ArtifactScanIndex(self.case_root)
                all_artifacts = artifact_index.get_all_artifacts()
                
                if not all_artifacts:
                    self._append_log("No artifacts found to parse. Pipeline aborted.", "ERROR")
                    self.operation_value.setText("Automated Parsing failed - No artifacts found.")
                    return
                
                # Filter out already parsed if needed, but normally we parse all for new extraction
                to_parse = [art for art in all_artifacts if not art.parsed]
                
                if not to_parse:
                    self._append_log("All found artifacts are already marked as parsed.", "INFO")
                    to_parse = all_artifacts # Force re-parse if needed? Let's just go with all_artifacts to be safe
                
                self._append_log(f"Invoking parsers for {len(to_parse)} artifacts...", "INFO")
                
                # We need a worker thread for parsing so we don't freeze the UI
                # For simplicity, we can use the same pattern as ParseArtifactsDialog uses internally
                # or just use ParserInvoker directly if it's already threaded (it's not).
                # To keep it consistent, let's create a quick local worker or repurpose the one from 
                # ParseArtifactsDialog if possible.
                
                # Since ParseArtifactsDialog has its own ParsingWorker, we'll implement a simple one here too or use it.
                from Offline_Importer.parse_artifacts_dialog import ParsingWorker
                
                invoker = ParserInvoker(self.case_root)
                
                # Define callbacks
                def progress_cb(current, total, name, type):
                    # Safely emit signal from worker thread to update GUI
                    if hasattr(self, 'parsing_worker'):
                        self.parsing_worker.progress_update.emit(current, total, name, type)
                
                def error_log_path():
                    return os.path.join(self.case_root, "parsing_errors.log")

                # Setup worker
                self.parsing_worker = ParsingWorker(
                    parser=invoker,
                    artifacts=to_parse,
                    progress_callback=progress_cb,
                    cancellation_check=lambda: False,
                    error_log_path=error_log_path()
                )
                
                # Connect signals
                self.parsing_worker.progress_update.connect(
                    lambda curr, tot, name, typ: self.operation_value.setText(f"Parsing {typ}: {name} ({curr}/{tot})")
                )
                
                self.parsing_worker.parsing_complete.connect(self._on_automated_parsing_complete)
                self.parsing_worker.parsing_error.connect(lambda err: self._append_log(f"Parsing Error: {err}", "ERROR"))
                
                self.parsing_worker.start()
                
        except Exception as e:
            import traceback
            error_msg = f"Failed to invoke artifact parser: {str(e)}"
            error_traceback = traceback.format_exc()
            self._append_log(error_msg, "ERROR")
            self._append_log(f"Traceback: {error_traceback}", "ERROR")
            QMessageBox.critical(
                self,
                "Parser Error",
                f"{error_msg}\n\nSee log for details."
            )
    
    def _on_automated_parsing_complete(self, results):
        """Handle completion of automated parsing."""
        self._append_log("Automated artifact parsing completed!", "SUCCESS")
        self.operation_value.setText("Parsing complete. Updating GUI...")
        
        # Determine unique artifact types parsed
        parsed_types = list(set(r.artifact_type for r in results if r.success))
        
        if parsed_types:
            self._on_artifacts_parsing_started(parsed_types)
            
            # CRITICAL: Trigger main GUI refresh if available
            if hasattr(self, 'crow_eye_main_window') and self.crow_eye_main_window:
                self._append_log("Notifying main window to refresh data tables...", "INFO")
                # We emit a signal that the main window should be listening to
                # or call its refresh method directly if we have a reference.
                if hasattr(self.crow_eye_main_window, 'refresh_gui_tabs_after_parsing'):
                    try:
                        self.crow_eye_main_window.refresh_gui_tabs_after_parsing(parsed_types)
                        self._append_log("Main GUI refresh triggered successfully.", "SUCCESS")
                    except Exception as e:
                        self._append_log(f"Refresh failed: {e}", "ERROR")
        else:
            self._append_log("No artifacts were successfully parsed.", "WARNING")
            
        # CRITICAL: Force GUI to process all pending events (like table population)
        # BEFORE showing the modal information dialog which blocks the event loop.
        from PyQt5.QtWidgets import QApplication
        QApplication.processEvents()
        
        QMessageBox.information(
            self,
            "Processing Complete",
            "Artifact extraction and parsing completed successfully!\n"
            "The main window is now updated with the forensic data."
        )

    def _on_artifacts_parsing_started(self, artifact_types: List[str]):
        """
        Handle artifacts_selected signal from ParseArtifactsDialog.
        
        Displays status message while GUI tables are being loaded.
        This is called when ParseArtifactsDialog emits the artifacts_selected
        signal after parsing completes.
        
        Args:
            artifact_types: List of artifact types that were parsed
                           (e.g., ['Registry', 'Prefetch', 'MFT'])
        
        Implements Requirements 7.3, 8.2, 8.3, 8.4, 16.6:
        - Displays parsing progress for each type
        - Shows "LOADING DATA INTO GUI TABLES..." status message
        """
        # Display loading status message
        if artifact_types:
            types_str = ", ".join(artifact_types)
            status_msg = f"LOADING DATA INTO GUI TABLES... ({len(artifact_types)} types: {types_str})"
            self._append_log(status_msg, "INFO")
            self.operation_value.setText("LOADING DATA INTO GUI TABLES...")
            
            # Log each artifact type being loaded
            for artifact_type in artifact_types:
                self._append_log(f"  - Loading {artifact_type} data into GUI", "INFO")
        else:
            self._append_log("No artifacts were parsed", "WARNING")
    
    def _on_export_results(self):
        """Handle export results button click."""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Results",
            "",
            "CSV Files (*.csv);;All Files (*.*)"
        )
        
        if file_path:
            try:
                import csv
                with open(file_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(['Type', 'Source Path', 'Status', 'Size', 'Hash'])
                    
                    for artifact in self.all_results:
                        writer.writerow([
                            artifact.get('artifact_type', ''),
                            artifact.get('source_path', ''),
                            artifact.get('collection_status', ''),
                            artifact.get('file_size', ''),
                            artifact.get('file_hash', '')
                        ])
                
                QMessageBox.information(
                    self,
                    "Export Complete",
                    f"Results exported successfully to:\n{file_path}"
                )
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Export Error",
                    f"Failed to export results:\n{str(e)}"
                )
    
    def _apply_results_filters(self):
        """Apply type filter to results table."""
        type_filter = self.results_type_filter.currentText()
        
        # Clear current table
        self.results_table.setRowCount(0)
        
        # Filter and display results
        for artifact in self.all_results:
            artifact_type = artifact.get('artifact_type', 'Unknown')
            
            # Skip Unknown artifacts
            if artifact_type == "Unknown":
                continue
            
            # Apply type filter
            if type_filter != "All Types" and artifact_type != type_filter:
                continue
            
            # Add row to table
            self._add_result_row(artifact)
    
    def _add_result_row(self, artifact: dict):
        """Add a single result row to the table."""
        try:
            self.results_table.setSortingEnabled(False)
            
            row = self.results_table.rowCount()
            self.results_table.insertRow(row)
            
            # Type column
            type_item = QTableWidgetItem(artifact.get('artifact_type', 'Unknown'))
            self.results_table.setItem(row, 0, type_item)
            
            # Source Path column
            source_item = QTableWidgetItem(artifact.get('source_path', ''))
            self.results_table.setItem(row, 1, source_item)
            
            # Status column
            status = artifact.get('collection_status', 'unknown')
            if status in ("success", "skipped_duplicate"):
                status_text = "✓ Success"
            else:
                status_text = "✗ Failed"
            status_item = QTableWidgetItem(status_text)
            self.results_table.setItem(row, 2, status_item)
            
            # Size column
            size_bytes = artifact.get('file_size', 0)
            size_str = self._format_file_size(size_bytes)
            size_item = QTableWidgetItem(size_str)
            size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.results_table.setItem(row, 3, size_item)
            
            # Hash column
            hash_value = artifact.get('file_hash', '')
            hash_item = QTableWidgetItem(hash_value[:16] + "..." if len(hash_value) > 16 else hash_value)
            hash_item.setToolTip(hash_value)
            self.results_table.setItem(row, 4, hash_item)
            
            self.results_table.setSortingEnabled(True)
        except Exception as e:
            print(f"[ERROR] Failed to add result row: {e}")
    
    # ========================================================================
    # Helper Methods
    # ========================================================================
    
    def _append_log(self, message: str, level: str = "INFO"):
        """Append a message to the log text area."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # Color coding based on level
        color = Colors.TEXT_PRIMARY
        if level == "ERROR":
            color = "#EF4444"
        elif level == "WARNING":
            color = "#F59E0B"
        elif level == "SUCCESS":
            color = "#10B981"
        
        formatted_msg = f'<span style="color: {color};">[{timestamp}] [{level}] {message}</span>'
        self.log_text_area.append(formatted_msg)
    
    def _format_file_size(self, size_bytes: int) -> str:
        """Format file size in human-readable format."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} TB"


# ============================================================================
# Standalone Entry Point
# ============================================================================

def show_dialog(case_root: str, parent=None):
    """Show the Image Parsing Dialog."""
    dialog = ImageParsingDialog(case_root, parent)
    return dialog.exec_()


if __name__ == "__main__":
    import sys
    from PyQt5.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    
    # Test with a temporary case directory
    test_case_root = os.path.join(os.path.expanduser("~"), ".crow_eye", "test_case")
    os.makedirs(test_case_root, exist_ok=True)
    
    dialog = ImageParsingDialog(test_case_root)
    dialog.show()
    
    sys.exit(app.exec_())
