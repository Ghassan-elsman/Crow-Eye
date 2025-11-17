"""
Event Details Panel - Display detailed information about selected timeline events.

This module provides the EventDetailsPanel class which displays comprehensive
information about selected events, including timestamps, artifact types, paths,
and type-specific metadata.
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QPushButton, QFrame, QTextEdit, QApplication
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QColor, QPalette
from datetime import datetime
from typing import List, Dict, Optional


class EventDetailsPanel(QWidget):
    """
    Event details display panel.
    
    This panel displays detailed information about selected timeline events,
    including timestamps, artifact types, file/registry paths, and type-specific
    metadata. Supports single and multi-select display with scrolling.
    
    Signals:
        jump_to_event_requested: Emitted when user clicks "Jump to Event" button
    """
    
    jump_to_event_requested = pyqtSignal(dict)  # Emits event data for navigation
    
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
    
    def __init__(self, parent=None):
        """
        Initialize the event details panel.
        
        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        
        # Current state
        self.current_events = []  # List of currently displayed events
        self.nearby_events = []   # Nearby events (before/after)
        self.related_events = []  # Related events (same file/app)
        
        # Initialize UI
        self._init_ui()
    
    def _init_ui(self):
        """Initialize the user interface."""
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Header with title and buttons
        header = self._create_header()
        main_layout.addWidget(header)
        
        # Scrollable content area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: #1E293B;
                border: none;
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
        
        # Content widget inside scroll area
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(10, 10, 10, 10)
        self.content_layout.setSpacing(10)
        self.content_layout.setAlignment(Qt.AlignTop)
        
        self.scroll_area.setWidget(self.content_widget)
        main_layout.addWidget(self.scroll_area)
        
        # Show empty state initially
        self._show_empty_state()
    
    def _create_header(self):
        """
        Create the header section with title and action buttons.
        
        Returns:
            QWidget: Header widget
        """
        header_widget = QWidget()
        header_widget.setStyleSheet("""
            QWidget {
                background-color: #0F172A;
                border-bottom: 1px solid #334155;
            }
        """)
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(10, 8, 10, 8)
        header_layout.setSpacing(10)
        
        # Title label
        title_label = QLabel("Event Details")
        title_font = QFont("Segoe UI", 11, QFont.Bold)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #00FFFF; border: none;")
        header_layout.addWidget(title_label)
        
        header_layout.addStretch()
        
        # Copy button
        self.copy_button = QPushButton("Copy Details")
        self.copy_button.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                color: #E2E8F0;
                border: 1px solid #475569;
                border-radius: 4px;
                padding: 4px 12px;
                font-size: 10px;
            }
            QPushButton:hover {
                background-color: #475569;
            }
            QPushButton:pressed {
                background-color: #1e293b;
            }
            QPushButton:disabled {
                background-color: #1e293b;
                color: #64748b;
            }
        """)
        self.copy_button.clicked.connect(self._copy_to_clipboard)
        self.copy_button.setEnabled(False)
        header_layout.addWidget(self.copy_button)
        
        # Jump to Event button
        self.jump_button = QPushButton("Jump to Event")
        self.jump_button.setStyleSheet("""
            QPushButton {
                background-color: #0ea5e9;
                color: #ffffff;
                border: none;
                border-radius: 4px;
                padding: 4px 12px;
                font-size: 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0284c7;
            }
            QPushButton:pressed {
                background-color: #0369a1;
            }
            QPushButton:disabled {
                background-color: #1e293b;
                color: #64748b;
            }
        """)
        self.jump_button.clicked.connect(self._jump_to_event)
        self.jump_button.setEnabled(False)
        header_layout.addWidget(self.jump_button)
        
        return header_widget
    
    def display_events(self, event_data_list: List[Dict]):
        """
        Display information for one or more selected events.
        
        Args:
            event_data_list: List of event data dictionaries
        """
        # Clear current content
        self._clear_content()
        
        if not event_data_list:
            self._show_empty_state()
            return
        
        # Store current events
        self.current_events = event_data_list
        
        # Enable buttons
        self.copy_button.setEnabled(True)
        self.jump_button.setEnabled(len(event_data_list) == 1)  # Only for single selection
        
        # Display count if multiple events
        if len(event_data_list) > 1:
            count_label = QLabel(f"Selected {len(event_data_list)} events")
            count_label.setStyleSheet("""
                color: #94A3B8;
                font-size: 11px;
                font-weight: bold;
                padding: 5px;
            """)
            self.content_layout.addWidget(count_label)
        
        # Display each event
        for i, event_data in enumerate(event_data_list):
            event_widget = self._create_event_widget(event_data, i)
            self.content_layout.addWidget(event_widget)
            
            # Add separator between events (except after last)
            if i < len(event_data_list) - 1:
                separator = QFrame()
                separator.setFrameShape(QFrame.HLine)
                separator.setStyleSheet("background-color: #334155; max-height: 1px;")
                self.content_layout.addWidget(separator)
        
        # Add stretch at the end to push content to top
        self.content_layout.addStretch()
    
    def _create_event_widget(self, event_data: Dict, index: int) -> QWidget:
        """
        Create a widget displaying a single event's information.
        
        Args:
            event_data: Event data dictionary
            index: Index of event in list (for numbering)
        
        Returns:
            QWidget: Event display widget
        """
        event_widget = QWidget()
        event_layout = QVBoxLayout(event_widget)
        event_layout.setContentsMargins(5, 5, 5, 5)
        event_layout.setSpacing(8)
        
        # Event header with artifact type indicator
        header_layout = QHBoxLayout()
        header_layout.setSpacing(10)
        
        # Artifact type color indicator
        artifact_type = event_data.get('artifact_type', 'Unknown')
        color = self.ARTIFACT_COLORS.get(artifact_type, '#64748b')
        
        color_indicator = QLabel()
        color_indicator.setFixedSize(4, 40)
        color_indicator.setStyleSheet(f"background-color: {color}; border-radius: 2px;")
        header_layout.addWidget(color_indicator)
        
        # Event info
        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)
        
        # Artifact type and display name
        name_label = QLabel(f"<b>{artifact_type}</b>: {event_data.get('display_name', 'Unknown')}")
        name_label.setStyleSheet(f"color: {color}; font-size: 12px;")
        name_label.setWordWrap(True)
        info_layout.addWidget(name_label)
        
        # Timestamp
        timestamp = event_data.get('timestamp')
        if timestamp:
            if isinstance(timestamp, datetime):
                timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M:%S")
            else:
                timestamp_str = str(timestamp)
            
            timestamp_label = QLabel(f"🕐 {timestamp_str}")
            timestamp_label.setStyleSheet("color: #E2E8F0; font-size: 11px;")
            info_layout.addWidget(timestamp_label)
        
        # Full path
        full_path = event_data.get('full_path', '')
        if full_path:
            path_label = QLabel(f"📁 {full_path}")
            path_label.setStyleSheet("color: #94A3B8; font-size: 10px;")
            path_label.setWordWrap(True)
            info_layout.addWidget(path_label)
        
        header_layout.addLayout(info_layout, stretch=1)
        event_layout.addLayout(header_layout)
        
        # Type-specific details
        details = event_data.get('details', {})
        if details:
            details_widget = self._create_details_widget(details, artifact_type)
            event_layout.addWidget(details_widget)
        
        # Annotation if present
        annotation = event_data.get('annotation')
        if annotation:
            annotation_widget = self._create_annotation_widget(annotation)
            event_layout.addWidget(annotation_widget)
        
        return event_widget
    
    def _create_details_widget(self, details: Dict, artifact_type: str) -> QWidget:
        """
        Create a widget displaying type-specific details.
        
        Args:
            details: Details dictionary
            artifact_type: Type of artifact
        
        Returns:
            QWidget: Details display widget
        """
        details_widget = QWidget()
        details_layout = QVBoxLayout(details_widget)
        details_layout.setContentsMargins(20, 5, 5, 5)
        details_layout.setSpacing(3)
        
        # Title
        title_label = QLabel("Details:")
        title_label.setStyleSheet("color: #94A3B8; font-size: 10px; font-weight: bold;")
        details_layout.addWidget(title_label)
        
        # Display details based on artifact type
        if artifact_type == 'Prefetch':
            self._add_detail_row(details_layout, "Run Count", details.get('run_count'))
            self._add_detail_row(details_layout, "Hash", details.get('hash'))
            self._add_detail_row(details_layout, "Created", details.get('created_on'))
            self._add_detail_row(details_layout, "Modified", details.get('modified_on'))
        
        elif artifact_type == 'LNK':
            self._add_detail_row(details_layout, "Target Path", details.get('target_path'))
            self._add_detail_row(details_layout, "Arguments", details.get('arguments'))
            self._add_detail_row(details_layout, "Working Directory", details.get('working_directory'))
            self._add_detail_row(details_layout, "Creation Time", details.get('creation_time'))
            self._add_detail_row(details_layout, "Access Time", details.get('access_time'))
        
        elif artifact_type == 'Registry':
            self._add_detail_row(details_layout, "Key Path", details.get('key_path'))
            self._add_detail_row(details_layout, "Value Name", details.get('value_name'))
            self._add_detail_row(details_layout, "Value Data", details.get('value_data'))
            self._add_detail_row(details_layout, "Value Type", details.get('value_type'))
        
        elif artifact_type == 'BAM':
            self._add_detail_row(details_layout, "Executable Path", details.get('executable_path'))
            self._add_detail_row(details_layout, "Last Execution", details.get('last_execution'))
        
        elif artifact_type == 'SRUM':
            self._add_detail_row(details_layout, "App Name", details.get('app_name'))
            self._add_detail_row(details_layout, "User SID", details.get('user_sid'))
            self._add_detail_row(details_layout, "Bytes Sent", details.get('bytes_sent'))
            self._add_detail_row(details_layout, "Bytes Received", details.get('bytes_received'))
        
        elif artifact_type == 'USN':
            self._add_detail_row(details_layout, "File Name", details.get('file_name'))
            self._add_detail_row(details_layout, "Reason", details.get('reason'))
            self._add_detail_row(details_layout, "File Attributes", details.get('file_attributes'))
        
        elif artifact_type == 'MFT':
            self._add_detail_row(details_layout, "File Name", details.get('file_name'))
            self._add_detail_row(details_layout, "Parent Path", details.get('parent_path'))
            self._add_detail_row(details_layout, "File Size", details.get('file_size'))
            self._add_detail_row(details_layout, "Is Directory", details.get('is_directory'))
        
        elif artifact_type == 'ShellBag':
            self._add_detail_row(details_layout, "Path", details.get('path'))
            self._add_detail_row(details_layout, "Shell Type", details.get('shell_type'))
        
        else:
            # Generic display for unknown types
            for key, value in details.items():
                self._add_detail_row(details_layout, key, value)
        
        return details_widget
    
    def _add_detail_row(self, layout: QVBoxLayout, label: str, value):
        """
        Add a detail row to the layout.
        
        Args:
            layout: Layout to add to
            label: Detail label
            value: Detail value
        """
        if value is None or value == '':
            return
        
        # Convert value to string
        if isinstance(value, datetime):
            value_str = value.strftime("%Y-%m-%d %H:%M:%S")
        else:
            value_str = str(value)
        
        # Create label
        detail_label = QLabel(f"• <b>{label}:</b> {value_str}")
        detail_label.setStyleSheet("color: #CBD5E1; font-size: 10px;")
        detail_label.setWordWrap(True)
        layout.addWidget(detail_label)
    
    def _create_annotation_widget(self, annotation: Dict) -> QWidget:
        """
        Create a widget displaying annotation information.
        
        Args:
            annotation: Annotation data dictionary
        
        Returns:
            QWidget: Annotation display widget
        """
        annotation_widget = QWidget()
        annotation_widget.setStyleSheet("""
            QWidget {
                background-color: #422006;
                border-left: 3px solid #f59e0b;
                border-radius: 4px;
                padding: 5px;
            }
        """)
        annotation_layout = QVBoxLayout(annotation_widget)
        annotation_layout.setContentsMargins(8, 5, 5, 5)
        annotation_layout.setSpacing(3)
        
        # Annotation title
        title_label = QLabel("📝 Annotation")
        title_label.setStyleSheet("color: #fbbf24; font-size: 10px; font-weight: bold;")
        annotation_layout.addWidget(title_label)
        
        # Annotation content
        content = annotation.get('content', '')
        content_label = QLabel(content)
        content_label.setStyleSheet("color: #fde68a; font-size: 10px;")
        content_label.setWordWrap(True)
        annotation_layout.addWidget(content_label)
        
        return annotation_widget
    
    def display_event_context(self, event_data: Dict, nearby_events: List[Dict], related_events: List[Dict]):
        """
        Display event with context information (nearby and related events).
        
        Args:
            event_data: Main event data
            nearby_events: List of nearby events (before/after)
            related_events: List of related events (same file/app)
        """
        # Store context
        self.nearby_events = nearby_events
        self.related_events = related_events
        
        # Display main event first
        self.display_events([event_data])
        
        # Add statistics section
        self._add_statistics_section(event_data, nearby_events, related_events)
        
        # Add context sections
        if nearby_events:
            self._add_context_section("Nearby Events", nearby_events, "🕐")
        
        if related_events:
            self._add_context_section("Related Events", related_events, "🔗")
    
    def _add_statistics_section(self, event_data: Dict, nearby_events: List[Dict], related_events: List[Dict]):
        """
        Add a statistics section showing event context metrics.
        
        Args:
            event_data: Main event data
            nearby_events: List of nearby events
            related_events: List of related events
        """
        # Create statistics widget
        stats_widget = QWidget()
        stats_widget.setStyleSheet("""
            QWidget {
                background-color: #0F172A;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 8px;
            }
        """)
        stats_layout = QVBoxLayout(stats_widget)
        stats_layout.setContentsMargins(8, 8, 8, 8)
        stats_layout.setSpacing(5)
        
        # Title
        title_label = QLabel("📊 Event Statistics")
        title_label.setStyleSheet("color: #00FFFF; font-size: 11px; font-weight: bold;")
        stats_layout.addWidget(title_label)
        
        # Statistics grid
        grid_widget = QWidget()
        grid_layout = QHBoxLayout(grid_widget)
        grid_layout.setContentsMargins(0, 5, 0, 0)
        grid_layout.setSpacing(15)
        
        # Nearby events count
        nearby_stat = self._create_stat_item("Nearby Events", len(nearby_events), "#3b82f6")
        grid_layout.addWidget(nearby_stat)
        
        # Related events count
        related_stat = self._create_stat_item("Related Events", len(related_events), "#10b981")
        grid_layout.addWidget(related_stat)
        
        # Artifact type
        artifact_type = event_data.get('artifact_type', 'Unknown')
        type_stat = self._create_stat_item("Type", artifact_type, "#8b5cf6")
        grid_layout.addWidget(type_stat)
        
        grid_layout.addStretch()
        
        stats_layout.addWidget(grid_widget)
        
        # Add to main layout
        self.content_layout.addWidget(stats_widget)
    
    def _create_stat_item(self, label: str, value, color: str) -> QWidget:
        """
        Create a statistics item widget.
        
        Args:
            label: Stat label
            value: Stat value
            color: Color for the value
        
        Returns:
            QWidget: Stat item widget
        """
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        
        # Value
        value_label = QLabel(str(value))
        value_label.setStyleSheet(f"color: {color}; font-size: 16px; font-weight: bold;")
        value_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(value_label)
        
        # Label
        label_widget = QLabel(label)
        label_widget.setStyleSheet("color: #94A3B8; font-size: 9px;")
        label_widget.setAlignment(Qt.AlignCenter)
        layout.addWidget(label_widget)
        
        return widget
    
    def _add_context_section(self, title: str, events: List[Dict], icon: str):
        """
        Add a context section showing related events.
        
        Args:
            title: Section title
            events: List of events to display
            icon: Icon for the section
        """
        # Section header
        header_label = QLabel(f"{icon} {title} ({len(events)})")
        header_label.setStyleSheet("""
            color: #00FFFF;
            font-size: 11px;
            font-weight: bold;
            padding: 10px 5px 5px 5px;
        """)
        self.content_layout.addWidget(header_label)
        
        # Display events in compact format
        for event in events[:5]:  # Limit to 5 events
            compact_widget = self._create_compact_event_widget(event)
            self.content_layout.addWidget(compact_widget)
        
        # Show "and X more" if there are more events
        if len(events) > 5:
            more_label = QLabel(f"... and {len(events) - 5} more")
            more_label.setStyleSheet("color: #64748b; font-size: 10px; padding-left: 20px;")
            self.content_layout.addWidget(more_label)
    
    def _create_compact_event_widget(self, event_data: Dict) -> QWidget:
        """
        Create a compact event widget for context display.
        
        Args:
            event_data: Event data dictionary
        
        Returns:
            QWidget: Compact event widget
        """
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(20, 3, 5, 3)
        layout.setSpacing(8)
        
        # Color indicator
        artifact_type = event_data.get('artifact_type', 'Unknown')
        color = self.ARTIFACT_COLORS.get(artifact_type, '#64748b')
        
        color_indicator = QLabel()
        color_indicator.setFixedSize(3, 20)
        color_indicator.setStyleSheet(f"background-color: {color}; border-radius: 1px;")
        layout.addWidget(color_indicator)
        
        # Event info (compact)
        timestamp = event_data.get('timestamp')
        if isinstance(timestamp, datetime):
            timestamp_str = timestamp.strftime("%H:%M:%S")
        else:
            timestamp_str = str(timestamp)
        
        display_name = event_data.get('display_name', 'Unknown')
        
        info_label = QLabel(f"{timestamp_str} - <b>{artifact_type}</b>: {display_name}")
        info_label.setStyleSheet("color: #94A3B8; font-size: 10px;")
        info_label.setWordWrap(True)
        layout.addWidget(info_label, stretch=1)
        
        return widget
    
    def clear(self):
        """Clear the panel and show empty state message."""
        self._clear_content()
        self._show_empty_state()
    
    def _clear_content(self):
        """Clear all content from the panel."""
        # Remove all widgets from content layout
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # Reset state
        self.current_events = []
        self.nearby_events = []
        self.related_events = []
        
        # Disable buttons
        self.copy_button.setEnabled(False)
        self.jump_button.setEnabled(False)
    
    def _show_empty_state(self):
        """Show empty state message when no event is selected."""
        empty_label = QLabel("No event selected\n\nClick on an event marker to view details")
        empty_label.setAlignment(Qt.AlignCenter)
        empty_label.setStyleSheet("""
            color: #64748b;
            font-size: 12px;
            padding: 40px;
        """)
        self.content_layout.addWidget(empty_label)
        self.content_layout.addStretch()
    
    def _copy_to_clipboard(self):
        """Copy event details to clipboard."""
        if not self.current_events:
            return
        
        # Build text representation
        text_parts = []
        
        for i, event in enumerate(self.current_events):
            if i > 0:
                text_parts.append("\n" + "="*60 + "\n")
            
            # Basic info
            text_parts.append(f"Artifact Type: {event.get('artifact_type', 'Unknown')}")
            text_parts.append(f"Display Name: {event.get('display_name', 'Unknown')}")
            
            timestamp = event.get('timestamp')
            if timestamp:
                if isinstance(timestamp, datetime):
                    timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    timestamp_str = str(timestamp)
                text_parts.append(f"Timestamp: {timestamp_str}")
            
            full_path = event.get('full_path', '')
            if full_path:
                text_parts.append(f"Path: {full_path}")
            
            # Details
            details = event.get('details', {})
            if details:
                text_parts.append("\nDetails:")
                for key, value in details.items():
                    if value is not None and value != '':
                        text_parts.append(f"  {key}: {value}")
        
        # Copy to clipboard
        clipboard_text = "\n".join(text_parts)
        clipboard = QApplication.clipboard()
        clipboard.setText(clipboard_text)
        
        # Visual feedback (change button text briefly)
        original_text = self.copy_button.text()
        self.copy_button.setText("Copied!")
        QApplication.processEvents()
        
        # Reset button text after delay
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(1000, lambda: self.copy_button.setText(original_text))
    
    def _jump_to_event(self):
        """Emit signal to jump to event in main GUI."""
        if len(self.current_events) == 1:
            self.jump_to_event_requested.emit(self.current_events[0])
