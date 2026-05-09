"""
Case Setup Dialog for EYE AI Forensic Assistant

This module provides dialogs for case context management:
- CaseSetupDialog: First-time case context initialization
- CaseContextEditDialog: Edit existing case context

The dialogs prompt investigators to enter case-specific information including:
- Investigation Reason (required)
- Primary Suspects (optional)
- Investigation Objectives (optional)
- Expected Evidence Types (optional)

"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTextEdit, QGroupBox, QMessageBox, QFormLayout,
    QScrollArea, QWidget
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QPalette, QColor


class CaseSetupDialog(QDialog):
    """
    Dialog for first-time case context initialization.
    
    Prompts investigators to enter case-specific information that will be used
    to tailor EYE's responses to the investigation objectives. The Investigation
    Reason field is required, while other fields are optional.
    
    The dialog follows the UI pattern from OnboardingWizard with dark theme styling
    and user-friendly form layout.
    
    """
    
    case_context_initialized = pyqtSignal(dict)  # Emits case context on completion
    
    def __init__(self, parent=None):
        """
        Initialize the case setup dialog.
        
        Args:
            parent: Parent widget (typically the main window or EYE tab)
        """
        super().__init__(parent)
        
        # Set window flags for independent styling
        self.setWindowFlags(self.windowFlags() | Qt.Window)
        
        # Case context data
        self.case_context = {
            "investigation_reason": "",
            "primary_suspects": "",
            "investigation_objectives": "",
            "expected_evidence_types": ""
        }
        
        self._init_ui()
        self._apply_styling()
    
    def _init_ui(self):
        """Initialize the user interface components."""
        self.setWindowTitle("Case Setup - EYE Assistant")
        self.setMinimumSize(800, 600)
        self.resize(900, 750)
        
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(16)
        main_layout.setContentsMargins(40, 40, 40, 20)
        
        # Title
        title = QLabel("Initialize Case Context")
        title.setStyleSheet(
            "font-size: 18pt; font-weight: bold; color: #00FFFF; background: transparent;"
        )
        title.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title)
        
        # Subtitle
        subtitle = QLabel(
            "Provide information about your investigation to help EYE tailor responses to your case objectives."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(
            "font-size: 11pt; color: #9CA3AF; background: transparent;"
        )
        subtitle.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(subtitle)
        
        main_layout.addSpacing(10)
        
        # Scroll Area for the form
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                border: none;
                background: #0B1220;
                width: 10px;
                margin: 0px 0px 0px 0px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background: #334155;
                min-height: 20px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover {
                background: #475569;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        """)
        
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 10, 0) # Small right margin for scrollbar
        scroll_layout.setSpacing(20)

        # Form group
        form_group = QGroupBox()
        form_group.setStyleSheet("""
            QGroupBox {
                border: 2px solid #334155;
                border-radius: 8px;
                padding-top: 20px;
                margin-top: 10px;
                background: #111827;
            }
        """)
        
        form_layout = QVBoxLayout()
        form_layout.setContentsMargins(20, 20, 20, 20)
        form_layout.setSpacing(20)
        
        # Investigation Reason (required)
        reason_label = QLabel("Investigation Reason <span style='color: #EF4444;'>*</span>")
        reason_label.setStyleSheet(
            "font-size: 11pt; font-weight: bold; color: #E5E7EB; background: transparent;"
        )
        form_layout.addWidget(reason_label)
        
        reason_help = QLabel(
            "Describe the primary objective or question driving this investigation."
        )
        reason_help.setWordWrap(True)
        reason_help.setStyleSheet(
            "font-size: 9pt; color: #9CA3AF; background: transparent; margin-left: 4px; margin-top: 2px;"
        )
        form_layout.addWidget(reason_help)
        
        self.investigation_reason_input = QTextEdit()
        self.investigation_reason_input.setPlaceholderText(
            "Example: Suspected data exfiltration by insider threat\n"
            "Example: Malware infection analysis and timeline reconstruction\n"
            "Example: Investigation of unauthorized access to financial systems"
        )
        self.investigation_reason_input.setMinimumHeight(100)
        self.investigation_reason_input.setMaximumHeight(120)
        self.investigation_reason_input.setStyleSheet("""
            QTextEdit {
                background: #1E293B;
                border: 2px solid #334155;
                padding: 10px;
                color: #F8FAFC;
                font-size: 10pt;
                border-radius: 4px;
            }
            QTextEdit:focus {
                border: 2px solid #00FFFF;
            }
        """)
        form_layout.addWidget(self.investigation_reason_input)
        
        # Primary Suspects (optional)
        suspects_label = QLabel("Primary Suspects")
        suspects_label.setStyleSheet(
            "font-size: 11pt; font-weight: bold; color: #E5E7EB; background: transparent;"
        )
        form_layout.addWidget(suspects_label)
        
        suspects_help = QLabel(
            "List suspects or entities under investigation (comma-separated)."
        )
        suspects_help.setWordWrap(True)
        suspects_help.setStyleSheet(
            "font-size: 9pt; color: #9CA3AF; background: transparent; margin-left: 4px; margin-top: 2px;"
        )
        form_layout.addWidget(suspects_help)
        
        self.primary_suspects_input = QLineEdit()
        self.primary_suspects_input.setPlaceholderText(
            "Example: John Doe, Jane Smith, External IP 192.168.1.100"
        )
        self.primary_suspects_input.setMinimumHeight(40)
        self.primary_suspects_input.setStyleSheet("""
            QLineEdit {
                background: #1E293B;
                border: 2px solid #334155;
                padding: 10px;
                color: #F8FAFC;
                font-size: 10pt;
                border-radius: 4px;
            }
            QLineEdit:focus {
                border: 2px solid #00FFFF;
            }
        """)
        form_layout.addWidget(self.primary_suspects_input)
        
        # Investigation Objectives (optional)
        objectives_label = QLabel("Investigation Objectives")
        objectives_label.setStyleSheet(
            "font-size: 11pt; font-weight: bold; color: #E5E7EB; background: transparent;"
        )
        form_layout.addWidget(objectives_label)
        
        objectives_help = QLabel(
            "List specific objectives for this investigation (one per line)."
        )
        objectives_help.setWordWrap(True)
        objectives_help.setStyleSheet(
            "font-size: 9pt; color: #9CA3AF; background: transparent; margin-left: 4px; margin-top: 2px;"
        )
        form_layout.addWidget(objectives_help)
        
        self.investigation_objectives_input = QTextEdit()
        self.investigation_objectives_input.setPlaceholderText(
            "Example:\n"
            "- Identify all files accessed by suspect\n"
            "- Determine timeline of malicious activity\n"
            "- Find evidence of data exfiltration"
        )
        self.investigation_objectives_input.setMinimumHeight(100)
        self.investigation_objectives_input.setMaximumHeight(120)
        self.investigation_objectives_input.setStyleSheet("""
            QTextEdit {
                background: #1E293B;
                border: 2px solid #334155;
                padding: 10px;
                color: #F8FAFC;
                font-size: 10pt;
                border-radius: 4px;
            }
            QTextEdit:focus {
                border: 2px solid #00FFFF;
            }
        """)
        form_layout.addWidget(self.investigation_objectives_input)
        
        # Expected Evidence Types (optional)
        evidence_label = QLabel("Expected Evidence Types")
        evidence_label.setStyleSheet(
            "font-size: 11pt; font-weight: bold; color: #E5E7EB; background: transparent;"
        )
        form_layout.addWidget(evidence_label)
        
        evidence_help = QLabel(
            "List types of evidence expected to be relevant (comma-separated)."
        )
        evidence_help.setWordWrap(True)
        evidence_help.setStyleSheet(
            "font-size: 9pt; color: #9CA3AF; background: transparent; margin-left: 4px; margin-top: 2px;"
        )
        form_layout.addWidget(evidence_help)
        
        self.expected_evidence_types_input = QLineEdit()
        self.expected_evidence_types_input.setPlaceholderText(
            "Example: Prefetch, Registry, Event Logs, Browser History, USB Artifacts"
        )
        self.expected_evidence_types_input.setMinimumHeight(40)
        self.expected_evidence_types_input.setStyleSheet("""
            QLineEdit {
                background: #1E293B;
                border: 2px solid #334155;
                padding: 10px;
                color: #F8FAFC;
                font-size: 10pt;
                border-radius: 4px;
            }
            QLineEdit:focus {
                border: 2px solid #00FFFF;
            }
        """)
        form_layout.addWidget(self.expected_evidence_types_input)
        
        form_group.setLayout(form_layout)
        scroll_layout.addWidget(form_group)
        scroll.setWidget(scroll_content)
        main_layout.addWidget(scroll, 1)
        
        # Required field note
        required_note = QLabel(
            "<span style='color: #EF4444;'>*</span> Required field"
        )
        required_note.setStyleSheet(
            "font-size: 9pt; color: #9CA3AF; background: transparent;"
        )
        main_layout.addWidget(required_note)
        
        # Button layout
        button_layout = QHBoxLayout()
        button_layout.setSpacing(12)
        button_layout.setContentsMargins(0, 12, 0, 0)
        
        button_layout.addStretch()
        
        # Cancel button
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setFixedHeight(40)
        self.cancel_button.setMinimumWidth(140)
        self.cancel_button.setStyleSheet("""
            QPushButton {
                background-color: #6B7280;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 11pt;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4B5563;
            }
            QPushButton:pressed {
                background-color: #374151;
            }
        """)
        self.cancel_button.clicked.connect(self._on_cancel)
        button_layout.addWidget(self.cancel_button)
        
        # Start Investigation button
        self.start_button = QPushButton("Start Investigation")
        self.start_button.setFixedHeight(40)
        self.start_button.setMinimumWidth(180)
        self.start_button.setStyleSheet("""
            QPushButton {
                background-color: #10B981;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 11pt;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #059669;
            }
            QPushButton:pressed {
                background-color: #047857;
            }
        """)
        self.start_button.clicked.connect(self._on_start_investigation)
        button_layout.addWidget(self.start_button)
        
        main_layout.addLayout(button_layout)
    
    def _apply_styling(self):
        """Apply comprehensive dark theme styling to the dialog."""
        # Set palette for backup styling
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor("#0B1220"))
        palette.setColor(QPalette.WindowText, QColor("#E5E7EB"))
        palette.setColor(QPalette.Base, QColor("#1E293B"))
        palette.setColor(QPalette.Text, QColor("#F8FAFC"))
        self.setPalette(palette)
        
        # Main dialog stylesheet
        dialog_style = """
            QDialog {
                background-color: #0B1220;
                color: #E5E7EB;
                font-size: 10pt;
            }
            QWidget {
                background-color: #0B1220;
                color: #E5E7EB;
            }
            QLabel {
                color: #E5E7EB;
                font-size: 10pt;
                background: transparent;
            }
        """
        
        self.setStyleSheet(dialog_style)
    
    def _validate_inputs(self) -> bool:
        """
        Validate form inputs.
        
        Ensures that the required Investigation Reason field is filled.
        
        Returns:
            bool: True if validation passes, False otherwise
        """
        # Get investigation reason
        investigation_reason = self.investigation_reason_input.toPlainText().strip()
        
        # Check if investigation reason is provided (required)
        if not investigation_reason:
            QMessageBox.warning(
                self,
                "Required Field Missing",
                "Investigation Reason is required.\n\n"
                "Please describe the primary objective or question driving this investigation."
            )
            self.investigation_reason_input.setFocus()
            return False
        
        return True
    
    def _parse_comma_separated(self, text: str) -> str:
        """
        Parse comma-separated input and return cleaned string.
        
        Args:
            text: Comma-separated input text
            
        Returns:
            str: Cleaned comma-separated string
        """
        if not text.strip():
            return ""
        
        # Split by comma, strip whitespace, filter empty strings
        items = [item.strip() for item in text.split(",") if item.strip()]
        
        # Rejoin with comma and space
        return ", ".join(items)
    
    def _parse_line_separated(self, text: str) -> str:
        """
        Parse line-separated input and return cleaned string.
        
        Args:
            text: Line-separated input text
            
        Returns:
            str: Cleaned line-separated string
        """
        if not text.strip():
            return ""
        
        # Split by newline, strip whitespace, filter empty strings
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        
        # Rejoin with newline
        return "\n".join(lines)
    
    def _on_start_investigation(self):
        """
        Handle Start Investigation button click.
        
        Validates inputs, collects case context data, and emits signal.
        """
        # Validate inputs
        if not self._validate_inputs():
            return
        
        # Collect case context data
        self.case_context["investigation_reason"] = self.investigation_reason_input.toPlainText().strip()
        self.case_context["primary_suspects"] = self._parse_comma_separated(
            self.primary_suspects_input.text()
        )
        self.case_context["investigation_objectives"] = self._parse_line_separated(
            self.investigation_objectives_input.toPlainText()
        )
        self.case_context["expected_evidence_types"] = self._parse_comma_separated(
            self.expected_evidence_types_input.text()
        )
        
        # Emit signal with case context
        self.case_context_initialized.emit(self.case_context)
        
        # Accept dialog
        self.accept()
    
    def _on_cancel(self):
        """
        Handle Cancel button click.
        
        Rejects the dialog without initializing case context.
        """
        # Show confirmation dialog
        reply = QMessageBox.question(
            self,
            "Cancel Case Setup",
            "Are you sure you want to cancel case setup?\n\n"
            "EYE will not be able to provide case-specific assistance without this information.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.reject()
    
    def get_case_context(self) -> dict:
        """
        Get the collected case context data.
        
        Returns:
            dict: Case context data with keys:
                - investigation_reason (str)
                - primary_suspects (str)
                - investigation_objectives (str)
                - expected_evidence_types (str)
        """
        return self.case_context

    def showEvent(self, event):
        """Force layout refresh on show."""
        super().showEvent(event)
        self.updateGeometry()
        if self.layout():
            self.layout().activate()



class CaseContextEditDialog(QDialog):
    """
    Dialog for editing existing case context.
    
    Allows investigators to modify case-specific information at any time during
    the investigation. Pre-populates all fields with current case context values
    and allows editing all fields including case variables.
    
    The dialog follows the same UI pattern as CaseSetupDialog with dark theme styling
    and user-friendly form layout.
    
    """
    
    case_context_updated = pyqtSignal(dict)  # Emits updated case context
    
    def __init__(self, current_context: dict, parent=None):
        """
        Initialize the case context edit dialog.
        
        Args:
            current_context: Current case context dictionary to pre-populate fields
            parent: Parent widget (typically the main window or EYE tab)
        """
        super().__init__(parent)
        
        # Set window flags for independent styling
        self.setWindowFlags(self.windowFlags() | Qt.Window)
        
        # Store current context for pre-population
        self.current_context = current_context or {}
        
        # Updated case context data
        self.updated_context = {}
        
        self._init_ui()
        self._apply_styling()
        self._populate_fields()
    
    def _init_ui(self):
        """Initialize the user interface components."""
        self.setWindowTitle("Edit Case Context - EYE Assistant")
        self.setMinimumSize(800, 600)
        self.resize(900, 750)
        
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(16)
        main_layout.setContentsMargins(40, 40, 40, 20)
        
        # Title
        title = QLabel("Edit Case Context")
        title.setStyleSheet(
            "font-size: 18pt; font-weight: bold; color: #00FFFF; background: transparent;"
        )
        title.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title)
        
        # Subtitle
        subtitle = QLabel(
            "Update case information to refine EYE's responses to your investigation objectives."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(
            "font-size: 11pt; color: #9CA3AF; background: transparent;"
        )
        subtitle.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(subtitle)
        
        main_layout.addSpacing(10)
        
        # Scroll Area for the form
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                border: none;
                background: #0B1220;
                width: 10px;
                margin: 0px 0px 0px 0px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background: #334155;
                min-height: 20px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover {
                background: #475569;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        """)
        
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 10, 0)
        scroll_layout.setSpacing(20)

        # Form group
        form_group = QGroupBox()
        form_group.setStyleSheet("""
            QGroupBox {
                border: 2px solid #334155;
                border-radius: 8px;
                padding-top: 20px;
                margin-top: 10px;
                background: #111827;
            }
        """)
        
        form_layout = QVBoxLayout()
        form_layout.setContentsMargins(20, 20, 20, 20)
        form_layout.setSpacing(20)
        
        # Investigation Reason (required)
        reason_label = QLabel("Investigation Reason <span style='color: #EF4444;'>*</span>")
        reason_label.setStyleSheet(
            "font-size: 11pt; font-weight: bold; color: #E5E7EB; background: transparent;"
        )
        form_layout.addWidget(reason_label)
        
        reason_help = QLabel(
            "Describe the primary objective or question driving this investigation."
        )
        reason_help.setWordWrap(True)
        reason_help.setStyleSheet(
            "font-size: 9pt; color: #9CA3AF; background: transparent; margin-left: 4px; margin-top: 2px;"
        )
        form_layout.addWidget(reason_help)
        
        self.investigation_reason_input = QTextEdit()
        self.investigation_reason_input.setPlaceholderText(
            "Example: Suspected data exfiltration by insider threat\n"
            "Example: Malware infection analysis and timeline reconstruction\n"
            "Example: Investigation of unauthorized access to financial systems"
        )
        self.investigation_reason_input.setMinimumHeight(100)
        self.investigation_reason_input.setMaximumHeight(120)
        self.investigation_reason_input.setStyleSheet("""
            QTextEdit {
                background: #1E293B;
                border: 2px solid #334155;
                padding: 10px;
                color: #F8FAFC;
                font-size: 10pt;
                border-radius: 4px;
            }
            QTextEdit:focus {
                border: 2px solid #00FFFF;
            }
        """)
        form_layout.addWidget(self.investigation_reason_input)
        
        # Primary Suspects (optional)
        suspects_label = QLabel("Primary Suspects")
        suspects_label.setStyleSheet(
            "font-size: 11pt; font-weight: bold; color: #E5E7EB; background: transparent;"
        )
        form_layout.addWidget(suspects_label)
        
        suspects_help = QLabel(
            "List suspects or entities under investigation (comma-separated)."
        )
        suspects_help.setWordWrap(True)
        suspects_help.setStyleSheet(
            "font-size: 9pt; color: #9CA3AF; background: transparent; margin-left: 4px; margin-top: 2px;"
        )
        form_layout.addWidget(suspects_help)
        
        self.primary_suspects_input = QLineEdit()
        self.primary_suspects_input.setPlaceholderText(
            "Example: John Doe, Jane Smith, External IP 192.168.1.100"
        )
        self.primary_suspects_input.setMinimumHeight(40)
        self.primary_suspects_input.setStyleSheet("""
            QLineEdit {
                background: #1E293B;
                border: 2px solid #334155;
                padding: 10px;
                color: #F8FAFC;
                font-size: 10pt;
                border-radius: 4px;
            }
            QLineEdit:focus {
                border: 2px solid #00FFFF;
            }
        """)
        form_layout.addWidget(self.primary_suspects_input)
        
        # Investigation Objectives (optional)
        objectives_label = QLabel("Investigation Objectives")
        objectives_label.setStyleSheet(
            "font-size: 11pt; font-weight: bold; color: #E5E7EB; background: transparent;"
        )
        form_layout.addWidget(objectives_label)
        
        objectives_help = QLabel(
            "List specific objectives for this investigation (one per line)."
        )
        objectives_help.setWordWrap(True)
        objectives_help.setStyleSheet(
            "font-size: 9pt; color: #9CA3AF; background: transparent; margin-left: 4px; margin-top: 2px;"
        )
        form_layout.addWidget(objectives_help)
        
        self.investigation_objectives_input = QTextEdit()
        self.investigation_objectives_input.setPlaceholderText(
            "Example:\n"
            "- Identify all files accessed by suspect\n"
            "- Determine timeline of malicious activity\n"
            "- Find evidence of data exfiltration"
        )
        self.investigation_objectives_input.setMinimumHeight(100)
        self.investigation_objectives_input.setMaximumHeight(120)
        self.investigation_objectives_input.setStyleSheet("""
            QTextEdit {
                background: #1E293B;
                border: 2px solid #334155;
                padding: 10px;
                color: #F8FAFC;
                font-size: 10pt;
                border-radius: 4px;
            }
            QTextEdit:focus {
                border: 2px solid #00FFFF;
            }
        """)
        form_layout.addWidget(self.investigation_objectives_input)
        
        # Expected Evidence Types (optional)
        evidence_label = QLabel("Expected Evidence Types")
        evidence_label.setStyleSheet(
            "font-size: 11pt; font-weight: bold; color: #E5E7EB; background: transparent;"
        )
        form_layout.addWidget(evidence_label)
        
        evidence_help = QLabel(
            "List types of evidence expected to be relevant (comma-separated)."
        )
        evidence_help.setWordWrap(True)
        evidence_help.setStyleSheet(
            "font-size: 9pt; color: #9CA3AF; background: transparent; margin-left: 4px; margin-top: 2px;"
        )
        form_layout.addWidget(evidence_help)
        
        self.expected_evidence_types_input = QLineEdit()
        self.expected_evidence_types_input.setPlaceholderText(
            "Example: Prefetch, Registry, Event Logs, Browser History, USB Artifacts"
        )
        self.expected_evidence_types_input.setMinimumHeight(40)
        self.expected_evidence_types_input.setStyleSheet("""
            QLineEdit {
                background: #1E293B;
                border: 2px solid #334155;
                padding: 10px;
                color: #F8FAFC;
                font-size: 10pt;
                border-radius: 4px;
            }
            QLineEdit:focus {
                border: 2px solid #00FFFF;
            }
        """)
        form_layout.addWidget(self.expected_evidence_types_input)
        
        # Case Variables (read-only display)
        variables_label = QLabel("Case Variables")
        variables_label.setStyleSheet(
            "font-size: 11pt; font-weight: bold; color: #E5E7EB; background: transparent;"
        )
        form_layout.addWidget(variables_label)
        
        variables_help = QLabel(
            "Case-specific variables (managed by EYE during investigation)."
        )
        variables_help.setWordWrap(True)
        variables_help.setStyleSheet(
            "font-size: 9pt; color: #9CA3AF; background: transparent; margin-left: 4px; margin-top: 2px;"
        )
        form_layout.addWidget(variables_help)
        
        self.case_variables_display = QTextEdit()
        self.case_variables_display.setReadOnly(True)
        self.case_variables_display.setPlaceholderText("No case variables set")
        self.case_variables_display.setMinimumHeight(80)
        self.case_variables_display.setMaximumHeight(100)
        self.case_variables_display.setStyleSheet("""
            QTextEdit {
                background: #0F172A;
                border: 2px solid #334155;
                padding: 10px;
                color: #94A3B8;
                font-size: 10pt;
                font-family: monospace;
                border-radius: 4px;
            }
        """)
        form_layout.addWidget(self.case_variables_display)
        
        form_group.setLayout(form_layout)
        scroll_layout.addWidget(form_group)
        scroll.setWidget(scroll_content)
        main_layout.addWidget(scroll, 1)
        
        # Required field note
        required_note = QLabel(
            "<span style='color: #EF4444;'>*</span> Required field"
        )
        required_note.setStyleSheet(
            "font-size: 9pt; color: #9CA3AF; background: transparent;"
        )
        main_layout.addWidget(required_note)
        
        # Button layout
        button_layout = QHBoxLayout()
        button_layout.setSpacing(12)
        button_layout.setContentsMargins(0, 12, 0, 0)
        
        button_layout.addStretch()
        
        # Cancel button
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setFixedHeight(40)
        self.cancel_button.setMinimumWidth(140)
        self.cancel_button.setStyleSheet("""
            QPushButton {
                background-color: #6B7280;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 11pt;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4B5563;
            }
            QPushButton:pressed {
                background-color: #374151;
            }
        """)
        self.cancel_button.clicked.connect(self._on_cancel)
        button_layout.addWidget(self.cancel_button)
        
        # Save Changes button
        self.save_button = QPushButton("Save Changes")
        self.save_button.setFixedHeight(40)
        self.save_button.setMinimumWidth(180)
        self.save_button.setStyleSheet("""
            QPushButton {
                background-color: #10B981;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 11pt;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #059669;
            }
            QPushButton:pressed {
                background-color: #047857;
            }
        """)
        self.save_button.clicked.connect(self._on_save_changes)
        button_layout.addWidget(self.save_button)
        
        main_layout.addLayout(button_layout)
    
    def _apply_styling(self):
        """Apply comprehensive dark theme styling to the dialog."""
        # Set palette for backup styling
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor("#0B1220"))
        palette.setColor(QPalette.WindowText, QColor("#E5E7EB"))
        palette.setColor(QPalette.Base, QColor("#1E293B"))
        palette.setColor(QPalette.Text, QColor("#F8FAFC"))
        self.setPalette(palette)
        
        # Main dialog stylesheet
        dialog_style = """
            QDialog {
                background-color: #0B1220;
                color: #E5E7EB;
                font-size: 10pt;
            }
            QWidget {
                background-color: #0B1220;
                color: #E5E7EB;
            }
            QLabel {
                color: #E5E7EB;
                font-size: 10pt;
                background: transparent;
            }
        """
        
        self.setStyleSheet(dialog_style)
    
    def _populate_fields(self):
        """
        Pre-populate form fields with current case context values.
        
        """
        # Investigation Reason
        investigation_reason = self.current_context.get("investigation_reason", "")
        self.investigation_reason_input.setPlainText(investigation_reason)
        
        # Primary Suspects
        primary_suspects = self.current_context.get("primary_suspects", "")
        self.primary_suspects_input.setText(primary_suspects)
        
        # Investigation Objectives
        investigation_objectives = self.current_context.get("investigation_objectives", "")
        self.investigation_objectives_input.setPlainText(investigation_objectives)
        
        # Expected Evidence Types
        expected_evidence_types = self.current_context.get("expected_evidence_types", "")
        self.expected_evidence_types_input.setText(expected_evidence_types)
        
        # Case Variables (read-only display)
        case_variables = self.current_context.get("case_variables", {})
        if case_variables:
            # Format as key: value pairs
            variables_text = "\n".join([f"{key}: {value}" for key, value in case_variables.items()])
            self.case_variables_display.setPlainText(variables_text)
        else:
            self.case_variables_display.setPlainText("No case variables set")
    
    def _validate_inputs(self) -> bool:
        """
        Validate form inputs.
        
        Ensures that the required Investigation Reason field is filled.
        
        Returns:
            bool: True if validation passes, False otherwise
        """
        # Get investigation reason
        investigation_reason = self.investigation_reason_input.toPlainText().strip()
        
        # Check if investigation reason is provided (required)
        if not investigation_reason:
            QMessageBox.warning(
                self,
                "Required Field Missing",
                "Investigation Reason is required.\n\n"
                "Please describe the primary objective or question driving this investigation."
            )
            self.investigation_reason_input.setFocus()
            return False
        
        return True
    
    def _parse_comma_separated(self, text: str) -> str:
        """
        Parse comma-separated input and return cleaned string.
        
        Args:
            text: Comma-separated input text
            
        Returns:
            str: Cleaned comma-separated string
        """
        if not text.strip():
            return ""
        
        # Split by comma, strip whitespace, filter empty strings
        items = [item.strip() for item in text.split(",") if item.strip()]
        
        # Rejoin with comma and space
        return ", ".join(items)
    
    def _parse_line_separated(self, text: str) -> str:
        """
        Parse line-separated input and return cleaned string.
        
        Args:
            text: Line-separated input text
            
        Returns:
            str: Cleaned line-separated string
        """
        if not text.strip():
            return ""
        
        # Split by newline, strip whitespace, filter empty strings
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        
        # Rejoin with newline
        return "\n".join(lines)
    
    def _on_save_changes(self):
        """
        Handle Save Changes button click.
        
        Validates inputs, collects updated case context data, and emits signal.
        
        """
        # Validate inputs
        if not self._validate_inputs():
            return
        
        # Collect updated case context data
        self.updated_context = {
            "investigation_reason": self.investigation_reason_input.toPlainText().strip(),
            "primary_suspects": self._parse_comma_separated(
                self.primary_suspects_input.text()
            ),
            "investigation_objectives": self._parse_line_separated(
                self.investigation_objectives_input.toPlainText()
            ),
            "expected_evidence_types": self._parse_comma_separated(
                self.expected_evidence_types_input.text()
            ),
            # Preserve case variables (not editable in this dialog)
            "case_variables": self.current_context.get("case_variables", {})
        }
        
        # Emit signal with updated case context
        self.case_context_updated.emit(self.updated_context)
        
        # Accept dialog
        self.accept()
    
    def _on_cancel(self):
        """
        Handle Cancel button click.
        
        Rejects the dialog without saving changes.
        """
        # Show confirmation dialog
        reply = QMessageBox.question(
            self,
            "Cancel Changes",
            "Are you sure you want to cancel?\n\n"
            "Any changes you made will be lost.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.reject()
    
    def get_updated_context(self) -> dict:
        """
        Get the updated case context data.
        
        Returns:
            dict: Updated case context data with keys:
                - investigation_reason (str)
                - primary_suspects (str)
                - investigation_objectives (str)
                - expected_evidence_types (str)
                - case_variables (dict)
        """
        return self.updated_context

    def showEvent(self, event):
        """Force layout refresh on show."""
        super().showEvent(event)
        self.updateGeometry()
        if self.layout():
            self.layout().activate()
