"""
Database Results Loader Dialog
Allows users to browse and load correlation results from multiple databases.
"""

import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QFileDialog, QMessageBox,
    QHeaderView, QCheckBox, QGroupBox, QComboBox, QLineEdit,
    QSplitter, QTextEdit, QWidget
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont

from ..engine.database_persistence import ResultsDatabase


class DatabaseResultsLoaderDialog(QDialog):
    """Dialog for browsing and loading correlation results from databases."""
    
    results_selected = pyqtSignal(list)  # List of (database_path, execution_id, engine_type) tuples
    
    def __init__(self, parent=None, default_db_path: str = None):
        super().__init__(parent)
        self.setWindowTitle("Load Correlation Results from Database")
        self.resize(1000, 700)
        
        self.current_db_path = default_db_path
        self.executions_data = []
        
        self._init_ui()
        
        if default_db_path:
            db_path_obj = Path(default_db_path)
            if db_path_obj.exists():
                self._load_database(default_db_path)
    
    def _init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout(self)
        
        # Database selection section
        db_group = QGroupBox("Database Selection")
        db_layout = QVBoxLayout()
        
        db_path_layout = QHBoxLayout()
        db_path_layout.addWidget(QLabel("Current Database:"))
        self.db_path_edit = QLineEdit()
        self.db_path_edit.setReadOnly(True)
        db_path_layout.addWidget(self.db_path_edit, 1)
        
        self.browse_btn = QPushButton("Browse Current Case...")
        self.browse_btn.clicked.connect(self._browse_database)
        db_path_layout.addWidget(self.browse_btn)
        
        self.browse_other_btn = QPushButton("Load Other Database...")
        self.browse_other_btn.clicked.connect(self._browse_other_database)
        self.browse_other_btn.setStyleSheet("""
            QPushButton {
                background-color: #3B82F6;
                color: white;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2563EB;
            }
        """)
        db_path_layout.addWidget(self.browse_other_btn)
        
        db_layout.addLayout(db_path_layout)
        db_group.setLayout(db_layout)
        layout.addWidget(db_group)
        
        # Executions table
        executions_group = QGroupBox("Available Executions (Select one or more)")
        executions_layout = QVBoxLayout()
        
        self.executions_table = QTableWidget()
        self.executions_table.setColumnCount(8)
        self.executions_table.setHorizontalHeaderLabels([
            "Select", "Execution ID", "Pipeline", "Engine Type", "Case Name", 
            "Investigator", "Execution Time", "Results Count"
        ])
        self.executions_table.horizontalHeader().setStretchLastSection(False)
        self.executions_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.executions_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.executions_table.setSelectionMode(QTableWidget.MultiSelection)
        self.executions_table.itemSelectionChanged.connect(self._on_execution_selected)
        self.executions_table.doubleClicked.connect(self._load_selected)
        
        executions_layout.addWidget(self.executions_table)
        
        # Selection buttons
        selection_btn_layout = QHBoxLayout()
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(self._select_all_executions)
        selection_btn_layout.addWidget(select_all_btn)
        
        deselect_all_btn = QPushButton("Deselect All")
        deselect_all_btn.clicked.connect(self._deselect_all_executions)
        selection_btn_layout.addWidget(deselect_all_btn)
        
        selection_btn_layout.addStretch()
        
        self.selection_count_label = QLabel("0 selected")
        self.selection_count_label.setStyleSheet("font-weight: bold; color: #00d9ff;")
        selection_btn_layout.addWidget(self.selection_count_label)
        
        executions_layout.addLayout(selection_btn_layout)
        
        executions_group.setLayout(executions_layout)
        layout.addWidget(executions_group, 1)
        
        # Details section
        details_group = QGroupBox("Execution Details")
        details_layout = QVBoxLayout()
        
        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setMaximumHeight(150)
        details_layout.addWidget(self.details_text)
        
        details_group.setLayout(details_layout)
        layout.addWidget(details_group)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.load_btn = QPushButton("Load Selected")
        self.load_btn.clicked.connect(self._load_selected)
        self.load_btn.setEnabled(False)
        self.load_btn.setStyleSheet("""
            QPushButton {
                background-color: #10B981;
                color: white;
                font-weight: bold;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background-color: #059669;
            }
            QPushButton:disabled {
                background-color: #4B5563;
                color: #9CA3AF;
            }
        """)
        button_layout.addWidget(self.load_btn)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout)
    
    def _browse_database(self):
        """Browse for a database file in current case."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Correlation Results Database",
            str(Path(self.current_db_path).parent) if self.current_db_path else "",
            "SQLite Database (*.db);;All Files (*.*)"
        )
        
        if file_path:
            self._load_database(file_path)
    
    def _browse_other_database(self):
        """Browse for a database file from any location."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Correlation Results Database from Other Case",
            "",
            "SQLite Database (*.db);;All Files (*.*)"
        )
        
        if file_path:
            self._load_database(file_path)
    
    def _load_database(self, db_path: str):
        """Load executions from the specified database."""
        try:
            db_path_obj = Path(db_path)
            if not db_path_obj.exists():
                QMessageBox.warning(self, "Database Not Found", 
                                  f"Database file not found:\n{db_path}")
                return
            
            self.current_db_path = db_path
            self.db_path_edit.setText(db_path)
            
            # Load executions from database
            with ResultsDatabase(db_path) as db:
                conn = db.conn
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT 
                        e.execution_id,
                        e.pipeline_name,
                        e.engine_type,
                        e.case_name,
                        e.investigator,
                        e.execution_time,
                        COUNT(r.result_id) as result_count
                    FROM executions e
                    LEFT JOIN results r ON e.execution_id = r.execution_id
                    GROUP BY e.execution_id
                    ORDER BY e.execution_time DESC
                """)
                
                rows = cursor.fetchall()
                
                self.executions_data = []
                for row in rows:
                    execution_data = {
                        'execution_id': row[0],
                        'pipeline_name': row[1],
                        'engine_type': row[2],
                        'case_name': row[3],
                        'investigator': row[4],
                        'execution_time': row[5],
                        'result_count': row[6]
                    }
                    self.executions_data.append(execution_data)
            
            self._populate_executions_table()
            
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            QMessageBox.critical(self, "Database Error",
                               f"Failed to load database:\n{str(e)}\n\nDetails:\n{error_details}")
    
    def _populate_executions_table(self):
        """Populate the executions table with data."""
        self.executions_table.setRowCount(len(self.executions_data))
        
        for row_idx, execution in enumerate(self.executions_data):
            # Checkbox column
            checkbox = QCheckBox()
            checkbox.setChecked(False)
            checkbox.stateChanged.connect(self._update_selection_count)
            checkbox_widget = QWidget()
            checkbox_layout = QHBoxLayout(checkbox_widget)
            checkbox_layout.addWidget(checkbox)
            checkbox_layout.setAlignment(Qt.AlignCenter)
            checkbox_layout.setContentsMargins(0, 0, 0, 0)
            self.executions_table.setCellWidget(row_idx, 0, checkbox_widget)
            
            self.executions_table.setItem(row_idx, 1, 
                QTableWidgetItem(str(execution['execution_id'])))
            self.executions_table.setItem(row_idx, 2, 
                QTableWidgetItem(execution['pipeline_name'] or ""))
            
            # Engine type with color coding
            engine_item = QTableWidgetItem(execution['engine_type'] or "")
            if execution['engine_type'] == 'identity_based':
                engine_item.setForeground(Qt.green)
            elif execution['engine_type'] == 'time_window_scanning':
                engine_item.setForeground(Qt.cyan)
            self.executions_table.setItem(row_idx, 3, engine_item)
            
            self.executions_table.setItem(row_idx, 4, 
                QTableWidgetItem(execution['case_name'] or ""))
            self.executions_table.setItem(row_idx, 5, 
                QTableWidgetItem(execution['investigator'] or ""))
            self.executions_table.setItem(row_idx, 6, 
                QTableWidgetItem(execution['execution_time'] or ""))
            self.executions_table.setItem(row_idx, 7, 
                QTableWidgetItem(str(execution['result_count'])))
        
        self.executions_table.resizeColumnsToContents()
        self._update_selection_count()
    
    def _on_execution_selected(self):
        """Handle execution selection."""
        selected_rows = self.executions_table.selectedItems()
        if not selected_rows:
            self.load_btn.setEnabled(False)
            self.details_text.clear()
            return
        
        row_idx = self.executions_table.currentRow()
        if row_idx < 0 or row_idx >= len(self.executions_data):
            return
        
        execution = self.executions_data[row_idx]
        
        # Check checkbox when row is selected
        checkbox_widget = self.executions_table.cellWidget(row_idx, 0)
        if checkbox_widget:
            checkbox = checkbox_widget.findChild(QCheckBox)
            if checkbox and not checkbox.isChecked():
                checkbox.setChecked(True)
        
        self.load_btn.setEnabled(self._get_selected_count() > 0)
        
        # Display execution details
        details = []
        details.append(f"<b>Execution ID:</b> {execution['execution_id']}")
        details.append(f"<b>Pipeline:</b> {execution['pipeline_name']}")
        details.append(f"<b>Engine Type:</b> {execution['engine_type']}")
        details.append(f"<b>Case Name:</b> {execution['case_name'] or 'N/A'}")
        details.append(f"<b>Investigator:</b> {execution['investigator'] or 'N/A'}")
        details.append(f"<b>Execution Time:</b> {execution['execution_time']}")
        details.append(f"<b>Results Count:</b> {execution['result_count']}")
        
        # Get additional statistics
        try:
            with ResultsDatabase(self.current_db_path) as db:
                conn = db.conn
                cursor = conn.cursor()
                
                # Get total matches count
                cursor.execute("""
                    SELECT COUNT(*) 
                    FROM matches m
                    JOIN results r ON m.result_id = r.result_id
                    WHERE r.execution_id = ?
                """, (execution['execution_id'],))
                match_count = cursor.fetchone()[0]
                details.append(f"<b>Total Matches:</b> {match_count:,}")
                
        except Exception as e:
            details.append(f"<i>Could not load additional statistics: {str(e)}</i>")
        
        self.details_text.setHtml("<br>".join(details))
    
    def _select_all_executions(self):
        """Select all executions."""
        for row_idx in range(self.executions_table.rowCount()):
            checkbox_widget = self.executions_table.cellWidget(row_idx, 0)
            if checkbox_widget:
                checkbox = checkbox_widget.findChild(QCheckBox)
                if checkbox:
                    checkbox.setChecked(True)
    
    def _deselect_all_executions(self):
        """Deselect all executions."""
        for row_idx in range(self.executions_table.rowCount()):
            checkbox_widget = self.executions_table.cellWidget(row_idx, 0)
            if checkbox_widget:
                checkbox = checkbox_widget.findChild(QCheckBox)
                if checkbox:
                    checkbox.setChecked(False)
    
    def _get_selected_count(self) -> int:
        """Get count of selected executions."""
        count = 0
        for row_idx in range(self.executions_table.rowCount()):
            checkbox_widget = self.executions_table.cellWidget(row_idx, 0)
            if checkbox_widget:
                checkbox = checkbox_widget.findChild(QCheckBox)
                if checkbox and checkbox.isChecked():
                    count += 1
        return count
    
    def _update_selection_count(self):
        """Update the selection count label."""
        count = self._get_selected_count()
        self.selection_count_label.setText(f"{count} selected")
        self.load_btn.setEnabled(count > 0)
    
    def _load_selected(self):
        """Load the selected executions."""
        selected_executions = []
        
        for row_idx in range(self.executions_table.rowCount()):
            checkbox_widget = self.executions_table.cellWidget(row_idx, 0)
            if checkbox_widget:
                checkbox = checkbox_widget.findChild(QCheckBox)
                if checkbox and checkbox.isChecked():
                    execution = self.executions_data[row_idx]
                    selected_executions.append((
                        self.current_db_path,
                        execution['execution_id'],
                        execution['engine_type']
                    ))
        
        if not selected_executions:
            QMessageBox.warning(self, "No Selection", "Please select at least one execution to load.")
            return
        
        # Emit signal with list of selected executions
        self.results_selected.emit(selected_executions)
        self.accept()
    
    def get_selected_executions(self) -> List[tuple]:
        """Get the selected executions as list of (database_path, execution_id, engine_type) tuples."""
        selected_executions = []
        
        for row_idx in range(self.executions_table.rowCount()):
            checkbox_widget = self.executions_table.cellWidget(row_idx, 0)
            if checkbox_widget:
                checkbox = checkbox_widget.findChild(QCheckBox)
                if checkbox and checkbox.isChecked():
                    execution = self.executions_data[row_idx]
                    selected_executions.append((
                        self.current_db_path,
                        execution['execution_id'],
                        execution['engine_type']
                    ))
        
        return selected_executions
