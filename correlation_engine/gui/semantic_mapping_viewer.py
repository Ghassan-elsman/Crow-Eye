"""
Semantic Mapping Viewer

Viewer for displaying and managing semantic mappings.
Shows built-in, global, and wing-specific mappings with coverage statistics.

Implements Task 13: Create Semantic Mapping Viewer
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QTableWidget, QTableWidgetItem, QLabel, QPushButton,
    QTextEdit, QGroupBox, QComboBox, QMessageBox, QHeaderView
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont
from typing import List, Dict, Optional

from correlation_engine.config.semantic_mapping import SemanticMappingManager, SemanticMapping


class SemanticMappingViewer(QDialog):
    """
    Viewer for semantic mappings with statistics and conflict detection.
    
    Implements Task 13: Semantic Mapping Viewer
    """
    
    def __init__(self, mapping_manager: SemanticMappingManager, parent=None):
        """
        Initialize semantic mapping viewer.
        
        Args:
            mapping_manager: SemanticMappingManager instance
            parent: Parent widget
        """
        super().__init__(parent)
        self.mapping_manager = mapping_manager
        self.setup_ui()
        self.load_data()
    
    def setup_ui(self):
        """Setup viewer UI."""
        self.setWindowTitle("Semantic Mapping Viewer")
        self.setMinimumSize(1000, 700)
        
        layout = QVBoxLayout(self)
        
        # Title
        title = QLabel("<h2>Semantic Mapping Viewer</h2>")
        layout.addWidget(title)
        
        # Statistics section
        stats_group = QGroupBox("Coverage Statistics")
        stats_layout = QVBoxLayout()
        self.stats_text = QTextEdit()
        self.stats_text.setReadOnly(True)
        self.stats_text.setMaximumHeight(100)
        stats_layout.addWidget(self.stats_text)
        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)
        
        # Filter section
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Filter by Artifact:"))
        self.artifact_filter = QComboBox()
        self.artifact_filter.addItem("All")
        self.artifact_filter.currentTextChanged.connect(self.apply_filter)
        filter_layout.addWidget(self.artifact_filter)
        filter_layout.addStretch()
        layout.addLayout(filter_layout)
        
        # Tabs for different mapping sources
        self.tabs = QTabWidget()
        
        # Tab 1: All Mappings
        self.all_tab = self._create_mapping_table()
        self.tabs.addTab(self.all_tab, "All Mappings")
        
        # Tab 2: Built-in Mappings
        self.builtin_tab = self._create_mapping_table()
        self.tabs.addTab(self.builtin_tab, "Built-in")
        
        # Tab 3: Global Mappings
        self.global_tab = self._create_mapping_table()
        self.tabs.addTab(self.global_tab, "Global")
        
        # Tab 4: Wing Mappings
        self.wing_tab = self._create_mapping_table()
        self.tabs.addTab(self.wing_tab, "Wing-specific")
        
        # Tab 5: Conflicts
        self.conflicts_tab = self._create_conflicts_tab()
        self.tabs.addTab(self.conflicts_tab, "Conflicts")
        
        layout.addWidget(self.tabs)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.load_data)
        button_layout.addWidget(refresh_btn)
        
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)
    
    def _create_mapping_table(self) -> QTableWidget:
        """Create a table widget for displaying mappings."""
        table = QTableWidget()
        table.setColumnCount(7)
        table.setHorizontalHeaderLabels([
            "Artifact", "Field", "Value", "Meaning", 
            "Category", "Severity", "Confidence"
        ])
        table.horizontalHeader().setStretchLastSection(True)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        return table
    
    def _create_conflicts_tab(self) -> QWidget:
        """Create conflicts detection tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        info_label = QLabel("Conflicts occur when multiple mappings match the same field value.")
        layout.addWidget(info_label)
        
        self.conflicts_table = QTableWidget()
        self.conflicts_table.setColumnCount(4)
        self.conflicts_table.setHorizontalHeaderLabels([
            "Field", "Value", "Conflicting Meanings", "Sources"
        ])
        self.conflicts_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.conflicts_table)
        
        return widget
    
    def load_data(self):
        """Load mapping data into viewer."""
        self._load_statistics()
        self._load_artifact_filter()
        self._load_all_mappings()
        self._load_builtin_mappings()
        self._load_global_mappings()
        self._load_wing_mappings()
        self._detect_conflicts()
    
    def _load_statistics(self):
        """Load coverage statistics."""
        # Count mappings by source
        builtin_count = sum(1 for m in self._get_all_mappings() 
                          if m.mapping_source == "built-in")
        global_count = sum(1 for m in self._get_all_mappings() 
                         if m.mapping_source == "global")
        wing_count = sum(1 for m in self._get_all_mappings() 
                       if m.mapping_source == "wing")
        
        # Count artifacts covered
        artifacts = set(m.artifact_type for m in self._get_all_mappings() if m.artifact_type)
        
        # Count categories
        categories = set(m.category for m in self._get_all_mappings() if m.category)
        
        stats_html = f"""
<b>Total Mappings:</b> {len(self._get_all_mappings())}<br>
<b>Built-in:</b> {builtin_count} | <b>Global:</b> {global_count} | <b>Wing-specific:</b> {wing_count}<br>
<b>Artifacts Covered:</b> {len(artifacts)}<br>
<b>Categories:</b> {len(categories)}<br>
        """
        self.stats_text.setHtml(stats_html)
    
    def _load_artifact_filter(self):
        """Load artifact types into filter dropdown."""
        artifacts = set(m.artifact_type for m in self._get_all_mappings() if m.artifact_type)
        
        current = self.artifact_filter.currentText()
        self.artifact_filter.clear()
        self.artifact_filter.addItem("All")
        self.artifact_filter.addItems(sorted(artifacts))
        
        # Restore selection
        index = self.artifact_filter.findText(current)
        if index >= 0:
            self.artifact_filter.setCurrentIndex(index)
    
    def _get_all_mappings(self) -> List[SemanticMapping]:
        """Get all mappings from manager."""
        all_mappings = []
        
        # Get from global mappings
        for mappings_list in self.mapping_manager.global_mappings.values():
            all_mappings.extend(mappings_list)
        
        # Get from artifact mappings
        for mappings_list in self.mapping_manager.artifact_mappings.values():
            all_mappings.extend(mappings_list)
        
        return all_mappings
    
    def _load_all_mappings(self):
        """Load all mappings into table."""
        self._populate_table(self.all_tab, self._get_all_mappings())
    
    def _load_builtin_mappings(self):
        """Load built-in mappings."""
        mappings = [m for m in self._get_all_mappings() if m.mapping_source == "built-in"]
        self._populate_table(self.builtin_tab, mappings)
    
    def _load_global_mappings(self):
        """Load global mappings."""
        mappings = [m for m in self._get_all_mappings() if m.mapping_source == "global"]
        self._populate_table(self.global_tab, mappings)
    
    def _load_wing_mappings(self):
        """Load wing-specific mappings."""
        mappings = [m for m in self._get_all_mappings() if m.mapping_source == "wing"]
        self._populate_table(self.wing_tab, mappings)
    
    def _populate_table(self, table: QTableWidget, mappings: List[SemanticMapping]):
        """Populate table with mappings."""
        # Apply artifact filter
        artifact_filter = self.artifact_filter.currentText()
        if artifact_filter != "All":
            mappings = [m for m in mappings if m.artifact_type == artifact_filter]
        
        table.setRowCount(len(mappings))
        
        for i, mapping in enumerate(mappings):
            table.setItem(i, 0, QTableWidgetItem(mapping.artifact_type or "N/A"))
            table.setItem(i, 1, QTableWidgetItem(mapping.field))
            table.setItem(i, 2, QTableWidgetItem(mapping.technical_value))
            table.setItem(i, 3, QTableWidgetItem(mapping.semantic_value))
            table.setItem(i, 4, QTableWidgetItem(mapping.category or "N/A"))
            
            # Severity with color
            severity_item = QTableWidgetItem(mapping.severity)
            if mapping.severity == "critical":
                severity_item.setForeground(QColor(255, 0, 0))
            elif mapping.severity == "high":
                severity_item.setForeground(QColor(255, 100, 0))
            elif mapping.severity == "medium":
                severity_item.setForeground(QColor(255, 255, 0))
            table.setItem(i, 5, severity_item)
            
            table.setItem(i, 6, QTableWidgetItem(f"{mapping.confidence:.2f}"))
    
    def _detect_conflicts(self):
        """Detect and display mapping conflicts."""
        # Group mappings by field and value
        mapping_groups: Dict[Tuple[str, str], List[SemanticMapping]] = {}
        
        for mapping in self._get_all_mappings():
            key = (mapping.field, mapping.technical_value)
            if key not in mapping_groups:
                mapping_groups[key] = []
            mapping_groups[key].append(mapping)
        
        # Find conflicts (multiple different meanings for same field/value)
        conflicts = []
        for (field, value), mappings in mapping_groups.items():
            meanings = set(m.semantic_value for m in mappings)
            if len(meanings) > 1:
                conflicts.append((field, value, mappings))
        
        # Populate conflicts table
        self.conflicts_table.setRowCount(len(conflicts))
        
        for i, (field, value, mappings) in enumerate(conflicts):
            self.conflicts_table.setItem(i, 0, QTableWidgetItem(field))
            self.conflicts_table.setItem(i, 1, QTableWidgetItem(value))
            
            meanings = ", ".join(set(m.semantic_value for m in mappings))
            self.conflicts_table.setItem(i, 2, QTableWidgetItem(meanings))
            
            sources = ", ".join(set(m.mapping_source for m in mappings))
            self.conflicts_table.setItem(i, 3, QTableWidgetItem(sources))
    
    def apply_filter(self):
        """Apply artifact filter to all tabs."""
        self._load_all_mappings()
        self._load_builtin_mappings()
        self._load_global_mappings()
        self._load_wing_mappings()
