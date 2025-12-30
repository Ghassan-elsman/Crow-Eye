"""
Pipeline Selection Dialog

This module provides a dialog for selecting a pipeline to load when no default
pipeline is set for the case.
"""

from pathlib import Path
from typing import Optional
import json
from datetime import datetime

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView, QAbstractItemView, QDialogButtonBox
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

# Import styles from main Crow-Eye application
try:
    from styles import CrowEyeStyles
except ImportError:
    # Fallback if styles not available
    class CrowEyeStyles:
        BUTTON_STYLE = ""
        GREEN_BUTTON = ""
        UNIFIED_TABLE_STYLE = ""


class PipelineSelectionDialog(QDialog):
    """
    Dialog for selecting a pipeline to load.
    
    Displays available pipelines and allows the user to select one to load
    into the Execution window.
    """
    
    def __init__(self, case_directory: str, parent=None):
        """
        Initialize the Pipeline Selection Dialog.
        
        Args:
            case_directory: Path to the case directory
            parent: Parent widget
        """
        super().__init__(parent)
        
        self.case_directory = Path(case_directory)
        self.pipelines_dir = self.case_directory / "Correlation" / "pipelines"
        self.selected_pipeline_path: Optional[str] = None
        
        self._init_ui()
        self._load_pipelines()
    
    def _init_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle("Select Pipeline")
        self.setMinimumSize(800, 500)
        self.setModal(True)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        
        # Title
        title = QLabel("SELECT PIPELINE TO EXECUTE")
        title.setStyleSheet("""
            QLabel {
                color: #00FFFF;
                font-size: 18px;
                font-weight: 700;
                font-family: 'BBH Sans Bogle', 'Segoe UI', sans-serif;
                text-transform: uppercase;
                letter-spacing: 1px;
            }
        """)
        layout.addWidget(title)
        
        # Info text
        info_label = QLabel(
            "No default pipeline is set for this case. "
            "Please select a pipeline to load for correlation analysis."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("""
            QLabel {
                color: #94A3B8;
                font-size: 12px;
                font-family: 'Segoe UI', sans-serif;
                padding: 10px;
                background-color: #1E293B;
                border-radius: 6px;
            }
        """)
        layout.addWidget(info_label)
        
        # Pipeline table
        self.pipeline_table = QTableWidget()
        self.pipeline_table.setColumnCount(4)
        self.pipeline_table.setHorizontalHeaderLabels([
            "Pipeline Name", "Wings", "Feathers", "Last Modified"
        ])
        self.pipeline_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.pipeline_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.pipeline_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        
        # Apply table styles
        try:
            CrowEyeStyles.apply_table_styles(self.pipeline_table)
        except:
            pass
        
        self.pipeline_table.setStyleSheet(CrowEyeStyles.UNIFIED_TABLE_STYLE + """
            QTableWidget {
                font-size: 13px;
            }
            QTableWidget::item {
                padding: 10px 8px;
                font-size: 13px;
                color: #F8FAFC;
            }
            QHeaderView::section {
                padding: 10px 8px;
                font-size: 12px;
            }
        """)
        
        # Configure column widths
        header = self.pipeline_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)  # Pipeline Name
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)  # Wings
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Feathers
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)  # Last Modified
        
        self.pipeline_table.setMinimumHeight(300)
        
        # Connect double-click to accept
        self.pipeline_table.itemDoubleClicked.connect(self._on_pipeline_double_clicked)
        self.pipeline_table.itemSelectionChanged.connect(self._on_selection_changed)
        
        layout.addWidget(self.pipeline_table)
        
        # Dialog buttons
        button_box = QDialogButtonBox()
        
        self.load_btn = QPushButton("Load Pipeline")
        self.load_btn.setFixedHeight(40)
        self.load_btn.setMinimumWidth(150)
        self.load_btn.setStyleSheet(CrowEyeStyles.GREEN_BUTTON + """
            QPushButton {
                font-size: 13px;
                padding: 10px 20px;
            }
        """)
        self.load_btn.clicked.connect(self.accept)
        self.load_btn.setEnabled(False)
        button_box.addButton(self.load_btn, QDialogButtonBox.AcceptRole)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(40)
        cancel_btn.setMinimumWidth(120)
        cancel_btn.setStyleSheet(CrowEyeStyles.BUTTON_STYLE + """
            QPushButton {
                font-size: 13px;
                padding: 10px 20px;
            }
        """)
        cancel_btn.clicked.connect(self.reject)
        button_box.addButton(cancel_btn, QDialogButtonBox.RejectRole)
        
        layout.addWidget(button_box)
        
        # Apply dialog styling
        self.setStyleSheet("""
            QDialog {
                background-color: #0F172A;
            }
        """)
    
    def _load_pipelines(self):
        """Load all pipelines from the case directory."""
        self.pipeline_table.setRowCount(0)
        
        if not self.pipelines_dir.exists():
            # Show message if no pipelines directory
            self.pipeline_table.setRowCount(1)
            item = QTableWidgetItem("No pipelines found. Please create a pipeline first.")
            item.setTextAlignment(Qt.AlignCenter)
            self.pipeline_table.setItem(0, 0, item)
            self.pipeline_table.setSpan(0, 0, 1, 4)
            return
        
        # Load all pipeline JSON files
        pipeline_files = sorted(self.pipelines_dir.glob("*.json"))
        
        if not pipeline_files:
            # Show message if no pipeline files
            self.pipeline_table.setRowCount(1)
            item = QTableWidgetItem("No pipelines found. Please create a pipeline first.")
            item.setTextAlignment(Qt.AlignCenter)
            self.pipeline_table.setItem(0, 0, item)
            self.pipeline_table.setSpan(0, 0, 1, 4)
            return
        
        for pipeline_file in pipeline_files:
            try:
                with open(pipeline_file, 'r') as f:
                    pipeline_data = json.load(f)
                
                self._add_pipeline_to_table(pipeline_data, pipeline_file)
                
            except Exception as e:
                print(f"Error loading pipeline {pipeline_file}: {e}")
                continue
    
    def _add_pipeline_to_table(self, pipeline_data: dict, pipeline_file: Path):
        """Add a pipeline to the table."""
        row = self.pipeline_table.rowCount()
        self.pipeline_table.insertRow(row)
        
        # Pipeline Name
        name_item = QTableWidgetItem(pipeline_data.get('pipeline_name', 'Unknown'))
        name_item.setData(Qt.UserRole, str(pipeline_file))  # Store file path
        self.pipeline_table.setItem(row, 0, name_item)
        
        # Wings count
        wings_count = len(pipeline_data.get('wing_configs', []))
        wings_item = QTableWidgetItem(str(wings_count))
        wings_item.setTextAlignment(Qt.AlignCenter)
        self.pipeline_table.setItem(row, 1, wings_item)
        
        # Feathers count
        feathers_count = len(pipeline_data.get('feather_configs', []))
        feathers_item = QTableWidgetItem(str(feathers_count))
        feathers_item.setTextAlignment(Qt.AlignCenter)
        self.pipeline_table.setItem(row, 2, feathers_item)
        
        # Last Modified
        last_modified = pipeline_data.get('last_modified', '')
        if last_modified:
            try:
                dt = datetime.fromisoformat(last_modified)
                last_modified = dt.strftime("%Y-%m-%d %H:%M")
            except:
                pass
        modified_item = QTableWidgetItem(last_modified)
        self.pipeline_table.setItem(row, 3, modified_item)
    
    def _on_selection_changed(self):
        """Handle selection change."""
        has_selection = len(self.pipeline_table.selectedItems()) > 0
        self.load_btn.setEnabled(has_selection)
        
        if has_selection:
            selected_rows = self.pipeline_table.selectionModel().selectedRows()
            if selected_rows:
                row = selected_rows[0].row()
                name_item = self.pipeline_table.item(row, 0)
                self.selected_pipeline_path = name_item.data(Qt.UserRole)
    
    def _on_pipeline_double_clicked(self, item):
        """Handle double-click on pipeline (load immediately)."""
        row = item.row()
        name_item = self.pipeline_table.item(row, 0)
        self.selected_pipeline_path = name_item.data(Qt.UserRole)
        self.accept()
    
    def get_selected_pipeline_path(self) -> Optional[str]:
        """
        Get the path to the selected pipeline.
        
        Returns:
            Path to selected pipeline JSON file, or None if no selection
        """
        return self.selected_pipeline_path
