"""
Timeline Configuration Dialog
=============================

This module provides a dialog for configuring the timeline visualization before data loading.
It allows the user to select:
1. Time range (start and end time)
2. Artifact types to include
3. Option to load all data

Author: Crow Eye Timeline Feature
Version: 1.0
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QDateTimeEdit, 
    QCheckBox, QGroupBox, QPushButton, QGridLayout, QScrollArea,
    QWidget, QMessageBox, QRadioButton, QButtonGroup
)
from PyQt5.QtCore import Qt, QDateTime, QDate, QTime
from datetime import datetime, timedelta

class TimelineConfigDialog(QDialog):
    """
    Dialog for configuring timeline data loading parameters.
    """
    
    def __init__(self, parent=None, data_manager=None):
        """
        Initialize the configuration dialog.
        
        Args:
            parent: Parent widget
            data_manager: TimelineDataManager instance to fetch available artifacts and bounds
        """
        super().__init__(parent)
        self.data_manager = data_manager
        self.result_config = None
        
        # Default bounds
        self.min_date = datetime(2000, 1, 1)
        self.max_date = datetime.now()
        
        # Fetch actual bounds if available
        if self.data_manager:
            try:
                start, end = self.data_manager.get_all_time_bounds()
                if start and end:
                    self.min_date = start
                    self.max_date = end
            except Exception:
                pass  # Fallback to defaults
        
        self._init_ui()
        
    def _init_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle("Timeline Configuration")
        self.setMinimumWidth(600)
        self.setMinimumHeight(500)
        self.setModal(True)
        
        # Apply dark theme styling
        self.setStyleSheet("""
            QDialog {
                background-color: #0F172A;
                color: #E2E8F0;
            }
            QLabel {
                color: #E2E8F0;
                font-size: 12px;
            }
            QGroupBox {
                background-color: #1E293B;
                color: #00FFFF;
                border: 2px solid #334155;
                border-radius: 8px;
                font-weight: 600;
                font-size: 13px;
                padding: 15px;
                margin-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px;
                color: #00FFFF;
            }
            QRadioButton {
                color: #E2E8F0;
                font-size: 12px;
                spacing: 8px;
            }
            QRadioButton::indicator {
                width: 16px;
                height: 16px;
                border-radius: 8px;
                border: 2px solid #475569;
                background-color: #1E293B;
            }
            QRadioButton::indicator:checked {
                background-color: #3B82F6;
                border: 2px solid #60A5FA;
            }
            QRadioButton::indicator:hover {
                border: 2px solid #00FFFF;
            }
            QCheckBox {
                color: #E2E8F0;
                font-size: 12px;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 3px;
                border: 2px solid #475569;
                background-color: #1E293B;
            }
            QCheckBox::indicator:checked {
                background-color: #3B82F6;
                border: 2px solid #60A5FA;
            }
            QCheckBox::indicator:hover {
                border: 2px solid #00FFFF;
            }
            QDateTimeEdit {
                background-color: #1E293B;
                color: #E2E8F0;
                border: 2px solid #475569;
                border-radius: 6px;
                padding: 6px;
                font-size: 12px;
            }
            QDateTimeEdit:focus {
                border: 2px solid #00FFFF;
            }
            QDateTimeEdit::up-button, QDateTimeEdit::down-button {
                background-color: #334155;
                border: none;
                width: 20px;
            }
            QDateTimeEdit::up-button:hover, QDateTimeEdit::down-button:hover {
                background-color: #475569;
            }
            QDateTimeEdit::up-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-bottom: 6px solid #E2E8F0;
            }
            QDateTimeEdit::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 6px solid #E2E8F0;
            }
            QPushButton {
                background-color: #334155;
                color: #E2E8F0;
                border: 1px solid #475569;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #475569;
                border: 1px solid #00FFFF;
            }
            QPushButton:pressed {
                background-color: #1E293B;
            }
            QScrollArea {
                background-color: #1E293B;
                border: 2px solid #334155;
                border-radius: 6px;
            }
            QScrollBar:vertical {
                background-color: #1E293B;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #475569;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #64748B;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # --- Time Range Section ---
        time_group = QGroupBox("Time Range")
        time_layout = QVBoxLayout(time_group)
        
        # Radio buttons for mode
        self.radio_all_time = QRadioButton("Load All Time")
        self.radio_custom_time = QRadioButton("Custom Range")
        self.radio_all_time.setChecked(True)
        
        time_bg = QButtonGroup(self)
        time_bg.addButton(self.radio_all_time)
        time_bg.addButton(self.radio_custom_time)
        
        time_layout.addWidget(self.radio_all_time)
        time_layout.addWidget(self.radio_custom_time)
        
        # Date pickers
        picker_layout = QGridLayout()
        picker_layout.addWidget(QLabel("From:"), 0, 0)
        self.start_picker = QDateTimeEdit()
        self.start_picker.setCalendarPopup(True)
        self.start_picker.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.start_picker.setDateTime(self.min_date)
        picker_layout.addWidget(self.start_picker, 0, 1)
        
        picker_layout.addWidget(QLabel("To:"), 1, 0)
        self.end_picker = QDateTimeEdit()
        self.end_picker.setCalendarPopup(True)
        self.end_picker.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.end_picker.setDateTime(self.max_date)
        picker_layout.addWidget(self.end_picker, 1, 1)
        
        # Container for pickers to enable/disable
        self.picker_container = QWidget()
        self.picker_container.setLayout(picker_layout)
        self.picker_container.setEnabled(False) # Disabled by default (All Time)
        
        time_layout.addWidget(self.picker_container)
        layout.addWidget(time_group)
        
        # Connect radio signals
        self.radio_all_time.toggled.connect(self._toggle_time_pickers)
        
        # --- Artifacts Section ---
        artifact_group = QGroupBox("Artifacts")
        artifact_layout = QVBoxLayout(artifact_group)
        
        # Control buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        
        self.btn_select_all = QPushButton("✓ Select All")
        self.btn_select_all.setStyleSheet("""
            QPushButton {
                background-color: #1E293B;
                color: #10B981;
                border: 1px solid #10B981;
                border-radius: 5px;
                padding: 6px 12px;
                font-size: 11px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #10B981;
                color: #FFFFFF;
                border: 1px solid #34D399;
            }
        """)
        
        self.btn_deselect_all = QPushButton("✗ Deselect All")
        self.btn_deselect_all.setStyleSheet("""
            QPushButton {
                background-color: #1E293B;
                color: #EF4444;
                border: 1px solid #EF4444;
                border-radius: 5px;
                padding: 6px 12px;
                font-size: 11px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #EF4444;
                color: #FFFFFF;
                border: 1px solid #F87171;
            }
        """)
        
        btn_layout.addWidget(self.btn_select_all)
        btn_layout.addWidget(self.btn_deselect_all)
        btn_layout.addStretch()
        artifact_layout.addLayout(btn_layout)
        
        # Scroll area for checkboxes
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(220)
        scroll.setStyleSheet("""
            QScrollArea {
                background-color: #0F172A;
                border: 2px solid #475569;
                border-radius: 8px;
            }
            QScrollBar:vertical {
                background-color: #1E293B;
                width: 14px;
                border-radius: 7px;
                margin: 2px;
            }
            QScrollBar::handle:vertical {
                background-color: #475569;
                border-radius: 6px;
                min-height: 30px;
                margin: 2px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #64748B;
            }
            QScrollBar::handle:vertical:pressed {
                background-color: #0EA5E9;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 0px;
                background: none;
            }
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: none;
            }
        """)
        
        scroll_content = QWidget()
        scroll_content.setStyleSheet("""
            QWidget {
                background-color: #0F172A;
            }
        """)
        self.artifact_grid = QGridLayout(scroll_content)
        self.artifact_grid.setSpacing(8)
        self.artifact_grid.setContentsMargins(10, 10, 10, 10)
        
        self.artifact_checkboxes = {}
        available_artifacts = []
        if self.data_manager:
            available_artifacts = self.data_manager.get_available_artifacts()
        
        # If no artifacts found/manager not ready, show some defaults or empty
        if not available_artifacts:
            available_artifacts = ['Prefetch', 'LNK', 'Registry', 'BAM', 'ShellBag', 'SRUM', 'USN', 'MFT', 'Logs']
            
        row, col = 0, 0
        for artifact in sorted(available_artifacts):
            # Create container for each checkbox with background
            cb_container = QWidget()
            cb_container.setStyleSheet("""
                QWidget {
                    background-color: #1E293B;
                    border: 1px solid #334155;
                    border-radius: 6px;
                    padding: 8px;
                }
                QWidget:hover {
                    background-color: #334155;
                    border: 1px solid #475569;
                }
            """)
            
            cb_layout = QHBoxLayout(cb_container)
            cb_layout.setContentsMargins(8, 6, 8, 6)
            cb_layout.setSpacing(0)
            
            cb = QCheckBox(artifact)
            cb.setChecked(True)
            cb.setStyleSheet("""
                QCheckBox {
                    color: #F1F5F9;
                    font-size: 13px;
                    font-weight: 500;
                    spacing: 10px;
                }
                QCheckBox::indicator {
                    width: 18px;
                    height: 18px;
                    border-radius: 4px;
                    border: 2px solid #64748B;
                    background-color: #0F172A;
                }
                QCheckBox::indicator:checked {
                    background-color: #3B82F6;
                    border: 2px solid #60A5FA;
                    image: none;
                }
                QCheckBox::indicator:checked:hover {
                    background-color: #60A5FA;
                    border: 2px solid #00FFFF;
                }
                QCheckBox::indicator:hover {
                    border: 2px solid #94A3B8;
                    background-color: #1E293B;
                }
            """)
            
            cb_layout.addWidget(cb)
            self.artifact_checkboxes[artifact] = cb
            self.artifact_grid.addWidget(cb_container, row, col)
            
            col += 1
            if col > 1: # 2 columns
                col = 0
                row += 1
                
        scroll.setWidget(scroll_content)
        artifact_layout.addWidget(scroll)
        layout.addWidget(artifact_group)
        
        # Connect buttons
        self.btn_select_all.clicked.connect(self._select_all_artifacts)
        self.btn_deselect_all.clicked.connect(self._deselect_all_artifacts)
        
        # --- Dialog Buttons ---
        button_box = QHBoxLayout()
        button_box.setSpacing(10)
        
        self.btn_visualize = QPushButton("🔍 Visualize Timeline")
        self.btn_visualize.setDefault(True)
        self.btn_visualize.setMinimumHeight(40)
        self.btn_visualize.setStyleSheet("""
            QPushButton {
                background-color: #0EA5E9;
                color: #FFFFFF;
                border: 2px solid #38BDF8;
                border-radius: 8px;
                padding: 10px 24px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #38BDF8;
                border: 2px solid #00FFFF;
            }
            QPushButton:pressed {
                background-color: #0284C7;
            }
        """)
        
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setMinimumHeight(40)
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                color: #E2E8F0;
                border: 2px solid #475569;
                border-radius: 8px;
                padding: 10px 24px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #475569;
                border: 2px solid #64748B;
            }
            QPushButton:pressed {
                background-color: #1E293B;
            }
        """)
        
        button_box.addStretch()
        button_box.addWidget(self.btn_cancel)
        button_box.addWidget(self.btn_visualize)
        
        layout.addLayout(button_box)
        
        self.btn_visualize.clicked.connect(self._on_visualize)
        self.btn_cancel.clicked.connect(self.reject)
        
    def _toggle_time_pickers(self, checked):
        """Enable/disable time pickers based on radio selection."""
        # If "All Time" is checked, disable pickers
        self.picker_container.setEnabled(not self.radio_all_time.isChecked())
        
    def _select_all_artifacts(self):
        for cb in self.artifact_checkboxes.values():
            cb.setChecked(True)
            
    def _deselect_all_artifacts(self):
        for cb in self.artifact_checkboxes.values():
            cb.setChecked(False)
            
    def _on_visualize(self):
        """Validate and accept the configuration."""
        # Check artifacts
        selected_artifacts = [name for name, cb in self.artifact_checkboxes.items() if cb.isChecked()]
        if not selected_artifacts:
            QMessageBox.warning(self, "No Artifacts", "Please select at least one artifact type to visualize.")
            return
            
        # Check time
        start_time = None
        end_time = None
        
        if self.radio_custom_time.isChecked():
            start_time = self.start_picker.dateTime().toPyDateTime()
            end_time = self.end_picker.dateTime().toPyDateTime()
            
            if start_time >= end_time:
                QMessageBox.warning(self, "Invalid Range", "Start time must be before end time.")
                return
        
        # If "All Time" is checked, start_time and end_time remain None
        
        self.result_config = {
            'start_time': start_time,
            'end_time': end_time,
            'artifact_types': selected_artifacts
        }
        
        self.accept()
        
    def get_config(self):
        """Return the configuration dictionary."""
        return self.result_config
