"""
Parse Artifacts Dialog Module

This module provides a tabbed dialog interface for selecting and parsing
offline artifacts that have been scanned and indexed.

Classes:
    ParseArtifactsDialog: Dialog for selecting and parsing artifacts by category
"""

import logging
import os
import sys
from typing import Dict, List, Optional

# Add parent directory to path to ensure we can import styles and ui modules
# even when this is called from within the package
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from PyQt5.QtCore import Qt, pyqtSignal, QThread
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QTableWidget, QTableWidgetItem, QCheckBox, QPushButton,
    QLabel, QHeaderView, QMessageBox, QProgressDialog
)

try:
    from styles import Colors, CrowEyeStyles
    STYLES_AVAILABLE = True
except ImportError:
    # Try one more path if direct import fails
    try:
        sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        from styles import Colors, CrowEyeStyles
        STYLES_AVAILABLE = True
    except ImportError:
        STYLES_AVAILABLE = False
        # Fallback color definitions
        class Colors:
            BG_PRIMARY = "#0F172A"
            BG_PANELS = "#1E293B"
            TEXT_PRIMARY = "#E2E8F0"
            ACCENT_BLUE = "#3B82F6"
        
        class CrowEyeStyles:
            BUTTON_STYLE = ""
            UNIFIED_TAB_STYLE = ""
            UNIFIED_TABLE_STYLE = ""
            DIALOG_STYLE = ""
            LOADING_DIALOG = ""
            OVERLAY_TITLE = ""
            OVERLAY_STATUS = ""
            OVERLAY_PROGRESS = ""
            OVERLAY_LOG = ""
            MESSAGE_BOX_STYLE = ""
            SECONDARY_BUTTON = ""
            GREEN_BUTTON = ""

from Artifacts_Collectors.Offline_Importer.artifact_scan_index import (
    ArtifactScanIndex, ScannedArtifact
)

# Import LoadingDialog for consistent parsing UI
try:
    from ui.Loading_dialog import LoadingDialog
    LOADING_DIALOG_AVAILABLE = True
except ImportError:
    try:
        # Fallback for different package structures
        from ...ui.Loading_dialog import LoadingDialog
        LOADING_DIALOG_AVAILABLE = True
    except (ImportError, ValueError):
        # ValueError can occur with relative imports if not in a package
        LOADING_DIALOG_AVAILABLE = False
        print("[DEBUG] LoadingDialog not available in ParseArtifactsDialog")



logger = logging.getLogger(__name__)


class ParsingWorker(QThread):
    """
    Worker thread for parsing artifacts without blocking the GUI.
    
    Bug Fix #3: Move parsing to separate thread to prevent GUI freezing.
    
    Signals:
        progress_update: Emitted during parsing (current, total, artifact_name, artifact_type)
        parsing_complete: Emitted when parsing finishes successfully (list of ParserResult)
        parsing_error: Emitted if parsing fails (error message string)
        heartbeat: Emitted every 250ms to keep QEventLoop active and animation smooth
    """
    
    progress_update = pyqtSignal(int, int, str, str)  # current, total, artifact_name, artifact_type
    parsing_complete = pyqtSignal(list)  # List of ParserResult
    parsing_error = pyqtSignal(str)  # Error message
    heartbeat = pyqtSignal()  # Emitted every 250ms to keep event loop active
    
    def __init__(self, parser, artifacts, progress_callback, cancellation_check, error_log_path):
        """
        Initialize the parsing worker thread.
        
        Args:
            parser: ParserInvoker instance
            artifacts: List of ScannedArtifact to parse
            progress_callback: Callback function for progress updates
            cancellation_check: Function that returns True if user cancelled
            error_log_path: Path to error log file
        """
        super().__init__()
        self.parser = parser
        self.artifacts = artifacts
        self.progress_callback = progress_callback
        self.cancellation_check = cancellation_check
        self.error_log_path = error_log_path
        
        # Note: QTimer will be created in run() method to ensure it's created in the worker thread
        # This prevents "QObject::killTimer: Timers cannot be stopped from another thread" error
        self.heartbeat_timer = None
    
    def run(self):
        """Execute parsing in background thread."""
        try:
            # Create heartbeat timer in worker thread to avoid Qt threading issues
            # This prevents "QObject::killTimer: Timers cannot be stopped from another thread" error
            from PyQt5.QtCore import QTimer
            self.heartbeat_timer = QTimer()
            self.heartbeat_timer.timeout.connect(self.heartbeat.emit)
            self.heartbeat_timer.setInterval(250)  # 250ms interval
            
            # Start heartbeat timer to keep QEventLoop active
            self.heartbeat_timer.start()
            
            # Create heartbeat callback that emits the heartbeat signal
            def heartbeat_callback():
                try:
                    self.heartbeat.emit()
                except Exception as e:
                    logger.error(f"Error emitting heartbeat signal: {e}", exc_info=True)
            
            results = self.parser.parse_artifacts_batch(
                self.artifacts,
                progress_callback=self.progress_callback,
                cancellation_check=self.cancellation_check,
                error_log_path=self.error_log_path,
                heartbeat_callback=heartbeat_callback
            )
            
            # Emit completion signal with exception handling
            try:
                self.parsing_complete.emit(results)
            except Exception as e:
                logger.error(f"Error emitting parsing_complete signal: {e}", exc_info=True)
                # Try to emit error signal instead
                try:
                    self.parsing_error.emit(f"Failed to emit completion signal: {str(e)}")
                except:
                    pass
                    
        except Exception as e:
            logger.error(f"Worker thread exception during parsing: {e}", exc_info=True)
            try:
                self.parsing_error.emit(str(e))
            except Exception as emit_error:
                logger.error(f"Error emitting parsing_error signal: {emit_error}", exc_info=True)
        finally:
            # Stop heartbeat timer after parsing completes or fails
            # Timer is guaranteed to be in the same thread since it was created in run()
            try:
                if self.heartbeat_timer is not None:
                    self.heartbeat_timer.stop()
            except Exception as e:
                logger.error(f"Error stopping heartbeat timer: {e}", exc_info=True)


class ParseArtifactsDialog(QDialog):
    """
    Dialog for selecting and parsing offline artifacts.
    
    Features:
    - Tabbed interface by artifact category
    - Checkbox selection (all or individual)
    - Progress tracking during parsing
    - Direct GUI integration after parsing
    
    Signals:
        artifacts_selected: Emitted when user clicks Parse Selected with list of artifact IDs
    """
    
    artifacts_selected = pyqtSignal(list)  # List of artifact types that were parsed
    
    def __init__(self, case_root: str, parent=None):
        """
        Initialize the Parse Artifacts Dialog.
        
        Args:
            case_root: Root directory of the case
            parent: Parent widget (optional)
        """
        super().__init__(parent)
        self.case_root = case_root
        self.artifact_index = ArtifactScanIndex(case_root)
        
        # Track selection state
        self.category_tables: Dict[str, QTableWidget] = {}
        self.category_select_all: Dict[str, QCheckBox] = {}
        self.selected_artifacts: List[str] = []
        
        self.setup_ui()
        self.load_artifacts()
    
    def showEvent(self, event):
        """
        Override showEvent to center dialog after Qt finalizes geometry.
        
        This ensures the dialog is properly centered on screen after show() is called,
        when Qt has finalized the dialog's geometry. Calling centering before show()
        doesn't work correctly because the geometry is not yet determined.
        
        Args:
            event: The show event from Qt
        """
        super().showEvent(event)  # Call parent class showEvent first
        self._center_on_screen()  # Now center with correct geometry
    
    def setup_ui(self):
        """Set up the dialog UI with Crow-eye styling."""
        self.setWindowTitle("Parse Offline Artifacts")
        self.setMinimumSize(900, 600)
        
        # Apply dialog styling
        if STYLES_AVAILABLE:
            self.setStyleSheet(f"""
                QDialog {{
                    background-color: {Colors.BG_PRIMARY};
                    color: {Colors.TEXT_PRIMARY};
                }}
            """)
        
        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # Title
        title_label = QLabel("Parse Offline Artifacts")
        title_label.setStyleSheet(f"""
            QLabel {{
                color: {Colors.ACCENT_BLUE if STYLES_AVAILABLE else '#3B82F6'};
                font-size: 20px;
                font-weight: bold;
                font-family: 'Segoe UI', sans-serif;
            }}
        """)
        layout.addWidget(title_label)
        
        # Tab widget for artifact categories
        self.tab_widget = QTabWidget()
        if STYLES_AVAILABLE:
            self.tab_widget.setStyleSheet(CrowEyeStyles.UNIFIED_TAB_STYLE)
        layout.addWidget(self.tab_widget)
        
        # Button layout
        button_layout = QHBoxLayout()
        
        # Select All button (across all categories)
        self.select_all_button = QPushButton("✓ Select All")
        if STYLES_AVAILABLE:
            self.select_all_button.setStyleSheet(CrowEyeStyles.BUTTON_STYLE)
        self.select_all_button.clicked.connect(self.on_select_all_categories)
        button_layout.addWidget(self.select_all_button)
        
        # Deselect All button
        self.deselect_all_button = QPushButton("✗ Deselect All")
        if STYLES_AVAILABLE:
            self.deselect_all_button.setStyleSheet(CrowEyeStyles.SECONDARY_BUTTON)
        self.deselect_all_button.clicked.connect(self.on_deselect_all_categories)
        button_layout.addWidget(self.deselect_all_button)
        
        button_layout.addStretch()
        
        # Cancel button
        self.cancel_button = QPushButton("Cancel")
        if STYLES_AVAILABLE:
            self.cancel_button.setStyleSheet(CrowEyeStyles.SECONDARY_BUTTON)
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)
        
        # Parse Selected button
        self.parse_button = QPushButton("Parse Selected")
        if STYLES_AVAILABLE:
            self.parse_button.setStyleSheet(CrowEyeStyles.GREEN_BUTTON)
        self.parse_button.clicked.connect(self.on_parse_clicked)
        self.parse_button.setEnabled(False)  # Disabled until artifacts selected
        button_layout.addWidget(self.parse_button)
        
        layout.addLayout(button_layout)
    
    def load_artifacts(self) -> None:
        """Load artifacts from ArtifactScanIndex and create tabs."""
        try:
            all_artifacts = self.artifact_index.get_all_artifacts()
            
            if not all_artifacts:
                # Show message if no artifacts available
                self.show_no_artifacts_message()
                return
            
            # Group artifacts by category
            categories: Dict[str, List[ScannedArtifact]] = {}
            for artifact in all_artifacts:
                category = artifact.artifact_type
                if category not in categories:
                    categories[category] = []
                categories[category].append(artifact)
            
            # Create tab for each category
            for category, artifacts in sorted(categories.items()):
                self.create_category_tab(category, artifacts)
            
            logger.info(f"Loaded {len(all_artifacts)} artifacts across {len(categories)} categories")
            
        except Exception as e:
            logger.error(f"Failed to load artifacts: {e}")
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Critical)
            msg_box.setWindowTitle("Error Loading Artifacts")
            msg_box.setText(f"Failed to load artifacts from index:\n{str(e)}")
            if STYLES_AVAILABLE:
                msg_box.setStyleSheet(CrowEyeStyles.MESSAGE_BOX_STYLE)
            msg_box.exec_()
    
    def show_no_artifacts_message(self):
        """Display message when no artifacts are available."""
        no_artifacts_label = QLabel("No artifacts available to parse.\n\n"
                                    "Please scan artifacts using the Offline Importer first.")
        no_artifacts_label.setAlignment(Qt.AlignCenter)
        no_artifacts_label.setStyleSheet(f"""
            QLabel {{
                color: {Colors.TEXT_PRIMARY if STYLES_AVAILABLE else '#E2E8F0'};
                font-size: 14px;
                font-family: 'Segoe UI', sans-serif;
                padding: 40px;
            }}
        """)
        
        # Add to a tab so the UI doesn't look empty
        empty_widget = QWidget()
        empty_layout = QVBoxLayout(empty_widget)
        empty_layout.addWidget(no_artifacts_label)
        self.tab_widget.addTab(empty_widget, "No Artifacts")
    
    def create_category_tab(self, category: str, artifacts: List[ScannedArtifact]) -> QWidget:
        """
        Create a tab for an artifact category.
        
        Args:
            category: Name of the artifact category
            artifacts: List of artifacts in this category
            
        Returns:
            QWidget containing the tab content
        """
        # Create tab widget
        tab_widget = QWidget()
        tab_layout = QVBoxLayout(tab_widget)
        tab_layout.setContentsMargins(10, 10, 10, 10)
        tab_layout.setSpacing(10)
        
        # Select All checkbox with count
        select_all_layout = QHBoxLayout()
        select_all_checkbox = QCheckBox(f"Select All ({len(artifacts)} artifacts)")
        select_all_checkbox.setStyleSheet(f"""
            QCheckBox {{
                color: {Colors.TEXT_PRIMARY if STYLES_AVAILABLE else '#E2E8F0'};
                font-family: 'Segoe UI', sans-serif;
                font-size: 13px;
                font-weight: bold;
                spacing: 8px;
                padding: 4px;
            }}
        """)
        select_all_checkbox.stateChanged.connect(
            lambda state: self.on_select_all_changed(category, state == Qt.Checked)
        )
        self.category_select_all[category] = select_all_checkbox
        select_all_layout.addWidget(select_all_checkbox)
        select_all_layout.addStretch()
        tab_layout.addLayout(select_all_layout)
        
        # Create table for artifacts
        table = QTableWidget()
        table.setColumnCount(5)
        table.setHorizontalHeaderLabels(["Select", "File Path", "Size", "Scanned", "Status"])
        table.setRowCount(len(artifacts))
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        
        # Apply table styling
        if STYLES_AVAILABLE:
            CrowEyeStyles.apply_table_styles(table)
        
        # Configure column widths
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)  # Select column
        header.setSectionResizeMode(1, QHeaderView.Stretch)  # File Path
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Size
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)  # Scanned
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)  # Status
        
        # Populate table with artifacts
        for row, artifact in enumerate(artifacts):
            # Checkbox for selection
            checkbox_widget = QWidget()
            checkbox_layout = QHBoxLayout(checkbox_widget)
            checkbox_layout.setContentsMargins(0, 0, 0, 0)
            checkbox_layout.setAlignment(Qt.AlignCenter)
            
            checkbox = QCheckBox()
            checkbox.setProperty("artifact_id", artifact.artifact_id)
            checkbox.stateChanged.connect(
                lambda state, cat=category: self.on_artifact_selection_changed(cat)
            )
            checkbox_layout.addWidget(checkbox)
            table.setCellWidget(row, 0, checkbox_widget)
            
            # File path
            path_item = QTableWidgetItem(artifact.current_path)
            path_item.setToolTip(artifact.current_path)
            table.setItem(row, 1, path_item)
            
            # File size (formatted)
            size_str = self.format_file_size(artifact.file_size)
            size_item = QTableWidgetItem(size_str)
            size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            table.setItem(row, 2, size_item)
            
            # Scan timestamp (formatted)
            scan_time = artifact.scan_timestamp.split('T')[0] if 'T' in artifact.scan_timestamp else artifact.scan_timestamp
            scan_item = QTableWidgetItem(scan_time)
            scan_item.setTextAlignment(Qt.AlignCenter)
            table.setItem(row, 3, scan_item)
            
            # Status
            status = "Parsed" if artifact.parsed else "Not Parsed"
            status_item = QTableWidgetItem(status)
            status_item.setTextAlignment(Qt.AlignCenter)
            if artifact.parsed:
                status_item.setForeground(Qt.green)
            table.setItem(row, 4, status_item)
        
        # Store table reference
        self.category_tables[category] = table
        tab_layout.addWidget(table)
        
        # Add tab to tab widget
        self.tab_widget.addTab(tab_widget, category)
        
        return tab_widget
    
    def format_file_size(self, size_bytes: int) -> str:
        """
        Format file size in human-readable format.
        
        Args:
            size_bytes: Size in bytes
            
        Returns:
            Formatted size string (e.g., "12.5 MB")
        """
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} TB"
    
    def on_select_all_categories(self) -> None:
        """Select all artifacts across all categories."""
        for category, checkbox in self.category_select_all.items():
            checkbox.setChecked(True)
        self.update_selection_count()
    
    def on_deselect_all_categories(self) -> None:
        """Deselect all artifacts across all categories."""
        for category, checkbox in self.category_select_all.items():
            checkbox.setChecked(False)
        self.update_selection_count()
    
    def on_select_all_changed(self, category: str, checked: bool) -> None:
        """
        Handle select all checkbox state change.
        
        Args:
            category: Category name
            checked: Whether checkbox is checked
        """
        table = self.category_tables.get(category)
        if not table:
            return
        
        # Update all checkboxes in the table (block signals to avoid recursion)
        for row in range(table.rowCount()):
            checkbox_widget = table.cellWidget(row, 0)
            if checkbox_widget:
                checkbox = checkbox_widget.findChild(QCheckBox)
                if checkbox:
                    checkbox.blockSignals(True)
                    checkbox.setChecked(checked)
                    checkbox.blockSignals(False)
        
        self.update_selection_count()
    
    def on_artifact_selection_changed(self, category: str) -> None:
        """
        Handle individual artifact selection change.
        
        Args:
            category: Category name
        """
        table = self.category_tables.get(category)
        select_all = self.category_select_all.get(category)
        
        if not table or not select_all:
            return
        
        # Count selected items
        selected_count = 0
        total_count = table.rowCount()
        
        for row in range(total_count):
            checkbox_widget = table.cellWidget(row, 0)
            if checkbox_widget:
                checkbox = checkbox_widget.findChild(QCheckBox)
                if checkbox and checkbox.isChecked():
                    selected_count += 1
        
        # Update select all checkbox state
        if selected_count == 0:
            select_all.setCheckState(Qt.Unchecked)
        elif selected_count == total_count:
            select_all.setCheckState(Qt.Checked)
        else:
            select_all.setCheckState(Qt.PartiallyChecked)
        
        self.update_selection_count()
    
    def update_selection_count(self) -> None:
        """Update the parse button text with selection count and enable/disable it."""
        selected_count = 0
        
        # Count all selected artifacts across all categories
        for table in self.category_tables.values():
            for row in range(table.rowCount()):
                checkbox_widget = table.cellWidget(row, 0)
                if checkbox_widget:
                    checkbox = checkbox_widget.findChild(QCheckBox)
                    if checkbox and checkbox.isChecked():
                        selected_count += 1
        
        # Update button text and state
        if selected_count > 0:
            self.parse_button.setText(f"Parse Selected ({selected_count})")
            self.parse_button.setEnabled(True)
        else:
            self.parse_button.setText("Parse Selected")
            self.parse_button.setEnabled(False)
    
    def on_parse_clicked(self) -> None:
        """Handle parse button click - collect selected artifacts and start parsing."""
        selected_artifact_ids = []
        
        # Collect all selected artifact IDs
        for table in self.category_tables.values():
            for row in range(table.rowCount()):
                checkbox_widget = table.cellWidget(row, 0)
                if checkbox_widget:
                    checkbox = checkbox_widget.findChild(QCheckBox)
                    if checkbox and checkbox.isChecked():
                        artifact_id = checkbox.property("artifact_id")
                        if artifact_id:
                            selected_artifact_ids.append(artifact_id)
        
        if selected_artifact_ids:
            logger.info(f"User selected {len(selected_artifact_ids)} artifacts for parsing")
            self.selected_artifacts = selected_artifact_ids
            
            # Get the artifact types before parsing
            selected_artifacts_objs = self.get_selected_artifacts()
            artifact_types_before = list(set(a.artifact_type for a in selected_artifacts_objs))
            
            # Parse artifacts with progress tracking
            success, index_save_success, success_count, error_count, parse_results, loading_dialog = self.parse_selected_artifacts_with_progress()
            
            if success:
                # Get the artifact types that were successfully parsed
                try:
                    # Re-load the index to get updated parsed status (only if save succeeded)
                    if index_save_success:
                        self.artifact_index.load()
                        logger.info("Artifact index reloaded successfully")
                    else:
                        logger.warning("Using in-memory artifact index (save failed)")
                    
                    parsed_artifacts = [a for a in self.artifact_index.get_all_artifacts() 
                                       if a.artifact_id in selected_artifact_ids and a.parsed]
                    parsed_artifact_types = list(set(a.artifact_type for a in parsed_artifacts))
                    
                    # Emit signal with the artifact types that were parsed
                    # This triggers auto-load when connected to refresh_gui_tabs_after_parsing in Crow Eye.py
                    if parsed_artifact_types:
                        logger.info(f"Emitting signal for parsed artifact types: {parsed_artifact_types}")
                        print(f"[DEBUG] About to emit artifacts_selected signal with types: {parsed_artifact_types}")
                        
                        # Ensure we're in the main thread for signal emission
                        from PyQt5.QtCore import QMetaObject, Qt, Q_ARG
                        from PyQt5.QtWidgets import QApplication
                        
                        # Emit the signal
                        self.artifacts_selected.emit(parsed_artifact_types)
                        
                        # Force immediate processing of the signal
                        QApplication.processEvents()
                        
                        print(f"[DEBUG] Signal emitted and processed")
                    else:
                        # Fallback to artifact types before parsing if we can't determine which were successful
                        logger.warning("Could not determine parsed artifact types, using selected types")
                        print(f"[DEBUG] Emitting fallback signal with types: {artifact_types_before}")
                        self.artifacts_selected.emit(artifact_types_before)
                        from PyQt5.QtWidgets import QApplication
                        QApplication.processEvents()
                        print(f"[DEBUG] Fallback signal emitted and processed")
                    
                    # NOTE: Data loading to GUI is handled by the signal connection above.
                    # The parent (Crow Eye or OfflineImporterGUI) connects artifacts_selected signal
                    # to their respective refresh methods. This is the correct Qt architecture pattern.
                    
                    # Process events to ensure signal is handled before closing dialogs
                    from PyQt5.QtWidgets import QApplication
                    QApplication.processEvents()
                    
                    # Give the GUI a moment to process the data loading
                    import time
                    time.sleep(0.5)
                    
                    # Close loading dialog now that data is loaded
                    if loading_dialog:
                        print("[DEBUG] Closing loading dialog after data load...")
                        loading_dialog.close()
                        print("[DEBUG] Loading dialog closed")
                    
                    # NOW show the completion dialog AFTER data has loaded
                    print("[DEBUG] Now showing completion dialog after data load...")
                    self._show_parsing_complete_dialog(parse_results, success_count, error_count, selected_artifacts_objs)
                    print("[DEBUG] Completion dialog shown")
                        
                except Exception as e:
                    logger.error(f"Failed to determine parsed artifact types: {e}")
                    # Fallback to artifact types before parsing
                    self.artifacts_selected.emit(artifact_types_before)
                    
                    # Close loading dialog on error
                    if loading_dialog:
                        loading_dialog.close()
                
                self.accept()
        else:
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Warning)
            msg_box.setWindowTitle("No Artifacts Selected")
            msg_box.setText("Please select at least one artifact to parse.")
            if STYLES_AVAILABLE:
                msg_box.setStyleSheet(CrowEyeStyles.MESSAGE_BOX_STYLE)
            msg_box.exec_()
    
    def get_selected_artifacts(self) -> List[ScannedArtifact]:
        """
        Get the full ScannedArtifact objects for selected artifacts.
        
        Returns:
            List of ScannedArtifact objects that were selected
        """
        all_artifacts = self.artifact_index.get_all_artifacts()
        return [
            artifact for artifact in all_artifacts
            if artifact.artifact_id in self.selected_artifacts
        ]
    
    def _center_on_screen(self):
        """Center the dialog on the screen (Bug Fix #5)."""
        from PyQt5.QtWidgets import QApplication
        
        # Get screen geometry
        screen = QApplication.desktop().screenGeometry()
        
        # Calculate center position
        center_x = (screen.width() - self.width()) // 2
        center_y = (screen.height() - self.height()) // 2
        
        # Move dialog to center
        self.move(center_x, center_y)
    
    def _determine_artifact_status(self, artifact_type: str, results: list) -> dict:
        """
        Determine status for an artifact type based on success rate (Bug Fix #4).
        
        Args:
            artifact_type: Type of artifact (Registry, AmCache, etc.)
            results: List of ParserResult for this artifact type
        
        Returns:
            dict with keys: status, files_success, files_total, records_total, details
        """
        total_files = len(results)
        success_files = sum(1 for r in results if r.success)
        success_rate = success_files / total_files if total_files > 0 else 0
        
        # Apply 75% threshold rule
        if success_rate > 0.75:
            status = "✓ Success"
        elif success_rate > 0:
            status = "⚠ Partial"
        else:
            status = "✗ Failed"
        
        # Calculate total records
        records_total = sum(r.records_parsed for r in results)
        
        # Generate details
        failed_count = total_files - success_files
        if failed_count == 0:
            details = "Complete"
        else:
            details = f"{failed_count} failed"
        
        return {
            "status": status,
            "files_success": success_files,
            "files_total": total_files,
            "records_total": records_total,
            "details": details
        }
    
    def _format_results_table(self, results_by_type: dict) -> str:
        """
        Format results as per-artifact-type status table (Bug Fix #4).
        
        Args:
            results_by_type: dict mapping artifact_type to list of ParserResult
        
        Returns:
            Formatted table string
        """
        lines = []
        
        # Header
        lines.append(f"{'Artifact Type':<15} | {'Status':<10} | {'Files':<12} | {'Database':<10} | {'Details':<15}")
        lines.append("─" * 15 + "┼" + "─" * 11 + "┼" + "─" * 13 + "┼" + "─" * 11 + "┼" + "─" * 15)
        
        # Rows
        for artifact_type, results in sorted(results_by_type.items()):
            status_info = self._determine_artifact_status(artifact_type, results)
            
            files_str = f"{status_info['files_success']}/{status_info['files_total']}"
            records_str = f"{status_info['records_total']:,}"
            
            lines.append(
                f"{artifact_type:<15} │ {status_info['status']:<10} │ {files_str:<12} │ "
                f"{records_str:<10} │ {status_info['details']:<15}"
            )
        
        return "\n".join(lines)
    
    def _show_parsing_complete_dialog(self, parse_results: list, success_count: int, error_count: int, selected_artifacts: list):
        """
        Show smart completion dialog with QTableWidget AFTER data has loaded into GUI.
        
        Args:
            parse_results: List of ParserResult objects
            success_count: Number of successful parses
            error_count: Number of failed parses
            selected_artifacts: List of selected ScannedArtifact objects
        """
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QHeaderView
        from PyQt5.QtCore import Qt
        
        # Group results by artifact type
        results_by_type = {}
        processed_count = len(parse_results)
        for i in range(processed_count):
            artifact = selected_artifacts[i]
            result = parse_results[i]
            
            if artifact.artifact_type not in results_by_type:
                results_by_type[artifact.artifact_type] = []
            results_by_type[artifact.artifact_type].append(result)
        
        # Calculate total records
        total_records = sum(r.records_parsed for r in parse_results if r.success)
        
        # Create custom dialog
        dialog = QDialog(self)
        dialog.setWindowTitle("✓ Parsing Complete - Data Loaded")
        dialog.setMinimumSize(800, 500)
        
        # Apply Crow-eye styling
        if STYLES_AVAILABLE:
            dialog.setStyleSheet(f"""
                QDialog {{
                    background-color: {Colors.BG_PRIMARY};
                    color: {Colors.TEXT_PRIMARY};
                }}
            """)
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # Title and summary
        title_label = QLabel(f"✓ Successfully parsed {success_count} artifact(s) and loaded data into GUI")
        title_label.setStyleSheet(f"""
            QLabel {{
                color: {Colors.ACCENT_BLUE if STYLES_AVAILABLE else '#3B82F6'};
                font-size: 16px;
                font-weight: bold;
                font-family: 'Segoe UI', sans-serif;
                padding: 10px;
            }}
        """)
        layout.addWidget(title_label)
        
        # Summary stats
        summary_label = QLabel(
            f"📊 Total Records: {total_records:,}  |  "
            f"Artifact Types: {len(results_by_type)}  |  "
            f"Status: All data loaded and ready to view"
        )
        summary_label.setStyleSheet(f"""
            QLabel {{
                color: {Colors.TEXT_PRIMARY if STYLES_AVAILABLE else '#E2E8F0'};
                font-size: 13px;
                font-family: 'Segoe UI', sans-serif;
                padding: 5px 10px;
            }}
        """)
        layout.addWidget(summary_label)
        
        # Smart QTableWidget
        table = QTableWidget()
        table.setColumnCount(5)
        table.setHorizontalHeaderLabels(["Artifact Type", "Status", "Files", "Records", "Details"])
        table.setRowCount(len(results_by_type))
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSortingEnabled(True)  # Make it sortable!
        
        # Apply table styling
        if STYLES_AVAILABLE:
            CrowEyeStyles.apply_table_styles(table)
        
        # Configure column widths
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)  # Artifact Type
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)  # Status
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Files
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)  # Records
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)  # Details
        
        # Populate table
        row = 0
        for artifact_type in sorted(results_by_type.keys()):
            results = results_by_type[artifact_type]
            status_info = self._determine_artifact_status(artifact_type, results)
            
            # Artifact Type
            type_item = QTableWidgetItem(artifact_type)
            table.setItem(row, 0, type_item)
            
            # Status
            status_item = QTableWidgetItem(status_info['status'])
            status_item.setTextAlignment(Qt.AlignCenter)
            if "Success" in status_info['status']:
                status_item.setForeground(Qt.green)
            table.setItem(row, 1, status_item)
            
            # Files
            files_item = QTableWidgetItem(f"{status_info['files_success']}/{status_info['files_total']}")
            files_item.setTextAlignment(Qt.AlignCenter)
            table.setItem(row, 2, files_item)
            
            # Records
            records_item = QTableWidgetItem(f"{status_info['records_total']:,}")
            records_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            table.setItem(row, 3, records_item)
            
            # Details
            details_item = QTableWidgetItem(status_info['details'])
            details_item.setTextAlignment(Qt.AlignCenter)
            table.setItem(row, 4, details_item)
            
            row += 1
        
        layout.addWidget(table)
        
        # OK button
        ok_button = QPushButton("OK")
        ok_button.setMinimumWidth(120)
        if STYLES_AVAILABLE:
            ok_button.setStyleSheet(CrowEyeStyles.GREEN_BUTTON)
        ok_button.clicked.connect(dialog.accept)
        
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(ok_button)
        layout.addLayout(button_layout)
        
        # Show dialog
        dialog.exec_()
    
    def show_error_dialog_with_status(self, status_table: str, error_messages: List[tuple], success_count: int, error_count: int) -> None:
        """
        Display enlarged error dialog with per-artifact-type status and parsing results (Bug Fix #4).
        
        Args:
            status_table: Formatted per-artifact-type status table
            error_messages: List of tuples (artifact_type, filename, error_message)
            success_count: Number of successfully parsed artifacts
            error_count: Number of failed artifacts
        """
        from PyQt5.QtWidgets import QTextEdit, QVBoxLayout, QPushButton
        
        # Create custom dialog subclass with showEvent override for proper centering
        class CenteredErrorDialog(QDialog):
            """Error dialog that centers itself after Qt finalizes geometry"""
            def showEvent(self, event):
                """Override showEvent to center dialog after Qt finalizes geometry"""
                super().showEvent(event)
                # Center on screen after geometry is finalized
                screen = QApplication.desktop().screenGeometry()
                center_x = (screen.width() - self.width()) // 2
                center_y = (screen.height() - self.height()) // 2
                self.move(center_x, center_y)
        
        # Create custom dialog with 900x600 size
        error_dialog = CenteredErrorDialog(self)
        error_dialog.setWindowTitle("Parsing Completed with Errors")
        error_dialog.setMinimumSize(900, 600)
        
        # Apply Crow-eye styling
        if STYLES_AVAILABLE:
            error_dialog.setStyleSheet(f"""
                QDialog {{
                    background-color: {Colors.BG_PRIMARY};
                    color: {Colors.TEXT_PRIMARY};
                }}
            """)
        
        # Create layout
        dialog_layout = QVBoxLayout(error_dialog)
        dialog_layout.setContentsMargins(20, 20, 20, 20)
        dialog_layout.setSpacing(15)
        
        # Summary label with status table
        summary_text = (
            f"Artifact parsing finished with some issues.\n\n"
            f"PER-ARTIFACT-TYPE STATUS:\n\n"
            f"{status_table}\n\n"
            f"Total: {success_count} Success, {error_count} Failed"
        )
        summary_label = QLabel(summary_text)
        summary_label.setStyleSheet(f"""
            QLabel {{
                color: {Colors.TEXT_PRIMARY if STYLES_AVAILABLE else '#E2E8F0'};
                font-size: 14px;
                font-weight: bold;
                font-family: 'Consolas', 'Courier New', monospace;
                padding: 10px;
            }}
        """)
        dialog_layout.addWidget(summary_label)
        
        # Error details text edit (scrollable)
        error_text = QTextEdit()
        error_text.setReadOnly(True)
        
        # Bug Fix #4: Group errors by artifact type and show per-type status
        # Group error messages by artifact type
        errors_by_type = {}
        for artifact_type, filename, error_msg in error_messages:
            if artifact_type not in errors_by_type:
                errors_by_type[artifact_type] = []
            errors_by_type[artifact_type].append((filename, error_msg))
        
        # Format error messages with per-artifact-type view
        error_lines = []
        error_lines.append("DETAILED ERROR LOG:")
        error_lines.append("=" * 120)
        error_lines.append("")
        
        for artifact_type in sorted(errors_by_type.keys()):
            error_lines.append(f"[{artifact_type}]")
            error_lines.append("-" * 120)
            for filename, error_msg in errors_by_type[artifact_type]:
                error_lines.append(f"  File: {filename}")
                error_lines.append(f"  Error: {error_msg}")
                error_lines.append("")
        
        error_text.setPlainText("\n".join(error_lines))
        
        # Apply styling to text edit
        if STYLES_AVAILABLE:
            error_text.setStyleSheet(f"""
                QTextEdit {{
                    background-color: {Colors.BG_PANELS};
                    color: {Colors.TEXT_PRIMARY};
                    font-family: 'Consolas', 'Courier New', monospace;
                    font-size: 11px;
                    border: 1px solid {Colors.ACCENT_BLUE};
                    border-radius: 4px;
                    padding: 8px;
                }}
            """)
        else:
            error_text.setStyleSheet("""
                QTextEdit {
                    font-family: 'Consolas', 'Courier New', monospace;
                    font-size: 11px;
                    padding: 8px;
                }
            """)
        
        dialog_layout.addWidget(error_text)
        
        # Close button
        close_button = QPushButton("Close")
        if STYLES_AVAILABLE:
            close_button.setStyleSheet(CrowEyeStyles.BUTTON_STYLE)
        close_button.clicked.connect(error_dialog.accept)
        
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(close_button)
        dialog_layout.addLayout(button_layout)
        
        # Show dialog modally (centering handled by showEvent)
        error_dialog.exec_()

    def parse_selected_artifacts_with_progress(self) -> tuple[bool, bool, int, int, list, object]:
        """
        Parse selected artifacts with progress tracking using LoadingDialog.
        
        Returns:
            Tuple of (success, index_save_success, success_count, error_count, parse_results, loading_dialog)
            - success: True if parsing process completed (even with partial failures)
            - index_save_success: True if artifact index was saved successfully
            - success_count: Number of artifacts parsed successfully
            - error_count: Number of artifacts that failed to parse
            - parse_results: List of ParserResult objects for displaying results dialog
            - loading_dialog: LoadingDialog object (kept open for data loading phase)
        """
        from Artifacts_Collectors.Offline_Importer.parser_invoker import ParserInvoker
        
        # Get selected artifacts
        selected_artifacts = self.get_selected_artifacts()
        
        if not selected_artifacts:
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Warning)
            msg_box.setWindowTitle("No Artifacts Selected")
            msg_box.setText("Please select at least one artifact to parse.")
            if STYLES_AVAILABLE:
                msg_box.setStyleSheet(CrowEyeStyles.MESSAGE_BOX_STYLE)
            msg_box.exec_()
            return False, False, 0, 0, [], None
        
        # Create LoadingDialog for consistent UI with live parsers (Requirement 3)
        if LOADING_DIALOG_AVAILABLE:
            # Use None as parent to avoid modal dialog conflicts (Bug Fix 3.3)
            loading_dialog = LoadingDialog("PARSING ARTIFACTS", None)
            
            # Apply EXACT cyberpunk styling used by live parsers (same as Crow Eye.py line 7325-7330)
            try:
                from styles import CrowEyeStyles
                from PyQt5 import QtWidgets
                
                # Apply the main dialog style (same as live parsers)
                loading_dialog.setStyleSheet(CrowEyeStyles.LOADING_DIALOG)
                
                # Apply title style (same as live parsers)
                title_label = loading_dialog.findChild(QtWidgets.QLabel, "titleLabel")
                if title_label:
                    title_label.setStyleSheet(CrowEyeStyles.OVERLAY_TITLE)
                
                # Apply status style (same as live parsers)
                status_label = loading_dialog.findChild(QtWidgets.QLabel, "statusLabel")
                if status_label:
                    status_label.setStyleSheet(CrowEyeStyles.OVERLAY_STATUS)
                
                # Apply progress bar style (same as live parsers)
                progress_bar = loading_dialog.findChild(QtWidgets.QProgressBar)
                if progress_bar:
                    progress_bar.setStyleSheet(CrowEyeStyles.OVERLAY_PROGRESS)
                
                # Apply log text style (same as live parsers)
                log_text = loading_dialog.findChild(QtWidgets.QTextEdit)
                if log_text:
                    log_text.setStyleSheet(CrowEyeStyles.OVERLAY_LOG)
                    
            except (ImportError, Exception) as e:
                print(f"[DEBUG] Failed to apply cyberpunk style to LoadingDialog: {e}")
            
            # Requirement 2: Group and order steps by artifact type (same as live parsers)
            canonical_order = [
                'link_jumplist', 'Registry', 'Prefetch', 'EVTX', 'ShimCache', 
                'AmCache', 'RecycleBin', 'SRUM', 'MFT', 'USN'
            ]
            
            # Get unique artifact types from selected artifacts
            unique_types = []
            for t in canonical_order:
                if any(a.artifact_type == t for a in selected_artifacts):
                    unique_types.append(t)
            
            # Add any other types not in canonical order
            other_types = sorted(list(set(a.artifact_type for a in selected_artifacts if a.artifact_type not in canonical_order)))
            unique_types.extend(other_types)
            
            # Set steps based on unique artifact types
            steps = [f"Analyzing {t}" for t in unique_types]
            loading_dialog.set_steps(steps)
            loading_dialog.show()
            
            # Force dialog to front and ensure visibility (Bug Fix 3.3)
            loading_dialog.raise_()  # Bring to front
            loading_dialog.activateWindow()  # Activate window
            
            # Force immediate rendering
            from PyQt5.QtWidgets import QApplication
            QApplication.processEvents()
            
            # Debug logging for visibility and window state
            logger.info(f"LoadingDialog visibility: {loading_dialog.isVisible()}, window state: {loading_dialog.windowState()}")
            
            # Map artifact types to their step index for progress reporting
            type_to_step_index = {t: i for i, t in enumerate(unique_types)}
            
            # Start log capture (same as live parsers - Crow Eye.py line 6991)
            loading_dialog.start_log_capture()

            # Connect cancellation signal
            def on_cancelled():
                nonlocal cancelled
                cancelled = True
                logger.warning("User clicked cancel in LoadingDialog")
                
                # Update dialog title to show cancellation is in progress
                if LOADING_DIALOG_AVAILABLE:
                    loading_dialog.title_label.setText("CANCELLING OPERATION...")
                    loading_dialog.add_log_message("\n⚠ Cancellation requested - waiting for current operation to complete...")
                
            loading_dialog.cancelled.connect(on_cancelled)
        else:
            # Fallback to QProgressDialog if LoadingDialog not available
            loading_dialog = None
            type_to_step_index = {}
        
        # Initialize parser
        parser = ParserInvoker(self.case_root)
        
        # Track results
        parse_results = []
        cancelled = False
        worker_finished = False
        worker_error = None
        
        def progress_callback(current: int, total: int, artifact_name: str, artifact_type: str):
            """Update loading dialog with current parsing status."""
            nonlocal cancelled
            
            if not LOADING_DIALOG_AVAILABLE:
                return
            
            # Ensure dialog stays visible (Bug Fix 3.3)
            if not loading_dialog.isVisible():
                logger.warning("LoadingDialog became invisible, re-showing")
                loading_dialog.show()
                loading_dialog.raise_()
                loading_dialog.activateWindow()
            
            # Update step based on artifact type
            if artifact_type in type_to_step_index:
                step_idx = type_to_step_index[artifact_type]
                filename = os.path.basename(artifact_name)
                
                # If we have a filename, include it in the status
                status_msg = f"Parsing {artifact_type}"
                if filename and filename != artifact_type:
                    status_msg += f": {filename}"
                
                loading_dialog.update_step(step_idx, status_msg)
                
                # If it's the "Complete" message from ParserInvoker
                if artifact_name == "Complete":
                    loading_dialog.show_completion("ARTIFACT PARSING COMPLETE")
            
            # Process events to keep UI responsive and ensure visibility
            from PyQt5.QtWidgets import QApplication
            QApplication.processEvents()
        
        # Bug Fix #3: Use worker thread to prevent GUI freezing
        def on_parsing_complete(results):
            """Handle parsing completion from worker thread."""
            nonlocal parse_results, worker_finished
            parse_results = results
            worker_finished = True
        
        def on_parsing_error(error_msg):
            """Handle parsing error from worker thread."""
            nonlocal worker_error, worker_finished
            worker_error = error_msg
            worker_finished = True
        
        try:
            # Create error log file path (Bug Fix #6: Use offline_parsing_logs.txt)
            error_log_path = os.path.join(self.case_root, "offline_parsing_logs.txt")
            
            # Bug Fix #3: Create and start worker thread
            worker = ParsingWorker(
                parser,
                selected_artifacts,
                progress_callback,
                lambda: cancelled,
                error_log_path
            )
            
            # Connect worker signals with exception handling
            try:
                worker.parsing_complete.connect(on_parsing_complete)
                worker.parsing_error.connect(on_parsing_error)
                
                # Connect heartbeat signal to keep QEventLoop active during long operations
                # This ensures animation timer events are processed even when no progress updates occur
                def on_heartbeat():
                    """Process events to keep animation smooth during long parsing operations."""
                    try:
                        from PyQt5.QtWidgets import QApplication
                        QApplication.processEvents()
                    except Exception as e:
                        logger.error(f"Error processing events in heartbeat: {e}", exc_info=True)
                
                worker.heartbeat.connect(on_heartbeat)
            except Exception as e:
                logger.error(f"Error connecting worker signals: {e}", exc_info=True)
                raise
            
            # Start worker thread (non-blocking)
            worker.start()
            
            # Use QEventLoop to wait without blocking GUI
            from PyQt5.QtCore import QEventLoop
            loop = QEventLoop()
            
            # Connect worker finished signal to quit the event loop
            try:
                worker.finished.connect(loop.quit)
            except Exception as e:
                logger.error(f"Error connecting worker finished signal: {e}", exc_info=True)
                raise
            
            # Run event loop - this keeps GUI responsive while waiting
            try:
                loop.exec_()
            except Exception as e:
                logger.error(f"Error in event loop execution: {e}", exc_info=True)
                raise
            
            # Check for worker errors
            if worker_error:
                raise Exception(worker_error)
            
            # Clean up worker thread
            try:
                worker.wait()  # Ensure thread is fully finished
            except Exception as e:
                logger.error(f"Error waiting for worker thread: {e}", exc_info=True)
            
            # Update artifact index with parsed status
            # Fix logical error: use min(len, len) to avoid IndexError if cancelled
            processed_count = min(len(selected_artifacts), len(parse_results))
            
            # Group results by artifact type to avoid duplicate messages for directory-based parsers
            results_by_type = {}
            for i in range(processed_count):
                artifact = selected_artifacts[i]
                result = parse_results[i]
                
                if artifact.artifact_type not in results_by_type:
                    results_by_type[artifact.artifact_type] = {
                        'artifacts': [],
                        'results': [],
                        'total_records': 0,
                        'success_count': 0,
                        'error_count': 0
                    }
                
                results_by_type[artifact.artifact_type]['artifacts'].append(artifact)
                results_by_type[artifact.artifact_type]['results'].append(result)
                
                if result.success:
                    results_by_type[artifact.artifact_type]['success_count'] += 1
                    results_by_type[artifact.artifact_type]['total_records'] += result.records_parsed
                else:
                    results_by_type[artifact.artifact_type]['error_count'] += 1
            
            # Update index and show ONE summary message per artifact type
            for artifact_type, type_data in results_by_type.items():
                # Mark all successful artifacts as parsed
                for artifact, result in zip(type_data['artifacts'], type_data['results']):
                    if result.success:
                        try:
                            self.artifact_index.mark_as_parsed(artifact.artifact_id)
                        except KeyError as e:
                            logger.error(f"Artifact {artifact.artifact_id} not found in index: {e}", exc_info=True)
                        except Exception as e:
                            logger.error(f"Failed to mark artifact {artifact.artifact_id} as parsed: {e}", exc_info=True)
                
                # Show ONE summary message per artifact type
                if LOADING_DIALOG_AVAILABLE:
                    success_count = type_data['success_count']
                    error_count = type_data['error_count']
                    total_records = type_data['total_records']
                    total_files = len(type_data['artifacts'])
                    
                    if success_count > 0:
                        if success_count == total_files:
                            # All files succeeded
                            loading_dialog.add_log_message(f"✓ {artifact_type}: Successfully parsed {total_records} records from {total_files} file(s)")
                        else:
                            # Partial success
                            loading_dialog.add_log_message(f"⚠ {artifact_type}: Parsed {total_records} records from {success_count}/{total_files} file(s)")
                    
                    if error_count > 0:
                        # Show error summary
                        error_details = []
                        for result in type_data['results']:
                            if not result.success and result.errors:
                                error_details.extend(result.errors)
                        
                        if error_details:
                            error_summary = error_details[0] if len(error_details) == 1 else f"{len(error_details)} errors"
                            loading_dialog.add_log_message(f"✗ {artifact_type}: {error_count} file(s) FAILED - {error_summary}")
            
            # Save updated index with verification
            index_save_success = False
            try:
                print("[DEBUG] About to save artifact index...")
                self.artifact_index.save()
                index_save_success = True
                logger.info("Artifact index saved successfully")
                print("Artifact index saved successfully")
                print("[DEBUG] Index save completed, continuing...")
            except Exception as e:
                logger.error(f"Failed to save artifact index: {e}", exc_info=True)
                print(f"[ERROR] Failed to save artifact index: {e}")
                if LOADING_DIALOG_AVAILABLE:
                    loading_dialog.add_log_message(f"⚠ Warning: Failed to save artifact index: {str(e)}")
            
            # Summary stats
            print("[DEBUG] Calculating summary stats...")
            success_count = sum(1 for r in parse_results if r.success)
            error_count = len(parse_results) - success_count
            print(f"[DEBUG] Summary: {success_count} success, {error_count} errors")
            
            # Show completion in loading dialog with summary (Requirement 11.2)
            print("[DEBUG] Parsing complete, keeping loading dialog open for data loading...")
            if LOADING_DIALOG_AVAILABLE:
                try:
                    loading_dialog.add_log_message("\n" + "="*50)
                    loading_dialog.add_log_message(f"PARSING SUMMARY: {success_count} Success, {error_count} Failed")
                    loading_dialog.add_log_message("="*50 + "\n")
                    
                    if error_count > 0:
                        loading_dialog.add_log_message("ERROR DETAILS:")
                        for i in range(processed_count):
                            if not parse_results[i].success:
                                artifact = selected_artifacts[i]
                                error_msg = ", ".join(parse_results[i].errors)
                                loading_dialog.add_log_message(f"  • {artifact.artifact_type}: {error_msg}")
                    
                    # Update dialog to show data loading phase
                    loading_dialog.add_log_message("\n📊 LOADING DATA INTO GUI TABLES...")
                    loading_dialog.title_label.setText("LOADING DATA INTO GUI")
                    from PyQt5.QtWidgets import QApplication
                    QApplication.processEvents()
                    print("[DEBUG] Loading dialog updated for data loading phase")
                except Exception as e:
                    logger.error(f"Error updating loading dialog: {e}", exc_info=True)
                    print(f"[ERROR] Exception in loading dialog: {e}")
                    import traceback
                    traceback.print_exc()
            
            # Show results summary dialog with enhanced details
            print("[DEBUG] Preparing results data for dialog (will be shown after data loads)...")
            # Don't show dialog here - return the data so it can be shown after GUI loads
            # The dialog will be displayed in on_parse_clicked() after refresh_gui_tabs_after_parsing()
            # Keep loading_dialog open so it can show data loading progress
            
            logger.info(f"Parsing complete: {success_count} success, {error_count} errors")
            return True, index_save_success, success_count, error_count, parse_results, loading_dialog if LOADING_DIALOG_AVAILABLE else None
            
        except Exception as e:
            logger.error(f"Parsing failed: {e}", exc_info=True)
            if LOADING_DIALOG_AVAILABLE:
                try:
                    loading_dialog.add_log_message(f"[Error] Parsing failed: {str(e)}")
                    # Keep error dialog open longer (same as live parsers - Crow Eye.py line 7017)
                    from PyQt5.QtCore import QTimer
                    from PyQt5.QtWidgets import QApplication
                    QApplication.processEvents()
                    QTimer.singleShot(3000, loading_dialog.close)
                except Exception as dialog_error:
                    logger.error(f"Failed to update loading dialog: {dialog_error}", exc_info=True)
            
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Critical)
            msg_box.setWindowTitle("Parsing Error")
            msg_box.setText(f"An error occurred during parsing:\n{str(e)}")
            if STYLES_AVAILABLE:
                msg_box.setStyleSheet(CrowEyeStyles.MESSAGE_BOX_STYLE)
            msg_box.exec_()
            return False, False, 0, 0, [], None
        
        finally:
            # Always stop log capture (same as live parsers - Crow Eye.py line 7023)
            if LOADING_DIALOG_AVAILABLE:
                try:
                    loading_dialog.stop_log_capture()
                except Exception as e:
                    logger.error(f"Failed to stop log capture: {e}", exc_info=True)
