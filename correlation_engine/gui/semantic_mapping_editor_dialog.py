"""
Semantic Mapping Editor Dialog

Provides detailed editing interface for individual semantic mappings.
Allows users to create and edit semantic mappings with validation,
pattern matching, and condition support.

Features:
- Comprehensive mapping field editing
- Pattern matching with regex support
- Multi-field condition editor
- Real-time validation
- Preview functionality
- Template support
"""

import logging
import re
from typing import Optional, Dict, Any, List
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget, QLabel,
    QLineEdit, QPushButton, QGroupBox, QFormLayout, QComboBox, 
    QTextEdit, QMessageBox, QCheckBox, QSpinBox, QDoubleSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget,
    QScrollArea, QFrame, QSplitter
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QSyntaxHighlighter, QTextCharFormat, QColor

from ..config.semantic_mapping import SemanticMapping

logger = logging.getLogger(__name__)


class RegexHighlighter(QSyntaxHighlighter):
    """Syntax highlighter for regex patterns"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Define highlighting rules
        self.highlighting_rules = []
        
        # Character classes
        char_class_format = QTextCharFormat()
        char_class_format.setForeground(QColor(0, 128, 0))
        char_class_format.setFontWeight(QFont.Bold)
        self.highlighting_rules.append((r'\[.*?\]', char_class_format))
        
        # Quantifiers
        quantifier_format = QTextCharFormat()
        quantifier_format.setForeground(QColor(255, 0, 0))
        quantifier_format.setFontWeight(QFont.Bold)
        self.highlighting_rules.append((r'[*+?{}\d,]', quantifier_format))
        
        # Groups
        group_format = QTextCharFormat()
        group_format.setForeground(QColor(0, 0, 255))
        group_format.setFontWeight(QFont.Bold)
        self.highlighting_rules.append((r'[()]', group_format))
        
        # Anchors
        anchor_format = QTextCharFormat()
        anchor_format.setForeground(QColor(128, 0, 128))
        anchor_format.setFontWeight(QFont.Bold)
        self.highlighting_rules.append((r'[\^$]', anchor_format))
        
        # Escape sequences
        escape_format = QTextCharFormat()
        escape_format.setForeground(QColor(255, 128, 0))
        self.highlighting_rules.append((r'\\[a-zA-Z\d]', escape_format))
    
    def highlightBlock(self, text):
        """Apply syntax highlighting to text block"""
        for pattern, format in self.highlighting_rules:
            expression = re.compile(pattern)
            for match in expression.finditer(text):
                start, end = match.span()
                self.setFormat(start, end - start, format)


class SemanticMappingEditorDialog(QDialog):
    """
    Dialog for editing individual semantic mappings.
    
    Provides comprehensive interface for creating and editing semantic mappings
    with validation, pattern matching, and condition support.
    """
    
    # Signal emitted when mapping is saved
    mapping_saved = pyqtSignal(dict)  # mapping data
    
    def __init__(self, mapping_data: Optional[Dict[str, Any]] = None, parent=None):
        super().__init__(parent)
        
        self.mapping_data = mapping_data or {}
        self.is_editing = mapping_data is not None
        
        self.setWindowTitle("Edit Semantic Mapping" if self.is_editing else "New Semantic Mapping")
        self.setModal(True)
        self.resize(800, 600)
        
        self._setup_ui()
        self._load_mapping_data()
        self._connect_signals()
    
    def _setup_ui(self):
        """Setup the user interface"""
        layout = QVBoxLayout(self)
        
        # Create tab widget
        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)
        
        # Create tabs
        self._create_basic_tab()
        self._create_pattern_tab()
        self._create_conditions_tab()
        self._create_preview_tab()
        
        # Create button bar
        self._create_button_bar(layout)
    
    def _create_basic_tab(self):
        """Create basic mapping information tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Basic information group
        basic_group = QGroupBox("Basic Information")
        basic_layout = QFormLayout(basic_group)
        
        # Source
        self.source_edit = QLineEdit()
        self.source_edit.setPlaceholderText("e.g., SecurityLogs, Prefetch, Registry")
        basic_layout.addRow("Source:", self.source_edit)
        
        # Field
        self.field_edit = QLineEdit()
        self.field_edit.setPlaceholderText("e.g., EventID, Status, executable_name")
        basic_layout.addRow("Field:", self.field_edit)
        
        # Technical value
        self.technical_value_edit = QLineEdit()
        self.technical_value_edit.setPlaceholderText("e.g., 4624, chrome.exe, 0x0")
        basic_layout.addRow("Technical Value:", self.technical_value_edit)
        
        # Semantic value
        self.semantic_value_edit = QLineEdit()
        self.semantic_value_edit.setPlaceholderText("e.g., User Login, Web Browser, Success")
        basic_layout.addRow("Semantic Value:", self.semantic_value_edit)
        
        # Description
        self.description_edit = QTextEdit()
        self.description_edit.setMaximumHeight(80)
        self.description_edit.setPlaceholderText("Optional detailed description of this mapping")
        basic_layout.addRow("Description:", self.description_edit)
        
        layout.addWidget(basic_group)
        
        # Classification group
        classification_group = QGroupBox("Classification")
        classification_layout = QFormLayout(classification_group)
        
        # Artifact type
        self.artifact_type_combo = QComboBox()
        self.artifact_type_combo.setEditable(True)
        self.artifact_type_combo.addItems([
            "Logs", "Prefetch", "Registry", "SRUM", "AmCache", "ShimCache",
            "Jumplists", "LNK", "MFT", "USN", "Browser", "Network"
        ])
        classification_layout.addRow("Artifact Type:", self.artifact_type_combo)
        
        # Category
        self.category_combo = QComboBox()
        self.category_combo.setEditable(True)
        self.category_combo.addItems([
            "authentication", "process_execution", "file_access", "network_activity",
            "system_power", "user_activity", "application_usage", "security_event"
        ])
        classification_layout.addRow("Category:", self.category_combo)
        
        # Severity
        self.severity_combo = QComboBox()
        self.severity_combo.addItems(["info", "low", "medium", "high", "critical"])
        classification_layout.addRow("Severity:", self.severity_combo)
        
        # Confidence
        self.confidence_spin = QDoubleSpinBox()
        self.confidence_spin.setRange(0.0, 1.0)
        self.confidence_spin.setSingleStep(0.1)
        self.confidence_spin.setDecimals(2)
        self.confidence_spin.setValue(1.0)
        self.confidence_spin.setToolTip("Confidence level for this mapping (0.0 to 1.0)")
        classification_layout.addRow("Confidence:", self.confidence_spin)
        
        layout.addWidget(classification_group)
        
        # Scope group
        scope_group = QGroupBox("Scope")
        scope_layout = QFormLayout(scope_group)
        
        # Scope
        self.scope_combo = QComboBox()
        self.scope_combo.addItems(["global", "case", "wing", "pipeline"])
        scope_layout.addRow("Scope:", self.scope_combo)
        
        # Wing ID (for wing scope)
        self.wing_id_edit = QLineEdit()
        self.wing_id_edit.setPlaceholderText("Required for wing scope")
        scope_layout.addRow("Wing ID:", self.wing_id_edit)
        
        # Pipeline ID (for pipeline scope)
        self.pipeline_id_edit = QLineEdit()
        self.pipeline_id_edit.setPlaceholderText("Required for pipeline scope")
        scope_layout.addRow("Pipeline ID:", self.pipeline_id_edit)
        
        layout.addWidget(scope_group)
        layout.addStretch()
        
        self.tab_widget.addTab(tab, "Basic")
    
    def _create_pattern_tab(self):
        """Create pattern matching tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Pattern matching group
        pattern_group = QGroupBox("Pattern Matching")
        pattern_layout = QVBoxLayout(pattern_group)
        
        # Enable pattern matching
        self.use_pattern_cb = QCheckBox("Use regex pattern matching")
        self.use_pattern_cb.setToolTip("Enable regex pattern matching instead of exact matching")
        self.use_pattern_cb.toggled.connect(self._on_pattern_enabled_changed)
        pattern_layout.addWidget(self.use_pattern_cb)
        
        # Pattern input
        pattern_input_layout = QFormLayout()
        
        self.pattern_edit = QLineEdit()
        self.pattern_edit.setPlaceholderText("Enter regex pattern (e.g., chrome.*\\.exe)")
        pattern_input_layout.addRow("Pattern:", self.pattern_edit)
        
        pattern_layout.addLayout(pattern_input_layout)
        
        # Pattern editor with syntax highlighting
        pattern_editor_label = QLabel("Pattern Editor:")
        pattern_layout.addWidget(pattern_editor_label)
        
        self.pattern_text_edit = QTextEdit()
        self.pattern_text_edit.setMaximumHeight(100)
        self.pattern_text_edit.setPlaceholderText("Enter multi-line regex pattern here for complex patterns")
        
        # Add syntax highlighting
        self.regex_highlighter = RegexHighlighter(self.pattern_text_edit.document())
        
        pattern_layout.addWidget(self.pattern_text_edit)
        
        # Pattern validation
        validation_layout = QHBoxLayout()
        
        self.validate_pattern_btn = QPushButton("Validate Pattern")
        self.validate_pattern_btn.clicked.connect(self._validate_pattern)
        validation_layout.addWidget(self.validate_pattern_btn)
        
        validation_layout.addStretch()
        
        self.pattern_status_label = QLabel("Pattern not validated")
        validation_layout.addWidget(self.pattern_status_label)
        
        pattern_layout.addLayout(validation_layout)
        
        layout.addWidget(pattern_group)
        
        # Pattern testing group
        testing_group = QGroupBox("Pattern Testing")
        testing_layout = QVBoxLayout(testing_group)
        
        # Test input
        test_layout = QFormLayout()
        
        self.test_input_edit = QLineEdit()
        self.test_input_edit.setPlaceholderText("Enter test value to match against pattern")
        test_layout.addRow("Test Value:", self.test_input_edit)
        
        testing_layout.addLayout(test_layout)
        
        # Test button and results
        test_button_layout = QHBoxLayout()
        
        self.test_pattern_btn = QPushButton("Test Pattern")
        self.test_pattern_btn.clicked.connect(self._test_pattern)
        test_button_layout.addWidget(self.test_pattern_btn)
        
        test_button_layout.addStretch()
        
        self.test_result_label = QLabel("No test performed")
        test_button_layout.addWidget(self.test_result_label)
        
        testing_layout.addLayout(test_button_layout)
        
        layout.addWidget(testing_group)
        
        # Pattern examples
        examples_group = QGroupBox("Pattern Examples")
        examples_layout = QVBoxLayout(examples_group)
        
        examples_text = QTextEdit()
        examples_text.setReadOnly(True)
        examples_text.setMaximumHeight(120)
        examples_text.setPlainText(
            "Common Pattern Examples:\n"
            "• chrome.*\\.exe - Matches chrome.exe, chrome_proxy.exe, etc.\n"
            "• \\d{4} - Matches any 4-digit number (e.g., Event IDs)\n"
            "• ^(SUCCESS|FAILURE)$ - Matches exactly SUCCESS or FAILURE\n"
            "• .*\\.log$ - Matches any file ending with .log\n"
            "• [Ww]indows - Matches Windows or windows\n"
            "• \\b\\w+\\.exe\\b - Matches any executable filename"
        )
        examples_layout.addWidget(examples_text)
        
        layout.addWidget(examples_group)
        layout.addStretch()
        
        self.tab_widget.addTab(tab, "Pattern")
    
    def _create_conditions_tab(self):
        """Create multi-field conditions tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Conditions group
        conditions_group = QGroupBox("Multi-Field Conditions")
        conditions_layout = QVBoxLayout(conditions_group)
        
        # Enable conditions
        self.use_conditions_cb = QCheckBox("Use multi-field conditions")
        self.use_conditions_cb.setToolTip("Enable conditions that must be met for this mapping to apply")
        self.use_conditions_cb.toggled.connect(self._on_conditions_enabled_changed)
        conditions_layout.addWidget(self.use_conditions_cb)
        
        # Logic operator
        logic_layout = QHBoxLayout()
        logic_layout.addWidget(QLabel("Logic:"))
        
        self.logic_combo = QComboBox()
        self.logic_combo.addItems(["AND", "OR"])
        self.logic_combo.setToolTip("Logic operator for combining multiple conditions")
        logic_layout.addWidget(self.logic_combo)
        
        logic_layout.addStretch()
        conditions_layout.addLayout(logic_layout)
        
        # Conditions table
        self.conditions_table = QTableWidget()
        self.conditions_table.setColumnCount(4)
        self.conditions_table.setHorizontalHeaderLabels([
            "Field", "Operator", "Value", "Actions"
        ])
        
        # Set column widths
        header = self.conditions_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        
        conditions_layout.addWidget(self.conditions_table)
        
        # Conditions buttons
        conditions_buttons_layout = QHBoxLayout()
        
        self.add_condition_btn = QPushButton("Add Condition")
        self.add_condition_btn.clicked.connect(self._add_condition)
        conditions_buttons_layout.addWidget(self.add_condition_btn)
        
        self.remove_condition_btn = QPushButton("Remove Condition")
        self.remove_condition_btn.clicked.connect(self._remove_condition)
        conditions_buttons_layout.addWidget(self.remove_condition_btn)
        
        conditions_buttons_layout.addStretch()
        
        self.test_conditions_btn = QPushButton("Test Conditions")
        self.test_conditions_btn.clicked.connect(self._test_conditions)
        conditions_buttons_layout.addWidget(self.test_conditions_btn)
        
        conditions_layout.addLayout(conditions_buttons_layout)
        
        layout.addWidget(conditions_group)
        
        # Condition examples
        examples_group = QGroupBox("Condition Examples")
        examples_layout = QVBoxLayout(examples_group)
        
        examples_text = QTextEdit()
        examples_text.setReadOnly(True)
        examples_text.setMaximumHeight(100)
        examples_text.setPlainText(
            "Condition Examples:\n"
            "• LogonType equals 2 - Interactive logon\n"
            "• Status in [0x0, 0xC0000064] - Success or account not found\n"
            "• ProcessName regex .*chrome.* - Any Chrome process\n"
            "• EventTime greater_than 2023-01-01 - Events after date"
        )
        examples_layout.addWidget(examples_text)
        
        layout.addWidget(examples_group)
        layout.addStretch()
        
        self.tab_widget.addTab(tab, "Conditions")
    
    def _create_preview_tab(self):
        """Create mapping preview tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Preview group
        preview_group = QGroupBox("Mapping Preview")
        preview_layout = QVBoxLayout(preview_group)
        
        # Generate preview button
        self.generate_preview_btn = QPushButton("Generate Preview")
        self.generate_preview_btn.clicked.connect(self._generate_preview)
        preview_layout.addWidget(self.generate_preview_btn)
        
        # Preview display
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        preview_layout.addWidget(self.preview_text)
        
        layout.addWidget(preview_group)
        
        # Test data group
        test_group = QGroupBox("Test Data")
        test_layout = QVBoxLayout(test_group)
        
        test_layout.addWidget(QLabel("Enter test record data (JSON format):"))
        
        self.test_data_edit = QTextEdit()
        self.test_data_edit.setMaximumHeight(150)
        self.test_data_edit.setPlaceholderText(
            '{\n'
            '  "EventID": "4624",\n'
            '  "LogonType": "2",\n'
            '  "Status": "0x0",\n'
            '  "ProcessName": "chrome.exe"\n'
            '}'
        )
        test_layout.addWidget(self.test_data_edit)
        
        # Test mapping button
        test_button_layout = QHBoxLayout()
        
        self.test_mapping_btn = QPushButton("Test Mapping")
        self.test_mapping_btn.clicked.connect(self._test_mapping)
        test_button_layout.addWidget(self.test_mapping_btn)
        
        test_button_layout.addStretch()
        
        self.test_mapping_result_label = QLabel("No test performed")
        test_button_layout.addWidget(self.test_mapping_result_label)
        
        test_layout.addLayout(test_button_layout)
        
        layout.addWidget(test_group)
        
        self.tab_widget.addTab(tab, "Preview")
    
    def _create_button_bar(self, parent_layout):
        """Create dialog button bar"""
        button_layout = QHBoxLayout()
        
        # Template buttons
        self.load_template_btn = QPushButton("Load Template")
        self.load_template_btn.clicked.connect(self._load_template)
        button_layout.addWidget(self.load_template_btn)
        
        self.save_template_btn = QPushButton("Save as Template")
        self.save_template_btn.clicked.connect(self._save_template)
        button_layout.addWidget(self.save_template_btn)
        
        button_layout.addStretch()
        
        # Standard buttons
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_btn)
        
        self.ok_btn = QPushButton("OK")
        self.ok_btn.clicked.connect(self._save_mapping)
        self.ok_btn.setDefault(True)
        button_layout.addWidget(self.ok_btn)
        
        parent_layout.addLayout(button_layout)
    
    def _connect_signals(self):
        """Connect UI signals"""
        # Update preview when basic fields change
        self.source_edit.textChanged.connect(self._on_basic_field_changed)
        self.field_edit.textChanged.connect(self._on_basic_field_changed)
        self.technical_value_edit.textChanged.connect(self._on_basic_field_changed)
        self.semantic_value_edit.textChanged.connect(self._on_basic_field_changed)
        
        # Update pattern when text changes
        self.pattern_edit.textChanged.connect(self._on_pattern_changed)
        self.pattern_text_edit.textChanged.connect(self._on_pattern_changed)
        
        # Enable/disable controls
        self._on_pattern_enabled_changed()
        self._on_conditions_enabled_changed()
    
    def _load_mapping_data(self):
        """Load existing mapping data into UI"""
        if not self.mapping_data:
            return
        
        # Basic information
        self.source_edit.setText(self.mapping_data.get('source', ''))
        self.field_edit.setText(self.mapping_data.get('field', ''))
        self.technical_value_edit.setText(self.mapping_data.get('technical_value', ''))
        self.semantic_value_edit.setText(self.mapping_data.get('semantic_value', ''))
        self.description_edit.setPlainText(self.mapping_data.get('description', ''))
        
        # Classification
        self.artifact_type_combo.setCurrentText(self.mapping_data.get('artifact_type', ''))
        self.category_combo.setCurrentText(self.mapping_data.get('category', ''))
        self.severity_combo.setCurrentText(self.mapping_data.get('severity', 'info'))
        self.confidence_spin.setValue(self.mapping_data.get('confidence', 1.0))
        
        # Scope
        self.scope_combo.setCurrentText(self.mapping_data.get('scope', 'global'))
        self.wing_id_edit.setText(self.mapping_data.get('wing_id', ''))
        self.pipeline_id_edit.setText(self.mapping_data.get('pipeline_id', ''))
        
        # Pattern
        pattern = self.mapping_data.get('pattern', '')
        if pattern:
            self.use_pattern_cb.setChecked(True)
            self.pattern_edit.setText(pattern)
            self.pattern_text_edit.setPlainText(pattern)
        
        # Conditions
        conditions = self.mapping_data.get('conditions', [])
        if conditions:
            self.use_conditions_cb.setChecked(True)
            self._load_conditions(conditions)
    
    def _load_conditions(self, conditions: List[Dict[str, Any]]):
        """Load conditions into the conditions table"""
        self.conditions_table.setRowCount(len(conditions))
        
        for row, condition in enumerate(conditions):
            # Field
            field_item = QTableWidgetItem(condition.get('field', ''))
            self.conditions_table.setItem(row, 0, field_item)
            
            # Operator
            operator_combo = QComboBox()
            operator_combo.addItems([
                "equals", "in", "regex", "greater_than", "less_than", "contains"
            ])
            operator_combo.setCurrentText(condition.get('operator', 'equals'))
            self.conditions_table.setCellWidget(row, 1, operator_combo)
            
            # Value
            value = condition.get('value', '')
            if isinstance(value, list):
                value = ', '.join(str(v) for v in value)
            value_item = QTableWidgetItem(str(value))
            self.conditions_table.setItem(row, 2, value_item)
            
            # Actions
            remove_btn = QPushButton("Remove")
            remove_btn.clicked.connect(lambda checked, r=row: self._remove_condition_row(r))
            self.conditions_table.setCellWidget(row, 3, remove_btn)
    
    def _on_basic_field_changed(self):
        """Handle basic field changes"""
        # Auto-generate preview when basic fields change
        if self.tab_widget.currentIndex() == 3:  # Preview tab
            self._generate_preview()
    
    def _on_pattern_changed(self):
        """Handle pattern changes"""
        # Sync pattern between line edit and text edit
        sender = self.sender()
        if sender == self.pattern_edit:
            self.pattern_text_edit.setPlainText(self.pattern_edit.text())
        elif sender == self.pattern_text_edit:
            pattern_text = self.pattern_text_edit.toPlainText()
            if '\n' not in pattern_text:
                self.pattern_edit.setText(pattern_text)
        
        # Reset validation status
        self.pattern_status_label.setText("Pattern not validated")
        self.pattern_status_label.setStyleSheet("")
    
    def _on_pattern_enabled_changed(self):
        """Handle pattern enabled state change"""
        enabled = self.use_pattern_cb.isChecked()
        
        self.pattern_edit.setEnabled(enabled)
        self.pattern_text_edit.setEnabled(enabled)
        self.validate_pattern_btn.setEnabled(enabled)
        self.test_pattern_btn.setEnabled(enabled)
        self.test_input_edit.setEnabled(enabled)
    
    def _on_conditions_enabled_changed(self):
        """Handle conditions enabled state change"""
        enabled = self.use_conditions_cb.isChecked()
        
        self.logic_combo.setEnabled(enabled)
        self.conditions_table.setEnabled(enabled)
        self.add_condition_btn.setEnabled(enabled)
        self.remove_condition_btn.setEnabled(enabled)
        self.test_conditions_btn.setEnabled(enabled)
    
    def _validate_pattern(self):
        """Validate the regex pattern"""
        pattern = self.pattern_text_edit.toPlainText() or self.pattern_edit.text()
        
        if not pattern:
            self.pattern_status_label.setText("No pattern to validate")
            self.pattern_status_label.setStyleSheet("color: orange;")
            return
        
        try:
            re.compile(pattern, re.IGNORECASE)
            self.pattern_status_label.setText("✓ Pattern is valid")
            self.pattern_status_label.setStyleSheet("color: green;")
        except re.error as e:
            self.pattern_status_label.setText(f"✗ Invalid pattern: {e}")
            self.pattern_status_label.setStyleSheet("color: red;")
    
    def _test_pattern(self):
        """Test the pattern against test input"""
        pattern = self.pattern_text_edit.toPlainText() or self.pattern_edit.text()
        test_value = self.test_input_edit.text()
        
        if not pattern or not test_value:
            self.test_result_label.setText("Enter pattern and test value")
            self.test_result_label.setStyleSheet("color: orange;")
            return
        
        try:
            compiled_pattern = re.compile(pattern, re.IGNORECASE)
            if compiled_pattern.search(test_value):
                self.test_result_label.setText("✓ Pattern matches")
                self.test_result_label.setStyleSheet("color: green;")
            else:
                self.test_result_label.setText("✗ Pattern does not match")
                self.test_result_label.setStyleSheet("color: red;")
        except re.error as e:
            self.test_result_label.setText(f"✗ Pattern error: {e}")
            self.test_result_label.setStyleSheet("color: red;")
    
    def _add_condition(self):
        """Add a new condition row"""
        row = self.conditions_table.rowCount()
        self.conditions_table.insertRow(row)
        
        # Field
        field_item = QTableWidgetItem("")
        self.conditions_table.setItem(row, 0, field_item)
        
        # Operator
        operator_combo = QComboBox()
        operator_combo.addItems([
            "equals", "in", "regex", "greater_than", "less_than", "contains"
        ])
        self.conditions_table.setCellWidget(row, 1, operator_combo)
        
        # Value
        value_item = QTableWidgetItem("")
        self.conditions_table.setItem(row, 2, value_item)
        
        # Actions
        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(lambda checked, r=row: self._remove_condition_row(r))
        self.conditions_table.setCellWidget(row, 3, remove_btn)
    
    def _remove_condition(self):
        """Remove selected condition"""
        current_row = self.conditions_table.currentRow()
        if current_row >= 0:
            self.conditions_table.removeRow(current_row)
    
    def _remove_condition_row(self, row: int):
        """Remove specific condition row"""
        if 0 <= row < self.conditions_table.rowCount():
            self.conditions_table.removeRow(row)
    
    def _test_conditions(self):
        """Test conditions against sample data"""
        QMessageBox.information(
            self, "Test Conditions",
            "Condition testing would be implemented here.\n"
            "This would test the conditions against sample record data."
        )
    
    def _generate_preview(self):
        """Generate mapping preview"""
        mapping_data = self._get_mapping_data()
        
        preview_lines = []
        preview_lines.append("=== Semantic Mapping Preview ===\n")
        
        # Basic information
        preview_lines.append("Basic Information:")
        preview_lines.append(f"  Source: {mapping_data.get('source', 'Not specified')}")
        preview_lines.append(f"  Field: {mapping_data.get('field', 'Not specified')}")
        preview_lines.append(f"  Technical Value: {mapping_data.get('technical_value', 'Not specified')}")
        preview_lines.append(f"  Semantic Value: {mapping_data.get('semantic_value', 'Not specified')}")
        
        if mapping_data.get('description'):
            preview_lines.append(f"  Description: {mapping_data['description']}")
        
        preview_lines.append("")
        
        # Classification
        preview_lines.append("Classification:")
        preview_lines.append(f"  Artifact Type: {mapping_data.get('artifact_type', 'Not specified')}")
        preview_lines.append(f"  Category: {mapping_data.get('category', 'Not specified')}")
        preview_lines.append(f"  Severity: {mapping_data.get('severity', 'info')}")
        preview_lines.append(f"  Confidence: {mapping_data.get('confidence', 1.0)}")
        preview_lines.append("")
        
        # Pattern matching
        if mapping_data.get('pattern'):
            preview_lines.append("Pattern Matching:")
            preview_lines.append(f"  Pattern: {mapping_data['pattern']}")
            preview_lines.append("  Matching Type: Regex pattern")
        else:
            preview_lines.append("Matching Type: Exact match")
        
        preview_lines.append("")
        
        # Conditions
        conditions = mapping_data.get('conditions', [])
        if conditions:
            preview_lines.append("Conditions:")
            logic = mapping_data.get('logic', 'AND')
            preview_lines.append(f"  Logic: {logic}")
            for i, condition in enumerate(conditions):
                preview_lines.append(f"  {i+1}. {condition.get('field')} {condition.get('operator')} {condition.get('value')}")
        else:
            preview_lines.append("Conditions: None")
        
        preview_lines.append("")
        
        # Scope
        preview_lines.append("Scope:")
        preview_lines.append(f"  Scope: {mapping_data.get('scope', 'global')}")
        if mapping_data.get('wing_id'):
            preview_lines.append(f"  Wing ID: {mapping_data['wing_id']}")
        if mapping_data.get('pipeline_id'):
            preview_lines.append(f"  Pipeline ID: {mapping_data['pipeline_id']}")
        
        self.preview_text.setPlainText("\n".join(preview_lines))
    
    def _test_mapping(self):
        """Test mapping against test data"""
        try:
            import json
            test_data_text = self.test_data_edit.toPlainText()
            if not test_data_text:
                self.test_mapping_result_label.setText("Enter test data")
                self.test_mapping_result_label.setStyleSheet("color: orange;")
                return
            
            test_data = json.loads(test_data_text)
            mapping_data = self._get_mapping_data()
            
            # Create SemanticMapping object
            mapping = SemanticMapping(**mapping_data)
            
            # Test if mapping matches
            field_value = test_data.get(mapping.field, '')
            matches_value = mapping.matches(str(field_value))
            matches_conditions = mapping.evaluate_conditions(test_data)
            
            if matches_value and matches_conditions:
                self.test_mapping_result_label.setText("✓ Mapping matches test data")
                self.test_mapping_result_label.setStyleSheet("color: green;")
            else:
                reasons = []
                if not matches_value:
                    reasons.append("value doesn't match")
                if not matches_conditions:
                    reasons.append("conditions not met")
                
                self.test_mapping_result_label.setText(f"✗ Mapping doesn't match: {', '.join(reasons)}")
                self.test_mapping_result_label.setStyleSheet("color: red;")
            
        except json.JSONDecodeError:
            self.test_mapping_result_label.setText("✗ Invalid JSON in test data")
            self.test_mapping_result_label.setStyleSheet("color: red;")
        except Exception as e:
            self.test_mapping_result_label.setText(f"✗ Test error: {e}")
            self.test_mapping_result_label.setStyleSheet("color: red;")
    
    def _load_template(self):
        """Load mapping from template"""
        QMessageBox.information(
            self, "Load Template",
            "Template loading would be implemented here.\n"
            "This would allow loading predefined mapping templates."
        )
    
    def _save_template(self):
        """Save current mapping as template"""
        QMessageBox.information(
            self, "Save Template",
            "Template saving would be implemented here.\n"
            "This would allow saving the current mapping as a reusable template."
        )
    
    def _get_mapping_data(self) -> Dict[str, Any]:
        """Get current mapping data from UI"""
        mapping_data = {
            'source': self.source_edit.text(),
            'field': self.field_edit.text(),
            'technical_value': self.technical_value_edit.text(),
            'semantic_value': self.semantic_value_edit.text(),
            'description': self.description_edit.toPlainText(),
            'artifact_type': self.artifact_type_combo.currentText(),
            'category': self.category_combo.currentText(),
            'severity': self.severity_combo.currentText(),
            'confidence': self.confidence_spin.value(),
            'scope': self.scope_combo.currentText(),
            'wing_id': self.wing_id_edit.text() or None,
            'pipeline_id': self.pipeline_id_edit.text() or None
        }
        
        # Pattern
        if self.use_pattern_cb.isChecked():
            pattern = self.pattern_text_edit.toPlainText() or self.pattern_edit.text()
            if pattern:
                mapping_data['pattern'] = pattern
        
        # Conditions
        if self.use_conditions_cb.isChecked():
            conditions = []
            for row in range(self.conditions_table.rowCount()):
                field_item = self.conditions_table.item(row, 0)
                operator_combo = self.conditions_table.cellWidget(row, 1)
                value_item = self.conditions_table.item(row, 2)
                
                if field_item and operator_combo and value_item:
                    field = field_item.text()
                    operator = operator_combo.currentText()
                    value = value_item.text()
                    
                    # Parse value for 'in' operator
                    if operator == 'in' and ',' in value:
                        value = [v.strip() for v in value.split(',')]
                    
                    if field and value:
                        conditions.append({
                            'field': field,
                            'operator': operator,
                            'value': value
                        })
            
            if conditions:
                mapping_data['conditions'] = conditions
                mapping_data['logic'] = self.logic_combo.currentText()
        
        return mapping_data
    
    def _validate_mapping(self) -> List[str]:
        """Validate current mapping data"""
        errors = []
        
        # Required fields
        if not self.source_edit.text():
            errors.append("Source is required")
        if not self.field_edit.text():
            errors.append("Field is required")
        if not self.technical_value_edit.text() and not self.use_pattern_cb.isChecked():
            errors.append("Technical value is required when not using pattern matching")
        if not self.semantic_value_edit.text():
            errors.append("Semantic value is required")
        
        # Pattern validation
        if self.use_pattern_cb.isChecked():
            pattern = self.pattern_text_edit.toPlainText() or self.pattern_edit.text()
            if not pattern:
                errors.append("Pattern is required when pattern matching is enabled")
            else:
                try:
                    re.compile(pattern, re.IGNORECASE)
                except re.error as e:
                    errors.append(f"Invalid regex pattern: {e}")
        
        # Scope validation
        scope = self.scope_combo.currentText()
        if scope == 'wing' and not self.wing_id_edit.text():
            errors.append("Wing ID is required for wing scope")
        if scope == 'pipeline' and not self.pipeline_id_edit.text():
            errors.append("Pipeline ID is required for pipeline scope")
        
        return errors
    
    def _save_mapping(self):
        """Save the mapping"""
        # Validate mapping
        errors = self._validate_mapping()
        if errors:
            QMessageBox.warning(
                self, "Validation Errors",
                "Please fix the following errors:\n\n" + "\n".join(f"• {error}" for error in errors)
            )
            return
        
        # Get mapping data
        mapping_data = self._get_mapping_data()
        
        # Emit signal
        self.mapping_saved.emit(mapping_data)
        
        # Close dialog
        self.accept()