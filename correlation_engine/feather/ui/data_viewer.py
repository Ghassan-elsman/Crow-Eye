"""
Feather Data Viewer
Browse and manage imported feather data.
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
    QLineEdit, QComboBox, QMessageBox, QGroupBox
)
from PyQt5.QtCore import Qt


class DataViewer(QWidget):
    """Widget for viewing and managing feather data."""
    
    def __init__(self, feather_db=None, parent=None):
        super().__init__(parent)
        self.feather_db = feather_db
        self.current_table = None
        self.init_ui()
    
    def init_ui(self):
        """Initialize the data viewer interface."""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        # Header with feather info
        info_group = QGroupBox("Feather Information")
        info_layout = QVBoxLayout()
        
        self.feather_info_label = QLabel("No feather database loaded")
        self.feather_info_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        info_layout.addWidget(self.feather_info_label)
        
        self.stats_label = QLabel("")
        info_layout.addWidget(self.stats_label)
        
        info_group.setLayout(info_layout)
        layout.addWidget(info_group)
        
        # Table selection
        table_layout = QHBoxLayout()
        table_label = QLabel("Select Table:")
        self.table_combo = QComboBox()
        self.table_combo.currentTextChanged.connect(self.on_table_selected)
        
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_data)
        
        table_layout.addWidget(table_label)
        table_layout.addWidget(self.table_combo, 2)
        table_layout.addWidget(self.refresh_btn)
        layout.addLayout(table_layout)
        
        # Search and filter
        search_layout = QHBoxLayout()
        search_label = QLabel("Search:")
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search across all columns...")
        self.search_input.textChanged.connect(self.filter_data)
        
        search_layout.addWidget(search_label)
        search_layout.addWidget(self.search_input, 3)
        layout.addLayout(search_layout)
        
        # Data table
        self.data_table = QTableWidget()
        self.data_table.setAlternatingRowColors(True)
        self.data_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.data_table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self.data_table)
        
        # Action buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.export_btn = QPushButton("Export Data")
        self.export_btn.clicked.connect(self.export_data)
        button_layout.addWidget(self.export_btn)
        
        self.delete_btn = QPushButton("Delete Selected")
        self.delete_btn.clicked.connect(self.delete_selected)
        button_layout.addWidget(self.delete_btn)
        
        layout.addLayout(button_layout)
    
    def set_feather_database(self, feather_db):
        """Set the feather database to view."""
        self.feather_db = feather_db
        self.load_feather_info()
        self.load_tables()
    
    def load_feather_info(self):
        """Load and display feather database information."""
        if not self.feather_db:
            return
        
        try:
            stats = self.feather_db.get_statistics()
            
            info_text = f"Feather: {stats['feather_name']}"
            self.feather_info_label.setText(info_text)
            
            stats_text = f"Total Records: {stats['total_records']} | Tables: {len(stats['tables'])}"
            self.stats_label.setText(stats_text)
            
        except Exception as e:
            QMessageBox.warning(self, "Info Error", f"Failed to load feather info: {str(e)}")
    
    def load_tables(self):
        """Load available tables from feather database."""
        if not self.feather_db:
            return
        
        try:
            tables = self.feather_db.get_table_names()
            self.table_combo.clear()
            
            if tables:
                self.table_combo.addItems(tables)
                # Automatically select and load the first table
                self.table_combo.setCurrentIndex(0)
                self.current_table = tables[0]
                self.load_table_data()
            
        except Exception as e:
            QMessageBox.warning(self, "Table Error", f"Failed to load tables: {str(e)}")
    
    def on_table_selected(self, table_name):
        """Handle table selection."""
        if not table_name or not self.feather_db:
            return
        
        self.current_table = table_name
        self.load_table_data()
    
    def load_table_data(self):
        """Load data from selected table."""
        if not self.current_table or not self.feather_db:
            return
        
        try:
            data = self.feather_db.get_table_data(self.current_table, limit=1000)
            
            if not data:
                self.data_table.setRowCount(0)
                self.data_table.setColumnCount(0)
                return
            
            # Set up table
            columns = list(data[0].keys())
            self.data_table.setColumnCount(len(columns))
            self.data_table.setHorizontalHeaderLabels(columns)
            self.data_table.setRowCount(len(data))
            
            # Populate data
            for row_idx, record in enumerate(data):
                for col_idx, col_name in enumerate(columns):
                    value = record.get(col_name, '')
                    item = QTableWidgetItem(str(value))
                    
                    # Highlight ID column
                    if col_name.lower() in ['id', 'artifact_id', 'rowid']:
                        item.setBackground(Qt.darkCyan)
                    
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    self.data_table.setItem(row_idx, col_idx, item)
            
            # Resize columns to content
            self.data_table.resizeColumnsToContents()
            
        except Exception as e:
            QMessageBox.critical(self, "Data Error", f"Failed to load table data: {str(e)}")
    
    def filter_data(self, search_text):
        """Filter table data based on search text."""
        if not search_text:
            # Show all rows
            for row in range(self.data_table.rowCount()):
                self.data_table.setRowHidden(row, False)
            return
        
        search_text = search_text.lower()
        
        # Hide rows that don't match search
        for row in range(self.data_table.rowCount()):
            match_found = False
            
            for col in range(self.data_table.columnCount()):
                item = self.data_table.item(row, col)
                if item and search_text in item.text().lower():
                    match_found = True
                    break
            
            self.data_table.setRowHidden(row, not match_found)
    
    def refresh_data(self):
        """Refresh the current view."""
        self.load_feather_info()
        self.load_tables()
        if self.current_table:
            self.load_table_data()
    
    def export_data(self):
        """Export current table data."""
        QMessageBox.information(
            self,
            "Export",
            "Export functionality will be implemented in future version."
        )
    
    def delete_selected(self):
        """Delete selected rows."""
        selected_rows = self.data_table.selectionModel().selectedRows()
        
        if not selected_rows:
            QMessageBox.warning(self, "No Selection", "Please select rows to delete.")
            return
        
        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Delete {len(selected_rows)} selected rows?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            QMessageBox.information(
                self,
                "Delete",
                "Delete functionality will be implemented in future version."
            )
