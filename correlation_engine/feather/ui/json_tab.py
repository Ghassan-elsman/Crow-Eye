"""
JSON Import Tab
Interface for importing data from JSON files.
"""

import json
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QFileDialog, QTableWidget, QTableWidgetItem,
    QHeaderView, QCheckBox, QLineEdit, QMessageBox, QTreeWidget,
    QTreeWidgetItem
)
from PyQt5.QtCore import Qt


class JSONTab(QWidget):
    """Tab for JSON import functionality."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.json_path = ""
        self.json_data = []
        self.all_keys = set()
        self.columns_data = []
        self.init_ui()
    
    def init_ui(self):
        """Initialize the JSON import interface."""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        # JSON file selection section
        file_select_layout = QHBoxLayout()
        file_label = QLabel("JSON File:")
        self.json_path_input = QLineEdit()
        self.json_path_input.setPlaceholderText("Select JSON file...")
        self.json_path_input.setReadOnly(True)
        
        self.json_browse_btn = QPushButton("Browse JSON")
        self.json_browse_btn.clicked.connect(self.select_json_file)
        
        file_select_layout.addWidget(file_label)
        file_select_layout.addWidget(self.json_path_input, 3)
        file_select_layout.addWidget(self.json_browse_btn)
        layout.addLayout(file_select_layout)
        
        # Key selection tree
        key_label = QLabel("Available Keys (select to include):")
        layout.addWidget(key_label)
        
        self.key_tree = QTreeWidget()
        self.key_tree.setHeaderLabels(["Include", "JSON Key", "Feather Column Name"])
        self.key_tree.setColumnWidth(0, 80)
        self.key_tree.setColumnWidth(1, 250)
        layout.addWidget(self.key_tree)
        
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
    
    def select_json_file(self):
        """Open file dialog to select JSON file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select JSON File",
            "",
            "JSON Files (*.json);;All Files (*)"
        )
        
        if file_path:
            # Reset previous data
            self.json_data = []
            self.all_keys = set()
            self.columns_data = []
            self.key_tree.clear()
            self.preview_table.setRowCount(0)
            self.preview_table.setColumnCount(0)
            
            self.json_path = file_path
            self.json_path_input.setText(file_path)
            self.load_json_file()
    
    def load_json_file(self):
        """Load and parse JSON file."""
        try:
            with open(self.json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Handle both array of objects and single object
            if isinstance(data, list):
                self.json_data = data
            elif isinstance(data, dict):
                self.json_data = [data]
            else:
                raise ValueError("JSON must be an object or array of objects")
            
            # Extract all unique keys from all objects
            self.all_keys = set()
            for item in self.json_data:
                self.extract_keys(item)
            
            self.setup_key_tree()
            self.load_data_preview()
            self.import_btn.setEnabled(True)
            
        except Exception as e:
            QMessageBox.critical(self, "JSON Error", f"Failed to load JSON file: {str(e)}")
    
    def extract_keys(self, obj, prefix=""):
        """Recursively extract all keys from JSON object."""
        if isinstance(obj, dict):
            for key, value in obj.items():
                full_key = f"{prefix}.{key}" if prefix else key
                
                if isinstance(value, (dict, list)):
                    self.extract_keys(value, full_key)
                else:
                    self.all_keys.add(full_key)
        elif isinstance(obj, list) and obj:
            # Sample first item in array
            if isinstance(obj[0], dict):
                self.extract_keys(obj[0], prefix)
    
    def setup_key_tree(self):
        """Setup key selection tree."""
        self.key_tree.clear()
        self.columns_data = []
        
        # Check if JSON has ID field
        has_id = any('id' in key.lower() for key in self.all_keys)
        
        # Add row count ID if no ID field exists
        if not has_id:
            self.add_tree_item('[ROW_COUNT]', 'id', True, is_generated=True)
        
        # Add all JSON keys
        sorted_keys = sorted(self.all_keys)
        for key in sorted_keys:
            # Convert nested keys to flat column names
            feather_name = key.replace('.', '_')
            self.add_tree_item(key, feather_name, True)
    
    def add_tree_item(self, original_key, feather_name, checked, is_generated=False):
        """Add item to key tree."""
        item = QTreeWidgetItem(self.key_tree)
        
        # Checkbox
        checkbox = QCheckBox()
        checkbox.setChecked(checked)
        self.key_tree.setItemWidget(item, 0, checkbox)
        
        # Original key
        item.setText(1, original_key)
        
        # Feather column name (editable)
        item.setText(2, feather_name)
        item.setFlags(item.flags() | Qt.ItemIsEditable)
        
        # Store column data
        self.columns_data.append({
            'original': original_key,
            'feather': feather_name,
            'include': checked,
            'is_generated': is_generated,
            'item': item,
            'checkbox': checkbox
        })
    
    def load_data_preview(self):
        """Load preview of JSON data."""
        try:
            # Show first 5 items
            preview_data = self.json_data[:5]
            
            # Get all keys for columns
            all_preview_keys = sorted(self.all_keys)
            
            self.preview_table.setColumnCount(len(all_preview_keys))
            self.preview_table.setHorizontalHeaderLabels(all_preview_keys)
            self.preview_table.setRowCount(len(preview_data))
            
            for row_idx, item in enumerate(preview_data):
                for col_idx, key in enumerate(all_preview_keys):
                    value = self.get_nested_value(item, key)
                    table_item = QTableWidgetItem(str(value) if value is not None else "")
                    table_item.setFlags(table_item.flags() & ~Qt.ItemIsEditable)
                    self.preview_table.setItem(row_idx, col_idx, table_item)
            
        except Exception as e:
            QMessageBox.warning(self, "Preview Error", f"Failed to load preview: {str(e)}")
    
    def get_nested_value(self, obj, key_path):
        """Get value from nested JSON using dot notation."""
        keys = key_path.split('.')
        value = obj
        
        try:
            for key in keys:
                if isinstance(value, dict):
                    value = value.get(key)
                elif isinstance(value, list) and value:
                    value = value[0].get(key) if isinstance(value[0], dict) else None
                else:
                    return None
            return value
        except:
            return None
    
    def import_data(self):
        """Import JSON data to feather database."""
        # Update column data from tree
        for col_data in self.columns_data:
            item = col_data['item']
            col_data['feather'] = item.text(2)
            col_data['include'] = col_data['checkbox'].isChecked()
        
        # Get selected columns
        selected_columns = [col for col in self.columns_data if col['include']]
        
        if not selected_columns:
            QMessageBox.warning(self, "No Keys", "Please select at least one key to import.")
            return
        
        QMessageBox.information(
            self,
            "Import Ready",
            f"Ready to import {len(selected_columns)} keys from JSON file"
        )
    
    def get_import_config(self):
        """Get the current import configuration."""
        # Update column data from tree
        for col_data in self.columns_data:
            item = col_data['item']
            col_data['feather'] = item.text(2)
            col_data['include'] = col_data['checkbox'].isChecked()
        
        return {
            'source_type': 'json',
            'source_path': self.json_path,
            'columns': [col for col in self.columns_data if col['include']],
            'data': self.json_data
        }
