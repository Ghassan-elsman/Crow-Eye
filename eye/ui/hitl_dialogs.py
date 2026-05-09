"""
Human-in-the-Loop (HitL) Approval Dialogs for EYE AI Forensic Assistant

This module provides dialogs for user approval of AI-proposed operations:
- SemanticMappingApprovalDialog: Approve/reject/edit semantic mapping rules
- ReportExportApprovalDialog: Approve/reject report exports (future)
- FileWriteApprovalDialog: Approve/reject file write operations (future)

Follows the pattern from correlation_engine/wings/ui/semantic_mapping_dialog.py
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QPushButton, QGroupBox, QMessageBox, QDialogButtonBox
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPalette, QColor, QFont
import json


class SemanticMappingApprovalDialog(QDialog):
    """
    Dialog for approving AI-proposed semantic mapping rules.
    
    Displays the proposed rule in JSON format with options to:
    - Approve: Accept the rule as-is
    - Reject: Cancel the operation
    - Edit: Modify the rule JSON before approval
    
    """
    
    def __init__(self, parent=None, proposed_rule=None):
        """
        Initialize the semantic mapping approval dialog.
        
        Args:
            parent: Parent widget (typically the main window)
            proposed_rule: Dict containing the proposed semantic mapping rule
        """
        super().__init__(parent)
        
        # Set window flags for independent styling
        self.setWindowFlags(self.windowFlags() | Qt.Window)
        
        self.proposed_rule = proposed_rule or {}
        self.approved_rule = None
        self.is_approved = False
        
        self._init_ui()
        self._apply_styling()
        self._load_rule()
    
    def _init_ui(self):
        """Initialize the user interface components."""
        self.setWindowTitle("Approve Semantic Mapping Rule")
        self.setMinimumSize(800, 600)
        self.resize(900, 700)
        
        # Main layout
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)
        
        # Header section
        header_label = QLabel("EYE has proposed a new semantic mapping rule:")
        header_label.setStyleSheet(
            "font-size: 12pt; font-weight: bold; color: #00FFFF; background: transparent;"
        )
        layout.addWidget(header_label)
        
        # Info text
        info_label = QLabel(
            "Review the rule below. You can approve it as-is, edit the JSON before approval, "
            "or reject the proposal."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet(
            "font-size: 10pt; color: #E5E7EB; background: transparent; padding: 4px 0px;"
        )
        layout.addWidget(info_label)
        
        # Rule display group
        rule_group = QGroupBox("Proposed Rule")
        rule_group.setStyleSheet("""
            QGroupBox {
                font-size: 11pt;
                font-weight: bold;
                color: #00FFFF;
                border: 2px solid #00FFFF;
                border-radius: 6px;
                padding-top: 18px;
                margin-top: 6px;
                background: #111827;
            }
            QGroupBox::title {
                background: #111827;
                padding: 2px 8px;
            }
        """)
        
        rule_layout = QVBoxLayout()
        rule_layout.setContentsMargins(14, 22, 14, 14)
        rule_layout.setSpacing(8)
        
        # JSON text editor
        self.rule_text_edit = QTextEdit()
        self.rule_text_edit.setReadOnly(True)
        self.rule_text_edit.setMinimumHeight(300)
        self.rule_text_edit.setStyleSheet("""
            QTextEdit {
                background: #0F172A;
                border: 1px solid #334155;
                padding: 12px;
                color: #F8FAFC;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 10pt;
                border-radius: 4px;
            }
        """)
        rule_layout.addWidget(self.rule_text_edit)
        
        rule_group.setLayout(rule_layout)
        layout.addWidget(rule_group, 1)
        
        # Action buttons section
        button_layout = QHBoxLayout()
        button_layout.setSpacing(12)
        
        # Edit button
        self.edit_button = QPushButton("Edit Rule")
        self.edit_button.setFixedHeight(40)
        self.edit_button.setMinimumWidth(120)
        self.edit_button.setStyleSheet("""
            QPushButton {
                background-color: #F59E0B;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 11pt;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #D97706;
            }
            QPushButton:pressed {
                background-color: #B45309;
            }
        """)
        self.edit_button.clicked.connect(self._on_edit)
        button_layout.addWidget(self.edit_button)
        
        button_layout.addStretch()
        
        # Reject button
        self.reject_button = QPushButton("Reject")
        self.reject_button.setFixedHeight(40)
        self.reject_button.setMinimumWidth(120)
        self.reject_button.setStyleSheet("""
            QPushButton {
                background-color: #EF4444;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 11pt;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #DC2626;
            }
            QPushButton:pressed {
                background-color: #B91C1C;
            }
        """)
        self.reject_button.clicked.connect(self._on_reject)
        button_layout.addWidget(self.reject_button)
        
        # Approve button
        self.approve_button = QPushButton("Approve")
        self.approve_button.setFixedHeight(40)
        self.approve_button.setMinimumWidth(120)
        self.approve_button.setStyleSheet("""
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
        self.approve_button.clicked.connect(self._on_approve)
        button_layout.addWidget(self.approve_button)
        
        layout.addLayout(button_layout)
    
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
    
    def _load_rule(self):
        """Load the proposed rule into the text editor."""
        if self.proposed_rule:
            # Format JSON with indentation for readability
            formatted_json = json.dumps(self.proposed_rule, indent=2)
            self.rule_text_edit.setPlainText(formatted_json)
    
    def _on_edit(self):
        """Handle Edit button click - enable editing of the rule JSON."""
        if self.rule_text_edit.isReadOnly():
            # Enable editing
            self.rule_text_edit.setReadOnly(False)
            self.rule_text_edit.setStyleSheet("""
                QTextEdit {
                    background: #1E293B;
                    border: 2px solid #F59E0B;
                    padding: 12px;
                    color: #F8FAFC;
                    font-family: 'Consolas', 'Courier New', monospace;
                    font-size: 10pt;
                    border-radius: 4px;
                }
            """)
            self.edit_button.setText("Lock Edits")
            self.edit_button.setStyleSheet("""
                QPushButton {
                    background-color: #8B5CF6;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 8px 16px;
                    font-size: 11pt;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #7C3AED;
                }
                QPushButton:pressed {
                    background-color: #6D28D9;
                }
            """)
            self.rule_text_edit.setFocus()
        else:
            # Lock editing
            self.rule_text_edit.setReadOnly(True)
            self.rule_text_edit.setStyleSheet("""
                QTextEdit {
                    background: #0F172A;
                    border: 1px solid #334155;
                    padding: 12px;
                    color: #F8FAFC;
                    font-family: 'Consolas', 'Courier New', monospace;
                    font-size: 10pt;
                    border-radius: 4px;
                }
            """)
            self.edit_button.setText("Edit Rule")
            self.edit_button.setStyleSheet("""
                QPushButton {
                    background-color: #F59E0B;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 8px 16px;
                    font-size: 11pt;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #D97706;
                }
                QPushButton:pressed {
                    background-color: #B45309;
                }
            """)
    
    def _on_approve(self):
        """
        Handle Approve button click.
        
        Validates and parses the edited rule JSON, then accepts the dialog.
        If JSON is invalid, shows an error message.
        """
        try:
            # Parse the JSON from the text editor
            rule_text = self.rule_text_edit.toPlainText()
            parsed_rule = json.loads(rule_text)
            
            # Validate that it's a dictionary
            if not isinstance(parsed_rule, dict):
                raise ValueError("Rule must be a JSON object (dictionary)")
            
            # Store the approved rule
            self.approved_rule = parsed_rule
            self.is_approved = True
            
            # Accept the dialog
            self.accept()
            
        except json.JSONDecodeError as e:
            # Show error message for invalid JSON
            QMessageBox.critical(
                self,
                "Invalid JSON",
                f"The rule JSON is invalid:\n\n{str(e)}\n\n"
                "Please correct the JSON syntax and try again."
            )
        except ValueError as e:
            # Show error message for validation errors
            QMessageBox.warning(
                self,
                "Invalid Rule",
                f"The rule is invalid:\n\n{str(e)}\n\n"
                "Please correct the rule and try again."
            )
        except Exception as e:
            # Show error message for unexpected errors
            QMessageBox.critical(
                self,
                "Error",
                f"An unexpected error occurred:\n\n{str(e)}"
            )
    
    def _on_reject(self):
        """
        Handle Reject button click.
        
        Cancels the operation and rejects the dialog.
        """
        self.approved_rule = None
        self.is_approved = False
        self.reject()
    
    def get_approved_rule(self):
        """
        Get the approved rule after dialog closes.
        
        Returns:
            dict: The approved rule (possibly edited), or None if rejected
        """
        return self.approved_rule if self.is_approved else None
    
    def was_approved(self):
        """
        Check if the rule was approved.
        
        Returns:
            bool: True if approved, False if rejected
        """
        return self.is_approved


class FileWriteApprovalDialog(QDialog):
    """
    Dialog for approving AI-proposed file write operations.
    
    Displays the file operation details with options to:
    - Approve: Accept the file write operation
    - Cancel: Reject the operation
    
    """
    
    def __init__(self, parent=None, operation_type="create", file_path="", content=""):
        """
        Initialize the file write approval dialog.
        
        Args:
            parent: Parent widget (typically the main window)
            operation_type: Type of operation ("create", "update", "delete")
            file_path: Path to the file being written
            content: Content to be written (for create/update operations)
        """
        super().__init__(parent)
        
        # Set window flags for independent styling
        self.setWindowFlags(self.windowFlags() | Qt.Window)
        
        self.operation_type = operation_type
        self.file_path = file_path
        self.content = content
        self.is_approved = False
        
        self._init_ui()
        self._apply_styling()
        self._load_content()
    
    def _init_ui(self):
        """Initialize the user interface components."""
        self.setWindowTitle("Approve File Write Operation")
        self.setMinimumSize(800, 600)
        self.resize(900, 700)
        
        # Main layout
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)
        
        # Header section
        header_label = QLabel("EYE has requested a file write operation:")
        header_label.setStyleSheet(
            "font-size: 12pt; font-weight: bold; color: #00FFFF; background: transparent;"
        )
        layout.addWidget(header_label)
        
        # Info text
        info_label = QLabel(
            "Review the operation details below. You can approve the operation or cancel it."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet(
            "font-size: 10pt; color: #E5E7EB; background: transparent; padding: 4px 0px;"
        )
        layout.addWidget(info_label)
        
        # Operation details group
        details_group = QGroupBox("Operation Details")
        details_group.setStyleSheet("""
            QGroupBox {
                font-size: 11pt;
                font-weight: bold;
                color: #00FFFF;
                border: 2px solid #00FFFF;
                border-radius: 6px;
                padding-top: 18px;
                margin-top: 6px;
                background: #111827;
            }
            QGroupBox::title {
                background: #111827;
                padding: 2px 8px;
            }
        """)
        
        details_layout = QVBoxLayout()
        details_layout.setContentsMargins(14, 22, 14, 14)
        details_layout.setSpacing(12)
        
        # Operation type
        operation_label = QLabel(f"<b>Operation Type:</b> {self.operation_type.upper()}")
        operation_label.setStyleSheet(
            "font-size: 10pt; color: #F8FAFC; background: transparent;"
        )
        details_layout.addWidget(operation_label)
        
        # File path
        path_label = QLabel(f"<b>File Path:</b> {self.file_path}")
        path_label.setWordWrap(True)
        path_label.setStyleSheet(
            "font-size: 10pt; color: #F8FAFC; background: transparent;"
        )
        details_layout.addWidget(path_label)
        
        details_group.setLayout(details_layout)
        layout.addWidget(details_group)
        
        # Content preview group (only for create/update operations)
        if self.operation_type in ["create", "update"]:
            preview_group = QGroupBox("Content Preview")
            preview_group.setStyleSheet("""
                QGroupBox {
                    font-size: 11pt;
                    font-weight: bold;
                    color: #00FFFF;
                    border: 2px solid #00FFFF;
                    border-radius: 6px;
                    padding-top: 18px;
                    margin-top: 6px;
                    background: #111827;
                }
                QGroupBox::title {
                    background: #111827;
                    padding: 2px 8px;
                }
            """)
            
            preview_layout = QVBoxLayout()
            preview_layout.setContentsMargins(14, 22, 14, 14)
            preview_layout.setSpacing(8)
            
            # Content text viewer
            self.content_text_edit = QTextEdit()
            self.content_text_edit.setReadOnly(True)
            self.content_text_edit.setMinimumHeight(250)
            self.content_text_edit.setStyleSheet("""
                QTextEdit {
                    background: #0F172A;
                    border: 1px solid #334155;
                    padding: 12px;
                    color: #F8FAFC;
                    font-family: 'Consolas', 'Courier New', monospace;
                    font-size: 10pt;
                    border-radius: 4px;
                }
            """)
            preview_layout.addWidget(self.content_text_edit)
            
            preview_group.setLayout(preview_layout)
            layout.addWidget(preview_group, 1)
        
        # Action buttons section
        button_layout = QHBoxLayout()
        button_layout.setSpacing(12)
        
        button_layout.addStretch()
        
        # Cancel button
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setFixedHeight(40)
        self.cancel_button.setMinimumWidth(120)
        self.cancel_button.setStyleSheet("""
            QPushButton {
                background-color: #EF4444;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 11pt;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #DC2626;
            }
            QPushButton:pressed {
                background-color: #B91C1C;
            }
        """)
        self.cancel_button.clicked.connect(self._on_cancel)
        button_layout.addWidget(self.cancel_button)
        
        # Approve button
        self.approve_button = QPushButton("Approve")
        self.approve_button.setFixedHeight(40)
        self.approve_button.setMinimumWidth(120)
        self.approve_button.setStyleSheet("""
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
        self.approve_button.clicked.connect(self._on_approve)
        button_layout.addWidget(self.approve_button)
        
        layout.addLayout(button_layout)
    
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
    
    def _load_content(self):
        """Load the content preview into the text editor."""
        if self.operation_type in ["create", "update"] and self.content:
            # Truncate to first 500 characters if content is longer
            preview_content = self.content
            if len(self.content) > 500:
                preview_content = self.content[:500] + "\n\n... (content truncated, showing first 500 characters)"
            
            self.content_text_edit.setPlainText(preview_content)
    
    def _on_approve(self):
        """
        Handle Approve button click.
        
        Approves the file write operation and accepts the dialog.
        """
        self.is_approved = True
        self.accept()
    
    def _on_cancel(self):
        """
        Handle Cancel button click.
        
        Cancels the operation and rejects the dialog.
        """
        self.is_approved = False
        self.reject()
    
    def was_approved(self):
        """
        Check if the operation was approved.
        
        Returns:
            bool: True if approved, False if cancelled
        """
        return self.is_approved


class ReportExportApprovalDialog(QDialog):
    """
    Dialog for approving report export operations.
    
    Displays the export details with options to:
    - Approve: Accept the export operation
    - Cancel: Reject the operation
    
    """
    
    def __init__(self, parent=None, format_type="html", file_size=0, destination_path=""):
        """
        Initialize the report export approval dialog.
        
        Args:
            parent: Parent widget (typically the main window)
            format_type: Export format ("html", "pdf", "markdown")
            file_size: Estimated file size in bytes
            destination_path: Destination file path
        """
        super().__init__(parent)
        
        # Set window flags for independent styling
        self.setWindowFlags(self.windowFlags() | Qt.Window)
        
        self.format_type = format_type
        self.file_size = file_size
        self.destination_path = destination_path
        self.is_approved = False
        
        self._init_ui()
        self._apply_styling()
    
    def _init_ui(self):
        """Initialize the user interface components."""
        self.setWindowTitle("Approve Report Export")
        self.setMinimumSize(700, 400)
        self.resize(800, 450)
        
        # Main layout
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)
        
        # Header section
        header_label = QLabel("EYE has requested to export a report:")
        header_label.setStyleSheet(
            "font-size: 12pt; font-weight: bold; color: #00FFFF; background: transparent;"
        )
        layout.addWidget(header_label)
        
        # Info text
        info_label = QLabel(
            "Review the export details below. You can approve the export or cancel it."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet(
            "font-size: 10pt; color: #E5E7EB; background: transparent; padding: 4px 0px;"
        )
        layout.addWidget(info_label)
        
        # Export details group
        details_group = QGroupBox("Export Details")
        details_group.setStyleSheet("""
            QGroupBox {
                font-size: 11pt;
                font-weight: bold;
                color: #00FFFF;
                border: 2px solid #00FFFF;
                border-radius: 6px;
                padding-top: 18px;
                margin-top: 6px;
                background: #111827;
            }
            QGroupBox::title {
                background: #111827;
                padding: 2px 8px;
            }
        """)
        
        details_layout = QVBoxLayout()
        details_layout.setContentsMargins(14, 22, 14, 14)
        details_layout.setSpacing(12)
        
        # Format type
        format_display = self._format_display_name(self.format_type)
        format_label = QLabel(f"<b>Export Format:</b> {format_display}")
        format_label.setStyleSheet(
            "font-size: 10pt; color: #F8FAFC; background: transparent;"
        )
        details_layout.addWidget(format_label)
        
        # File size
        size_display = self._format_file_size(self.file_size)
        size_label = QLabel(f"<b>Estimated File Size:</b> {size_display}")
        size_label.setStyleSheet(
            "font-size: 10pt; color: #F8FAFC; background: transparent;"
        )
        details_layout.addWidget(size_label)
        
        # Destination path
        path_label = QLabel(f"<b>Destination Path:</b> {self.destination_path}")
        path_label.setWordWrap(True)
        path_label.setStyleSheet(
            "font-size: 10pt; color: #F8FAFC; background: transparent;"
        )
        details_layout.addWidget(path_label)
        
        details_group.setLayout(details_layout)
        layout.addWidget(details_group)
        
        layout.addStretch()
        
        # Action buttons section
        button_layout = QHBoxLayout()
        button_layout.setSpacing(12)
        
        button_layout.addStretch()
        
        # Cancel button
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setFixedHeight(40)
        self.cancel_button.setMinimumWidth(120)
        self.cancel_button.setStyleSheet("""
            QPushButton {
                background-color: #EF4444;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 11pt;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #DC2626;
            }
            QPushButton:pressed {
                background-color: #B91C1C;
            }
        """)
        self.cancel_button.clicked.connect(self._on_cancel)
        button_layout.addWidget(self.cancel_button)
        
        # Approve button
        self.approve_button = QPushButton("Approve")
        self.approve_button.setFixedHeight(40)
        self.approve_button.setMinimumWidth(120)
        self.approve_button.setStyleSheet("""
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
        self.approve_button.clicked.connect(self._on_approve)
        button_layout.addWidget(self.approve_button)
        
        layout.addLayout(button_layout)
    
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
    
    def _format_display_name(self, format_type: str) -> str:
        """
        Convert format type to display name.
        
        Args:
            format_type: Format type ("html", "pdf", "markdown")
            
        Returns:
            Display name for the format
        """
        format_map = {
            "html": "Interactive HTML",
            "pdf": "PDF Document",
            "markdown": "Markdown"
        }
        return format_map.get(format_type.lower(), format_type.upper())
    
    def _format_file_size(self, size_bytes: int) -> str:
        """
        Format file size in human-readable format.
        
        Args:
            size_bytes: File size in bytes
            
        Returns:
            Formatted file size string
        """
        if size_bytes < 1024:
            return f"{size_bytes} bytes"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.2f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.2f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"
    
    def _on_approve(self):
        """
        Handle Approve button click.
        
        Approves the export operation and accepts the dialog.
        """
        self.is_approved = True
        self.accept()
    
    def _on_cancel(self):
        """
        Handle Cancel button click.
        
        Cancels the operation and rejects the dialog.
        """
        self.is_approved = False
        self.reject()
    
    def was_approved(self):
        """
        Check if the export was approved.
        
        Returns:
            bool: True if approved, False if cancelled
        """
        return self.is_approved


class CaseVariableApprovalDialog(QDialog):
    """
    Dialog for approving AI-proposed case variable changes.
    
    Displays the variable details with options to:
    - Approve: Accept the variable change
    - Cancel: Reject the operation
    
    """
    
    def __init__(self, parent=None, variable_name="", variable_value="", case_context=None):
        """
        Initialize the case variable approval dialog.
        
        Args:
            parent: Parent widget (typically the main window)
            variable_name: Name of the case variable
            variable_value: Value to be set
            case_context: Dictionary containing case context information
        """
        super().__init__(parent)
        
        # Set window flags for independent styling
        self.setWindowFlags(self.windowFlags() | Qt.Window)
        
        self.variable_name = variable_name
        self.variable_value = variable_value
        self.case_context = case_context or {}
        self.is_approved = False
        
        self._init_ui()
        self._apply_styling()
    
    def _init_ui(self):
        """Initialize the user interface components."""
        self.setWindowTitle("Approve Case Variable Change")
        self.setMinimumSize(700, 450)
        self.resize(800, 500)
        
        # Main layout
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)
        
        # Header section
        header_label = QLabel("EYE has requested to set a case variable:")
        header_label.setStyleSheet(
            "font-size: 12pt; font-weight: bold; color: #00FFFF; background: transparent;"
        )
        layout.addWidget(header_label)
        
        # Info text
        info_label = QLabel(
            "Review the variable details below. You can approve the change or cancel it."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet(
            "font-size: 10pt; color: #E5E7EB; background: transparent; padding: 4px 0px;"
        )
        layout.addWidget(info_label)
        
        # Variable details group
        details_group = QGroupBox("Variable Details")
        details_group.setStyleSheet("""
            QGroupBox {
                font-size: 11pt;
                font-weight: bold;
                color: #00FFFF;
                border: 2px solid #00FFFF;
                border-radius: 6px;
                padding-top: 18px;
                margin-top: 6px;
                background: #111827;
            }
            QGroupBox::title {
                background: #111827;
                padding: 2px 8px;
            }
        """)
        
        details_layout = QVBoxLayout()
        details_layout.setContentsMargins(14, 22, 14, 14)
        details_layout.setSpacing(12)
        
        # Variable name
        name_label = QLabel(f"<b>Variable Name:</b> {self.variable_name}")
        name_label.setStyleSheet(
            "font-size: 10pt; color: #F8FAFC; background: transparent;"
        )
        details_layout.addWidget(name_label)
        
        # Variable value
        value_display = str(self.variable_value)
        if len(value_display) > 100:
            value_display = value_display[:100] + "..."
        value_label = QLabel(f"<b>Variable Value:</b> {value_display}")
        value_label.setWordWrap(True)
        value_label.setStyleSheet(
            "font-size: 10pt; color: #F8FAFC; background: transparent;"
        )
        details_layout.addWidget(value_label)
        
        details_group.setLayout(details_layout)
        layout.addWidget(details_group)
        
        # Case context group
        if self.case_context:
            context_group = QGroupBox("Case Context")
            context_group.setStyleSheet("""
                QGroupBox {
                    font-size: 11pt;
                    font-weight: bold;
                    color: #00FFFF;
                    border: 2px solid #00FFFF;
                    border-radius: 6px;
                    padding-top: 18px;
                    margin-top: 6px;
                    background: #111827;
                }
                QGroupBox::title {
                    background: #111827;
                    padding: 2px 8px;
                }
            """)
            
            context_layout = QVBoxLayout()
            context_layout.setContentsMargins(14, 22, 14, 14)
            context_layout.setSpacing(8)
            
            # Case name
            case_name = self.case_context.get("case_name", "Unknown")
            case_label = QLabel(f"<b>Case:</b> {case_name}")
            case_label.setStyleSheet(
                "font-size: 10pt; color: #F8FAFC; background: transparent;"
            )
            context_layout.addWidget(case_label)
            
            # Investigation reason
            investigation_reason = self.case_context.get("investigation_reason", "")
            if investigation_reason:
                reason_label = QLabel(f"<b>Investigation Reason:</b> {investigation_reason}")
                reason_label.setWordWrap(True)
                reason_label.setStyleSheet(
                    "font-size: 10pt; color: #F8FAFC; background: transparent;"
                )
                context_layout.addWidget(reason_label)
            
            context_group.setLayout(context_layout)
            layout.addWidget(context_group)
        
        layout.addStretch()
        
        # Action buttons section
        button_layout = QHBoxLayout()
        button_layout.setSpacing(12)
        
        button_layout.addStretch()
        
        # Cancel button
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setFixedHeight(40)
        self.cancel_button.setMinimumWidth(120)
        self.cancel_button.setStyleSheet("""
            QPushButton {
                background-color: #EF4444;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 11pt;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #DC2626;
            }
            QPushButton:pressed {
                background-color: #B91C1C;
            }
        """)
        self.cancel_button.clicked.connect(self._on_cancel)
        button_layout.addWidget(self.cancel_button)
        
        # Approve button
        self.approve_button = QPushButton("Approve")
        self.approve_button.setFixedHeight(40)
        self.approve_button.setMinimumWidth(120)
        self.approve_button.setStyleSheet("""
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
        self.approve_button.clicked.connect(self._on_approve)
        button_layout.addWidget(self.approve_button)
        
        layout.addLayout(button_layout)
    
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
    
    def _on_approve(self):
        """
        Handle Approve button click.
        
        Approves the case variable change and accepts the dialog.
        """
        self.is_approved = True
        self.accept()
    
    def _on_cancel(self):
        """
        Handle Cancel button click.
        
        Cancels the operation and rejects the dialog.
        """
        self.is_approved = False
        self.reject()
    
    def was_approved(self):
        """
        Check if the variable change was approved.
        
        Returns:
            bool: True if approved, False if cancelled
        """
        return self.is_approved
