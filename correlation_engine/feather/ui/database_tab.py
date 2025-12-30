"""
Database Import Tab
Interface for importing data from existing databases.
"""

import sqlite3
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
    QLabel, QFileDialog, QTableWidget, QTableWidgetItem,
    QHeaderView, QCheckBox, QLineEdit, QMessageBox, QComboBox
)
from PyQt5.QtCore import Qt, pyqtSignal


class DatabaseTab(QWidget):
    """Tab for database import functionality."""
    
    # Signal emitted when database is selected
    database_selected = pyqtSignal(str)  # Emits database path
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.db_path = ""
        self.db_connection = None
        self.tables = []
        self.selected_table = None
        self.columns_data = []
        self.init_ui()
    
    def init_ui(self):
        """Initialize the database import interface."""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        # Database selection section
        db_select_layout = QHBoxLayout()
        db_label = QLabel("Database File:")
        self.db_path_input = QLineEdit()
        self.db_path_input.setPlaceholderText("Select database file...")
        self.db_path_input.setReadOnly(True)
        
        self.db_browse_btn = QPushButton("Browse Database")
        self.db_browse_btn.clicked.connect(self.select_database)
        
        db_select_layout.addWidget(db_label)
        db_select_layout.addWidget(self.db_path_input, 3)
        db_select_layout.addWidget(self.db_browse_btn)
        layout.addLayout(db_select_layout)
        
        # Table selection
        table_layout = QHBoxLayout()
        table_label = QLabel("Select Table:")
        self.table_combo = QComboBox()
        self.table_combo.currentTextChanged.connect(self.on_table_selected)
        
        table_layout.addWidget(table_label)
        table_layout.addWidget(self.table_combo, 2)
        table_layout.addStretch()
        layout.addLayout(table_layout)
        
        # Column mapping table
        mapping_label = QLabel("Column Mapping:")
        layout.addWidget(mapping_label)
        
        self.column_table = QTableWidget()
        self.column_table.setColumnCount(4)
        self.column_table.setHorizontalHeaderLabels([
            "Include", "Original Column", "Feather Column Name", "Data Type"
        ])
        self.column_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.column_table)
        
        # Preview section
        preview_label = QLabel("Data Preview:")
        layout.addWidget(preview_label)
        
        self.preview_table = QTableWidget()
        self.preview_table.setMaximumHeight(200)
        layout.addWidget(self.preview_table)
        
        # Import button
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        self.import_btn = QPushButton("Import to Feather")
        self.import_btn.setEnabled(False)
        self.import_btn.clicked.connect(self.import_data)
        button_layout.addWidget(self.import_btn)
        layout.addLayout(button_layout)
    
    def select_database(self):
        """Open file dialog to select database."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Database File",
            "",
            "SQLite Database (*.db *.sqlite *.sqlite3);;All Files (*)"
        )
        
        if file_path:
            self.db_path = file_path
            self.db_path_input.setText(file_path)
            self.load_database_tables()
            
            # Emit signal for artifact detection
            self.database_selected.emit(file_path)
    
    def load_database_tables(self):
        """Load tables from the selected database."""
        try:
            # Close existing connection if any
            if self.db_connection:
                try:
                    self.db_connection.close()
                except:
                    pass
                self.db_connection = None
            
            # Open new connection
            self.db_connection = sqlite3.connect(self.db_path)
            cursor = self.db_connection.cursor()
            
            # Get all tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            self.tables = [row[0] for row in cursor.fetchall()]
            
            self.table_combo.clear()
            self.table_combo.addItems(self.tables)
            
        except Exception as e:
            QMessageBox.critical(self, "Database Error", f"Failed to load database: {str(e)}")
    
    def on_table_selected(self, table_name):
        """Handle table selection."""
        if not table_name or not self.db_connection:
            return
        
        # Reset previous table data
        self.selected_table = table_name
        self.columns_data = []
        self.column_table.setRowCount(0)
        self.preview_table.setRowCount(0)
        self.preview_table.setColumnCount(0)
        
        # Load new table data
        self.load_table_columns()
        self.load_data_preview()
    
    def load_table_columns(self):
        """Load columns from selected table."""
        try:
            cursor = self.db_connection.cursor()
            cursor.execute(f"PRAGMA table_info({self.selected_table})")
            columns_info = cursor.fetchall()
            
            self.columns_data = []
            self.column_table.setRowCount(0)
            
            # Check if table has ID column
            has_id = any(col[1].lower() in ['id', 'rowid', '_id'] for col in columns_info)
            
            for col_info in columns_info:
                col_name = col_info[1]
                col_type = col_info[2]
                
                self.columns_data.append({
                    'original': col_name,
                    'feather': col_name,
                    'type': col_type,
                    'include': True
                })
            
            # Add row count ID if no ID column exists
            if not has_id:
                self.columns_data.insert(0, {
                    'original': '[ROW_COUNT]',
                    'feather': 'id',
                    'type': 'INTEGER',
                    'include': True
                })
            
            self.populate_column_table()
            self.import_btn.setEnabled(True)
            
        except Exception as e:
            QMessageBox.critical(self, "Column Error", f"Failed to load columns: {str(e)}")
    
    def populate_column_table(self):
        """Populate the column mapping table."""
        self.column_table.setRowCount(len(self.columns_data))
        
        for row, col_data in enumerate(self.columns_data):
            # Include checkbox - add directly without container
            checkbox = QCheckBox()
            checkbox.setChecked(col_data['include'])
            checkbox.stateChanged.connect(lambda state, r=row: self.on_include_changed(r, state))
            
            # Create a simple container that matches the cell
            from PyQt5.QtGui import QPalette, QColor
            checkbox_widget = QWidget()
            
            # Set palette to match table background
            palette = checkbox_widget.palette()
            if row % 2 == 0:
                palette.setColor(QPalette.Window, QColor("#162032"))
            else:
                palette.setColor(QPalette.Window, QColor("#0B1220"))
            checkbox_widget.setPalette(palette)
            checkbox_widget.setAutoFillBackground(True)
            
            checkbox_layout = QHBoxLayout(checkbox_widget)
            checkbox_layout.addWidget(checkbox)
            checkbox_layout.setAlignment(Qt.AlignCenter)
            checkbox_layout.setContentsMargins(0, 0, 0, 0)
            checkbox_layout.setSpacing(0)
            self.column_table.setCellWidget(row, 0, checkbox_widget)
            
            # Original column name
            orig_item = QTableWidgetItem(col_data['original'])
            orig_item.setFlags(orig_item.flags() & ~Qt.ItemIsEditable)
            self.column_table.setItem(row, 1, orig_item)
            
            # Feather column name (editable)
            feather_item = QTableWidgetItem(col_data['feather'])
            self.column_table.setItem(row, 2, feather_item)
            
            # Data type
            type_item = QTableWidgetItem(col_data['type'])
            type_item.setFlags(type_item.flags() & ~Qt.ItemIsEditable)
            self.column_table.setItem(row, 3, type_item)
    
    def on_include_changed(self, row, state):
        """Handle include checkbox state change."""
        self.columns_data[row]['include'] = (state == Qt.Checked)
    
    def load_data_preview(self):
        """Load preview of table data."""
        try:
            cursor = self.db_connection.cursor()
            cursor.execute(f"SELECT * FROM {self.selected_table} LIMIT 5")
            rows = cursor.fetchall()
            
            # Get column names
            column_names = [description[0] for description in cursor.description]
            
            self.preview_table.setColumnCount(len(column_names))
            self.preview_table.setHorizontalHeaderLabels(column_names)
            self.preview_table.setRowCount(len(rows))
            
            for row_idx, row_data in enumerate(rows):
                for col_idx, value in enumerate(row_data):
                    item = QTableWidgetItem(str(value))
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    self.preview_table.setItem(row_idx, col_idx, item)
            
        except Exception as e:
            QMessageBox.warning(self, "Preview Error", f"Failed to load preview: {str(e)}")
    
    def import_data(self):
        """Import data to feather database."""
        # Update feather column names from table
        for row in range(self.column_table.rowCount()):
            feather_item = self.column_table.item(row, 2)
            if feather_item:
                self.columns_data[row]['feather'] = feather_item.text()
        
        # Get selected columns
        selected_columns = [col for col in self.columns_data if col['include']]
        
        if not selected_columns:
            QMessageBox.warning(self, "No Columns", "Please select at least one column to import.")
            return
        
        # Emit signal or call parent method to handle import
        QMessageBox.information(
            self,
            "Import Ready",
            f"Ready to import {len(selected_columns)} columns from {self.selected_table}"
        )
    
    def get_import_config(self):
        """Get the current import configuration."""
        # Update feather column names
        for row in range(self.column_table.rowCount()):
            feather_item = self.column_table.item(row, 2)
            if feather_item:
                self.columns_data[row]['feather'] = feather_item.text()
        
        return {
            'source_type': 'database',
            'source_path': self.db_path,
            'table_name': self.selected_table,
            'columns': [col for col in self.columns_data if col['include']],
            'connection': self.db_connection
        }
