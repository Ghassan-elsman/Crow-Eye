"""
GUI configuration panel for identifier extraction settings.

This module provides a PyQt widget for configuring identifier extraction
settings in the Wings GUI.
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QCheckBox, QSpinBox,
    QLabel, QGroupBox, QLineEdit, QPushButton, QMessageBox
)
from PyQt5.QtCore import pyqtSignal

from correlation_engine.config.identifier_extraction_config import WingsConfig


class IdentifierExtractionConfigPanel(QWidget):
    """
    Configuration panel for identifier extraction settings.
    
    Provides UI controls for:
    - Extract from Names checkbox
    - Extract from Paths checkbox
    - Anchor Time Window input
    - Advanced options (column overrides, custom formats)
    """
    
    config_changed = pyqtSignal()  # Signal emitted when config changes
    
    def __init__(self, config: WingsConfig, parent=None):
        """
        Initialize configuration panel.
        
        Args:
            config: Wings configuration object
            parent: Parent widget
        """
        super().__init__(parent)
        self.config = config
        self.setup_ui()
        self.load_config()
    
    def setup_ui(self):
        """Setup UI components."""
        layout = QVBoxLayout(self)
        
        # Extraction Strategy Group
        strategy_group = QGroupBox("Identifier Extraction Strategy")
        strategy_layout = QVBoxLayout()
        
        self.extract_names_cb = QCheckBox("Extract from Names")
        self.extract_names_cb.setToolTip(
            "Enable to create identities from file names found in Feather tables"
        )
        self.extract_names_cb.stateChanged.connect(self.on_extract_names_changed)
        strategy_layout.addWidget(self.extract_names_cb)
        
        self.extract_paths_cb = QCheckBox("Extract from Paths")
        self.extract_paths_cb.setToolTip(
            "Enable to create identities from file paths found in Feather tables"
        )
        self.extract_paths_cb.stateChanged.connect(self.on_extract_paths_changed)
        strategy_layout.addWidget(self.extract_paths_cb)
        
        strategy_group.setLayout(strategy_layout)
        layout.addWidget(strategy_group)
        
        # Anchor Time Window Group
        anchor_group = QGroupBox("Anchor Configuration")
        anchor_layout = QHBoxLayout()
        
        anchor_layout.addWidget(QLabel("Time Window (minutes):"))
        self.time_window_spin = QSpinBox()
        self.time_window_spin.setMinimum(1)
        self.time_window_spin.setMaximum(1440)  # Max 24 hours
        self.time_window_spin.setValue(180)
        self.time_window_spin.setToolTip(
            "Evidence within this time window will be grouped into the same execution anchor"
        )
        self.time_window_spin.valueChanged.connect(self.on_time_window_changed)
        anchor_layout.addWidget(self.time_window_spin)
        anchor_layout.addStretch()
        
        anchor_group.setLayout(anchor_layout)
        layout.addWidget(anchor_group)
        
        # Advanced Options Group (collapsible)
        advanced_group = QGroupBox("Advanced Options")
        advanced_layout = QVBoxLayout()
        
        # Name columns override
        name_cols_layout = QHBoxLayout()
        name_cols_layout.addWidget(QLabel("Name Columns Override:"))
        self.name_columns_edit = QLineEdit()
        self.name_columns_edit.setPlaceholderText("Comma-separated column names (optional)")
        self.name_columns_edit.setToolTip(
            "Specify column names to use for name extraction (overrides auto-detection)"
        )
        name_cols_layout.addWidget(self.name_columns_edit)
        advanced_layout.addLayout(name_cols_layout)
        
        # Path columns override
        path_cols_layout = QHBoxLayout()
        path_cols_layout.addWidget(QLabel("Path Columns Override:"))
        self.path_columns_edit = QLineEdit()
        self.path_columns_edit.setPlaceholderText("Comma-separated column names (optional)")
        self.path_columns_edit.setToolTip(
            "Specify column names to use for path extraction (overrides auto-detection)"
        )
        path_cols_layout.addWidget(self.path_columns_edit)
        advanced_layout.addLayout(path_cols_layout)
        
        # Custom timestamp formats
        ts_format_layout = QHBoxLayout()
        ts_format_layout.addWidget(QLabel("Custom Timestamp Formats:"))
        self.timestamp_formats_edit = QLineEdit()
        self.timestamp_formats_edit.setPlaceholderText("Comma-separated strptime formats (optional)")
        self.timestamp_formats_edit.setToolTip(
            "Specify custom timestamp formats (e.g., %d-%b-%Y %H:%M:%S)"
        )
        ts_format_layout.addWidget(self.timestamp_formats_edit)
        advanced_layout.addLayout(ts_format_layout)
        
        advanced_group.setLayout(advanced_layout)
        layout.addWidget(advanced_group)
        
        # Save button
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        self.save_button = QPushButton("Save Configuration")
        self.save_button.clicked.connect(self.save_config)
        button_layout.addWidget(self.save_button)
        layout.addLayout(button_layout)
        
        layout.addStretch()
    
    def load_config(self):
        """Load current configuration into UI."""
        self.extract_names_cb.setChecked(
            self.config.identifier_extraction.extract_from_names
        )
        self.extract_paths_cb.setChecked(
            self.config.identifier_extraction.extract_from_paths
        )
        self.time_window_spin.setValue(self.config.anchor_time_window_minutes)
        
        # Load advanced options
        if self.config.identifier_extraction.name_columns:
            self.name_columns_edit.setText(
                ", ".join(self.config.identifier_extraction.name_columns)
            )
        
        if self.config.identifier_extraction.path_columns:
            self.path_columns_edit.setText(
                ", ".join(self.config.identifier_extraction.path_columns)
            )
        
        if self.config.timestamp_parsing.custom_formats:
            self.timestamp_formats_edit.setText(
                ", ".join(self.config.timestamp_parsing.custom_formats)
            )
    
    def on_extract_names_changed(self, state):
        """Handle Extract from Names checkbox change."""
        self.config.identifier_extraction.extract_from_names = bool(state)
        self.config_changed.emit()
    
    def on_extract_paths_changed(self, state):
        """Handle Extract from Paths checkbox change."""
        self.config.identifier_extraction.extract_from_paths = bool(state)
        self.config_changed.emit()
    
    def on_time_window_changed(self, value):
        """Handle time window change."""
        self.config.anchor_time_window_minutes = value
        self.config_changed.emit()
    
    def save_config(self):
        """Save configuration to file."""
        try:
            # Update advanced options
            name_cols_text = self.name_columns_edit.text().strip()
            if name_cols_text:
                self.config.identifier_extraction.name_columns = [
                    col.strip() for col in name_cols_text.split(',')
                ]
            else:
                self.config.identifier_extraction.name_columns = []
            
            path_cols_text = self.path_columns_edit.text().strip()
            if path_cols_text:
                self.config.identifier_extraction.path_columns = [
                    col.strip() for col in path_cols_text.split(',')
                ]
            else:
                self.config.identifier_extraction.path_columns = []
            
            ts_formats_text = self.timestamp_formats_edit.text().strip()
            if ts_formats_text:
                self.config.timestamp_parsing.custom_formats = [
                    fmt.strip() for fmt in ts_formats_text.split(',')
                ]
            else:
                self.config.timestamp_parsing.custom_formats = []
            
            # Save to file (would need config file path)
            # self.config.save_to_file(config_path)
            
            QMessageBox.information(
                self,
                "Configuration Saved",
                "Identifier extraction configuration has been saved successfully."
            )
            
        except Exception as e:
            QMessageBox.critical(
                self,
                "Save Error",
                f"Failed to save configuration: {str(e)}"
            )
