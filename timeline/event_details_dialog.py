"""
Event Details Dialog - Display detailed information about a timeline event in a dialog.

This module provides the EventDetailsDialog class which displays comprehensive
information about a single event in a modal dialog window when double-clicked.
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QPushButton, QFrame, QTextEdit, QApplication, QGridLayout, QWidget
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QColor
from datetime import datetime
from typing import Dict, Optional


class EventDetailsDialog(QDialog):
    """
    Event details dialog window.
    
    This dialog displays comprehensive information about a single timeline event,
    including timestamps, artifact types, file/registry paths, and type-specific
    metadata. Opened on double-click of timeline events.
    """
    
    # Color mapping for artifact types (matches EventRenderer)
    ARTIFACT_COLORS = {
        'Prefetch': '#3498db',  # Blue
        'LNK': '#2ecc71',       # Green
        'Registry': '#9b59b6',  # Purple
        'BAM': '#e67e22',       # Orange
        'ShellBag': '#1abc9c',  # Cyan
        'SRUM': '#e74c3c',      # Red
        'USN': '#f39c12',       # Yellow
        'MFT': '#e91e63',       # Pink
        'Logs': '#8B4513',      # Brown (Windows Event Logs)
        'Unknown': '#95a5a6'    # Gray (fallback)
    }
    
    def __init__(self, event_data: Dict, parent=None):
        """
        Initialize the event details dialog.
        
        Args:
            event_data: Dictionary containing event information
            parent: Parent widget
        """
        super().__init__(parent)
        
        self.event_data = event_data
        
        # Configure dialog
        self.setWindowTitle("Event Details")
        self.setModal(True)
        self.setMinimumSize(700, 500)
        self.resize(800, 600)
        
        # Apply dark theme
        self.setStyleSheet("""
            QDialog {
                background-color: #0F172A;
            }
            QLabel {
                color: #E2E8F0;
            }
            QPushButton {
                background-color: #3B82F6;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2563EB;
            }
            QPushButton:pressed {
                background-color: #1D4ED8;
            }
        """)
        
        # Initialize UI
        self._init_ui()
        
        # Display event data
        self._display_event()
    
    def _init_ui(self):
        """Initialize the user interface."""
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)
        
        # Header with artifact type badge
        header_layout = QHBoxLayout()
        
        # Artifact type badge
        artifact_type = self.event_data.get('artifact_type', 'Unknown')
        color = self.ARTIFACT_COLORS.get(artifact_type, self.ARTIFACT_COLORS['Unknown'])
        
        self.type_badge = QLabel(artifact_type)
        self.type_badge.setStyleSheet(f"""
            QLabel {{
                background-color: {color};
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 14px;
            }}
        """)
        header_layout.addWidget(self.type_badge)
        header_layout.addStretch()
        
        main_layout.addLayout(header_layout)
        
        # Scrollable content area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: #1E293B;
                border: 1px solid #334155;
                border-radius: 8px;
            }
            QScrollBar:vertical {
                background-color: #0F172A;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #475569;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #64748b;
            }
        """)
        
        # Content widget
        content_widget = QWidget()
        content_widget.setStyleSheet("background-color: #1E293B;")
        self.content_layout = QVBoxLayout(content_widget)
        self.content_layout.setContentsMargins(20, 20, 20, 20)
        self.content_layout.setSpacing(15)
        
        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area)
        
        # Button row
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        # Copy button
        copy_btn = QPushButton("📋 Copy Details")
        copy_btn.clicked.connect(self._copy_to_clipboard)
        button_layout.addWidget(copy_btn)
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        button_layout.addWidget(close_btn)
        
        main_layout.addLayout(button_layout)
    
    def _display_event(self):
        """Display the event information."""
        # Clear existing content
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # Basic Information Section
        self._add_section_header("Basic Information")
        
        # Timestamp
        timestamp = self.event_data.get('timestamp')
        if isinstance(timestamp, datetime):
            timestamp_str = timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        else:
            timestamp_str = str(timestamp)
        self._add_field("Timestamp", timestamp_str)
        
        # Display name
        display_name = self.event_data.get('display_name', 'N/A')
        self._add_field("Name", display_name)
        
        # Full path
        full_path = self.event_data.get('full_path', 'N/A')
        self._add_field("Path", full_path, wrap=True)
        
        # Event ID
        event_id = self.event_data.get('id', 'N/A')
        self._add_field("Event ID", event_id)
        
        # Type-specific details
        details = self.event_data.get('details', {})
        if details:
            self._add_section_header("Additional Details")
            
            # Display all detail fields
            for key, value in details.items():
                # Format key (convert snake_case to Title Case)
                formatted_key = key.replace('_', ' ').title()
                
                # Format value
                if isinstance(value, datetime):
                    formatted_value = value.strftime('%Y-%m-%d %H:%M:%S')
                elif isinstance(value, (list, tuple)):
                    formatted_value = ', '.join(str(v) for v in value)
                elif isinstance(value, dict):
                    formatted_value = '\n'.join(f"{k}: {v}" for k, v in value.items())
                else:
                    formatted_value = str(value)
                
                self._add_field(formatted_key, formatted_value, wrap=True)
        
        # Add stretch at the end
        self.content_layout.addStretch()
    
    def _add_section_header(self, title: str):
        """
        Add a section header.
        
        Args:
            title: Section title
        """
        header = QLabel(title)
        header.setFont(QFont("Segoe UI", 12, QFont.Bold))
        header.setStyleSheet("color: #60A5FA; margin-top: 10px; margin-bottom: 5px;")
        self.content_layout.addWidget(header)
        
        # Add separator line
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setStyleSheet("background-color: #334155; max-height: 1px;")
        self.content_layout.addWidget(separator)
    
    def _add_field(self, label: str, value: str, wrap: bool = False):
        """
        Add a field with label and value.
        
        Args:
            label: Field label
            value: Field value
            wrap: Whether to wrap long text
        """
        # Create container
        field_layout = QVBoxLayout()
        field_layout.setSpacing(5)
        
        # Label
        label_widget = QLabel(label + ":")
        label_widget.setFont(QFont("Segoe UI", 10, QFont.Bold))
        label_widget.setStyleSheet("color: #94A3B8;")
        field_layout.addWidget(label_widget)
        
        # Value
        if wrap and len(value) > 80:
            # Use QTextEdit for long wrapped text
            value_widget = QTextEdit()
            value_widget.setPlainText(value)
            value_widget.setReadOnly(True)
            value_widget.setMaximumHeight(100)
            value_widget.setStyleSheet("""
                QTextEdit {
                    background-color: #0F172A;
                    color: #E2E8F0;
                    border: 1px solid #334155;
                    border-radius: 4px;
                    padding: 8px;
                    font-family: 'Consolas', monospace;
                }
            """)
        else:
            # Use QLabel for short text
            value_widget = QLabel(value)
            value_widget.setFont(QFont("Consolas", 10))
            value_widget.setStyleSheet("""
                QLabel {
                    color: #E2E8F0;
                    background-color: #0F172A;
                    border: 1px solid #334155;
                    border-radius: 4px;
                    padding: 8px;
                }
            """)
            if wrap:
                value_widget.setWordWrap(True)
        
        field_layout.addWidget(value_widget)
        
        self.content_layout.addLayout(field_layout)
    
    def _copy_to_clipboard(self):
        """Copy event details to clipboard."""
        # Format event data as text
        text_parts = []
        
        # Header
        artifact_type = self.event_data.get('artifact_type', 'Unknown')
        text_parts.append(f"=== {artifact_type} Event Details ===\n")
        
        # Basic info
        timestamp = self.event_data.get('timestamp')
        if isinstance(timestamp, datetime):
            timestamp_str = timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        else:
            timestamp_str = str(timestamp)
        
        text_parts.append(f"Timestamp: {timestamp_str}")
        text_parts.append(f"Name: {self.event_data.get('display_name', 'N/A')}")
        text_parts.append(f"Path: {self.event_data.get('full_path', 'N/A')}")
        text_parts.append(f"Event ID: {self.event_data.get('id', 'N/A')}")
        
        # Additional details
        details = self.event_data.get('details', {})
        if details:
            text_parts.append("\n--- Additional Details ---")
            for key, value in details.items():
                formatted_key = key.replace('_', ' ').title()
                if isinstance(value, datetime):
                    formatted_value = value.strftime('%Y-%m-%d %H:%M:%S')
                else:
                    formatted_value = str(value)
                text_parts.append(f"{formatted_key}: {formatted_value}")
        
        # Copy to clipboard
        clipboard_text = '\n'.join(text_parts)
        clipboard = QApplication.clipboard()
        clipboard.setText(clipboard_text)
        
        # Show feedback (change button text temporarily)
        sender = self.sender()
        if sender:
            original_text = sender.text()
            sender.setText("✓ Copied!")
            sender.setStyleSheet("""
                QPushButton {
                    background-color: #10B981;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    border-radius: 4px;
                    font-weight: bold;
                }
            """)
            
            # Reset after 2 seconds
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(2000, lambda: self._reset_copy_button(sender, original_text))
    
    def _reset_copy_button(self, button, original_text):
        """Reset copy button to original state."""
        button.setText(original_text)
        button.setStyleSheet("""
            QPushButton {
                background-color: #3B82F6;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2563EB;
            }
        """)
