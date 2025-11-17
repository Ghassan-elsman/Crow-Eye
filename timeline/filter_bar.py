"""
Filter Bar - Control panel for timeline filtering and navigation.

This module provides the FilterBar widget which contains controls for:
- Artifact type filtering with checkboxes
- Legend display with color indicators
- Time range selection
- Search functionality
- Zoom controls
- Quick filter presets
"""

from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QCheckBox, QPushButton,
    QLabel, QFrame, QScrollArea, QGroupBox, QRadioButton, QDateTimeEdit,
    QMessageBox, QToolButton, QSizePolicy, QComboBox
)
from PyQt5.QtCore import Qt, pyqtSignal, QDateTime, QSize
from PyQt5.QtGui import QFont, QColor, QPalette, QIcon, QPixmap, QPainter
from datetime import datetime
from timeline.rendering.event_renderer import EventRenderer
from timeline.rendering.zoom_manager import ZoomManager


class FilterBar(QWidget):
    """
    Filter bar widget providing timeline filtering and navigation controls.
    
    This widget provides:
    - Checkboxes for each artifact type with color indicators
    - "Select All" and "Deselect All" buttons
    - Legend showing color mapping for all artifact types
    - Filter state management
    
    Signals:
        filter_changed: Emitted when filter configuration changes (dict)
        time_range_changed: Emitted when time range is modified (start, end)
        zoom_changed: Emitted when zoom level changes (int)
        search_requested: Emitted when search is performed (str)
    """
    
    filter_changed = pyqtSignal(dict)  # Emits filter configuration
    time_range_changed = pyqtSignal(object, object)  # Emits (start_time, end_time)
    zoom_changed = pyqtSignal(int)  # Emits zoom level
    search_requested = pyqtSignal(str)  # Emits search term
    srum_show_ids_changed = pyqtSignal(bool)  # Emits show_ids state
    power_events_toggled = pyqtSignal(bool)  # Emits show_power_events state
    clustering_toggled = pyqtSignal(bool)  # Emits clustering enabled state
    grouping_mode_changed = pyqtSignal(str)  # Emits grouping mode (time/application/path/user/artifact_type)
    force_individual_display = pyqtSignal(bool)  # Emits force individual display state
    
    def __init__(self, parent=None):
        """
        Initialize the filter bar.
        
        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        
        # Initialize event renderer for color mapping
        self.event_renderer = EventRenderer()
        
        # Initialize zoom manager
        self.zoom_manager = ZoomManager(initial_zoom=4)  # Default to day view
        
        # Store checkbox references
        self.artifact_checkboxes = {}
        
        # Store active artifact types (all enabled by default)
        self.active_artifact_types = list(self.event_renderer.COLORS.keys())
        if 'Unknown' in self.active_artifact_types:
            self.active_artifact_types.remove('Unknown')  # Don't include Unknown by default
        
        # Time range state
        self.time_range_mode = 'all_time'  # 'all_time' or 'custom'
        self.custom_start_time = None
        self.custom_end_time = None
        
        # Event count tracking
        self.total_events = 0
        self.filtered_events = 0
        self.events_per_type = {}
        self.is_sampled = False
        self.sample_count = 0
        self.total_available = 0
        
        # Filter feedback tracking
        self.filters_active = False
        self.active_filter_count = 0
        
        # Sampling button reference (created in advanced options dialog)
        self.disable_sampling_btn = None
        
        # Power events state
        self.show_power_events = False
        
        # Clustering state
        self.clustering_enabled = True  # Enabled by default
        self.grouping_mode = 'time'  # Default grouping mode: time-based clustering
        
        # Aggregation state
        self.force_individual = False  # Allow automatic aggregation by default
        
        # Initialize UI
        self._init_ui()
    
    def _init_ui(self):
        """Initialize the user interface components."""
        # Set widget styling with default border
        self.setStyleSheet("""
            QWidget {
                background-color: #1E293B;
                color: #E2E8F0;
                font-family: 'Segoe UI', sans-serif;
            }
        """)
        
        # Set object name for styling
        self.setObjectName("FilterBar")
        
        # Create main layout (horizontal for compact display)
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # Create filter controls section (compact)
        filter_section = self._create_filter_section_compact()
        filter_section.setMinimumWidth(350)
        main_layout.addWidget(filter_section, stretch=2)
        
        # Create time range section (compact)
        time_range_section = self._create_time_range_section_compact()
        time_range_section.setMinimumWidth(200)
        main_layout.addWidget(time_range_section, stretch=1)
        
        # Create zoom controls section (compact)
        zoom_section = self._create_zoom_section_compact()
        zoom_section.setMinimumWidth(150)
        main_layout.addWidget(zoom_section, stretch=0)
        
        # Create power events toggle section
        power_section = self._create_power_events_section()
        power_section.setMinimumWidth(150)
        main_layout.addWidget(power_section, stretch=0)
        
        # Create grouping controls section
        grouping_section = self._create_grouping_section()
        grouping_section.setMinimumWidth(200)
        main_layout.addWidget(grouping_section, stretch=0)
        
        # Create aggregation toggle section
        aggregation_section = self._create_aggregation_section()
        aggregation_section.setMinimumWidth(150)
        main_layout.addWidget(aggregation_section, stretch=0)
        
        # Add stretch to push everything to the left
        main_layout.addStretch()
        
        # Set the layout
        self.setLayout(main_layout)
    
    def _create_filter_section(self):
        """
        Create the artifact type filter section.
        
        Returns:
            QWidget: Filter section widget
        """
        # Create group box for filters
        filter_group = QGroupBox("Artifact Type Filters")
        filter_group.setStyleSheet("""
            QGroupBox {
                background-color: #0F172A;
                color: #00FFFF;
                border: 1px solid #334155;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
                font-weight: 600;
                font-size: 13px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 5px 10px;
                color: #00FFFF;
            }
        """)
        
        filter_layout = QVBoxLayout(filter_group)
        filter_layout.setSpacing(8)
        
        # Create checkboxes for each artifact type
        artifact_types = [
            'Prefetch', 'LNK', 'Registry', 'BAM', 
            'ShellBag', 'SRUM', 'USN', 'MFT', 'Logs'
        ]
        
        for artifact_type in artifact_types:
            checkbox = self._create_artifact_checkbox(artifact_type)
            self.artifact_checkboxes[artifact_type] = checkbox
            filter_layout.addWidget(checkbox)
        
        # Add separator
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setStyleSheet("background-color: #334155; max-height: 1px;")
        filter_layout.addWidget(separator)
        
        # Create button layout for Select All / Deselect All
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        
        # Select All button
        select_all_btn = QPushButton("Select All")
        select_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #3B82F6;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: 600;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #60A5FA;
                border: 1px solid #00FFFF;
            }
            QPushButton:pressed {
                background-color: #1E40AF;
            }
        """)
        select_all_btn.setCursor(Qt.PointingHandCursor)
        select_all_btn.clicked.connect(self._select_all)
        button_layout.addWidget(select_all_btn)
        
        # Deselect All button
        deselect_all_btn = QPushButton("Deselect All")
        deselect_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #64748B;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: 600;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #94A3B8;
                border: 1px solid #00FFFF;
            }
            QPushButton:pressed {
                background-color: #334155;
            }
        """)
        deselect_all_btn.setCursor(Qt.PointingHandCursor)
        deselect_all_btn.clicked.connect(self._deselect_all)
        button_layout.addWidget(deselect_all_btn)
        
        filter_layout.addLayout(button_layout)
        
        return filter_group
    
    def _create_artifact_checkbox(self, artifact_type):
        """
        Create a checkbox for an artifact type with color indicator.
        
        Args:
            artifact_type (str): Artifact type name
        
        Returns:
            QWidget: Checkbox widget with color indicator
        """
        # Create container widget
        container = QWidget()
        container_layout = QHBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(8)
        
        # Create color indicator
        color = self.event_renderer.get_color_for_artifact_type(artifact_type)
        color_indicator = QLabel()
        color_indicator.setFixedSize(16, 16)
        color_indicator.setStyleSheet(f"""
            QLabel {{
                background-color: {color};
                border: 1px solid #E2E8F0;
                border-radius: 3px;
            }}
        """)
        color_indicator.setProperty('artifact_type', artifact_type)
        container_layout.addWidget(color_indicator)
        
        # Create checkbox
        checkbox = QCheckBox(artifact_type)
        checkbox.setChecked(True)  # All enabled by default
        checkbox.setStyleSheet("""
            QCheckBox {
                color: #E2E8F0;
                font-size: 12px;
                font-weight: 500;
                spacing: 5px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 3px;
                border: 1px solid #475569;
                background-color: #1E293B;
            }
            QCheckBox::indicator:unchecked:hover {
                border: 1px solid #00FFFF;
            }
            QCheckBox::indicator:checked {
                background-color: #3B82F6;
                border: 1px solid #3B82F6;
            }
            QCheckBox::indicator:checked:hover {
                background-color: #60A5FA;
                border: 1px solid #00FFFF;
            }
        """)
        checkbox.stateChanged.connect(lambda: self._on_filter_changed())
        checkbox.setProperty('artifact_type', artifact_type)
        checkbox.setProperty('color_indicator', color_indicator)
        container_layout.addWidget(checkbox, stretch=1)
        
        return container
    
    def _create_time_range_section(self):
        """
        Create the time range selection section.
        
        Returns:
            QWidget: Time range section widget
        """
        # Create group box for time range
        time_range_group = QGroupBox("Time Range")
        time_range_group.setStyleSheet("""
            QGroupBox {
                background-color: #0F172A;
                color: #00FFFF;
                border: 1px solid #334155;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
                font-weight: 600;
                font-size: 13px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 5px 10px;
                color: #00FFFF;
            }
        """)
        
        time_range_layout = QVBoxLayout(time_range_group)
        time_range_layout.setSpacing(10)
        
        # Create radio buttons for mode selection
        self.all_time_radio = QRadioButton("All Time")
        self.all_time_radio.setChecked(True)  # Default to all time
        self.all_time_radio.setStyleSheet("""
            QRadioButton {
                color: #E2E8F0;
                font-size: 12px;
                font-weight: 500;
                spacing: 5px;
            }
            QRadioButton::indicator {
                width: 16px;
                height: 16px;
                border-radius: 8px;
                border: 1px solid #475569;
                background-color: #1E293B;
            }
            QRadioButton::indicator:unchecked:hover {
                border: 1px solid #00FFFF;
            }
            QRadioButton::indicator:checked {
                background-color: #3B82F6;
                border: 1px solid #3B82F6;
            }
            QRadioButton::indicator:checked:hover {
                background-color: #60A5FA;
                border: 1px solid #00FFFF;
            }
        """)
        self.all_time_radio.toggled.connect(self._on_time_range_mode_changed)
        time_range_layout.addWidget(self.all_time_radio)
        
        self.custom_range_radio = QRadioButton("Custom Range")
        self.custom_range_radio.setStyleSheet("""
            QRadioButton {
                color: #E2E8F0;
                font-size: 12px;
                font-weight: 500;
                spacing: 5px;
            }
            QRadioButton::indicator {
                width: 16px;
                height: 16px;
                border-radius: 8px;
                border: 1px solid #475569;
                background-color: #1E293B;
            }
            QRadioButton::indicator:unchecked:hover {
                border: 1px solid #00FFFF;
            }
            QRadioButton::indicator:checked {
                background-color: #3B82F6;
                border: 1px solid #3B82F6;
            }
            QRadioButton::indicator:checked:hover {
                background-color: #60A5FA;
                border: 1px solid #00FFFF;
            }
        """)
        self.custom_range_radio.toggled.connect(self._on_time_range_mode_changed)
        time_range_layout.addWidget(self.custom_range_radio)
        
        # Create custom range controls container
        self.custom_range_container = QWidget()
        custom_range_layout = QVBoxLayout(self.custom_range_container)
        custom_range_layout.setContentsMargins(20, 5, 0, 0)
        custom_range_layout.setSpacing(8)
        
        # Start time picker
        start_time_layout = QHBoxLayout()
        start_time_layout.setSpacing(8)
        
        start_label = QLabel("Start:")
        start_label.setStyleSheet("""
            QLabel {
                color: #94A3B8;
                font-size: 11px;
                font-weight: 500;
                min-width: 40px;
            }
        """)
        start_time_layout.addWidget(start_label)
        
        self.start_time_edit = QDateTimeEdit()
        self.start_time_edit.setCalendarPopup(True)
        self.start_time_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.start_time_edit.setDateTime(QDateTime.currentDateTime().addDays(-7))  # Default to 7 days ago
        self.start_time_edit.setStyleSheet("""
            QDateTimeEdit {
                background-color: #1E293B;
                color: #E2E8F0;
                border: 1px solid #475569;
                border-radius: 4px;
                padding: 6px;
                font-size: 11px;
            }
            QDateTimeEdit:hover {
                border: 1px solid #00FFFF;
            }
            QDateTimeEdit:focus {
                border: 1px solid #3B82F6;
            }
            QDateTimeEdit::up-button, QDateTimeEdit::down-button {
                background-color: #334155;
                border: none;
                width: 16px;
            }
            QDateTimeEdit::up-button:hover, QDateTimeEdit::down-button:hover {
                background-color: #475569;
            }
        """)
        self.start_time_edit.dateTimeChanged.connect(self._on_custom_range_changed)
        start_time_layout.addWidget(self.start_time_edit, stretch=1)
        
        custom_range_layout.addLayout(start_time_layout)
        
        # End time picker
        end_time_layout = QHBoxLayout()
        end_time_layout.setSpacing(8)
        
        end_label = QLabel("End:")
        end_label.setStyleSheet("""
            QLabel {
                color: #94A3B8;
                font-size: 11px;
                font-weight: 500;
                min-width: 40px;
            }
        """)
        end_time_layout.addWidget(end_label)
        
        self.end_time_edit = QDateTimeEdit()
        self.end_time_edit.setCalendarPopup(True)
        self.end_time_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.end_time_edit.setDateTime(QDateTime.currentDateTime())  # Default to now
        self.end_time_edit.setStyleSheet("""
            QDateTimeEdit {
                background-color: #1E293B;
                color: #E2E8F0;
                border: 1px solid #475569;
                border-radius: 4px;
                padding: 6px;
                font-size: 11px;
            }
            QDateTimeEdit:hover {
                border: 1px solid #00FFFF;
            }
            QDateTimeEdit:focus {
                border: 1px solid #3B82F6;
            }
            QDateTimeEdit::up-button, QDateTimeEdit::down-button {
                background-color: #334155;
                border: none;
                width: 16px;
            }
            QDateTimeEdit::up-button:hover, QDateTimeEdit::down-button:hover {
                background-color: #475569;
            }
        """)
        self.end_time_edit.dateTimeChanged.connect(self._on_custom_range_changed)
        end_time_layout.addWidget(self.end_time_edit, stretch=1)
        
        custom_range_layout.addLayout(end_time_layout)
        
        time_range_layout.addWidget(self.custom_range_container)
        
        # Initially disable custom range controls
        self.custom_range_container.setEnabled(False)
        
        return time_range_group
    
    def _create_zoom_section(self):
        """
        Create the zoom controls section.
        
        Returns:
            QWidget: Zoom section widget
        """
        # Create group box for zoom controls
        zoom_group = QGroupBox("Zoom Controls")
        zoom_group.setStyleSheet("""
            QGroupBox {
                background-color: #0F172A;
                color: #00FFFF;
                border: 1px solid #334155;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
                font-weight: 600;
                font-size: 13px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 5px 10px;
                color: #00FFFF;
            }
        """)
        
        zoom_layout = QVBoxLayout(zoom_group)
        zoom_layout.setSpacing(10)
        
        # Create zoom level label
        self.zoom_level_label = QLabel(f"Level: {self.zoom_manager.get_zoom_label()}")
        self.zoom_level_label.setStyleSheet("""
            QLabel {
                color: #E2E8F0;
                font-size: 12px;
                font-weight: 600;
                padding: 5px;
            }
        """)
        self.zoom_level_label.setAlignment(Qt.AlignCenter)
        zoom_layout.addWidget(self.zoom_level_label)
        
        # Create button layout for zoom controls
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        
        # Zoom Out button
        self.zoom_out_btn = QPushButton("Zoom Out (−)")
        self.zoom_out_btn.setStyleSheet("""
            QPushButton {
                background-color: #64748B;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 10px 16px;
                font-weight: 600;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #94A3B8;
                border: 1px solid #00FFFF;
            }
            QPushButton:pressed {
                background-color: #334155;
            }
            QPushButton:disabled {
                background-color: #334155;
                color: #64748B;
            }
        """)
        self.zoom_out_btn.setCursor(Qt.PointingHandCursor)
        self.zoom_out_btn.clicked.connect(self._on_zoom_out)
        button_layout.addWidget(self.zoom_out_btn)
        
        # Zoom In button
        self.zoom_in_btn = QPushButton("Zoom In (+)")
        self.zoom_in_btn.setStyleSheet("""
            QPushButton {
                background-color: #3B82F6;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 10px 16px;
                font-weight: 600;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #60A5FA;
                border: 1px solid #00FFFF;
            }
            QPushButton:pressed {
                background-color: #1E40AF;
            }
            QPushButton:disabled {
                background-color: #334155;
                color: #64748B;
            }
        """)
        self.zoom_in_btn.setCursor(Qt.PointingHandCursor)
        self.zoom_in_btn.clicked.connect(self._on_zoom_in)
        button_layout.addWidget(self.zoom_in_btn)
        
        zoom_layout.addLayout(button_layout)
        
        # Update button states
        self._update_zoom_button_states()
        
        return zoom_group
    
    def _create_legend_section(self):
        """
        Create the legend section showing color mapping.
        
        Returns:
            QWidget: Legend section widget
        """
        # Create group box for legend
        legend_group = QGroupBox("Legend")
        legend_group.setStyleSheet("""
            QGroupBox {
                background-color: #0F172A;
                color: #00FFFF;
                border: 1px solid #334155;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
                font-weight: 600;
                font-size: 13px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 5px 10px;
                color: #00FFFF;
            }
        """)
        
        legend_layout = QVBoxLayout(legend_group)
        legend_layout.setSpacing(6)
        
        # Create legend items for each artifact type
        artifact_types = [
            'Prefetch', 'LNK', 'Registry', 'BAM', 
            'ShellBag', 'SRUM', 'USN', 'MFT', 'Logs'
        ]
        
        for artifact_type in artifact_types:
            legend_item = self._create_legend_item(artifact_type)
            legend_layout.addWidget(legend_item)
        
        return legend_group
    
    def _create_legend_item(self, artifact_type):
        """
        Create a legend item showing color and artifact type name.
        
        Args:
            artifact_type (str): Artifact type name
        
        Returns:
            QWidget: Legend item widget
        """
        # Create container widget
        container = QWidget()
        container.setProperty('artifact_type', artifact_type)
        container_layout = QHBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(8)
        
        # Create color box
        color = self.event_renderer.get_color_for_artifact_type(artifact_type)
        color_box = QLabel()
        color_box.setFixedSize(20, 20)
        color_box.setStyleSheet(f"""
            QLabel {{
                background-color: {color};
                border: 1px solid #E2E8F0;
                border-radius: 4px;
            }}
        """)
        color_box.setProperty('artifact_type', artifact_type)
        container_layout.addWidget(color_box)
        
        # Create label
        label = QLabel(artifact_type)
        label.setStyleSheet("""
            QLabel {
                color: #E2E8F0;
                font-size: 12px;
                font-weight: 500;
            }
        """)
        label.setProperty('artifact_type', artifact_type)
        container_layout.addWidget(label, stretch=1)
        
        return container
    
    def _select_all(self):
        """Select all artifact type checkboxes."""
        for checkbox_widget in self.artifact_checkboxes.values():
            # Check if it's a QCheckBox directly or a container
            if isinstance(checkbox_widget, QCheckBox):
                checkbox_widget.setChecked(True)
            elif hasattr(checkbox_widget, 'checkbox'):
                # Container with checkbox attribute
                checkbox_widget.checkbox.setChecked(True)
            else:
                # Find the checkbox within the container
                checkbox = checkbox_widget.findChild(QCheckBox)
                if checkbox:
                    checkbox.setChecked(True)
    
    def _deselect_all(self):
        """Deselect all artifact type checkboxes."""
        for checkbox_widget in self.artifact_checkboxes.values():
            # Check if it's a QCheckBox directly or a container
            if isinstance(checkbox_widget, QCheckBox):
                checkbox_widget.setChecked(False)
            elif hasattr(checkbox_widget, 'checkbox'):
                # Container with checkbox attribute
                checkbox_widget.checkbox.setChecked(False)
            else:
                # Find the checkbox within the container
                checkbox = checkbox_widget.findChild(QCheckBox)
                if checkbox:
                    checkbox.setChecked(False)
    
    def _toggle_advanced_options(self):
        """Open advanced options in a dialog."""
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QDialogButtonBox
        
        # Create dialog
        dialog = QDialog(self)
        dialog.setWindowTitle("Advanced Timeline Options")
        dialog.setMinimumWidth(400)
        dialog.setStyleSheet("""
            QDialog {
                background-color: #0F172A;
                color: #E2E8F0;
            }
            QLabel {
                color: #E2E8F0;
            }
        """)
        
        layout = QVBoxLayout(dialog)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Select All / Deselect All buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        
        select_all_btn = QPushButton("Select All Artifacts")
        select_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #3B82F6;
                color: #FFFFFF;
                border: none;
                border-radius: 4px;
                padding: 8px 15px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #60A5FA;
            }
        """)
        select_all_btn.clicked.connect(self._select_all)
        button_layout.addWidget(select_all_btn)
        
        deselect_all_btn = QPushButton("Deselect All Artifacts")
        deselect_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #64748B;
                color: #FFFFFF;
                border: none;
                border-radius: 4px;
                padding: 8px 15px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #94A3B8;
            }
        """)
        deselect_all_btn.clicked.connect(self._deselect_all)
        button_layout.addWidget(deselect_all_btn)
        
        layout.addLayout(button_layout)
        
        # Sampling threshold control
        sampling_group = QWidget()
        sampling_layout = QVBoxLayout(sampling_group)
        sampling_layout.setContentsMargins(0, 0, 0, 0)
        
        sampling_label = QLabel("Event Sampling:")
        sampling_label.setStyleSheet("color: #E2E8F0; font-size: 12px; font-weight: bold;")
        sampling_layout.addWidget(sampling_label)
        
        sampling_desc = QLabel("Sampling reduces memory usage for large datasets by showing a representative subset of events.")
        sampling_desc.setStyleSheet("color: #94A3B8; font-size: 10px;")
        sampling_desc.setWordWrap(True)
        sampling_layout.addWidget(sampling_desc)
        
        self.disable_sampling_btn = QPushButton("Disable Sampling (Show All Events)")
        self.disable_sampling_btn.setStyleSheet("""
            QPushButton {
                background-color: #DC2626;
                color: #FFFFFF;
                border: none;
                border-radius: 4px;
                padding: 8px 15px;
                font-size: 11px;
                margin-top: 5px;
            }
            QPushButton:hover {
                background-color: #EF4444;
            }
            QPushButton:disabled {
                background-color: #334155;
                color: #64748B;
            }
        """)
        self.disable_sampling_btn.setEnabled(False)
        self.disable_sampling_btn.clicked.connect(self._disable_sampling)
        sampling_layout.addWidget(self.disable_sampling_btn)
        
        layout.addWidget(sampling_group)
        
        # SRUM show IDs control
        srum_group = QWidget()
        srum_layout = QVBoxLayout(srum_group)
        srum_layout.setContentsMargins(0, 0, 0, 0)
        
        srum_label = QLabel("SRUM Display Options:")
        srum_label.setStyleSheet("color: #E2E8F0; font-size: 12px; font-weight: bold;")
        srum_layout.addWidget(srum_label)
        
        self.srum_show_ids_checkbox = QCheckBox("Show SRUM Application IDs")
        self.srum_show_ids_checkbox.setStyleSheet("""
            QCheckBox {
                color: #E2E8F0;
                font-size: 11px;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border: 1px solid #475569;
                border-radius: 3px;
                background-color: #1E293B;
            }
            QCheckBox::indicator:checked {
                background-color: #3B82F6;
                border-color: #3B82F6;
            }
            QCheckBox::indicator:hover {
                border-color: #60A5FA;
            }
        """)
        self.srum_show_ids_checkbox.setToolTip("Show SRUM application IDs alongside resolved names")
        self.srum_show_ids_checkbox.stateChanged.connect(self._on_srum_show_ids_changed)
        srum_layout.addWidget(self.srum_show_ids_checkbox)
        
        layout.addWidget(srum_group)
        
        # Dialog buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.setStyleSheet("""
            QDialogButtonBox QPushButton {
                background-color: #3B82F6;
                color: #FFFFFF;
                border: none;
                border-radius: 4px;
                padding: 8px 20px;
                font-size: 11px;
            }
            QDialogButtonBox QPushButton:hover {
                background-color: #60A5FA;
            }
        """)
        button_box.rejected.connect(dialog.accept)
        layout.addWidget(button_box)
        
        # Show dialog
        dialog.exec_()
    
    def _on_srum_show_ids_changed(self, state):
        """Handle SRUM show IDs checkbox state change."""
        show_ids = (state == Qt.Checked)
        self.srum_show_ids_changed.emit(show_ids)
    
    def _disable_sampling(self):
        """Disable sampling and request full data load."""
        # Show warning
        reply = QMessageBox.warning(
            self,
            "Disable Sampling",
            f"Loading all {self.total_available:,} events may impact performance.\n\n"
            "This may cause the timeline to become slow or unresponsive.\n\n"
            "Do you want to continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # Emit signal to request full data load
            # This would need to be handled by the timeline dialog
            # For now, just log the request
            print(f"User requested to disable sampling and load all {self.total_available} events")
    
    def update_event_counts(self, total_events, filtered_events, events_per_type=None):
        """
        Update event count display.
        
        Args:
            total_events (int): Total number of events loaded
            filtered_events (int): Number of events after filtering
            events_per_type (dict): Optional dictionary of counts per artifact type
        """
        self.total_events = total_events
        self.filtered_events = filtered_events
        
        if events_per_type:
            self.events_per_type = events_per_type
        
        # Calculate filtered count
        filtered_count = total_events - filtered_events if total_events > filtered_events else 0
        
        # Update label with filter status
        if filtered_count > 0:
            self.event_count_label.setText(
                f"Events: {filtered_events:,} of {total_events:,} ({filtered_count:,} filtered)"
            )
        else:
            self.event_count_label.setText(
                f"Events: {total_events:,} total | {filtered_events:,} displayed"
            )
        
        # Add per-type breakdown to tooltip
        if events_per_type:
            tooltip_lines = ["Events per type:"]
            for artifact_type, count in sorted(events_per_type.items()):
                tooltip_lines.append(f"  {artifact_type}: {count:,}")
            self.event_count_label.setToolTip("\n".join(tooltip_lines))
    
    def update_sampling_indicator(self, is_sampled, sample_count, total_available):
        """
        Update sampling indicator display.
        
        Args:
            is_sampled (bool): Whether events are sampled
            sample_count (int): Number of events shown (sampled)
            total_available (int): Total number of events available
        """
        self.is_sampled = is_sampled
        self.sample_count = sample_count
        self.total_available = total_available
        
        if is_sampled:
            # Show sampling indicator
            percentage = (sample_count / total_available * 100) if total_available > 0 else 0
            self.sampling_indicator.setText(
                f"⚠ SAMPLED: Showing {sample_count:,} of {total_available:,} events ({percentage:.1f}%)"
            )
            # Explicitly set visible and update geometry
            self.sampling_indicator.setVisible(True)
            self.sampling_indicator.setHidden(False)
            self.sampling_indicator.updateGeometry()
            # Enable button if it exists (only when advanced dialog is open)
            if self.disable_sampling_btn:
                self.disable_sampling_btn.setEnabled(True)
        else:
            # Hide sampling indicator
            self.sampling_indicator.setVisible(False)
            self.sampling_indicator.setHidden(True)
            # Disable button if it exists
            if self.disable_sampling_btn:
                self.disable_sampling_btn.setEnabled(False)
    
    def _on_filter_changed(self):
        """Handle filter change and emit signal."""
        # Update active artifact types
        self.active_artifact_types = self.get_active_artifact_types()
        
        # Calculate how many filters are active (how many are unchecked)
        total_artifact_types = len(self.artifact_checkboxes)
        active_count = len(self.active_artifact_types)
        filtered_count = total_artifact_types - active_count
        
        # Update filter state tracking
        self.filters_active = (filtered_count > 0)
        self.active_filter_count = filtered_count
        
        # Update visual feedback elements
        self._update_filter_visual_feedback()
        
        # Update color indicators for unchecked items
        for artifact_type, checkbox_widget in self.artifact_checkboxes.items():
            is_checked = False
            
            if isinstance(checkbox_widget, QCheckBox):
                is_checked = checkbox_widget.isChecked()
            elif hasattr(checkbox_widget, 'checkbox'):
                is_checked = checkbox_widget.checkbox.isChecked()
                
                # Update color indicator opacity
                if hasattr(checkbox_widget, 'color_indicator'):
                    color = self.event_renderer.get_color_for_artifact_type(artifact_type)
                    if is_checked:
                        checkbox_widget.color_indicator.setStyleSheet(f"""
                            QLabel {{
                                background-color: {color};
                                border: 1px solid #E2E8F0;
                                border-radius: 6px;
                            }}
                        """)
                    else:
                        checkbox_widget.color_indicator.setStyleSheet("""
                            QLabel {
                                background-color: #64748B;
                                border: 1px solid #475569;
                                border-radius: 6px;
                            }
                        """)
        
        # Update legend to gray out filtered types
        self._update_legend()
        
        # Emit filter changed signal
        filter_config = {
            'artifact_types': self.active_artifact_types
        }
        self.filter_changed.emit(filter_config)
    
    def _on_time_range_mode_changed(self):
        """Handle time range mode change."""
        if self.all_time_radio.isChecked():
            self.time_range_mode = 'all_time'
            # Enable/disable and show/hide custom range container if it exists
            if hasattr(self, 'custom_range_container'):
                self.custom_range_container.setEnabled(False)
                self.custom_range_container.setVisible(False)
            # Emit signal with None values for all time
            self.time_range_changed.emit(None, None)
        else:
            self.time_range_mode = 'custom'
            # Enable/disable and show/hide custom range container if it exists
            if hasattr(self, 'custom_range_container'):
                self.custom_range_container.setEnabled(True)
                self.custom_range_container.setVisible(True)
            # Validate and emit current custom range
            self._validate_and_emit_custom_range()
    
    def _on_custom_range_changed(self):
        """Handle custom date/time range change."""
        if self.time_range_mode == 'custom':
            self._validate_and_emit_custom_range()
    
    def _validate_and_emit_custom_range(self):
        """Validate custom time range and emit signal if valid."""
        # Check if time edit widgets exist (they don't in compact layout)
        if not hasattr(self, 'start_time_edit') or not hasattr(self, 'end_time_edit'):
            return
        
        # Get start and end times
        start_qdt = self.start_time_edit.dateTime()
        end_qdt = self.end_time_edit.dateTime()
        
        # Convert to Python datetime
        start_time = datetime(
            start_qdt.date().year(),
            start_qdt.date().month(),
            start_qdt.date().day(),
            start_qdt.time().hour(),
            start_qdt.time().minute(),
            start_qdt.time().second()
        )
        end_time = datetime(
            end_qdt.date().year(),
            end_qdt.date().month(),
            end_qdt.date().day(),
            end_qdt.time().hour(),
            end_qdt.time().minute(),
            end_qdt.time().second()
        )
        
        # Validate: start time must be before end time
        if start_time >= end_time:
            QMessageBox.warning(
                self,
                "Invalid Time Range",
                "Start time must be before end time.\n\n"
                f"Start: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"End: {end_time.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            return
        
        # Store validated times
        self.custom_start_time = start_time
        self.custom_end_time = end_time
        
        # Emit signal with custom range
        self.time_range_changed.emit(start_time, end_time)
    
    def _update_legend(self):
        """Update legend to gray out filtered artifact types."""
        # Update color indicators in filter checkboxes (if they exist)
        for artifact_type, checkbox_widget in self.artifact_checkboxes.items():
            # Check if it's a container with color indicator or just a checkbox
            if isinstance(checkbox_widget, QCheckBox):
                # Compact layout - checkbox has icon, no separate color indicator
                continue
            else:
                # Original layout - find the checkbox and color indicator
                checkbox = checkbox_widget.findChild(QCheckBox)
                color_indicator = checkbox.property('color_indicator') if checkbox else None
                
                if checkbox and color_indicator:
                    is_checked = checkbox.isChecked()
                    
                    # Update color indicator opacity
                    if is_checked:
                        # Full color
                        color = self.event_renderer.get_color_for_artifact_type(artifact_type)
                        color_indicator.setStyleSheet(f"""
                            QLabel {{
                                background-color: {color};
                                border: 1px solid #E2E8F0;
                                border-radius: 3px;
                            }}
                        """)
                    else:
                        # Grayed out
                        color_indicator.setStyleSheet("""
                            QLabel {
                                background-color: #64748B;
                                border: 1px solid #475569;
                                border-radius: 3px;
                            }
                        """)
        
        # Update legend items
        # Find the legend group box by title
        legend_group = None
        for group_box in self.findChildren(QGroupBox):
            if group_box.title() == "Legend":
                legend_group = group_box
                break
        
        if legend_group:
            # Get direct children of legend group (legend item containers)
            legend_items = []
            for child in legend_group.children():
                if isinstance(child, QWidget) and child.property('artifact_type'):
                    legend_items.append(child)
            
            # Update each legend item
            for legend_item in legend_items:
                artifact_type = legend_item.property('artifact_type')
                if artifact_type:
                    is_active = artifact_type in self.active_artifact_types
                    
                    # Find color box and label (direct children of legend item)
                    color_box = None
                    label = None
                    for child in legend_item.children():
                        if isinstance(child, QLabel):
                            if child.property('artifact_type') == artifact_type:
                                if child.text() == "":
                                    color_box = child
                                else:
                                    label = child
                    
                    # Update color box
                    if color_box:
                        if is_active:
                            # Full color
                            color = self.event_renderer.get_color_for_artifact_type(artifact_type)
                            color_box.setStyleSheet(f"""
                                QLabel {{
                                    background-color: {color};
                                    border: 1px solid #E2E8F0;
                                    border-radius: 4px;
                                }}
                            """)
                        else:
                            # Grayed out
                            color_box.setStyleSheet("""
                                QLabel {
                                    background-color: #64748B;
                                    border: 1px solid #475569;
                                    border-radius: 4px;
                                }
                            """)
                    
                    # Update label
                    if label:
                        if is_active:
                            label.setStyleSheet("""
                                QLabel {
                                    color: #E2E8F0;
                                    font-size: 12px;
                                    font-weight: 500;
                                }
                            """)
                        else:
                            label.setStyleSheet("""
                                QLabel {
                                    color: #64748B;
                                    font-size: 12px;
                                    font-weight: 500;
                                }
                            """)
    
    def _on_zoom_in(self):
        """Handle zoom in button click."""
        if self.zoom_manager.zoom_in():
            # Update label
            self.zoom_level_label.setText(f"Level: {self.zoom_manager.get_zoom_label()}")
            
            # Update button states
            self._update_zoom_button_states()
            
            # Emit zoom changed signal
            self.zoom_changed.emit(self.zoom_manager.current_zoom)
    
    def _on_zoom_out(self):
        """Handle zoom out button click."""
        if self.zoom_manager.zoom_out():
            # Update label
            self.zoom_level_label.setText(f"Level: {self.zoom_manager.get_zoom_label()}")
            
            # Update button states
            self._update_zoom_button_states()
            
            # Emit zoom changed signal
            self.zoom_changed.emit(self.zoom_manager.current_zoom)
    
    def _update_zoom_button_states(self):
        """Update enabled/disabled state of zoom buttons."""
        self.zoom_in_btn.setEnabled(self.zoom_manager.can_zoom_in())
        self.zoom_out_btn.setEnabled(self.zoom_manager.can_zoom_out())
    
    def get_active_artifact_types(self):
        """
        Get list of currently selected artifact types.
        
        Returns:
            list: List of active artifact type names
        """
        active_types = []
        for artifact_type, checkbox_widget in self.artifact_checkboxes.items():
            # Check if it's a QCheckBox directly or a container
            if isinstance(checkbox_widget, QCheckBox):
                if checkbox_widget.isChecked():
                    active_types.append(artifact_type)
            elif hasattr(checkbox_widget, 'checkbox'):
                # Container with checkbox attribute
                if checkbox_widget.checkbox.isChecked():
                    active_types.append(artifact_type)
            else:
                # Find the checkbox within the container
                checkbox = checkbox_widget.findChild(QCheckBox)
                if checkbox and checkbox.isChecked():
                    active_types.append(artifact_type)
        return active_types
    
    def get_time_range(self):
        """
        Get the current time range selection.
        
        Returns:
            tuple: (start_time, end_time) or (None, None) for all time
        """
        if self.time_range_mode == 'all_time':
            return (None, None)
        else:
            return (self.custom_start_time, self.custom_end_time)
    
    def set_time_range_mode(self, mode):
        """
        Set time range mode: 'all_time' or 'custom'.
        
        Args:
            mode (str): Time range mode ('all_time' or 'custom')
        """
        if mode == 'all_time':
            self.all_time_radio.setChecked(True)
        elif mode == 'custom':
            self.custom_range_radio.setChecked(True)
        else:
            raise ValueError(f"Invalid time range mode: {mode}. Must be 'all_time' or 'custom'.")
    
    def set_custom_range(self, start_time, end_time):
        """
        Set custom time range with validation.
        
        Args:
            start_time (datetime): Start time
            end_time (datetime): End time
        
        Raises:
            ValueError: If start_time is not before end_time
        """
        # Validate
        if start_time >= end_time:
            raise ValueError(f"Start time must be before end time. Got start={start_time}, end={end_time}")
        
        # Convert to QDateTime and set
        start_qdt = QDateTime(
            start_time.year, start_time.month, start_time.day,
            start_time.hour, start_time.minute, start_time.second
        )
        end_qdt = QDateTime(
            end_time.year, end_time.month, end_time.day,
            end_time.hour, end_time.minute, end_time.second
        )
        
        self.start_time_edit.setDateTime(start_qdt)
        self.end_time_edit.setDateTime(end_qdt)
        
        # Store times
        self.custom_start_time = start_time
        self.custom_end_time = end_time
        
        # Switch to custom mode if not already
        if self.time_range_mode != 'custom':
            self.set_time_range_mode('custom')
    
    def set_quick_filter(self, preset_name):
        """
        Apply a quick filter preset.
        
        Args:
            preset_name (str): Name of the preset to apply
        """
        # TODO: Implement in Phase 7 when quick filter presets are added
        pass
    
    def update_legend(self, artifact_counts):
        """
        Update legend with event counts per artifact type.
        
        Args:
            artifact_counts (dict): Dictionary mapping artifact types to counts
        """
        # TODO: Implement event count display in future enhancement
        # For now, just update the legend display
        self._update_legend()
    
    def get_zoom_manager(self):
        """
        Get the ZoomManager instance.
        
        Returns:
            ZoomManager: The zoom manager instance
        """
        return self.zoom_manager
    
    def get_current_zoom_level(self):
        """
        Get the current zoom level.
        
        Returns:
            int: Current zoom level (0-10)
        """
        return self.zoom_manager.current_zoom
    
    def set_zoom_level(self, level):
        """
        Set the zoom level programmatically.
        
        Args:
            level (int): Zoom level to set (0-10)
        """
        self.zoom_manager.set_zoom_level(level)
        
        # Update UI
        self.zoom_level_label.setText(f"Level: {self.zoom_manager.get_zoom_label()}")
        self._update_zoom_button_states()
        
        # Emit signal
        self.zoom_changed.emit(self.zoom_manager.current_zoom)
    
    def _create_icon_for_artifact(self, artifact_type):
        """
        Create a colored icon for an artifact type.
        
        Args:
            artifact_type (str): Artifact type name
            
        Returns:
            QIcon: Icon with artifact type color
        """
        # Create a 16x16 pixmap
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.transparent)
        
        # Get color for artifact type
        color_str = self.event_renderer.get_color_for_artifact_type(artifact_type)
        color = QColor(color_str)
        
        # Draw a filled circle
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(color)
        painter.setPen(QColor("#E2E8F0"))
        painter.drawEllipse(2, 2, 12, 12)
        painter.end()
        
        return QIcon(pixmap)
    
    def _create_filter_section_compact(self):
        """Create compact horizontal filter section with icons."""
        filter_group = QGroupBox("Artifact Filters")
        filter_group.setStyleSheet("""
            QGroupBox {
                background-color: #0F172A;
                color: #00FFFF;
                border: 1px solid #334155;
                border-radius: 6px;
                font-weight: 600;
                font-size: 11px;
                padding: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 5px;
            }
        """)
        
        main_layout = QVBoxLayout(filter_group)
        main_layout.setSpacing(5)
        main_layout.setContentsMargins(8, 18, 8, 8)
        
        # Create checkboxes in compact horizontal layout
        checkbox_layout = QHBoxLayout()
        checkbox_layout.setSpacing(8)
        checkbox_layout.setContentsMargins(0, 0, 0, 0)
        
        artifact_types = ['Prefetch', 'LNK', 'Registry', 'BAM', 'ShellBag', 'SRUM', 'USN', 'MFT', 'Logs']
        
        for artifact_type in artifact_types:
            checkbox = self._create_compact_artifact_checkbox(artifact_type)
            self.artifact_checkboxes[artifact_type] = checkbox
            checkbox_layout.addWidget(checkbox, stretch=0)
        
        checkbox_layout.addStretch()
        main_layout.addLayout(checkbox_layout)
        
        # Add event count display with filter status
        count_layout = QHBoxLayout()
        count_layout.setSpacing(8)
        count_layout.setContentsMargins(0, 0, 0, 0)
        
        self.event_count_label = QLabel("Events: 0 total | 0 displayed")
        self.event_count_label.setStyleSheet("""
            QLabel {
                color: #94A3B8;
                font-size: 10px;
                font-weight: 500;
                padding: 2px;
            }
        """)
        count_layout.addWidget(self.event_count_label)
        
        # Add active filter count badge (initially hidden)
        self.filter_badge = QLabel()
        self.filter_badge.setStyleSheet("""
            QLabel {
                background-color: #F59E0B;
                color: #FFFFFF;
                font-size: 9px;
                font-weight: 700;
                padding: 2px 6px;
                border-radius: 8px;
                min-width: 16px;
            }
        """)
        self.filter_badge.setAlignment(Qt.AlignCenter)
        self.filter_badge.setVisible(False)
        self.filter_badge.setToolTip("Number of active filters")
        count_layout.addWidget(self.filter_badge)
        
        # Add "Clear All Filters" button (initially hidden)
        self.clear_filters_btn = QPushButton("Clear Filters")
        self.clear_filters_btn.setStyleSheet("""
            QPushButton {
                background-color: #DC2626;
                color: #FFFFFF;
                border: none;
                border-radius: 4px;
                padding: 3px 8px;
                font-size: 9px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #EF4444;
            }
            QPushButton:pressed {
                background-color: #B91C1C;
            }
        """)
        self.clear_filters_btn.setVisible(False)
        self.clear_filters_btn.setToolTip("Clear all active filters and show all events")
        self.clear_filters_btn.clicked.connect(self._clear_all_filters)
        count_layout.addWidget(self.clear_filters_btn)
        
        count_layout.addStretch()
        main_layout.addLayout(count_layout)
        
        # Add sampling indicator (initially hidden)
        self.sampling_indicator = QLabel()
        self.sampling_indicator.setStyleSheet("""
            QLabel {
                color: #F59E0B;
                font-size: 10px;
                font-weight: 600;
                padding: 2px;
                background-color: #78350F;
                border-radius: 3px;
            }
        """)
        self.sampling_indicator.setVisible(False)
        main_layout.addWidget(self.sampling_indicator)
        
        # Add advanced options button (opens dialog)
        self.advanced_toggle_btn = QPushButton("⚙ Advanced Options")
        self.advanced_toggle_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #64748B;
                border: none;
                text-align: left;
                padding: 3px;
                font-size: 10px;
            }
            QPushButton:hover {
                color: #00FFFF;
            }
            QPushButton:checked {
                color: #00FFFF;
            }
        """)
        self.advanced_toggle_btn.clicked.connect(self._toggle_advanced_options)
        main_layout.addWidget(self.advanced_toggle_btn)
        
        return filter_group
    
    def _create_compact_artifact_checkbox(self, artifact_type):
        """
        Create a compact checkbox with icon for an artifact type.
        
        Args:
            artifact_type (str): Artifact type name
        
        Returns:
            QWidget: Container with icon and checkbox
        """
        # Create container
        container = QWidget()
        container_layout = QHBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(3)
        
        # Create color indicator icon
        color = self.event_renderer.get_color_for_artifact_type(artifact_type)
        color_indicator = QLabel()
        color_indicator.setFixedSize(12, 12)
        color_indicator.setStyleSheet(f"""
            QLabel {{
                background-color: {color};
                border: 1px solid #E2E8F0;
                border-radius: 6px;
            }}
        """)
        container_layout.addWidget(color_indicator)
        
        # Create checkbox with text
        checkbox = QCheckBox(artifact_type)
        checkbox.setChecked(True)  # All enabled by default
        
        # Compact styling
        checkbox.setStyleSheet("""
            QCheckBox {
                color: #E2E8F0;
                font-size: 10px;
                font-weight: 500;
                spacing: 3px;
            }
            QCheckBox::indicator {
                width: 12px;
                height: 12px;
                border-radius: 2px;
                border: 1px solid #475569;
                background-color: #1E293B;
            }
            QCheckBox::indicator:unchecked:hover {
                border: 1px solid #00FFFF;
            }
            QCheckBox::indicator:checked {
                background-color: #3B82F6;
                border: 1px solid #3B82F6;
            }
            QCheckBox::indicator:checked:hover {
                background-color: #60A5FA;
            }
        """)
        
        checkbox.stateChanged.connect(lambda: self._on_filter_changed())
        checkbox.setProperty('artifact_type', artifact_type)
        container_layout.addWidget(checkbox)
        
        # Store checkbox reference in container for easy access
        container.checkbox = checkbox
        container.color_indicator = color_indicator
        
        return container
    
    def _create_time_range_section_compact(self):
        """Create compact time range section with collapsible custom range controls."""
        time_group = QGroupBox("Time Range")
        time_group.setStyleSheet("""
            QGroupBox {
                background-color: #0F172A;
                color: #00FFFF;
                border: 1px solid #334155;
                border-radius: 6px;
                font-weight: 600;
                font-size: 11px;
                padding-top: 10px;
            }
        """)
        
        main_layout = QVBoxLayout(time_group)
        main_layout.setSpacing(5)
        main_layout.setContentsMargins(8, 18, 8, 8)
        
        # Radio buttons in horizontal layout
        radio_layout = QHBoxLayout()
        radio_layout.setSpacing(8)
        
        self.all_time_radio = QRadioButton("All Time")
        self.all_time_radio.setChecked(True)
        self.all_time_radio.setStyleSheet("""
            QRadioButton {
                color: #E2E8F0;
                font-size: 10px;
                font-weight: 500;
                spacing: 3px;
            }
            QRadioButton::indicator {
                width: 12px;
                height: 12px;
                border-radius: 6px;
                border: 1px solid #475569;
                background-color: #1E293B;
            }
            QRadioButton::indicator:unchecked:hover {
                border: 1px solid #00FFFF;
            }
            QRadioButton::indicator:checked {
                background-color: #3B82F6;
                border: 1px solid #3B82F6;
            }
            QRadioButton::indicator:checked:hover {
                background-color: #60A5FA;
            }
        """)
        self.all_time_radio.toggled.connect(self._on_time_range_mode_changed)
        radio_layout.addWidget(self.all_time_radio)
        
        self.custom_range_radio = QRadioButton("Custom")
        self.custom_range_radio.setStyleSheet("""
            QRadioButton {
                color: #E2E8F0;
                font-size: 10px;
                font-weight: 500;
                spacing: 3px;
            }
            QRadioButton::indicator {
                width: 12px;
                height: 12px;
                border-radius: 6px;
                border: 1px solid #475569;
                background-color: #1E293B;
            }
            QRadioButton::indicator:unchecked:hover {
                border: 1px solid #00FFFF;
            }
            QRadioButton::indicator:checked {
                background-color: #3B82F6;
                border: 1px solid #3B82F6;
            }
            QRadioButton::indicator:checked:hover {
                background-color: #60A5FA;
            }
        """)
        self.custom_range_radio.toggled.connect(self._on_time_range_mode_changed)
        radio_layout.addWidget(self.custom_range_radio)
        radio_layout.addStretch()
        
        main_layout.addLayout(radio_layout)
        
        # Create collapsible custom range controls container
        self.custom_range_container = QWidget()
        custom_range_layout = QVBoxLayout(self.custom_range_container)
        custom_range_layout.setContentsMargins(5, 5, 5, 0)
        custom_range_layout.setSpacing(5)
        
        # Start time picker
        start_time_layout = QHBoxLayout()
        start_time_layout.setSpacing(5)
        
        start_label = QLabel("Start:")
        start_label.setStyleSheet("""
            QLabel {
                color: #94A3B8;
                font-size: 10px;
                font-weight: 500;
                min-width: 35px;
            }
        """)
        start_time_layout.addWidget(start_label)
        
        self.start_time_edit = QDateTimeEdit()
        self.start_time_edit.setCalendarPopup(True)
        self.start_time_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.start_time_edit.setDateTime(QDateTime.currentDateTime().addDays(-7))  # Default to 7 days ago
        self.start_time_edit.setStyleSheet("""
            QDateTimeEdit {
                background-color: #1E293B;
                color: #E2E8F0;
                border: 1px solid #475569;
                border-radius: 4px;
                padding: 4px;
                font-size: 10px;
            }
            QDateTimeEdit:hover {
                border: 1px solid #00FFFF;
            }
            QDateTimeEdit:focus {
                border: 1px solid #3B82F6;
            }
            QDateTimeEdit::up-button, QDateTimeEdit::down-button {
                background-color: #334155;
                border: none;
                width: 14px;
            }
            QDateTimeEdit::up-button:hover, QDateTimeEdit::down-button:hover {
                background-color: #475569;
            }
        """)
        self.start_time_edit.dateTimeChanged.connect(self._on_custom_range_changed)
        start_time_layout.addWidget(self.start_time_edit, stretch=1)
        
        custom_range_layout.addLayout(start_time_layout)
        
        # End time picker
        end_time_layout = QHBoxLayout()
        end_time_layout.setSpacing(5)
        
        end_label = QLabel("End:")
        end_label.setStyleSheet("""
            QLabel {
                color: #94A3B8;
                font-size: 10px;
                font-weight: 500;
                min-width: 35px;
            }
        """)
        end_time_layout.addWidget(end_label)
        
        self.end_time_edit = QDateTimeEdit()
        self.end_time_edit.setCalendarPopup(True)
        self.end_time_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.end_time_edit.setDateTime(QDateTime.currentDateTime())  # Default to now
        self.end_time_edit.setStyleSheet("""
            QDateTimeEdit {
                background-color: #1E293B;
                color: #E2E8F0;
                border: 1px solid #475569;
                border-radius: 4px;
                padding: 4px;
                font-size: 10px;
            }
            QDateTimeEdit:hover {
                border: 1px solid #00FFFF;
            }
            QDateTimeEdit:focus {
                border: 1px solid #3B82F6;
            }
            QDateTimeEdit::up-button, QDateTimeEdit::down-button {
                background-color: #334155;
                border: none;
                width: 14px;
            }
            QDateTimeEdit::up-button:hover, QDateTimeEdit::down-button:hover {
                background-color: #475569;
            }
        """)
        self.end_time_edit.dateTimeChanged.connect(self._on_custom_range_changed)
        end_time_layout.addWidget(self.end_time_edit, stretch=1)
        
        custom_range_layout.addLayout(end_time_layout)
        
        # Initially disable and hide custom range controls
        self.custom_range_container.setEnabled(False)
        self.custom_range_container.setVisible(False)
        
        main_layout.addWidget(self.custom_range_container)
        
        return time_group
    
    def _create_zoom_section_compact(self):
        """Create compact zoom controls section."""
        zoom_group = QGroupBox("Zoom")
        zoom_group.setStyleSheet("""
            QGroupBox {
                background-color: #0F172A;
                color: #00FFFF;
                border: 1px solid #334155;
                border-radius: 6px;
                font-weight: 600;
                font-size: 11px;
                padding-top: 10px;
            }
        """)
        
        layout = QHBoxLayout(zoom_group)
        layout.setSpacing(5)
        
        # Zoom level label
        self.zoom_level_label = QLabel(f"{self.zoom_manager.get_zoom_label()}")
        self.zoom_level_label.setStyleSheet("color: #E2E8F0; font-size: 11px;")
        layout.addWidget(self.zoom_level_label)
        
        # Zoom out button
        self.zoom_out_btn = QPushButton("−")
        self.zoom_out_btn.setFixedSize(40, 40)
        self.zoom_out_btn.setStyleSheet("""
            QPushButton {
                background-color: #1E293B;
                color: #E2E8F0;
                border: 2px solid #475569;
                border-radius: 6px;
                font-size: 20px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #334155;
                border-color: #00FFFF;
            }
            QPushButton:pressed {
                background-color: #0F172A;
            }
            QPushButton:disabled {
                background-color: #0F172A;
                color: #475569;
                border-color: #334155;
            }
        """)
        self.zoom_out_btn.setToolTip("Zoom Out (Mouse Wheel Down)")
        self.zoom_out_btn.clicked.connect(self._on_zoom_out)
        layout.addWidget(self.zoom_out_btn)
        
        # Zoom in button
        self.zoom_in_btn = QPushButton("+")
        self.zoom_in_btn.setFixedSize(40, 40)
        self.zoom_in_btn.setStyleSheet("""
            QPushButton {
                background-color: #1E293B;
                color: #E2E8F0;
                border: 2px solid #475569;
                border-radius: 6px;
                font-size: 20px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #334155;
                border-color: #00FFFF;
            }
            QPushButton:pressed {
                background-color: #0F172A;
            }
            QPushButton:disabled {
                background-color: #0F172A;
                color: #475569;
                border-color: #334155;
            }
        """)
        self.zoom_in_btn.setToolTip("Zoom In (Mouse Wheel Up)")
        self.zoom_in_btn.clicked.connect(self._on_zoom_in)
        layout.addWidget(self.zoom_in_btn)
        
        self._update_zoom_button_states()
        
        return zoom_group

    def _create_power_events_section(self):
        """Create power events toggle section."""
        power_group = QGroupBox("Power Events")
        power_group.setStyleSheet("""
            QGroupBox {
                background-color: #0F172A;
                color: #00FFFF;
                border: 1px solid #334155;
                border-radius: 6px;
                font-weight: 600;
                font-size: 11px;
                padding-top: 10px;
            }
        """)
        
        layout = QVBoxLayout(power_group)
        layout.setSpacing(5)
        
        # Power events checkbox
        self.power_events_checkbox = QCheckBox("Show Power Events")
        self.power_events_checkbox.setStyleSheet("""
            QCheckBox {
                color: #E2E8F0;
                font-size: 11px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
            }
        """)
        self.power_events_checkbox.setChecked(False)
        self.power_events_checkbox.stateChanged.connect(self._on_power_events_toggled)
        layout.addWidget(self.power_events_checkbox)
        
        return power_group
    
    def _on_power_events_toggled(self, state):
        """Handle power events checkbox toggle."""
        self.show_power_events = (state == Qt.Checked)
        self.power_events_toggled.emit(self.show_power_events)
    
    def get_show_power_events(self):
        """Get current power events visibility state."""
        return self.show_power_events
    
    def set_show_power_events(self, show: bool):
        """Set power events visibility state."""
        self.show_power_events = show
        self.power_events_checkbox.setChecked(show)
    
    def _create_grouping_section(self):
        """Create event grouping/clustering controls section."""
        grouping_group = QGroupBox("Event Grouping")
        grouping_group.setStyleSheet("""
            QGroupBox {
                background-color: #0F172A;
                color: #00FFFF;
                border: 1px solid #334155;
                border-radius: 6px;
                font-weight: 600;
                font-size: 11px;
                padding-top: 10px;
            }
        """)
        
        layout = QVBoxLayout(grouping_group)
        layout.setSpacing(8)
        
        # Clustering toggle checkbox
        self.clustering_checkbox = QCheckBox("Enable Clustering")
        self.clustering_checkbox.setStyleSheet("""
            QCheckBox {
                color: #E2E8F0;
                font-size: 11px;
                font-weight: 500;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 3px;
                border: 1px solid #475569;
                background-color: #1E293B;
            }
            QCheckBox::indicator:unchecked:hover {
                border: 1px solid #00FFFF;
            }
            QCheckBox::indicator:checked {
                background-color: #3B82F6;
                border: 1px solid #3B82F6;
            }
            QCheckBox::indicator:checked:hover {
                background-color: #60A5FA;
            }
        """)
        self.clustering_checkbox.setChecked(True)  # Enabled by default
        self.clustering_checkbox.setToolTip("Group nearby events to reduce visual clutter")
        self.clustering_checkbox.stateChanged.connect(self._on_clustering_toggled)
        layout.addWidget(self.clustering_checkbox)
        
        # Grouping mode selector
        grouping_mode_layout = QHBoxLayout()
        grouping_mode_layout.setSpacing(5)
        
        grouping_label = QLabel("Group By:")
        grouping_label.setStyleSheet("""
            QLabel {
                color: #94A3B8;
                font-size: 10px;
                font-weight: 500;
            }
        """)
        grouping_mode_layout.addWidget(grouping_label)
        
        self.grouping_mode_combo = QComboBox()
        self.grouping_mode_combo.addItems([
            "Time Window",
            "Application",
            "File Path",
            "User",
            "Artifact Type"
        ])
        self.grouping_mode_combo.setStyleSheet("""
            QComboBox {
                background-color: #1E293B;
                color: #E2E8F0;
                border: 1px solid #475569;
                border-radius: 4px;
                padding: 5px;
                font-size: 10px;
            }
            QComboBox:hover {
                border: 1px solid #00FFFF;
            }
            QComboBox:focus {
                border: 1px solid #3B82F6;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid #E2E8F0;
                margin-right: 5px;
            }
            QComboBox QAbstractItemView {
                background-color: #1E293B;
                color: #E2E8F0;
                border: 1px solid #475569;
                selection-background-color: #3B82F6;
                selection-color: #FFFFFF;
            }
        """)
        self.grouping_mode_combo.setToolTip(
            "Time Window: Group events within time window\n"
            "Application: Group by application name\n"
            "File Path: Group by file/registry path\n"
            "User: Group by user (if available)\n"
            "Artifact Type: Group by artifact type"
        )
        self.grouping_mode_combo.currentTextChanged.connect(self._on_grouping_mode_changed)
        grouping_mode_layout.addWidget(self.grouping_mode_combo, stretch=1)
        
        layout.addLayout(grouping_mode_layout)
        
        # Initially enable grouping controls
        self.grouping_mode_combo.setEnabled(True)
        
        return grouping_group
    
    def _on_clustering_toggled(self, state):
        """Handle clustering checkbox toggle."""
        self.clustering_enabled = (state == Qt.Checked)
        
        # Enable/disable grouping mode selector based on clustering state
        self.grouping_mode_combo.setEnabled(self.clustering_enabled)
        
        # Emit signal
        self.clustering_toggled.emit(self.clustering_enabled)
    
    def _on_grouping_mode_changed(self, text):
        """Handle grouping mode selection change."""
        # Map display text to internal mode names
        mode_mapping = {
            "Time Window": "time",
            "Application": "application",
            "File Path": "path",
            "User": "user",
            "Artifact Type": "artifact_type"
        }
        
        self.grouping_mode = mode_mapping.get(text, "time")
        
        # Emit signal
        self.grouping_mode_changed.emit(self.grouping_mode)
    
    def get_clustering_enabled(self):
        """Get current clustering enabled state."""
        return self.clustering_enabled
    
    def set_clustering_enabled(self, enabled: bool):
        """Set clustering enabled state."""
        self.clustering_enabled = enabled
        self.clustering_checkbox.setChecked(enabled)
    
    def get_grouping_mode(self):
        """Get current grouping mode."""
        return self.grouping_mode
    
    def set_grouping_mode(self, mode: str):
        """
        Set grouping mode.
        
        Args:
            mode (str): Grouping mode ('time', 'application', 'path', 'user', 'artifact_type')
        """
        # Map internal mode names to display text
        mode_mapping = {
            "time": "Time Window",
            "application": "Application",
            "path": "File Path",
            "user": "User",
            "artifact_type": "Artifact Type"
        }
        
        display_text = mode_mapping.get(mode, "Time Window")
        index = self.grouping_mode_combo.findText(display_text)
        if index >= 0:
            self.grouping_mode_combo.setCurrentIndex(index)
            self.grouping_mode = mode

    def _create_aggregation_section(self):
        """
        Create the aggregation toggle section.
        
        Returns:
            QWidget: Aggregation section widget
        """
        # Create group box for aggregation controls
        aggregation_group = QGroupBox("Display Mode")
        aggregation_group.setStyleSheet("""
            QGroupBox {
                background-color: #0F172A;
                color: #00FFFF;
                border: 1px solid #334155;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
                font-weight: 600;
                font-size: 13px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 5px 10px;
                color: #00FFFF;
            }
        """)
        
        aggregation_layout = QVBoxLayout(aggregation_group)
        aggregation_layout.setSpacing(10)
        
        # Create checkbox for force individual display
        self.force_individual_checkbox = QCheckBox("Force Individual Events")
        self.force_individual_checkbox.setStyleSheet("""
            QCheckBox {
                color: #E2E8F0;
                font-size: 12px;
                font-weight: 500;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 2px solid #475569;
                border-radius: 4px;
                background-color: #1E293B;
            }
            QCheckBox::indicator:hover {
                border: 2px solid #00FFFF;
            }
            QCheckBox::indicator:checked {
                background-color: #3B82F6;
                border: 2px solid #3B82F6;
                image: url(none);
            }
            QCheckBox::indicator:checked:hover {
                background-color: #60A5FA;
                border: 2px solid #00FFFF;
            }
        """)
        self.force_individual_checkbox.setChecked(False)
        self.force_individual_checkbox.setToolTip(
            "Force individual event display even when >1000 events are visible.\n"
            "Disables automatic aggregation mode."
        )
        self.force_individual_checkbox.stateChanged.connect(self._on_force_individual_changed)
        aggregation_layout.addWidget(self.force_individual_checkbox)
        
        # Add info label
        info_label = QLabel("Auto-aggregates when >1000 events visible")
        info_label.setStyleSheet("""
            QLabel {
                color: #94A3B8;
                font-size: 10px;
                font-style: italic;
            }
        """)
        info_label.setWordWrap(True)
        aggregation_layout.addWidget(info_label)
        
        return aggregation_group
    
    def _on_force_individual_changed(self, state):
        """Handle force individual display checkbox state change."""
        self.force_individual = (state == Qt.Checked)
        self.force_individual_display.emit(self.force_individual)
    
    def get_force_individual(self):
        """
        Get current force individual display state.
        
        Returns:
            bool: True if forcing individual display, False otherwise
        """
        return self.force_individual
    
    def set_force_individual(self, force: bool):
        """
        Set force individual display state.
        
        Args:
            force (bool): True to force individual display, False to allow aggregation
        """
        self.force_individual = force
        if hasattr(self, 'force_individual_checkbox'):
            self.force_individual_checkbox.setChecked(force)
    
    def _update_filter_visual_feedback(self):
        """Update visual feedback elements based on filter state."""
        if self.filters_active:
            # Show filter badge with count
            self.filter_badge.setText(f"{self.active_filter_count}")
            self.filter_badge.setVisible(True)
            
            # Show clear filters button
            self.clear_filters_btn.setVisible(True)
            
            # Highlight filter bar with colored border
            self.setStyleSheet("""
                QWidget#FilterBar {
                    background-color: #1E293B;
                    color: #E2E8F0;
                    font-family: 'Segoe UI', sans-serif;
                    border: 2px solid #F59E0B;
                    border-radius: 4px;
                }
            """)
            
            # Update event count label to show filter status
            if self.total_events > 0:
                filtered_out = self.total_events - self.filtered_events
                self.event_count_label.setText(
                    f"Events: {self.filtered_events:,} of {self.total_events:,} ({filtered_out:,} filtered)"
                )
        else:
            # Hide filter badge
            self.filter_badge.setVisible(False)
            
            # Hide clear filters button
            self.clear_filters_btn.setVisible(False)
            
            # Reset filter bar border to default
            self.setStyleSheet("""
                QWidget#FilterBar {
                    background-color: #1E293B;
                    color: #E2E8F0;
                    font-family: 'Segoe UI', sans-serif;
                }
            """)
            
            # Update event count label to normal display
            if self.total_events > 0:
                self.event_count_label.setText(
                    f"Events: {self.total_events:,} total | {self.filtered_events:,} displayed"
                )
    
    def _clear_all_filters(self):
        """Clear all active filters and show all artifact types."""
        # Select all artifact type checkboxes
        self._select_all()
        
        # Reset time range to all time if custom range is active
        if self.time_range_mode == 'custom':
            self.all_time_radio.setChecked(True)
        
        # Note: Filter change signal will be emitted by _select_all() -> checkbox state changes -> _on_filter_changed()
