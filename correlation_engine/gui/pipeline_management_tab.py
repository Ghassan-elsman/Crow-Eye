"""
Pipeline Management Tab for Settings Dialog

This module provides a comprehensive interface for managing case pipelines
within the Crow-Eye Settings dialog. Users can create, edit, delete, duplicate,
and set default pipelines for their forensic cases.
"""

import os
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QMessageBox, QHeaderView, QGroupBox, QSplitter,
    QTextEdit, QAbstractItemView
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QIcon

# Import styles from main Crow-Eye application
try:
    from styles import CrowEyeStyles
except ImportError:
    # Fallback if styles not available
    class CrowEyeStyles:
        BUTTON_STYLE = ""
        GREEN_BUTTON = ""
        RED_BUTTON = ""
        UNIFIED_TABLE_STYLE = ""
        MESSAGE_BOX_STYLE = ""
        GROUP_BOX = ""


class PipelineManagementTab(QWidget):
    """
    Tab for managing case pipelines in Settings dialog.
    
    Provides functionality to:
    - View all pipelines for the current case
    - Create new pipelines
    - Edit existing pipelines
    - Delete pipelines
    - Duplicate pipelines
    - Set default pipeline for auto-loading
    """
    
    # Signal emitted when pipeline list changes
    pipelines_changed = pyqtSignal()
    
    def __init__(self, case_directory: str, parent=None):
        """
        Initialize the Pipeline Management Tab.
        
        Args:
            case_directory: Path to the case directory
            parent: Parent widget
        """
        super().__init__(parent)
        
        self.case_directory = Path(case_directory)
        self.pipelines_dir = self.case_directory / "Correlation" / "pipelines"
        self.config_file = self.case_directory / "Correlation" / "case_config.json"
        
        # Ensure directories exist
        self.pipelines_dir.mkdir(parents=True, exist_ok=True)
        
        self._init_ui()
        self.load_pipelines()
    
    def _init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        
        # Title
        title = QLabel("PIPELINE MANAGEMENT")
        title.setStyleSheet("""
            QLabel {
                color: #00FFFF;
                font-size: 20px;
                font-weight: 700;
                font-family: 'BBH Sans Bogle', 'Segoe UI', sans-serif;
                text-transform: uppercase;
                letter-spacing: 1px;
            }
        """)
        layout.addWidget(title)
        
        # Info text
        info_label = QLabel(
            "Manage correlation pipelines for this case. "
            "Pipelines define which feathers and wings to use for correlation analysis."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("""
            QLabel {
                color: #94A3B8;
                font-size: 13px;
                font-family: 'Segoe UI', sans-serif;
                padding: 10px;
                background-color: #1E293B;
                border-radius: 6px;
            }
        """)
        layout.addWidget(info_label)
        
        # Create splitter for table and details
        splitter = QSplitter(Qt.Vertical)
        
        # Pipeline list section
        list_widget = self._create_pipeline_list_section()
        splitter.addWidget(list_widget)
        
        # Pipeline details section
        details_widget = self._create_pipeline_details_section()
        splitter.addWidget(details_widget)
        
        # Set splitter sizes (70% list, 30% details)
        splitter.setSizes([700, 300])
        
        layout.addWidget(splitter, 1)
        
        # Action buttons
        button_layout = self._create_action_buttons()
        layout.addLayout(button_layout)
    
    def _create_pipeline_list_section(self) -> QWidget:
        """Create the pipeline list table section."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        
        # Section label
        label = QLabel("Available Pipelines")
        label.setStyleSheet("""
            QLabel {
                color: #E2E8F0;
                font-size: 14px;
                font-weight: 600;
                font-family: 'Segoe UI', sans-serif;
            }
        """)
        layout.addWidget(label)
        
        # Pipeline table
        self.pipeline_table = QTableWidget()
        self.pipeline_table.setColumnCount(5)
        self.pipeline_table.setHorizontalHeaderLabels([
            "Pipeline Name", "Wings", "Feathers", "Last Modified", "Default"
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
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)  # Default
        
        self.pipeline_table.setMinimumHeight(300)
        
        # Connect selection change
        self.pipeline_table.itemSelectionChanged.connect(self._on_pipeline_selection_changed)
        self.pipeline_table.itemDoubleClicked.connect(self._on_pipeline_double_clicked)
        
        layout.addWidget(self.pipeline_table)
        
        return widget
    
    def _create_pipeline_details_section(self) -> QWidget:
        """Create the pipeline details panel."""
        widget = QGroupBox("Pipeline Details")
        widget.setStyleSheet(CrowEyeStyles.GROUP_BOX)
        
        layout = QVBoxLayout(widget)
        layout.setSpacing(10)
        
        # Details text area
        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setPlaceholderText("Select a pipeline to view details...")
        self.details_text.setStyleSheet("""
            QTextEdit {
                background-color: #0F172A;
                color: #E2E8F0;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 10px;
                font-size: 12px;
                font-family: 'Segoe UI', sans-serif;
            }
        """)
        self.details_text.setMaximumHeight(200)
        
        layout.addWidget(self.details_text)
        
        return widget
    
    def _create_action_buttons(self) -> QHBoxLayout:
        """Create action buttons layout."""
        layout = QHBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(0, 15, 0, 0)
        
        # Create New Pipeline button
        self.create_btn = QPushButton("➕ Create New Pipeline")
        self.create_btn.setFixedHeight(45)
        self.create_btn.setMinimumWidth(180)
        self.create_btn.setStyleSheet(CrowEyeStyles.BUTTON_STYLE + """
            QPushButton {
                font-size: 13px;
                padding: 12px 24px;
            }
        """)
        self.create_btn.clicked.connect(self.create_pipeline)
        layout.addWidget(self.create_btn)
        
        # Edit Pipeline button
        self.edit_btn = QPushButton("✏ Edit Pipeline")
        self.edit_btn.setFixedHeight(45)
        self.edit_btn.setMinimumWidth(150)
        self.edit_btn.setStyleSheet(CrowEyeStyles.BUTTON_STYLE + """
            QPushButton {
                font-size: 13px;
                padding: 12px 24px;
            }
        """)
        self.edit_btn.clicked.connect(self.edit_pipeline)
        self.edit_btn.setEnabled(False)
        layout.addWidget(self.edit_btn)
        
        # Duplicate Pipeline button
        self.duplicate_btn = QPushButton("📋 Duplicate")
        self.duplicate_btn.setFixedHeight(45)
        self.duplicate_btn.setMinimumWidth(150)
        self.duplicate_btn.setStyleSheet(CrowEyeStyles.BUTTON_STYLE + """
            QPushButton {
                font-size: 13px;
                padding: 12px 24px;
            }
        """)
        self.duplicate_btn.clicked.connect(self.duplicate_pipeline)
        self.duplicate_btn.setEnabled(False)
        layout.addWidget(self.duplicate_btn)
        
        # Set as Default button
        self.set_default_btn = QPushButton("⭐ Set as Default")
        self.set_default_btn.setFixedHeight(45)
        self.set_default_btn.setMinimumWidth(170)
        self.set_default_btn.setStyleSheet(CrowEyeStyles.GREEN_BUTTON + """
            QPushButton {
                font-size: 13px;
                padding: 12px 24px;
            }
        """)
        self.set_default_btn.clicked.connect(self.set_default_pipeline)
        self.set_default_btn.setEnabled(False)
        layout.addWidget(self.set_default_btn)
        
        # Delete Pipeline button
        self.delete_btn = QPushButton("🗑 Delete Pipeline")
        self.delete_btn.setFixedHeight(45)
        self.delete_btn.setMinimumWidth(170)
        self.delete_btn.setStyleSheet(CrowEyeStyles.RED_BUTTON + """
            QPushButton {
                font-size: 13px;
                padding: 12px 24px;
            }
        """)
        self.delete_btn.clicked.connect(self.delete_pipeline)
        self.delete_btn.setEnabled(False)
        layout.addWidget(self.delete_btn)
        
        layout.addStretch()
        
        return layout
    
    def load_pipelines(self):
        """Load all pipelines from the case directory."""
        self.pipeline_table.setRowCount(0)
        
        if not self.pipelines_dir.exists():
            return
        
        # Get default pipeline
        default_pipeline = self._get_default_pipeline()
        
        # Load all pipeline JSON files
        pipeline_files = sorted(self.pipelines_dir.glob("*.json"))
        
        for pipeline_file in pipeline_files:
            try:
                with open(pipeline_file, 'r') as f:
                    pipeline_data = json.load(f)
                
                self._add_pipeline_to_table(pipeline_data, pipeline_file, default_pipeline)
                
            except Exception as e:
                print(f"Error loading pipeline {pipeline_file}: {e}")
                continue
    
    def _add_pipeline_to_table(self, pipeline_data: dict, pipeline_file: Path, default_pipeline: str):
        """Add a pipeline to the table."""
        row = self.pipeline_table.rowCount()
        self.pipeline_table.insertRow(row)
        
        # Pipeline Name
        name_item = QTableWidgetItem(pipeline_data.get('pipeline_name', 'Unknown'))
        name_item.setData(Qt.UserRole, str(pipeline_file))  # Store file path
        name_item.setData(Qt.UserRole + 1, pipeline_data)  # Store pipeline data
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
        
        # Default indicator
        is_default = pipeline_data.get('config_name', '') == default_pipeline
        default_item = QTableWidgetItem("⭐ Default" if is_default else "")
        default_item.setTextAlignment(Qt.AlignCenter)
        if is_default:
            default_item.setForeground(Qt.yellow)
            font = default_item.font()
            font.setBold(True)
            default_item.setFont(font)
        self.pipeline_table.setItem(row, 4, default_item)
    
    def _on_pipeline_selection_changed(self):
        """Handle pipeline selection change."""
        has_selection = len(self.pipeline_table.selectedItems()) > 0
        
        self.edit_btn.setEnabled(has_selection)
        self.duplicate_btn.setEnabled(has_selection)
        self.set_default_btn.setEnabled(has_selection)
        self.delete_btn.setEnabled(has_selection)
        
        if has_selection:
            self._update_pipeline_details()
        else:
            self.details_text.clear()
    
    def _on_pipeline_double_clicked(self, item):
        """Handle double-click on pipeline (opens for editing)."""
        self.edit_pipeline()
    
    def _update_pipeline_details(self):
        """Update the pipeline details panel with selected pipeline info."""
        selected_rows = self.pipeline_table.selectionModel().selectedRows()
        if not selected_rows:
            self.details_text.clear()
            return
        
        row = selected_rows[0].row()
        name_item = self.pipeline_table.item(row, 0)
        pipeline_data = name_item.data(Qt.UserRole + 1)
        
        if not pipeline_data:
            self.details_text.clear()
            return
        
        # Build details text
        details = []
        details.append(f"<h3 style='color: #00FFFF;'>{pipeline_data.get('pipeline_name', 'Unknown')}</h3>")
        details.append(f"<p><b>Description:</b> {pipeline_data.get('description', 'No description')}</p>")
        details.append(f"<p><b>Case:</b> {pipeline_data.get('case_name', 'N/A')}</p>")
        details.append(f"<p><b>Case ID:</b> {pipeline_data.get('case_id', 'N/A')}</p>")
        details.append(f"<p><b>Investigator:</b> {pipeline_data.get('investigator', 'N/A')}</p>")
        
        # Wings
        wings = pipeline_data.get('wing_configs', [])
        if wings:
            details.append(f"<p><b>Wings ({len(wings)}):</b></p>")
            details.append("<ul>")
            for wing in wings[:5]:  # Show first 5
                wing_name = wing.get('wing_name', 'Unknown')
                details.append(f"<li>{wing_name}</li>")
            if len(wings) > 5:
                details.append(f"<li><i>... and {len(wings) - 5} more</i></li>")
            details.append("</ul>")
        
        # Feathers
        feathers = pipeline_data.get('feather_configs', [])
        if feathers:
            details.append(f"<p><b>Feathers ({len(feathers)}):</b></p>")
            details.append("<ul>")
            for feather in feathers[:5]:  # Show first 5
                feather_name = feather.get('feather_name', 'Unknown')
                artifact_type = feather.get('artifact_type', 'Unknown')
                details.append(f"<li>{feather_name} ({artifact_type})</li>")
            if len(feathers) > 5:
                details.append(f"<li><i>... and {len(feathers) - 5} more</i></li>")
            details.append("</ul>")
        
        # Metadata
        details.append(f"<p><b>Created:</b> {self._format_datetime(pipeline_data.get('created_date', ''))}</p>")
        details.append(f"<p><b>Last Modified:</b> {self._format_datetime(pipeline_data.get('last_modified', ''))}</p>")
        if pipeline_data.get('last_executed'):
            details.append(f"<p><b>Last Executed:</b> {self._format_datetime(pipeline_data.get('last_executed', ''))}</p>")
        
        self.details_text.setHtml("".join(details))
    
    def create_pipeline(self):
        """Create a new pipeline using Pipeline Builder."""
        try:
            from .pipeline_builder import PipelineBuilderWidget
            from ..config import ConfigManager
            
            # Create Pipeline Builder dialog
            from PyQt5.QtWidgets import QDialog, QVBoxLayout, QDialogButtonBox
            
            dialog = QDialog(self)
            dialog.setWindowTitle("Create New Pipeline")
            dialog.setMinimumSize(1000, 700)
            dialog.setModal(True)
            
            layout = QVBoxLayout(dialog)
            
            # Create Pipeline Builder widget
            builder = PipelineBuilderWidget()
            builder.set_case_directory(str(self.case_directory))
            
            # Set up config manager
            correlation_dir = self.case_directory / "Correlation"
            config_manager = ConfigManager(str(correlation_dir))
            builder.set_config_manager(config_manager)
            
            layout.addWidget(builder)
            
            # Add dialog buttons
            button_box = QDialogButtonBox(
                QDialogButtonBox.Save | QDialogButtonBox.Cancel
            )
            button_box.accepted.connect(lambda: self._save_pipeline(builder, dialog))
            button_box.rejected.connect(dialog.reject)
            layout.addWidget(button_box)
            
            # Apply styling
            dialog.setStyleSheet("""
                QDialog {
                    background-color: #0F172A;
                }
            """)
            
            if dialog.exec_() == QDialog.Accepted:
                self.load_pipelines()
                self.pipelines_changed.emit()
                
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to open Pipeline Builder:\n{str(e)}"
            )
    
    def edit_pipeline(self):
        """Edit the selected pipeline using Pipeline Builder."""
        selected_rows = self.pipeline_table.selectionModel().selectedRows()
        if not selected_rows:
            return
        
        row = selected_rows[0].row()
        name_item = self.pipeline_table.item(row, 0)
        pipeline_file = Path(name_item.data(Qt.UserRole))
        
        try:
            from .pipeline_builder import PipelineBuilderWidget
            from ..config import ConfigManager, PipelineConfig
            from PyQt5.QtWidgets import QDialog, QVBoxLayout, QDialogButtonBox
            
            # Load pipeline
            pipeline_config = PipelineConfig.load_from_file(str(pipeline_file))
            
            # Create Pipeline Builder dialog
            dialog = QDialog(self)
            dialog.setWindowTitle(f"Edit Pipeline: {pipeline_config.pipeline_name}")
            dialog.setMinimumSize(1000, 700)
            dialog.setModal(True)
            
            layout = QVBoxLayout(dialog)
            
            # Create Pipeline Builder widget
            builder = PipelineBuilderWidget()
            builder.set_case_directory(str(self.case_directory))
            
            # Set up config manager
            correlation_dir = self.case_directory / "Correlation"
            config_manager = ConfigManager(str(correlation_dir))
            builder.set_config_manager(config_manager)
            
            # Load pipeline into builder
            builder.load_pipeline(pipeline_config)
            
            layout.addWidget(builder)
            
            # Add dialog buttons
            button_box = QDialogButtonBox(
                QDialogButtonBox.Save | QDialogButtonBox.Cancel
            )
            button_box.accepted.connect(lambda: self._save_pipeline(builder, dialog))
            button_box.rejected.connect(dialog.reject)
            layout.addWidget(button_box)
            
            # Apply styling
            dialog.setStyleSheet("""
                QDialog {
                    background-color: #0F172A;
                }
            """)
            
            if dialog.exec_() == QDialog.Accepted:
                self.load_pipelines()
                self.pipelines_changed.emit()
                
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to edit pipeline:\n{str(e)}"
            )
    
    def _save_pipeline(self, builder, dialog):
        """Save pipeline from builder."""
        try:
            # Validate pipeline
            is_valid, errors = builder.validate_pipeline()
            if not is_valid:
                QMessageBox.warning(
                    dialog,
                    "Validation Error",
                    "Pipeline validation failed:\n" + "\n".join(errors)
                )
                return
            
            # Get pipeline config
            pipeline_config = builder.get_pipeline_config()
            if not pipeline_config:
                QMessageBox.warning(
                    dialog,
                    "Error",
                    "Failed to get pipeline configuration"
                )
                return
            
            # Save to file
            pipeline_file = self.pipelines_dir / f"{pipeline_config.config_name}.json"
            pipeline_config.save_to_file(str(pipeline_file))
            
            dialog.accept()
            
        except Exception as e:
            QMessageBox.critical(
                dialog,
                "Save Error",
                f"Failed to save pipeline:\n{str(e)}"
            )
    
    def delete_pipeline(self):
        """Delete the selected pipeline."""
        selected_rows = self.pipeline_table.selectionModel().selectedRows()
        if not selected_rows:
            return
        
        row = selected_rows[0].row()
        name_item = self.pipeline_table.item(row, 0)
        pipeline_file = Path(name_item.data(Qt.UserRole))
        pipeline_data = name_item.data(Qt.UserRole + 1)
        pipeline_name = pipeline_data.get('pipeline_name', 'Unknown')
        
        # Confirm deletion
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Delete Pipeline")
        msg_box.setText(
            f"Delete pipeline '{pipeline_name}'?\n\n"
            "This action cannot be undone."
        )
        msg_box.setIcon(QMessageBox.Warning)
        msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg_box.setDefaultButton(QMessageBox.No)
        msg_box.setStyleSheet(CrowEyeStyles.MESSAGE_BOX_STYLE)
        
        if msg_box.exec_() == QMessageBox.Yes:
            try:
                # Delete file
                pipeline_file.unlink()
                
                # Reload table
                self.load_pipelines()
                self.pipelines_changed.emit()
                
                QMessageBox.information(
                    self,
                    "Success",
                    f"Pipeline '{pipeline_name}' deleted successfully."
                )
                
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Error",
                    f"Failed to delete pipeline:\n{str(e)}"
                )
    
    def duplicate_pipeline(self):
        """Duplicate the selected pipeline."""
        selected_rows = self.pipeline_table.selectionModel().selectedRows()
        if not selected_rows:
            return
        
        row = selected_rows[0].row()
        name_item = self.pipeline_table.item(row, 0)
        pipeline_file = Path(name_item.data(Qt.UserRole))
        pipeline_data = name_item.data(Qt.UserRole + 1)
        
        try:
            # Create copy with modified name
            new_pipeline_data = pipeline_data.copy()
            original_name = new_pipeline_data.get('pipeline_name', 'Pipeline')
            new_pipeline_data['pipeline_name'] = f"{original_name}_Copy"
            new_pipeline_data['config_name'] = f"{new_pipeline_data.get('config_name', 'pipeline')}_copy"
            new_pipeline_data['created_date'] = datetime.now().isoformat()
            new_pipeline_data['last_modified'] = datetime.now().isoformat()
            new_pipeline_data['last_executed'] = None
            
            # Find unique name if copy already exists
            counter = 1
            new_file = self.pipelines_dir / f"{new_pipeline_data['config_name']}.json"
            while new_file.exists():
                counter += 1
                new_pipeline_data['pipeline_name'] = f"{original_name}_Copy{counter}"
                new_pipeline_data['config_name'] = f"{pipeline_data.get('config_name', 'pipeline')}_copy{counter}"
                new_file = self.pipelines_dir / f"{new_pipeline_data['config_name']}.json"
            
            # Save duplicate
            with open(new_file, 'w') as f:
                json.dump(new_pipeline_data, f, indent=2)
            
            # Reload table
            self.load_pipelines()
            self.pipelines_changed.emit()
            
            QMessageBox.information(
                self,
                "Success",
                f"Pipeline duplicated as '{new_pipeline_data['pipeline_name']}'"
            )
            
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to duplicate pipeline:\n{str(e)}"
            )
    
    def set_default_pipeline(self):
        """Set the selected pipeline as the default."""
        selected_rows = self.pipeline_table.selectionModel().selectedRows()
        if not selected_rows:
            return
        
        row = selected_rows[0].row()
        name_item = self.pipeline_table.item(row, 0)
        pipeline_data = name_item.data(Qt.UserRole + 1)
        config_name = pipeline_data.get('config_name', '')
        pipeline_name = pipeline_data.get('pipeline_name', 'Unknown')
        
        try:
            # Load or create case config
            case_config = {}
            if self.config_file.exists():
                with open(self.config_file, 'r') as f:
                    case_config = json.load(f)
            
            # Update default pipeline
            case_config['default_pipeline'] = config_name
            case_config['correlation_settings'] = case_config.get('correlation_settings', {})
            case_config['correlation_settings']['auto_load_default_pipeline'] = True
            
            # Save config
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, 'w') as f:
                json.dump(case_config, f, indent=2)
            
            # Reload table to update default indicator
            self.load_pipelines()
            self.pipelines_changed.emit()
            
            QMessageBox.information(
                self,
                "Success",
                f"'{pipeline_name}' set as default pipeline.\n\n"
                "This pipeline will be automatically loaded when opening the Correlation Engine."
            )
            
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to set default pipeline:\n{str(e)}"
            )
    
    def _get_default_pipeline(self) -> str:
        """Get the default pipeline config name."""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r') as f:
                    case_config = json.load(f)
                return case_config.get('default_pipeline', '')
        except:
            pass
        return ''
    
    def _format_datetime(self, dt_str: str) -> str:
        """Format datetime string for display."""
        if not dt_str:
            return 'N/A'
        
        try:
            dt = datetime.fromisoformat(dt_str)
            return dt.strftime("%Y-%m-%d %H:%M")
        except:
            return dt_str
