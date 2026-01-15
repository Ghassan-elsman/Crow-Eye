"""
Semantic Mapping Dialog
Enhanced dialog for adding/editing semantic mappings with multi-value support.

Features:
- Multi-value conditions with AND/OR logic
- Wildcard (*) support for "any value" matching
- Rule preview in human-readable format
- Validation before save
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QTextEdit, QDialogButtonBox, QFormLayout, QGroupBox,
    QMessageBox, QComboBox, QRadioButton, QButtonGroup,
    QTableWidget, QTableWidgetItem, QPushButton, QHeaderView,
    QWidget, QSizePolicy, QFrame
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor
from ...gui.ui_styling import CorrelationEngineStyles
from ...config.semantic_mapping import SemanticCondition, SemanticRule
import uuid


class SemanticMappingDialog(QDialog):
    """Enhanced dialog for adding or editing semantic mappings with multi-value support"""
    
    def __init__(self, parent=None, mapping=None, scope='global', wing_id=None, 
                 available_feathers=None, mode='simple'):
        """
        Initialize the dialog.
        
        Args:
            parent: Parent widget
            mapping: Existing mapping dict to edit (None for new mapping)
            scope: Scope of the mapping ('global' or 'wing')
            wing_id: Wing ID if scope is 'wing'
            available_feathers: List of available feather IDs for conditions
            mode: 'simple' for basic mapping, 'advanced' for multi-value rules
        """
        super().__init__(parent)
        self.mapping = mapping or {}
        self.scope = scope
        self.wing_id = wing_id
        self.available_feathers = available_feathers or []
        self.mode = mode
        self.conditions = []  # List of condition data dicts
        
        # Detect if editing an advanced rule
        if self.mapping and 'conditions' in self.mapping and len(self.mapping.get('conditions', [])) > 0:
            self.mode = 'advanced'
        
        self.init_ui()
        self.load_mapping()
    
    def init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle("Semantic Mapping" if not self.mapping else "Edit Semantic Mapping")
        self.setMinimumWidth(900)
        self.setMinimumHeight(650)
        self.resize(1000, 800)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(12, 12, 12, 12)
        
        # Header with title and icon
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 4)
        header_layout.setSpacing(8)
        
        # Icon
        icon_label = QLabel("🔗")
        icon_label.setStyleSheet("font-size: 18pt;")
        header_layout.addWidget(icon_label)
        
        # Title
        title = QLabel("Add Semantic Mapping" if not self.mapping else "Edit Semantic Mapping")
        title.setStyleSheet("font-size: 12pt; font-weight: bold; color: #00FFFF;")
        header_layout.addWidget(title)
        header_layout.addStretch()
        
        layout.addWidget(header_widget)
        
        # Mode selector (compact)
        self._create_mode_selector(layout)
        
        # Scope selection (only show if not editing existing mapping)
        if not self.mapping:
            self._create_scope_section(layout)
        
        # Simple mode form
        self.simple_form_group = self._create_simple_form()
        layout.addWidget(self.simple_form_group)
        
        # Advanced mode sections
        self.advanced_container = QWidget()
        advanced_layout = QVBoxLayout(self.advanced_container)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.setSpacing(2)
        
        # Semantic value for advanced mode
        self.advanced_semantic_group = self._create_advanced_semantic_section()
        advanced_layout.addWidget(self.advanced_semantic_group)
        
        # Conditions section
        self.conditions_group = self._create_conditions_section()
        advanced_layout.addWidget(self.conditions_group)
        
        # Logic selector
        self.logic_group = self._create_logic_selector()
        advanced_layout.addWidget(self.logic_group)
        
        # Rule preview
        self.preview_group = self._create_preview_section()
        advanced_layout.addWidget(self.preview_group)
        
        layout.addWidget(self.advanced_container)
        
        layout.addStretch()
        
        # Buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self.accept_mapping)
        
        # Add icons to buttons
        ok_button = button_box.button(QDialogButtonBox.Ok)
        if ok_button:
            CorrelationEngineStyles.add_button_icon(ok_button, "check", "#FFFFFF")
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        
        # Apply dark theme styling
        self._apply_styling()
        
        # Update visibility based on mode
        self._update_mode_visibility()
    
    def _create_mode_selector(self, layout):
        """Create mode selector (Simple/Advanced) with enhanced styling"""
        mode_container = QFrame()
        mode_container.setStyleSheet("""
            QFrame {
                background-color: #0F172A;
                border: 1px solid #1E3A5F;
                border-radius: 6px;
                padding: 4px;
            }
        """)
        mode_layout = QHBoxLayout(mode_container)
        mode_layout.setContentsMargins(10, 6, 10, 6)
        mode_layout.setSpacing(12)
        
        mode_label = QLabel("Mode:")
        mode_label.setStyleSheet("color: #94A3B8; font-weight: bold;")
        mode_layout.addWidget(mode_label)
        
        self.mode_button_group = QButtonGroup()
        
        self.simple_mode_radio = QRadioButton("📝 Simple (single value)")
        self.simple_mode_radio.setChecked(self.mode == 'simple')
        self.simple_mode_radio.toggled.connect(self._on_mode_changed)
        self.simple_mode_radio.setStyleSheet("""
            QRadioButton { color: #E5E7EB; padding: 4px 8px; }
            QRadioButton:checked { color: #00FFFF; font-weight: bold; }
        """)
        self.mode_button_group.addButton(self.simple_mode_radio)
        mode_layout.addWidget(self.simple_mode_radio)
        
        self.advanced_mode_radio = QRadioButton("⚡ Advanced (multi-value with AND/OR)")
        self.advanced_mode_radio.setChecked(self.mode == 'advanced')
        self.advanced_mode_radio.toggled.connect(self._on_mode_changed)
        self.advanced_mode_radio.setStyleSheet("""
            QRadioButton { color: #E5E7EB; padding: 4px 8px; }
            QRadioButton:checked { color: #00FFFF; font-weight: bold; }
        """)
        self.mode_button_group.addButton(self.advanced_mode_radio)
        mode_layout.addWidget(self.advanced_mode_radio)
        
        mode_layout.addStretch()
        layout.addWidget(mode_container)
    
    def _create_scope_section(self, layout):
        """Create scope selection section with enhanced styling"""
        scope_group = QGroupBox("📁 Mapping Scope")
        scope_layout = QHBoxLayout()
        scope_layout.setSpacing(20)
        scope_layout.setContentsMargins(12, 12, 12, 12)
        
        self.scope_button_group = QButtonGroup()
        
        self.global_radio = QRadioButton("🌐 Global (all Wings)")
        self.global_radio.setChecked(self.scope == 'global')
        self.global_radio.setStyleSheet("""
            QRadioButton { 
                color: #E5E7EB; 
                padding: 6px 10px;
                font-size: 10pt;
            }
            QRadioButton:checked { 
                color: #10B981; 
                font-weight: bold; 
            }
            QRadioButton::indicator {
                width: 16px;
                height: 16px;
            }
        """)
        self.scope_button_group.addButton(self.global_radio)
        scope_layout.addWidget(self.global_radio)
        
        self.wing_radio = QRadioButton("🦅 Wing-specific")
        self.wing_radio.setChecked(self.scope == 'wing')
        self.wing_radio.setEnabled(self.wing_id is not None)
        self.wing_radio.setStyleSheet("""
            QRadioButton { 
                color: #E5E7EB; 
                padding: 6px 10px;
                font-size: 10pt;
            }
            QRadioButton:checked { 
                color: #F59E0B; 
                font-weight: bold; 
            }
            QRadioButton:disabled { 
                color: #64748B; 
            }
            QRadioButton::indicator {
                width: 16px;
                height: 16px;
            }
        """)
        if self.wing_id is None:
            self.wing_radio.setToolTip("Only available when editing from Wings Creator")
        self.scope_button_group.addButton(self.wing_radio)
        scope_layout.addWidget(self.wing_radio)
        
        scope_layout.addStretch()
        
        scope_group.setLayout(scope_layout)
        scope_group.setMinimumHeight(60)
        layout.addWidget(scope_group)
    
    def _create_simple_form(self):
        """Create simple mode form with enhanced styling"""
        form_group = QGroupBox("📋 Mapping Details")
        form_layout = QFormLayout()
        form_layout.setSpacing(8)
        form_layout.setContentsMargins(12, 12, 12, 12)
        form_layout.setLabelAlignment(Qt.AlignRight)
        form_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        
        # Source (with dropdown)
        self.source_combo = QComboBox()
        self.source_combo.setEditable(True)
        self.source_combo.addItems([
            "SecurityLogs", "SystemLogs", "ApplicationLogs",
            "Prefetch", "ShimCache", "AmCache", "Registry",
            "SRUM", "MFT", "RecycleBin", "LNK", "Jumplists"
        ])
        self.source_combo.setCurrentText("")
        self.source_combo.setToolTip("The artifact source (e.g., SecurityLogs)")
        self.source_combo.setMinimumHeight(28)
        form_layout.addRow("Source*:", self.source_combo)
        
        # Field (with dropdown)
        self.field_combo = QComboBox()
        self.field_combo.setEditable(True)
        self.field_combo.addItems([
            "EventID", "Status", "Code", "Type", "Value", "Result"
        ])
        self.field_combo.setCurrentText("")
        self.field_combo.setToolTip("The field name containing the technical value")
        self.field_combo.setMinimumHeight(28)
        form_layout.addRow("Field*:", self.field_combo)
        
        # Technical Value
        self.technical_value_input = QLineEdit()
        self.technical_value_input.setPlaceholderText("e.g., 4624, 0x00000000")
        self.technical_value_input.setToolTip("The technical value to map")
        self.technical_value_input.setMinimumHeight(28)
        form_layout.addRow("Technical Value*:", self.technical_value_input)
        
        # Semantic Value
        self.semantic_value_input = QLineEdit()
        self.semantic_value_input.setPlaceholderText("e.g., User Login, Success")
        self.semantic_value_input.setToolTip("The human-readable meaning")
        self.semantic_value_input.setMinimumHeight(28)
        form_layout.addRow("Semantic Value*:", self.semantic_value_input)
        
        # Description
        self.description_input = QTextEdit()
        self.description_input.setPlaceholderText("Optional description...")
        self.description_input.setMinimumHeight(40)
        self.description_input.setMaximumHeight(60)
        form_layout.addRow("Description:", self.description_input)
        
        form_group.setLayout(form_layout)
        return form_group
    
    def _create_advanced_semantic_section(self):
        """Create semantic value section for advanced mode with enhanced styling"""
        group = QGroupBox("🎯 Rule Output")
        layout = QFormLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setLabelAlignment(Qt.AlignRight)
        layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        
        # Rule name
        self.rule_name_input = QLineEdit()
        self.rule_name_input.setPlaceholderText("e.g., Suspicious Login Pattern")
        self.rule_name_input.textChanged.connect(self._update_preview)
        self.rule_name_input.setMinimumHeight(28)
        layout.addRow("Rule Name*:", self.rule_name_input)
        
        # Semantic value for advanced mode
        self.advanced_semantic_input = QLineEdit()
        self.advanced_semantic_input.setPlaceholderText("e.g., Suspicious Activity")
        self.advanced_semantic_input.textChanged.connect(self._update_preview)
        self.advanced_semantic_input.setMinimumHeight(28)
        layout.addRow("Semantic Value*:", self.advanced_semantic_input)
        
        # Description for advanced mode
        self.advanced_description_input = QTextEdit()
        self.advanced_description_input.setPlaceholderText("Optional description...")
        self.advanced_description_input.setMinimumHeight(36)
        self.advanced_description_input.setMaximumHeight(50)
        layout.addRow("Description:", self.advanced_description_input)
        
        # Category and Severity in one row
        cat_sev_widget = QWidget()
        cat_sev_layout = QHBoxLayout(cat_sev_widget)
        cat_sev_layout.setContentsMargins(0, 0, 0, 0)
        cat_sev_layout.setSpacing(12)
        
        cat_label = QLabel("Category:")
        cat_label.setStyleSheet("font-weight: normal; color: #94A3B8;")
        cat_sev_layout.addWidget(cat_label)
        
        self.category_combo = QComboBox()
        self.category_combo.setEditable(True)
        self.category_combo.setMinimumWidth(160)
        self.category_combo.setMinimumHeight(28)
        self.category_combo.addItems([
            "", "authentication", "process_execution", "file_access",
            "network_activity", "persistence", "lateral_movement",
            "data_exfiltration", "suspicious_activity"
        ])
        cat_sev_layout.addWidget(self.category_combo)
        
        sev_label = QLabel("Severity:")
        sev_label.setStyleSheet("font-weight: normal; color: #94A3B8;")
        cat_sev_layout.addWidget(sev_label)
        
        self.severity_combo = QComboBox()
        self.severity_combo.setMinimumWidth(100)
        self.severity_combo.setMinimumHeight(28)
        self.severity_combo.addItems(["info", "low", "medium", "high", "critical"])
        cat_sev_layout.addWidget(self.severity_combo)
        cat_sev_layout.addStretch()
        
        layout.addRow("", cat_sev_widget)
        
        group.setLayout(layout)
        return group

    def _create_conditions_section(self):
        """Create section for managing multiple conditions with enhanced styling"""
        conditions_group = QGroupBox("📊 Input Conditions")
        layout = QVBoxLayout()
        layout.setSpacing(6)
        layout.setContentsMargins(12, 12, 12, 12)
        
        # Conditions table
        self.conditions_table = QTableWidget()
        self.conditions_table.setColumnCount(5)
        self.conditions_table.setHorizontalHeaderLabels([
            "Feather", "Field", "Operator", "Value", ""
        ])
        self.conditions_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.conditions_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.conditions_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self.conditions_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.conditions_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Fixed)
        self.conditions_table.setColumnWidth(2, 100)
        self.conditions_table.setColumnWidth(4, 40)
        self.conditions_table.setMinimumHeight(100)
        self.conditions_table.setMaximumHeight(150)
        self.conditions_table.setAlternatingRowColors(True)
        self.conditions_table.verticalHeader().setVisible(False)
        self.conditions_table.verticalHeader().setDefaultSectionSize(30)
        self.conditions_table.setShowGrid(False)
        self.conditions_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.conditions_table.setSelectionMode(QTableWidget.SingleSelection)
        
        # Apply dark theme styling to table header
        self.conditions_table.setStyleSheet("""
            QTableWidget {
                background-color: #111827;
                border: 1px solid #1E3A5F;
                border-radius: 4px;
                gridline-color: #1E3A5F;
                color: #F8FAFC;
                font-size: 9pt;
            }
            QTableWidget::item {
                padding: 4px 6px;
                border-bottom: 1px solid #1E3A5F;
            }
            QTableWidget::item:selected {
                background-color: #00FFFF;
                color: #0B1220;
            }
            QTableWidget::item:hover {
                background-color: #1E293B;
            }
            QTableWidget::item:alternate {
                background-color: #0F172A;
            }
            QHeaderView::section {
                background-color: #0F172A;
                color: #00FFFF;
                padding: 6px 8px;
                border: none;
                border-bottom: 2px solid #1E3A5F;
                font-weight: bold;
                font-size: 9pt;
            }
        """)
        layout.addWidget(self.conditions_table)
        
        # Add button - smaller and more compact
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 4, 0, 0)
        self.add_condition_btn = QPushButton("+ Add")
        self.add_condition_btn.setStyleSheet("""
            QPushButton {
                background-color: #10B981;
                color: white;
                border: none;
                border-radius: 3px;
                padding: 4px 12px;
                font-weight: bold;
                font-size: 9pt;
                max-width: 80px;
            }
            QPushButton:hover {
                background-color: #059669;
            }
            QPushButton:pressed {
                background-color: #047857;
            }
        """)
        self.add_condition_btn.clicked.connect(self._add_condition)
        btn_layout.addWidget(self.add_condition_btn)
        btn_layout.addStretch()
        
        # Help text
        help_label = QLabel("💡 Use * for wildcard")
        help_label.setStyleSheet("color: #64748B; font-size: 8pt; font-style: italic;")
        btn_layout.addWidget(help_label)
        
        layout.addLayout(btn_layout)
        
        conditions_group.setLayout(layout)
        return conditions_group
    
    def _create_logic_selector(self):
        """Create AND/OR logic selector with enhanced styling"""
        logic_group = QGroupBox("⚙️ Condition Logic")
        layout = QHBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        
        label = QLabel("Evaluate:")
        label.setStyleSheet("font-weight: normal; color: #94A3B8;")
        layout.addWidget(label)
        
        self.logic_combo = QComboBox()
        self.logic_combo.addItems([
            "AND - ALL must match",
            "OR - ANY must match"
        ])
        self.logic_combo.currentIndexChanged.connect(self._update_preview)
        self.logic_combo.setMinimumWidth(180)
        self.logic_combo.setMinimumHeight(26)
        layout.addWidget(self.logic_combo)
        
        # Visual indicator
        self.logic_indicator = QLabel("🔗")
        self.logic_indicator.setStyleSheet("font-size: 12pt;")
        self.logic_indicator.setToolTip("AND: All conditions must be true")
        layout.addWidget(self.logic_indicator)
        
        # Connect to update indicator
        self.logic_combo.currentIndexChanged.connect(self._update_logic_indicator)
        
        layout.addStretch()
        
        logic_group.setLayout(layout)
        logic_group.setMinimumHeight(55)
        logic_group.setMaximumHeight(65)
        return logic_group
    
    def _update_logic_indicator(self):
        """Update the logic indicator based on selection"""
        if self.logic_combo.currentIndex() == 0:
            self.logic_indicator.setText("🔗")
            self.logic_indicator.setToolTip("AND: All conditions must be true")
        else:
            self.logic_indicator.setText("🔀")
            self.logic_indicator.setToolTip("OR: Any condition can be true")
    
    def _update_logic_explanation(self):
        """Update the logic explanation text - no longer needed in compact mode"""
        pass
    
    def _create_preview_section(self):
        """Create rule preview section with enhanced styling"""
        preview_group = QGroupBox("👁️ Rule Preview")
        layout = QVBoxLayout()
        layout.setContentsMargins(12, 8, 12, 8)
        
        self.preview_label = QLabel()
        self.preview_label.setWordWrap(True)
        self.preview_label.setStyleSheet("""
            QLabel {
                background-color: #0F172A;
                border: 2px solid #1E3A5F;
                border-radius: 6px;
                padding: 10px;
                font-family: 'Consolas', 'Courier New', monospace;
                color: #00FFFF;
                font-size: 10pt;
                line-height: 1.4;
            }
        """)
        self.preview_label.setMinimumHeight(50)
        self.preview_label.setMaximumHeight(80)
        layout.addWidget(self.preview_label)
        
        preview_group.setLayout(layout)
        return preview_group
    
    def _add_condition(self):
        """Add a new condition row to the table with enhanced styling"""
        row = self.conditions_table.rowCount()
        self.conditions_table.insertRow(row)
        
        # Feather selector
        feather_combo = QComboBox()
        feather_combo.setEditable(True)
        feather_combo.setStyleSheet("QComboBox { padding: 4px 6px; font-size: 9pt; min-height: 24px; }")
        if self.available_feathers:
            feather_combo.addItems(self.available_feathers)
        else:
            # Default feather options
            feather_combo.addItems([
                "SecurityLogs", "SystemLogs", "ApplicationLogs",
                "Prefetch", "ShimCache", "AmCache", "Registry",
                "SRUM", "MFT", "RecycleBin", "LNK", "Jumplists"
            ])
        feather_combo.currentTextChanged.connect(self._update_preview)
        self.conditions_table.setCellWidget(row, 0, feather_combo)
        
        # Field input
        field_combo = QComboBox()
        field_combo.setEditable(True)
        field_combo.setStyleSheet("QComboBox { padding: 4px 6px; font-size: 9pt; min-height: 24px; }")
        field_combo.addItems([
            "EventID", "Status", "Code", "Type", "Value", "Result",
            "executable_name", "path", "user", "timestamp"
        ])
        field_combo.currentTextChanged.connect(self._update_preview)
        self.conditions_table.setCellWidget(row, 1, field_combo)
        
        # Operator selector
        operator_combo = QComboBox()
        operator_combo.setStyleSheet("QComboBox { padding: 4px 6px; font-size: 9pt; min-height: 24px; }")
        operator_combo.addItems(["equals", "contains", "regex", "wildcard (*)"])
        operator_combo.currentIndexChanged.connect(lambda: self._on_operator_changed(row))
        operator_combo.currentIndexChanged.connect(self._update_preview)
        self.conditions_table.setCellWidget(row, 2, operator_combo)
        
        # Value input with wildcard indicator
        value_widget = QWidget()
        value_layout = QHBoxLayout(value_widget)
        value_layout.setContentsMargins(2, 2, 2, 2)
        value_layout.setSpacing(4)
        
        value_edit = QLineEdit()
        value_edit.setPlaceholderText("Value or *")
        value_edit.setStyleSheet("QLineEdit { padding: 4px 6px; font-size: 9pt; min-height: 24px; }")
        value_edit.textChanged.connect(lambda: self._on_value_changed(row))
        value_edit.textChanged.connect(self._update_preview)
        value_layout.addWidget(value_edit)
        
        # Wildcard indicator
        wildcard_indicator = QLabel("✨")
        wildcard_indicator.setToolTip("Wildcard: matches any non-empty value")
        wildcard_indicator.setVisible(False)
        wildcard_indicator.setStyleSheet("font-size: 12px; padding: 0;")
        value_layout.addWidget(wildcard_indicator)
        
        self.conditions_table.setCellWidget(row, 3, value_widget)
        
        # Remove button
        remove_btn = QPushButton("✕")
        remove_btn.setStyleSheet("""
            QPushButton {
                background-color: #EF4444;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 4px 8px;
                font-weight: bold;
                font-size: 11pt;
                min-width: 28px;
                min-height: 28px;
            }
            QPushButton:hover {
                background-color: #DC2626;
            }
            QPushButton:pressed {
                background-color: #B91C1C;
            }
        """)
        remove_btn.clicked.connect(lambda: self._remove_condition(row))
        self.conditions_table.setCellWidget(row, 4, remove_btn)
        
        self._update_preview()
    
    def _remove_condition(self, row):
        """Remove a condition row"""
        # Find the actual row (may have changed due to previous removals)
        sender = self.sender()
        for r in range(self.conditions_table.rowCount()):
            if self.conditions_table.cellWidget(r, 4) == sender:
                self.conditions_table.removeRow(r)
                break
        self._update_preview()
    
    def _on_operator_changed(self, row):
        """Handle operator change - update value field for wildcard"""
        operator_combo = self.conditions_table.cellWidget(row, 2)
        value_widget = self.conditions_table.cellWidget(row, 3)
        
        if operator_combo and value_widget:
            value_edit = value_widget.findChild(QLineEdit)
            wildcard_indicator = value_widget.findChild(QLabel)
            
            if operator_combo.currentText() == "wildcard (*)":
                if value_edit:
                    value_edit.setText("*")
                    value_edit.setEnabled(False)
                if wildcard_indicator:
                    wildcard_indicator.setVisible(True)
            else:
                if value_edit:
                    if value_edit.text() == "*":
                        value_edit.setText("")
                    value_edit.setEnabled(True)
                if wildcard_indicator:
                    wildcard_indicator.setVisible(value_edit and value_edit.text() == "*")
    
    def _on_value_changed(self, row):
        """Handle value change - show wildcard indicator if * is entered"""
        value_widget = self.conditions_table.cellWidget(row, 3)
        if value_widget:
            value_edit = value_widget.findChild(QLineEdit)
            wildcard_indicator = value_widget.findChild(QLabel)
            
            if value_edit and wildcard_indicator:
                is_wildcard = value_edit.text().strip() == "*"
                wildcard_indicator.setVisible(is_wildcard)

    def _update_preview(self):
        """Update the rule preview"""
        if self.mode == 'simple' or self.simple_mode_radio.isChecked():
            return
        
        rule_name = self.rule_name_input.text().strip() or "[Rule Name]"
        semantic_value = self.advanced_semantic_input.text().strip() or "[Semantic Value]"
        logic = "AND" if self.logic_combo.currentIndex() == 0 else "OR"
        
        # Build conditions text
        conditions_text = []
        for row in range(self.conditions_table.rowCount()):
            feather_combo = self.conditions_table.cellWidget(row, 0)
            field_combo = self.conditions_table.cellWidget(row, 1)
            operator_combo = self.conditions_table.cellWidget(row, 2)
            value_widget = self.conditions_table.cellWidget(row, 3)
            
            if feather_combo and field_combo and operator_combo and value_widget:
                feather = feather_combo.currentText() or "[feather]"
                field_name = field_combo.currentText() or "[field]"
                operator = operator_combo.currentText().replace(" (*)", "")
                
                value_edit = value_widget.findChild(QLineEdit)
                value = value_edit.text() if value_edit else "[value]"
                
                if value == "*" or operator == "wildcard":
                    conditions_text.append(f"{feather}.{field_name} has any value")
                else:
                    conditions_text.append(f"{feather}.{field_name} {operator} '{value}'")
        
        if conditions_text:
            logic_word = f" {logic} "
            conditions_str = logic_word.join(conditions_text)
            preview = f"IF {conditions_str}\nTHEN → {semantic_value}"
        else:
            preview = f"'{rule_name}' → {semantic_value}\n(Add conditions to define when this rule matches)"
        
        self.preview_label.setText(preview)
    
    def _on_mode_changed(self):
        """Handle mode change between simple and advanced"""
        self.mode = 'advanced' if self.advanced_mode_radio.isChecked() else 'simple'
        self._update_mode_visibility()
    
    def _update_mode_visibility(self):
        """Update visibility of sections based on mode"""
        is_advanced = self.mode == 'advanced' or (hasattr(self, 'advanced_mode_radio') and self.advanced_mode_radio.isChecked())
        
        self.simple_form_group.setVisible(not is_advanced)
        self.advanced_container.setVisible(is_advanced)
        
        if is_advanced:
            self._update_preview()
    
    def _apply_styling(self):
        """Apply enhanced dark theme styling"""
        self.setStyleSheet("""
            QDialog {
                background-color: #0B1220;
                color: #E5E7EB;
                font-family: 'Segoe UI', sans-serif;
                font-size: 9pt;
            }
            QGroupBox {
                background-color: #111827;
                border: 1px solid #1E3A5F;
                border-radius: 6px;
                color: #00FFFF;
                font-weight: bold;
                font-size: 9pt;
                padding: 10px;
                padding-top: 20px;
                margin-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 10px;
                top: 2px;
                padding: 0 6px;
                background-color: #111827;
            }
            QLineEdit {
                background-color: #1E293B;
                border: 1px solid #334155;
                border-radius: 4px;
                padding: 6px 8px;
                color: #F8FAFC;
                font-size: 9pt;
                min-height: 24px;
            }
            QLineEdit:hover {
                border-color: #475569;
                background-color: #263449;
            }
            QLineEdit:focus {
                border-color: #00FFFF;
                background-color: #1E293B;
            }
            QLineEdit::placeholder {
                color: #64748B;
            }
            QTextEdit {
                background-color: #1E293B;
                border: 1px solid #334155;
                border-radius: 4px;
                padding: 6px;
                color: #F8FAFC;
                font-size: 9pt;
            }
            QTextEdit:hover {
                border-color: #475569;
            }
            QTextEdit:focus {
                border-color: #00FFFF;
            }
            QComboBox {
                background-color: #1E293B;
                border: 1px solid #334155;
                border-radius: 4px;
                padding: 6px 8px;
                color: #F8FAFC;
                font-size: 9pt;
                min-height: 24px;
            }
            QComboBox:hover {
                border-color: #475569;
                background-color: #263449;
            }
            QComboBox:focus {
                border-color: #00FFFF;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
                background-color: transparent;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 6px solid #00FFFF;
                width: 0;
                height: 0;
                margin-right: 6px;
            }
            QComboBox QAbstractItemView {
                background-color: #1E293B;
                color: #F8FAFC;
                selection-background-color: #00FFFF;
                selection-color: #0B1220;
                border: 1px solid #334155;
                border-radius: 4px;
                padding: 4px;
            }
            QRadioButton {
                color: #E5E7EB;
                font-size: 9pt;
                spacing: 6px;
                padding: 2px;
            }
            QRadioButton::indicator {
                width: 14px;
                height: 14px;
                border-radius: 7px;
                border: 2px solid #475569;
                background-color: #1E293B;
            }
            QRadioButton::indicator:hover {
                border-color: #00FFFF;
            }
            QRadioButton::indicator:checked {
                background-color: #00FFFF;
                border-color: #00FFFF;
            }
            QPushButton {
                background-color: #3B82F6;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 9pt;
            }
            QPushButton:hover {
                background-color: #2563EB;
            }
            QPushButton:pressed {
                background-color: #1D4ED8;
            }
            QLabel {
                color: #E5E7EB;
                font-size: 9pt;
            }
            QTableWidget {
                background-color: #111827;
                border: 1px solid #1E3A5F;
                border-radius: 6px;
                gridline-color: #1E3A5F;
                color: #F8FAFC;
                font-size: 9pt;
            }
            QTableWidget::item {
                padding: 4px 6px;
                border-bottom: 1px solid #1E3A5F;
            }
            QTableWidget::item:selected {
                background-color: #00FFFF;
                color: #0B1220;
            }
            QTableWidget::item:hover {
                background-color: #1E293B;
            }
            QTableWidget::item:alternate {
                background-color: #0F172A;
            }
            QHeaderView::section {
                background-color: #0F172A;
                color: #00FFFF;
                padding: 6px 8px;
                border: none;
                border-bottom: 2px solid #1E3A5F;
                font-weight: bold;
                font-size: 9pt;
            }
            QScrollBar:vertical {
                background-color: #111827;
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background-color: #334155;
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #475569;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
            QDialogButtonBox QPushButton {
                min-width: 90px;
                min-height: 28px;
            }
        """)
    def load_mapping(self):
        """Load existing mapping into form"""
        if self.mapping:
            # Simple mode fields
            self.source_combo.setCurrentText(self.mapping.get('source', ''))
            self.field_combo.setCurrentText(self.mapping.get('field', ''))
            self.technical_value_input.setText(self.mapping.get('technical_value', ''))
            self.semantic_value_input.setText(self.mapping.get('semantic_value', ''))
            self.description_input.setPlainText(self.mapping.get('description', ''))
            
            # Advanced mode fields
            if 'name' in self.mapping:
                self.rule_name_input.setText(self.mapping.get('name', ''))
            if 'semantic_value' in self.mapping:
                self.advanced_semantic_input.setText(self.mapping.get('semantic_value', ''))
            if 'description' in self.mapping:
                self.advanced_description_input.setPlainText(self.mapping.get('description', ''))
            if 'category' in self.mapping:
                self.category_combo.setCurrentText(self.mapping.get('category', ''))
            if 'severity' in self.mapping:
                idx = self.severity_combo.findText(self.mapping.get('severity', 'info'))
                if idx >= 0:
                    self.severity_combo.setCurrentIndex(idx)
            
            # Logic operator
            logic = self.mapping.get('logic_operator', 'AND')
            self.logic_combo.setCurrentIndex(0 if logic == 'AND' else 1)
            
            # Load conditions
            conditions = self.mapping.get('conditions', [])
            for cond in conditions:
                self._add_condition()
                row = self.conditions_table.rowCount() - 1
                
                feather_combo = self.conditions_table.cellWidget(row, 0)
                field_combo = self.conditions_table.cellWidget(row, 1)
                operator_combo = self.conditions_table.cellWidget(row, 2)
                value_widget = self.conditions_table.cellWidget(row, 3)
                
                if feather_combo:
                    feather_combo.setCurrentText(cond.get('feather_id', ''))
                if field_combo:
                    field_combo.setCurrentText(cond.get('field_name', ''))
                if operator_combo:
                    op = cond.get('operator', 'equals')
                    if op == 'wildcard':
                        op = 'wildcard (*)'
                    idx = operator_combo.findText(op)
                    if idx >= 0:
                        operator_combo.setCurrentIndex(idx)
                if value_widget:
                    value_edit = value_widget.findChild(QLineEdit)
                    if value_edit:
                        value_edit.setText(cond.get('value', ''))
            
            self._update_preview()

    def _validate_simple_mode(self):
        """Validate simple mode fields"""
        source = self.source_combo.currentText().strip()
        field = self.field_combo.currentText().strip()
        technical_value = self.technical_value_input.text().strip()
        semantic_value = self.semantic_value_input.text().strip()
        
        if not source:
            QMessageBox.warning(self, "Validation Error", "Source is required.")
            self.source_combo.setFocus()
            return False
        
        if not field:
            QMessageBox.warning(self, "Validation Error", "Field is required.")
            self.field_combo.setFocus()
            return False
        
        if not technical_value:
            QMessageBox.warning(self, "Validation Error", "Technical Value is required.")
            self.technical_value_input.setFocus()
            return False
        
        if not semantic_value:
            QMessageBox.warning(self, "Validation Error", "Semantic Value is required.")
            self.semantic_value_input.setFocus()
            return False
        
        return True
    
    def _validate_advanced_mode(self):
        """Validate advanced mode fields"""
        rule_name = self.rule_name_input.text().strip()
        semantic_value = self.advanced_semantic_input.text().strip()
        
        if not rule_name:
            QMessageBox.warning(self, "Validation Error", "Rule Name is required.")
            self.rule_name_input.setFocus()
            return False
        
        if not semantic_value:
            QMessageBox.warning(self, "Validation Error", "Semantic Value is required.")
            self.advanced_semantic_input.setFocus()
            return False
        
        # Require at least one condition
        if self.conditions_table.rowCount() == 0:
            QMessageBox.warning(
                self, "Validation Error", 
                "At least one condition is required for advanced rules.\n"
                "Click '+ Add Condition' to add a condition."
            )
            return False
        
        # Validate all conditions
        for row in range(self.conditions_table.rowCount()):
            feather_combo = self.conditions_table.cellWidget(row, 0)
            field_combo = self.conditions_table.cellWidget(row, 1)
            operator_combo = self.conditions_table.cellWidget(row, 2)
            value_widget = self.conditions_table.cellWidget(row, 3)
            
            feather = feather_combo.currentText().strip() if feather_combo else ""
            field_name = field_combo.currentText().strip() if field_combo else ""
            operator = operator_combo.currentText() if operator_combo else ""
            
            value = ""
            if value_widget:
                value_edit = value_widget.findChild(QLineEdit)
                if value_edit:
                    value = value_edit.text().strip()
            
            if not feather:
                QMessageBox.warning(
                    self, "Validation Error", 
                    f"Condition {row + 1}: Feather is required."
                )
                return False
            
            if not field_name:
                QMessageBox.warning(
                    self, "Validation Error", 
                    f"Condition {row + 1}: Field is required."
                )
                return False
            
            # Value is required unless operator is wildcard
            if not value and "wildcard" not in operator.lower():
                QMessageBox.warning(
                    self, "Validation Error", 
                    f"Condition {row + 1}: Value is required (or use wildcard operator)."
                )
                return False
        
        return True
    
    def accept_mapping(self):
        """Validate and accept the mapping"""
        is_advanced = self.mode == 'advanced' or self.advanced_mode_radio.isChecked()
        
        if is_advanced:
            if not self._validate_advanced_mode():
                return
        else:
            if not self._validate_simple_mode():
                return
        
        # Accept the dialog
        self.accept()
    
    def get_mapping(self):
        """
        Get the mapping data.
        
        Returns:
            Dictionary with mapping data including scope
        """
        is_advanced = self.mode == 'advanced' or self.advanced_mode_radio.isChecked()
        
        # Determine scope
        if self.mapping:
            # Editing existing mapping - keep original scope
            scope = self.mapping.get('scope', 'global')
        else:
            # New mapping - use selected scope
            scope = 'wing' if hasattr(self, 'wing_radio') and self.wing_radio.isChecked() else 'global'
        
        if is_advanced:
            # Build conditions list
            conditions = []
            for row in range(self.conditions_table.rowCount()):
                feather_combo = self.conditions_table.cellWidget(row, 0)
                field_combo = self.conditions_table.cellWidget(row, 1)
                operator_combo = self.conditions_table.cellWidget(row, 2)
                value_widget = self.conditions_table.cellWidget(row, 3)
                
                feather = feather_combo.currentText().strip() if feather_combo else ""
                field_name = field_combo.currentText().strip() if field_combo else ""
                operator = operator_combo.currentText() if operator_combo else "equals"
                
                # Clean up operator
                if "wildcard" in operator.lower():
                    operator = "wildcard"
                
                value = ""
                if value_widget:
                    value_edit = value_widget.findChild(QLineEdit)
                    if value_edit:
                        value = value_edit.text().strip()
                
                if feather and field_name:
                    conditions.append({
                        'feather_id': feather,
                        'field_name': field_name,
                        'value': value if value else "*",
                        'operator': operator
                    })
            
            # Get logic operator
            logic = "AND" if self.logic_combo.currentIndex() == 0 else "OR"
            
            mapping_data = {
                'rule_id': self.mapping.get('rule_id', str(uuid.uuid4())),
                'name': self.rule_name_input.text().strip(),
                'semantic_value': self.advanced_semantic_input.text().strip(),
                'description': self.advanced_description_input.toPlainText().strip(),
                'conditions': conditions,
                'logic_operator': logic,
                'scope': scope,
                'category': self.category_combo.currentText().strip(),
                'severity': self.severity_combo.currentText(),
                'confidence': 1.0,
                'mode': 'advanced'
            }
        else:
            # Simple mode
            mapping_data = {
                'source': self.source_combo.currentText().strip(),
                'field': self.field_combo.currentText().strip(),
                'technical_value': self.technical_value_input.text().strip(),
                'semantic_value': self.semantic_value_input.text().strip(),
                'description': self.description_input.toPlainText().strip(),
                'scope': scope,
                'mode': 'simple'
            }
        
        # Add wing_id if scope is wing
        if scope == 'wing' and self.wing_id:
            mapping_data['wing_id'] = self.wing_id
        
        return mapping_data
    
    def get_rule(self):
        """
        Get the mapping as a SemanticRule object (for advanced mode).
        
        Returns:
            SemanticRule object or None if in simple mode
        """
        mapping_data = self.get_mapping()
        
        if mapping_data.get('mode') != 'advanced':
            return None
        
        conditions = []
        for cond_data in mapping_data.get('conditions', []):
            conditions.append(SemanticCondition(
                feather_id=cond_data['feather_id'],
                field_name=cond_data['field_name'],
                value=cond_data['value'],
                operator=cond_data['operator']
            ))
        
        return SemanticRule(
            rule_id=mapping_data.get('rule_id', str(uuid.uuid4())),
            name=mapping_data.get('name', ''),
            semantic_value=mapping_data.get('semantic_value', ''),
            description=mapping_data.get('description', ''),
            conditions=conditions,
            logic_operator=mapping_data.get('logic_operator', 'AND'),
            scope=mapping_data.get('scope', 'global'),
            wing_id=mapping_data.get('wing_id'),
            category=mapping_data.get('category', ''),
            severity=mapping_data.get('severity', 'info'),
            confidence=mapping_data.get('confidence', 1.0)
        )
    
    def get_rule_data(self):
        """
        Get the rule data as a dictionary (alias for get_mapping for advanced mode).
        
        This method is used by Pipeline Builder and Wings Creator for consistency.
        
        Returns:
            Dictionary with rule data
        """
        return self.get_mapping()
