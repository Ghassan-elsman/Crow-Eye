"""
CSV Import Tab
Interface for importing data from CSV files.
"""

import csv
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QFileDialog, QTableWidget, QTableWidgetItem,
    QHeaderView, QCheckBox, QLineEdit, QMessageBox, QComboBox
)
from PyQt5.QtCore import Qt


class CSVTab(QWidget):
    """Tab for CSV import functionality."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.csv_path = ""
        self.csv_data = []
        self.headers = []
        self.columns_data = []
        self.delimiter = ','
        self.init_ui()
    
    def init_ui(self):
        """Initialize the CSV import interface."""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        # CSV file selection section
        file_select_layout = QHBoxLayout()
        file_label = QLabel("CSV File:")
        self.csv_path_input = QLineEdit()
        self.csv_path_input.setPlaceholderText("Select CSV file...")
        self.csv_path_input.setReadOnly(True)
        
        self.csv_browse_btn = QPushButton("Browse CSV")
        self.csv_browse_btn.clicked.connect(self.select_csv_file)
        
        file_select_layout.addWidget(file_label)
        file_select_layout.addWidget(self.csv_path_input, 3)
        file_select_layout.addWidget(self.csv_browse_btn)
        layout.addLayout(file_select_layout)
        
        # Delimiter selection
        delimiter_layout = QHBoxLayout()
        delimiter_label = QLabel("Delimiter:")
        self.delimiter_combo = QComboBox()
        self.delimiter_combo.addItems(["Comma (,)", "Semicolon (;)", "Tab", "Pipe (|)"])
        self.delimiter_combo.currentTextChanged.connect(self.on_delimiter_changed)
        
        delimiter_layout.addWidget(delimiter_label)
        delimiter_layout.addWidget(self.delimiter_combo)
        delimiter_layout.addStretch()
        layout.addLayout(delimiter_layout)
        
        # Column mapping table
        mapping_label = QLabel("Column Mapping:")
        layout.addWidget(mapping_label)
        
        self.column_table = QTableWidget()
        self.column_table.setColumnCount(3)
        self.column_table.setHorizontalHeaderLabels([
            "Include", "Original Header", "Feather Column Name"
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
    
    def select_csv_file(self):
        """Open file dialog to select CSV file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select CSV File",
            "",
            "CSV Files (*.csv);;Text Files (*.txt);;All Files (*)"
        )
        
        if file_path:
            # Reset previous data
            self.csv_data = []
            self.headers = []
            self.columns_data = []
            self.column_table.setRowCount(0)
            self.preview_table.setRowCount(0)
            self.preview_table.setColumnCount(0)
            
            self.csv_path = file_path
            self.csv_path_input.setText(file_path)
            self.load_csv_file()
    
    def on_delimiter_changed(self, text):
        """Handle delimiter selection change."""
        delimiter_map = {
            "Comma (,)": ',',
            "Semicolon (;)": ';',
            "Tab": '\t',
            "Pipe (|)": '|'
        }
        self.delimiter = delimiter_map.get(text, ',')
        
        if self.csv_path:
            # Reset previous data when delimiter changes
            self.csv_data = []
            self.headers = []
            self.columns_data = []
            self.column_table.setRowCount(0)
            self.preview_table.setRowCount(0)
            self.preview_table.setColumnCount(0)
            
            self.load_csv_file()
    
    def load_csv_file(self):
        """Load and parse CSV file."""
        try:
            with open(self.csv_path, 'r', encoding='utf-8') as f:
                # Detect if file has headers
                sample = f.read(1024)
                f.seek(0)
                sniffer = csv.Sniffer()
                has_header = sniffer.has_header(sample)
                
                reader = csv.reader(f, delimiter=self.delimiter)
                
                if has_header:
                    self.headers = next(reader)
                else:
                    # Generate column names if no headers
                    first_row = next(reader)
                    self.headers = [f"Column_{i+1}" for i in range(len(first_row))]
                    f.seek(0)
                    reader = csv.reader(f, delimiter=self.delimiter)
                
                # Read data (limit to first 100 rows for preview)
                self.csv_data = []
                for i, row in enumerate(reader):
                    if i >= 100:
                        break
                    self.csv_data.append(row)
            
            self.setup_column_mapping()
            self.load_data_preview()
            self.import_btn.setEnabled(True)
            
        except Exception as e:
            QMessageBox.critical(self, "CSV Error", f"Failed to load CSV file: {str(e)}")
    
    def setup_column_mapping(self):
        """Setup column mapping table."""
        self.columns_data = []
        
        # Check if CSV has ID column
        has_id = any(header.lower() in ['id', 'rowid', '_id'] for header in self.headers)
        
        # Add row count ID if no ID column exists
        if not has_id:
            self.columns_data.append({
                'original': '[ROW_COUNT]',
                'feather': 'id',
                'include': True
            })
        
        # Add all CSV headers
        for header in self.headers:
            self.columns_data.append({
                'original': header,
                'feather': header,
                'include': True
            })
        
        self.populate_column_table()
    
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
            
            # Original header
            orig_item = QTableWidgetItem(col_data['original'])
            orig_item.setFlags(orig_item.flags() & ~Qt.ItemIsEditable)
            self.column_table.setItem(row, 1, orig_item)
            
            # Feather column name (editable)
            feather_item = QTableWidgetItem(col_data['feather'])
            self.column_table.setItem(row, 2, feather_item)
    
    def on_include_changed(self, row, state):
        """Handle include checkbox state change."""
        self.columns_data[row]['include'] = (state == Qt.Checked)
    
    def load_data_preview(self):
        """Load preview of CSV data."""
        try:
            # Show first 5 rows
            preview_rows = self.csv_data[:5]
            
            self.preview_table.setColumnCount(len(self.headers))
            self.preview_table.setHorizontalHeaderLabels(self.headers)
            self.preview_table.setRowCount(len(preview_rows))
            
            for row_idx, row_data in enumerate(preview_rows):
                for col_idx, value in enumerate(row_data):
                    if col_idx < len(row_data):
                        item = QTableWidgetItem(str(value))
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                        self.preview_table.setItem(row_idx, col_idx, item)
            
        except Exception as e:
            QMessageBox.warning(self, "Preview Error", f"Failed to load preview: {str(e)}")
    
    def import_data(self):
        """Import CSV data to feather database."""
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
        
        QMessageBox.information(
            self,
            "Import Ready",
            f"Ready to import {len(selected_columns)} columns from CSV file"
        )
    
    def get_import_config(self):
        """Get the current import configuration."""
        # Update feather column names
        for row in range(self.column_table.rowCount()):
            feather_item = self.column_table.item(row, 2)
            if feather_item:
                self.columns_data[row]['feather'] = feather_item.text()
        
        return {
            'source_type': 'csv',
            'source_path': self.csv_path,
            'delimiter': self.delimiter,
            'headers': self.headers,
            'columns': [col for col in self.columns_data if col['include']],
            'data': self.csv_data
        }
