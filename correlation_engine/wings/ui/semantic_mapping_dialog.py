"""
Semantic Mapping Dialog
Dialog for adding/editing semantic mappings in Wings Creator.
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QTextEdit, QDialogButtonBox, QFormLayout, QGroupBox,
    QMessageBox, QComboBox, QRadioButton, QButtonGroup
)
from PyQt5.QtCore import Qt
from ...gui.ui_styling import CorrelationEngineStyles



class SemanticMappingDialog(QDialog):
    """Dialog for adding or editing a semantic mapping"""
    
    def __init__(self, parent=None, mapping=None, scope='global', wing_id=None):
        """
        Initialize the dialog.
        
        Args:
            parent: Parent widget
            mapping: Existing mapping dict to edit (None for new mapping)
            scope: Scope of the mapping ('global' or 'wing')
            wing_id: Wing ID if scope is 'wing'
        """
        super().__init__(parent)
        self.mapping = mapping or {}
        self.scope = scope
        self.wing_id = wing_id
        self.init_ui()
        self.load_mapping()
    
    def init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle("Semantic Mapping" if not self.mapping else "Edit Semantic Mapping")
        self.setMinimumWidth(650)
        self.setMinimumHeight(500)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        # Title
        title = QLabel("Add Semantic Mapping" if not self.mapping else "Edit Semantic Mapping")
        title.setStyleSheet("font-size: 14pt; font-weight: bold; color: #00d9ff;")
        layout.addWidget(title)
        
        # Help text
        help_text = QLabel(
            "Define how a technical value should be displayed in correlation results. "
            "For example, map Event ID '4624' to 'User Login'."
        )
        help_text.setWordWrap(True)
        help_text.setStyleSheet("color: #888; font-size: 9pt; margin-bottom: 10px;")
        layout.addWidget(help_text)
        
        # Scope selection (only show if not editing existing mapping)
        if not self.mapping:
            scope_group = QGroupBox("Mapping Scope")
            scope_layout = QVBoxLayout()
            scope_layout.setSpacing(10)
            
            self.scope_button_group = QButtonGroup()
            
            self.global_radio = QRadioButton("Global (applies to all Wings)")
            self.global_radio.setChecked(self.scope == 'global')
            self.scope_button_group.addButton(self.global_radio)
            scope_layout.addWidget(self.global_radio)
            
            self.wing_radio = QRadioButton("Wing-specific (applies only to this Wing)")
            self.wing_radio.setChecked(self.scope == 'wing')
            self.wing_radio.setEnabled(self.wing_id is not None)
            if self.wing_id is None:
                self.wing_radio.setToolTip("Only available when editing from Wings Creator")
            self.scope_button_group.addButton(self.wing_radio)
            scope_layout.addWidget(self.wing_radio)
            
            scope_help = QLabel(
                "💡 Global mappings apply to all Wings. Wing-specific mappings override global ones."
            )
            scope_help.setStyleSheet("color: #888; font-size: 8pt; font-style: italic;")
            scope_layout.addWidget(scope_help)
            
            scope_group.setLayout(scope_layout)
            layout.addWidget(scope_group)
        else:
            # Show current scope for existing mappings
            scope_label = QLabel(f"Scope: {self.mapping.get('scope', 'global').title()}")
            scope_label.setStyleSheet("color: #888; font-size: 9pt; font-style: italic;")
            layout.addWidget(scope_label)
        
        # Form group
        form_group = QGroupBox("Mapping Details")
        form_layout = QFormLayout()
        form_layout.setSpacing(10)
        
        # Source (with dropdown)
        self.source_combo = QComboBox()
        self.source_combo.setEditable(True)
        self.source_combo.addItems([
            "SecurityLogs",
            "SystemLogs",
            "ApplicationLogs",
            "Prefetch",
            "ShimCache",
            "AmCache",
            "Registry",
            "SRUM",
            "MFT",
            "RecycleBin",
            "LNK",
            "Jumplists"
        ])
        self.source_combo.setCurrentText("")
        form_layout.addRow("Source*:", self.source_combo)
        
        source_help = QLabel("The artifact source (e.g., SecurityLogs, SystemLogs)")
        source_help.setStyleSheet("color: #888; font-size: 8pt;")
        form_layout.addRow("", source_help)
        
        # Field (with dropdown)
        self.field_combo = QComboBox()
        self.field_combo.setEditable(True)
        self.field_combo.addItems([
            "EventID",
            "Status",
            "Code",
            "Type",
            "Value",
            "Result"
        ])
        self.field_combo.setCurrentText("")
        form_layout.addRow("Field*:", self.field_combo)
        
        field_help = QLabel("The field name containing the technical value")
        field_help.setStyleSheet("color: #888; font-size: 8pt;")
        form_layout.addRow("", field_help)
        
        # Technical Value
        self.technical_value_input = QLineEdit()
        self.technical_value_input.setPlaceholderText("e.g., 4624, 0x00000000")
        form_layout.addRow("Technical Value*:", self.technical_value_input)
        
        tech_help = QLabel("The technical value to map (e.g., Event ID, status code)")
        tech_help.setStyleSheet("color: #888; font-size: 8pt;")
        form_layout.addRow("", tech_help)
        
        # Semantic Value
        self.semantic_value_input = QLineEdit()
        self.semantic_value_input.setPlaceholderText("e.g., User Login, Success, Error")
        form_layout.addRow("Semantic Value*:", self.semantic_value_input)
        
        semantic_help = QLabel("The human-readable meaning")
        semantic_help.setStyleSheet("color: #888; font-size: 8pt;")
        form_layout.addRow("", semantic_help)
        
        # Description
        desc_label = QLabel("Description (optional):")
        form_layout.addRow(desc_label)
        
        self.description_input = QTextEdit()
        self.description_input.setPlaceholderText("Optional detailed description...")
        self.description_input.setMaximumHeight(80)
        form_layout.addRow(self.description_input)
        
        form_group.setLayout(form_layout)
        layout.addWidget(form_group)
        
        # Examples section
        examples_group = QGroupBox("Examples")
        examples_layout = QVBoxLayout()
        
        examples_text = QLabel(
            "• Source: SecurityLogs, Field: EventID, Technical: 4624, Semantic: User Login\n"
            "• Source: SystemLogs, Field: EventID, Technical: 6005, Semantic: System Startup\n"
            "• Source: Registry, Field: Status, Technical: 0x00000000, Semantic: Success"
        )
        examples_text.setStyleSheet("color: #888; font-size: 8pt; font-family: 'Consolas';")
        examples_layout.addWidget(examples_text)
        
        examples_group.setLayout(examples_layout)
        layout.addWidget(examples_group)
        
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
        self.setStyleSheet("""
            QDialog {
                background-color: #0B1220;
                color: #E5E7EB;
            }
            QGroupBox {
                background-color: #1a1f2e;
                border: 2px solid #334155;
                border-radius: 8px;
                color: #00d9ff;
                font-weight: bold;
                padding-top: 15px;
                margin-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QLineEdit, QTextEdit {
                background-color: #1a1f2e;
                border: 2px solid #334155;
                border-radius: 6px;
                padding: 8px;
                color: #E5E7EB;
                font-size: 10pt;
            }
            QLineEdit:focus, QTextEdit:focus, QComboBox:focus {
                border-color: #00d9ff;
            }
            QComboBox {
                background-color: #1a1f2e;
                border: 2px solid #334155;
                border-radius: 6px;
                padding: 8px;
                color: #E5E7EB;
                font-size: 10pt;
            }
            QComboBox::drop-down {
                border: none;
                width: 30px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 6px solid #00d9ff;
                width: 0;
                height: 0;
            }
            QComboBox QAbstractItemView {
                background-color: #1a1f2e;
                color: #E5E7EB;
                selection-background-color: #00d9ff;
                selection-color: #0B1220;
                border: 2px solid #334155;
            }
            QRadioButton {
                color: #E5E7EB;
                font-size: 10pt;
                spacing: 8px;
            }
            QRadioButton::indicator {
                width: 18px;
                height: 18px;
                border-radius: 9px;
                border: 2px solid #334155;
                background-color: #1a1f2e;
            }
            QRadioButton::indicator:checked {
                background-color: #00d9ff;
                border-color: #00d9ff;
            }
            QRadioButton::indicator:hover {
                border-color: #00d9ff;
            }
            QPushButton {
                background-color: #3B82F6;
                color: white;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2563EB;
            }
            QLabel {
                color: #E5E7EB;
            }
        """)
    
    def load_mapping(self):
        """Load existing mapping into form"""
        if self.mapping:
            self.source_combo.setCurrentText(self.mapping.get('source', ''))
            self.field_combo.setCurrentText(self.mapping.get('field', ''))
            self.technical_value_input.setText(self.mapping.get('technical_value', ''))
            self.semantic_value_input.setText(self.mapping.get('semantic_value', ''))
            self.description_input.setPlainText(self.mapping.get('description', ''))
    
    def accept_mapping(self):
        """Validate and accept the mapping"""
        # Validate required fields
        source = self.source_combo.currentText().strip()
        field = self.field_combo.currentText().strip()
        technical_value = self.technical_value_input.text().strip()
        semantic_value = self.semantic_value_input.text().strip()
        
        if not source:
            QMessageBox.warning(self, "Validation Error", "Source is required.")
            self.source_combo.setFocus()
            return
        
        if not field:
            QMessageBox.warning(self, "Validation Error", "Field is required.")
            self.field_combo.setFocus()
            return
        
        if not technical_value:
            QMessageBox.warning(self, "Validation Error", "Technical Value is required.")
            self.technical_value_input.setFocus()
            return
        
        if not semantic_value:
            QMessageBox.warning(self, "Validation Error", "Semantic Value is required.")
            self.semantic_value_input.setFocus()
            return
        
        # Accept the dialog
        self.accept()
    
    def get_mapping(self):
        """
        Get the mapping data.
        
        Returns:
            Dictionary with mapping data including scope
        """
        # Determine scope
        if self.mapping:
            # Editing existing mapping - keep original scope
            scope = self.mapping.get('scope', 'global')
        else:
            # New mapping - use selected scope
            scope = 'wing' if hasattr(self, 'wing_radio') and self.wing_radio.isChecked() else 'global'
        
        mapping_data = {
            'source': self.source_combo.currentText().strip(),
            'field': self.field_combo.currentText().strip(),
            'technical_value': self.technical_value_input.text().strip(),
            'semantic_value': self.semantic_value_input.text().strip(),
            'description': self.description_input.toPlainText().strip(),
            'scope': scope
        }
        
        # Add wing_id if scope is wing
        if scope == 'wing' and self.wing_id:
            mapping_data['wing_id'] = self.wing_id
        
        return mapping_data
