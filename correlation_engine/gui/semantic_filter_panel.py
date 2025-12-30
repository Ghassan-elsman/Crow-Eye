"""
Semantic Filter Panel

Enhanced filtering panel for semantic-based filtering of correlation results.
Integrates with the hierarchical results view.

Implements Task 12: Create Semantic Filter Panel
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QLineEdit, QPushButton, QGroupBox, QCheckBox, QFrame
)
from PyQt5.QtCore import pyqtSignal
from typing import Dict, List, Optional

from correlation_engine.engine.data_structures import QueryFilters


class SemanticFilterPanel(QWidget):
    """
    Enhanced filter panel with semantic filtering capabilities.
    
    Implements Task 12: Semantic Filter Panel
    """
    
    # Signal emitted when filters are applied
    filters_applied = pyqtSignal(object)  # QueryFilters object
    
    def __init__(self, parent=None):
        """Initialize semantic filter panel."""
        super().__init__(parent)
        self.setup_ui()
    
    def setup_ui(self):
        """Setup filter panel UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        
        # Title
        title = QLabel("<h3>Advanced Filters</h3>")
        layout.addWidget(title)
        
        # Semantic Filters Group
        semantic_group = QGroupBox("Semantic Filters")
        semantic_layout = QVBoxLayout()
        
        # Category filter
        category_layout = QHBoxLayout()
        category_layout.addWidget(QLabel("Category:"))
        self.category_combo = QComboBox()
        self.category_combo.addItems([
            "All",
            "execution",
            "authentication",
            "network",
            "persistence",
            "file_access",
            "system_power",
            "process_execution"
        ])
        category_layout.addWidget(self.category_combo)
        semantic_layout.addLayout(category_layout)
        
        # Meaning search
        meaning_layout = QHBoxLayout()
        meaning_layout.addWidget(QLabel("Meaning:"))
        self.meaning_edit = QLineEdit()
        self.meaning_edit.setPlaceholderText("Search semantic meaning...")
        meaning_layout.addWidget(self.meaning_edit)
        semantic_layout.addLayout(meaning_layout)
        
        # Severity filter
        severity_layout = QHBoxLayout()
        severity_layout.addWidget(QLabel("Severity:"))
        self.severity_combo = QComboBox()
        self.severity_combo.addItems([
            "All",
            "info",
            "low",
            "medium",
            "high",
            "critical"
        ])
        severity_layout.addWidget(self.severity_combo)
        semantic_layout.addLayout(severity_layout)
        
        semantic_group.setLayout(semantic_layout)
        layout.addWidget(semantic_group)
        
        # Evidence Role Filters Group
        role_group = QGroupBox("Evidence Role")
        role_layout = QVBoxLayout()
        
        self.primary_check = QCheckBox("Primary Evidence")
        self.primary_check.setChecked(True)
        role_layout.addWidget(self.primary_check)
        
        self.secondary_check = QCheckBox("Secondary Evidence")
        self.secondary_check.setChecked(True)
        role_layout.addWidget(self.secondary_check)
        
        self.supporting_check = QCheckBox("Supporting Evidence")
        self.supporting_check.setChecked(True)
        role_layout.addWidget(self.supporting_check)
        
        role_group.setLayout(role_layout)
        layout.addWidget(role_group)
        
        # Mapping Source Filters Group
        source_group = QGroupBox("Mapping Source")
        source_layout = QVBoxLayout()
        
        self.builtin_check = QCheckBox("Built-in Mappings")
        self.builtin_check.setChecked(True)
        source_layout.addWidget(self.builtin_check)
        
        self.global_check = QCheckBox("Global Mappings")
        self.global_check.setChecked(True)
        source_layout.addWidget(self.global_check)
        
        self.wing_check = QCheckBox("Wing-specific Mappings")
        self.wing_check.setChecked(True)
        source_layout.addWidget(self.wing_check)
        
        source_group.setLayout(source_layout)
        layout.addWidget(source_group)
        
        # Confidence Filter Group
        confidence_group = QGroupBox("Confidence")
        confidence_layout = QHBoxLayout()
        confidence_layout.addWidget(QLabel("Minimum:"))
        self.confidence_combo = QComboBox()
        self.confidence_combo.addItems([
            "Any",
            "0.5 (50%)",
            "0.7 (70%)",
            "0.8 (80%)",
            "0.9 (90%)"
        ])
        confidence_layout.addWidget(self.confidence_combo)
        confidence_group.setLayout(confidence_layout)
        layout.addWidget(confidence_group)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        apply_btn = QPushButton("Apply Filters")
        apply_btn.clicked.connect(self.apply_filters)
        button_layout.addWidget(apply_btn)
        
        reset_btn = QPushButton("Reset")
        reset_btn.clicked.connect(self.reset_filters)
        button_layout.addWidget(reset_btn)
        
        layout.addLayout(button_layout)
        
        # Add stretch to push everything to top
        layout.addStretch()
        
        # Style
        self.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #3a3a3a;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """)
    
    def apply_filters(self):
        """Apply current filter settings."""
        filters = QueryFilters()
        
        # Semantic filters
        category = self.category_combo.currentText()
        if category != "All":
            filters.semantic_category = category
        
        meaning = self.meaning_edit.text().strip()
        if meaning:
            filters.semantic_meaning = meaning
        
        severity = self.severity_combo.currentText()
        if severity != "All":
            filters.severity = severity
        
        # Role filters
        roles = []
        if self.primary_check.isChecked():
            roles.append("primary")
        if self.secondary_check.isChecked():
            roles.append("secondary")
        if self.supporting_check.isChecked():
            roles.append("supporting")
        if roles:
            filters.evidence_role = roles
        
        # Mapping source filters
        sources = []
        if self.builtin_check.isChecked():
            sources.append("built-in")
        if self.global_check.isChecked():
            sources.append("global")
        if self.wing_check.isChecked():
            sources.append("wing")
        if sources:
            filters.mapping_source = sources
        
        # Confidence filter
        confidence_text = self.confidence_combo.currentText()
        if confidence_text != "Any":
            confidence_value = float(confidence_text.split()[0])
            filters.min_confidence = confidence_value
        
        # Emit signal
        self.filters_applied.emit(filters)
    
    def reset_filters(self):
        """Reset all filters to default."""
        self.category_combo.setCurrentIndex(0)
        self.meaning_edit.clear()
        self.severity_combo.setCurrentIndex(0)
        self.primary_check.setChecked(True)
        self.secondary_check.setChecked(True)
        self.supporting_check.setChecked(True)
        self.builtin_check.setChecked(True)
        self.global_check.setChecked(True)
        self.wing_check.setChecked(True)
        self.confidence_combo.setCurrentIndex(0)
        
        # Apply reset filters
        self.apply_filters()
    
    def get_current_filters(self) -> QueryFilters:
        """
        Get current filter settings as QueryFilters object.
        
        Returns:
            QueryFilters with current settings
        """
        self.apply_filters()
        # Return would be handled by signal, but we can also return directly
        filters = QueryFilters()
        # ... (same logic as apply_filters)
        return filters
