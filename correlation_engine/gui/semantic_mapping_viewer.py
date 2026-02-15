"""
Semantic Mapping Viewer

Viewer for displaying and managing semantic mappings.
Shows built-in, global, and wing-specific mappings with coverage statistics.
Enhanced to display advanced rules and cross-feather rules.

Implements Task 13: Create Semantic Mapping Viewer
Enhanced: Cross-feather rule visualization
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QTableWidget, QTableWidgetItem, QLabel, QPushButton,
    QTextEdit, QGroupBox, QComboBox, QMessageBox, QHeaderView,
    QCheckBox, QSplitter
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont
from typing import List, Dict, Optional

from correlation_engine.config.semantic_mapping import SemanticMappingManager, SemanticMapping, SemanticRule


class SemanticMappingViewer(QDialog):
    """
    Viewer for semantic mappings with statistics and conflict detection.
    Enhanced to show advanced rules and cross-feather rules.
    
    Implements Task 13: Semantic Mapping Viewer
    Enhanced: Cross-feather rule visualization
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
        self.show_cross_feather_only = False
        self.setup_ui()
        self.load_data()
    
    def setup_ui(self):
        """Setup viewer UI with cross-feather support."""
        self.setWindowTitle("Semantic Mapping Viewer")
        self.setMinimumSize(1200, 800)
        
        layout = QVBoxLayout(self)
        
        # Title
        title = QLabel("<h2>Semantic Mapping Viewer</h2>")
        layout.addWidget(title)
        
        # Statistics section - enhanced with rule stats
        stats_group = QGroupBox("Coverage Statistics")
        stats_layout = QVBoxLayout()
        self.stats_text = QTextEdit()
        self.stats_text.setReadOnly(True)
        self.stats_text.setMaximumHeight(120)
        stats_layout.addWidget(self.stats_text)
        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)
        
        # Filter section - enhanced with cross-feather filter
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Filter by Artifact:"))
        self.artifact_filter = QComboBox()
        self.artifact_filter.addItem("All")
        self.artifact_filter.currentTextChanged.connect(self.apply_filter)
        filter_layout.addWidget(self.artifact_filter)
        
        # Cross-feather filter checkbox
        self.cross_feather_checkbox = QCheckBox("Show only cross-feather rules")
        self.cross_feather_checkbox.stateChanged.connect(self._toggle_cross_feather_filter)
        filter_layout.addWidget(self.cross_feather_checkbox)
        
        filter_layout.addStretch()
        layout.addLayout(filter_layout)
        
        # Tabs for different mapping sources
        self.tabs = QTabWidget()
        
        # Tab 1: All Mappings (enhanced with type column)
        self.all_tab = self._create_enhanced_mapping_table()
        self.tabs.addTab(self.all_tab, "All Mappings")
        
        # Tab 2: Simple Mappings
        self.simple_tab = self._create_mapping_table()
        self.tabs.addTab(self.simple_tab, "Simple Mappings")
        
        # Tab 3: Advanced Rules (NEW)
        self.advanced_tab = self._create_advanced_rules_table()
        self.tabs.addTab(self.advanced_tab, "Advanced Rules")
        
        # Tab 4: Cross-Feather Rules (NEW)
        self.cross_feather_tab = self._create_cross_feather_table()
        self.tabs.addTab(self.cross_feather_tab, "Cross-Feather Rules")
        
        # Tab 5: Built-in Mappings
        self.builtin_tab = self._create_mapping_table()
        self.tabs.addTab(self.builtin_tab, "Built-in")
        
        # Tab 6: Global Mappings
        self.global_tab = self._create_mapping_table()
        self.tabs.addTab(self.global_tab, "Global")
        
        # Tab 7: Wing Mappings
        self.wing_tab = self._create_mapping_table()
        self.tabs.addTab(self.wing_tab, "Wing-specific")
        
        # Tab 8: Conflicts
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
        """Create a table widget for displaying simple mappings."""
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
    
    def _create_enhanced_mapping_table(self) -> QTableWidget:
        """Create enhanced table with type and feathers columns."""
        table = QTableWidget()
        table.setColumnCount(9)
        table.setHorizontalHeaderLabels([
            "Type", "Name/Artifact", "Field/Conditions", "Value/Logic", "Meaning", 
            "Feathers", "Category", "Severity", "Confidence"
        ])
        table.horizontalHeader().setStretchLastSection(True)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.doubleClicked.connect(self._show_rule_details)
        return table
    
    def _create_advanced_rules_table(self) -> QTableWidget:
        """Create table for advanced rules with conditions."""
        table = QTableWidget()
        table.setColumnCount(8)
        table.setHorizontalHeaderLabels([
            "Rule Name", "Semantic Value", "Logic", "Conditions", 
            "Feathers", "Category", "Severity", "Confidence"
        ])
        table.horizontalHeader().setStretchLastSection(True)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.doubleClicked.connect(self._show_rule_details)
        return table
    
    def _create_cross_feather_table(self) -> QTableWidget:
        """Create table specifically for cross-feather rules."""
        table = QTableWidget()
        table.setColumnCount(9)
        table.setHorizontalHeaderLabels([
            "Rule Name", "Semantic Value", "Logic", "Feather Count",
            "Feathers Involved", "Conditions", "Category", "Severity", "Confidence"
        ])
        table.horizontalHeader().setStretchLastSection(True)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.doubleClicked.connect(self._show_rule_details)
        
        # Add info label
        info = QLabel("Cross-feather rules correlate data across multiple artifact types (e.g., Prefetch + LNK + Registry)")
        info.setWordWrap(True)
        info.setStyleSheet("color: #3B82F6; font-style: italic; padding: 5px;")
        
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(info)
        layout.addWidget(table)
        layout.setContentsMargins(0, 0, 0, 0)
        
        return widget
    
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
        """Load mapping data into viewer with cross-feather support."""
        self._load_statistics()
        self._load_artifact_filter()
        self._load_all_mappings_enhanced()
        self._load_simple_mappings()
        self._load_advanced_rules()
        self._load_cross_feather_rules()
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

    
    def _toggle_cross_feather_filter(self, state):
        """Toggle cross-feather filter."""
        self.show_cross_feather_only = (state == Qt.Checked)
        self.apply_filter()
    
    def _get_all_rules(self) -> List[SemanticRule]:
        """Get all advanced rules from manager."""
        all_rules = []
        
        # Get global rules
        all_rules.extend(self.mapping_manager.global_rules)
        
        # Get wing rules
        for wing_rules in self.mapping_manager.wing_rules.values():
            all_rules.extend(wing_rules)
        
        # Get pipeline rules
        for pipeline_rules in self.mapping_manager.pipeline_rules.values():
            all_rules.extend(pipeline_rules)
        
        return all_rules
    
    def _is_cross_feather_rule(self, rule: SemanticRule) -> bool:
        """Check if rule is cross-feather (uses multiple feathers)."""
        feathers = set()
        for condition in rule.conditions:
            if condition.feather_id != "_identity":
                feathers.add(condition.feather_id)
        return len(feathers) > 1
    
    def _get_rule_feathers(self, rule: SemanticRule) -> List[str]:
        """Get list of feathers used in rule."""
        feathers = set()
        for condition in rule.conditions:
            if condition.feather_id != "_identity":
                feathers.add(condition.feather_id)
        return sorted(list(feathers))
    
    def _load_statistics(self):
        """Load coverage statistics with rule information."""
        # Count mappings by source
        all_mappings = self._get_all_mappings()
        builtin_count = sum(1 for m in all_mappings if m.mapping_source == "built-in")
        global_count = sum(1 for m in all_mappings if m.mapping_source == "global")
        wing_count = sum(1 for m in all_mappings if m.mapping_source == "wing")
        
        # Count rules
        all_rules = self._get_all_rules()
        total_rules = len(all_rules)
        cross_feather_rules = sum(1 for r in all_rules if self._is_cross_feather_rule(r))
        
        # Count artifacts covered
        artifacts = set(m.artifact_type for m in all_mappings if m.artifact_type)
        
        # Count categories
        categories = set(m.category for m in all_mappings if m.category)
        categories.update(r.category for r in all_rules if r.category)
        
        stats_html = f"""
<b>Simple Mappings:</b> {len(all_mappings)} (Built-in: {builtin_count}, Global: {global_count}, Wing: {wing_count})<br>
<b>Advanced Rules:</b> {total_rules} | <b style="color: #00FFFF;">Cross-Feather Rules:</b> {cross_feather_rules}<br>
<b>Artifacts Covered:</b> {len(artifacts)} | <b>Categories:</b> {len(categories)}<br>
        """
        self.stats_text.setHtml(stats_html)
    
    def _load_all_mappings_enhanced(self):
        """Load all mappings and rules into enhanced table."""
        table = self.all_tab
        
        # Get all mappings and rules
        mappings = self._get_all_mappings()
        rules = self._get_all_rules()
        
        # Apply filters
        if self.show_cross_feather_only:
            rules = [r for r in rules if self._is_cross_feather_rule(r)]
            mappings = []  # Don't show simple mappings when filtering for cross-feather
        
        artifact_filter = self.artifact_filter.currentText()
        if artifact_filter != "All":
            mappings = [m for m in mappings if m.artifact_type == artifact_filter]
            # For rules, check if any condition uses this artifact
            rules = [r for r in rules if artifact_filter in self._get_rule_feathers(r)]
        
        total_items = len(mappings) + len(rules)
        table.setRowCount(total_items)
        
        row = 0
        
        # Add simple mappings
        for mapping in mappings:
            table.setItem(row, 0, QTableWidgetItem("Simple"))
            table.setItem(row, 1, QTableWidgetItem(mapping.artifact_type or "N/A"))
            table.setItem(row, 2, QTableWidgetItem(mapping.field))
            table.setItem(row, 3, QTableWidgetItem(mapping.technical_value))
            table.setItem(row, 4, QTableWidgetItem(mapping.semantic_value))
            table.setItem(row, 5, QTableWidgetItem("1"))
            table.setItem(row, 6, QTableWidgetItem(mapping.category or "N/A"))
            
            severity_item = QTableWidgetItem(mapping.severity)
            if mapping.severity == "critical":
                severity_item.setForeground(QColor(255, 0, 0))
            elif mapping.severity == "high":
                severity_item.setForeground(QColor(255, 100, 0))
            elif mapping.severity == "medium":
                severity_item.setForeground(QColor(255, 255, 0))
            table.setItem(row, 7, severity_item)
            
            table.setItem(row, 8, QTableWidgetItem(f"{mapping.confidence:.2f}"))
            row += 1
        
        # Add advanced rules
        for rule in rules:
            type_item = QTableWidgetItem("Advanced")
            type_item.setForeground(QColor(0, 255, 255))  # Cyan for advanced
            table.setItem(row, 0, type_item)
            
            table.setItem(row, 1, QTableWidgetItem(rule.name))
            table.setItem(row, 2, QTableWidgetItem(f"{len(rule.conditions)} conditions"))
            table.setItem(row, 3, QTableWidgetItem(rule.logic_operator))
            table.setItem(row, 4, QTableWidgetItem(rule.semantic_value))
            
            feathers = self._get_rule_feathers(rule)
            feather_item = QTableWidgetItem(str(len(feathers)))
            if len(feathers) > 1:
                feather_item.setForeground(QColor(0, 255, 255))  # Highlight cross-feather
                feather_item.setFont(QFont("Arial", 10, QFont.Bold))
            table.setItem(row, 5, feather_item)
            
            table.setItem(row, 6, QTableWidgetItem(rule.category or "N/A"))
            
            severity_item = QTableWidgetItem(rule.severity)
            if rule.severity == "critical":
                severity_item.setForeground(QColor(255, 0, 0))
            elif rule.severity == "high":
                severity_item.setForeground(QColor(255, 100, 0))
            elif rule.severity == "medium":
                severity_item.setForeground(QColor(255, 255, 0))
            table.setItem(row, 7, severity_item)
            
            table.setItem(row, 8, QTableWidgetItem(f"{rule.confidence:.2f}"))
            row += 1
    
    def _load_simple_mappings(self):
        """Load simple mappings only."""
        mappings = self._get_all_mappings()
        self._populate_table(self.simple_tab, mappings)
    
    def _load_advanced_rules(self):
        """Load advanced rules into table."""
        rules = self._get_all_rules()
        
        # Apply filters
        if self.show_cross_feather_only:
            rules = [r for r in rules if self._is_cross_feather_rule(r)]
        
        artifact_filter = self.artifact_filter.currentText()
        if artifact_filter != "All":
            rules = [r for r in rules if artifact_filter in self._get_rule_feathers(r)]
        
        table = self.advanced_tab
        table.setRowCount(len(rules))
        
        for i, rule in enumerate(rules):
            table.setItem(i, 0, QTableWidgetItem(rule.name))
            table.setItem(i, 1, QTableWidgetItem(rule.semantic_value))
            table.setItem(i, 2, QTableWidgetItem(rule.logic_operator))
            table.setItem(i, 3, QTableWidgetItem(f"{len(rule.conditions)} conditions"))
            
            feathers = self._get_rule_feathers(rule)
            feather_text = ", ".join(feathers) if feathers else "Identity-level"
            feather_item = QTableWidgetItem(feather_text)
            if len(feathers) > 1:
                feather_item.setForeground(QColor(0, 255, 255))
                feather_item.setFont(QFont("Arial", 10, QFont.Bold))
            table.setItem(i, 4, feather_item)
            
            table.setItem(i, 5, QTableWidgetItem(rule.category or "N/A"))
            
            severity_item = QTableWidgetItem(rule.severity)
            if rule.severity == "critical":
                severity_item.setForeground(QColor(255, 0, 0))
            elif rule.severity == "high":
                severity_item.setForeground(QColor(255, 100, 0))
            elif rule.severity == "medium":
                severity_item.setForeground(QColor(255, 255, 0))
            table.setItem(i, 6, severity_item)
            
            table.setItem(i, 7, QTableWidgetItem(f"{rule.confidence:.2f}"))
    
    def _load_cross_feather_rules(self):
        """Load cross-feather rules only."""
        rules = self._get_all_rules()
        cross_feather_rules = [r for r in rules if self._is_cross_feather_rule(r)]
        
        # Get the table from the widget
        widget = self.cross_feather_tab
        if isinstance(widget, QWidget):
            # Find the table widget
            table = None
            for child in widget.findChildren(QTableWidget):
                table = child
                break
            if not table:
                return
        else:
            table = widget
        
        table.setRowCount(len(cross_feather_rules))
        
        for i, rule in enumerate(cross_feather_rules):
            table.setItem(i, 0, QTableWidgetItem(rule.name))
            table.setItem(i, 1, QTableWidgetItem(rule.semantic_value))
            table.setItem(i, 2, QTableWidgetItem(rule.logic_operator))
            
            feathers = self._get_rule_feathers(rule)
            feather_count_item = QTableWidgetItem(str(len(feathers)))
            feather_count_item.setForeground(QColor(0, 255, 255))
            feather_count_item.setFont(QFont("Arial", 10, QFont.Bold))
            table.setItem(i, 3, feather_count_item)
            
            feather_text = ", ".join(feathers)
            feather_item = QTableWidgetItem(feather_text)
            feather_item.setForeground(QColor(0, 255, 255))
            table.setItem(i, 4, feather_item)
            
            # Build conditions summary
            conditions_text = []
            for condition in rule.conditions:
                conditions_text.append(f"{condition.feather_id}.{condition.field_name}")
            table.setItem(i, 5, QTableWidgetItem(" | ".join(conditions_text[:3]) + ("..." if len(conditions_text) > 3 else "")))
            
            table.setItem(i, 6, QTableWidgetItem(rule.category or "N/A"))
            
            severity_item = QTableWidgetItem(rule.severity)
            if rule.severity == "critical":
                severity_item.setForeground(QColor(255, 0, 0))
            elif rule.severity == "high":
                severity_item.setForeground(QColor(255, 100, 0))
            elif rule.severity == "medium":
                severity_item.setForeground(QColor(255, 255, 0))
            table.setItem(i, 7, severity_item)
            
            table.setItem(i, 8, QTableWidgetItem(f"{rule.confidence:.2f}"))
    
    def _show_rule_details(self, index):
        """Show detailed view of a rule when double-clicked."""
        # Get the table that was clicked
        table = self.sender()
        if not isinstance(table, QTableWidget):
            return
        
        row = index.row()
        
        # Try to determine if this is a rule or simple mapping
        # For enhanced table, check the Type column
        if table == self.all_tab:
            type_item = table.item(row, 0)
            if type_item and type_item.text() == "Simple":
                return  # Don't show details for simple mappings
            name = table.item(row, 1).text() if table.item(row, 1) else ""
        else:
            name = table.item(row, 0).text() if table.item(row, 0) else ""
        
        # Find the rule by name
        all_rules = self._get_all_rules()
        rule = None
        for r in all_rules:
            if r.name == name:
                rule = r
                break
        
        if not rule:
            return
        
        # Build detailed message
        feathers = self._get_rule_feathers(rule)
        is_cross_feather = len(feathers) > 1
        
        details = f"""
<h3>{rule.name}</h3>
<p><b>Semantic Value:</b> {rule.semantic_value}</p>
<p><b>Description:</b> {rule.description or 'N/A'}</p>
<p><b>Type:</b> {'<span style="color: #00FFFF; font-weight: bold;">Cross-Feather Rule</span>' if is_cross_feather else 'Single-Feather Rule'}</p>
<p><b>Logic Operator:</b> {rule.logic_operator}</p>
<p><b>Feathers Involved:</b> {', '.join(feathers) if feathers else 'Identity-level'}</p>
<p><b>Category:</b> {rule.category or 'N/A'}</p>
<p><b>Severity:</b> {rule.severity}</p>
<p><b>Confidence:</b> {rule.confidence:.2f}</p>

<h4>Conditions:</h4>
<ul>
"""
        
        for condition in rule.conditions:
            details += f"<li><b>{condition.feather_id}</b>.{condition.field_name} {condition.operator} '{condition.value}'</li>"
        
        details += "</ul>"
        
        # Show in message box
        msg = QMessageBox(self)
        msg.setWindowTitle("Rule Details")
        msg.setTextFormat(Qt.RichText)
        msg.setText(details)
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec_()
    
    def apply_filter(self):
        """Apply artifact and cross-feather filters to all tabs."""
        self._load_all_mappings_enhanced()
        self._load_simple_mappings()
        self._load_advanced_rules()
        self._load_cross_feather_rules()
        self._load_builtin_mappings()
        self._load_global_mappings()
        self._load_wing_mappings()

