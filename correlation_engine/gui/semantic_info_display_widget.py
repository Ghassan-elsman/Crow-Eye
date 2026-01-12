"""
Semantic Info Display Widget

Simple widget for displaying semantic information in correlation results.
This is a minimal implementation for Task 11.1 testing.
"""

from typing import Dict, Any
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont


class SemanticInfoDisplayWidget(QWidget):
    """
    Widget for displaying semantic information in correlation results.
    
    Shows semantic mappings for individual records with basic display.
    """
    
    def __init__(self, parent=None):
        """
        Initialize semantic info display widget.
        
        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        self.semantic_data = {}
        self.current_record = {}
        self.setup_ui()
    
    def setup_ui(self):
        """Setup the semantic info display UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Header
        title_label = QLabel("Semantic Information")
        title_label.setFont(QFont("Arial", 10, QFont.Bold))
        layout.addWidget(title_label)
        
        # Semantic info table
        self.semantic_table = QTableWidget()
        self.semantic_table.setColumnCount(3)
        self.semantic_table.setHorizontalHeaderLabels([
            "Field", "Raw Value", "Semantic Value"
        ])
        
        # Configure table
        self.semantic_table.setAlternatingRowColors(True)
        self.semantic_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.semantic_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.semantic_table.verticalHeader().setVisible(False)
        
        layout.addWidget(self.semantic_table)
        
        # Summary section
        self.summary_label = QLabel("No semantic information available")
        self.summary_label.setStyleSheet("color: #666; font-style: italic;")
        layout.addWidget(self.summary_label)
    
    def display_semantic_info(self, record: Dict[str, Any], semantic_data: Dict[str, Any]):
        """
        Display semantic information for a correlation record.
        
        Args:
            record: Correlation record data
            semantic_data: Semantic mapping information
        """
        self.current_record = record
        self.semantic_data = semantic_data
        self.refresh_display()
    
    def refresh_display(self):
        """Refresh the semantic information display."""
        self.semantic_table.setRowCount(0)
        
        if not self.semantic_data or '_semantic_mappings' not in self.semantic_data:
            self.summary_label.setText("No semantic mappings available for this record")
            return
        
        semantic_mappings = self.semantic_data['_semantic_mappings']
        
        # Count statistics
        total_fields = 0
        mapped_fields = 0
        
        # Process all fields in the record
        for field_name, field_value in self.current_record.items():
            if field_name.startswith('_'):  # Skip internal fields
                continue
            
            total_fields += 1
            has_mapping = field_name in semantic_mappings
            
            if has_mapping:
                mapped_fields += 1
            
            # Add row to table
            row = self.semantic_table.rowCount()
            self.semantic_table.insertRow(row)
            
            # Field name
            field_item = QTableWidgetItem(field_name)
            if has_mapping:
                field_item.setFont(QFont("Arial", 9, QFont.Bold))
            
            self.semantic_table.setItem(row, 0, field_item)
            
            # Raw value
            raw_value_item = QTableWidgetItem(str(field_value))
            self.semantic_table.setItem(row, 1, raw_value_item)
            
            if has_mapping:
                mapping_info = semantic_mappings[field_name]
                
                # Semantic value
                semantic_value = mapping_info.get('semantic_value', str(field_value))
                semantic_item = QTableWidgetItem(semantic_value)
                semantic_item.setFont(QFont("Arial", 9, QFont.Bold))
                self.semantic_table.setItem(row, 2, semantic_item)
            else:
                # No mapping available
                no_mapping_item = QTableWidgetItem("(no mapping)")
                no_mapping_item.setStyleSheet("color: #999; font-style: italic;")
                self.semantic_table.setItem(row, 2, no_mapping_item)
        
        # Update summary
        if total_fields > 0:
            mapping_percentage = (mapped_fields / total_fields) * 100
            self.summary_label.setText(
                f"Semantic coverage: {mapped_fields}/{total_fields} fields mapped ({mapping_percentage:.1f}%)"
            )
        else:
            self.summary_label.setText("No fields found in record")
        
        self.semantic_table.resizeRowsToContents()
    
    def clear(self):
        """Clear all displayed semantic information."""
        self.semantic_table.setRowCount(0)
        self.semantic_data = {}
        self.current_record = {}
        self.summary_label.setText("No semantic information available")