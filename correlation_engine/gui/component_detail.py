"""
Component Detail Panel
Display detailed information about feather and wing configurations.
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QScrollArea, QLabel, QGroupBox,
    QFormLayout, QTextEdit
)
from PyQt5.QtCore import Qt

from ..config import FeatherConfig, WingConfig


class ComponentDetailPanel(QWidget):
    """Widget for displaying component configuration details"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._init_ui()
    
    def _init_ui(self):
        """Initialize the user interface"""
        layout = QVBoxLayout(self)
        
        # Create scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        # Create content widget
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.addStretch()
        
        scroll.setWidget(self.content_widget)
        layout.addWidget(scroll)
        
        # Initial message
        self._show_empty_message()
    
    def _show_empty_message(self):
        """Show message when no component is selected"""
        self._clear_content()
        
        label = QLabel("Select a component to view details")
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("color: #888; font-size: 14px;")
        self.content_layout.insertWidget(0, label)
    
    def _clear_content(self):
        """Clear all content"""
        while self.content_layout.count() > 1:  # Keep stretch
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
    
    def display_feather_details(self, feather_config: FeatherConfig):
        """
        Display feather configuration details.
        
        Args:
            feather_config: Feather configuration to display
        """
        self._clear_content()
        
        # Identification section
        id_group = QGroupBox("Identification")
        id_layout = QFormLayout()
        id_layout.addRow("Config Name:", QLabel(feather_config.config_name))
        id_layout.addRow("Feather Name:", QLabel(feather_config.feather_name))
        id_layout.addRow("Artifact Type:", QLabel(feather_config.artifact_type))
        id_group.setLayout(id_layout)
        self.content_layout.insertWidget(0, id_group)
        
        # Source information section
        source_group = QGroupBox("Source Information")
        source_layout = QFormLayout()
        source_layout.addRow("Source Database:", QLabel(feather_config.source_database))
        source_layout.addRow("Source Table:", QLabel(feather_config.source_table))
        source_group.setLayout(source_layout)
        self.content_layout.insertWidget(1, source_group)
        
        # Column mapping section
        mapping_group = QGroupBox("Column Mapping")
        mapping_layout = QFormLayout()
        
        # Selected columns
        columns_text = ", ".join(feather_config.selected_columns)
        columns_label = QLabel(columns_text)
        columns_label.setWordWrap(True)
        mapping_layout.addRow("Selected Columns:", columns_label)
        
        # Column mappings
        for orig_col, feather_col in feather_config.column_mapping.items():
            mapping_layout.addRow(f"{orig_col} →", QLabel(feather_col))
        
        mapping_group.setLayout(mapping_layout)
        self.content_layout.insertWidget(2, mapping_group)
        
        # Transformation settings section
        transform_group = QGroupBox("Transformation Settings")
        transform_layout = QFormLayout()
        transform_layout.addRow("Timestamp Column:", QLabel(feather_config.timestamp_column))
        transform_layout.addRow("Timestamp Format:", QLabel(feather_config.timestamp_format))
        
        if feather_config.application_column:
            transform_layout.addRow("Application Column:", QLabel(feather_config.application_column))
        if feather_config.path_column:
            transform_layout.addRow("Path Column:", QLabel(feather_config.path_column))
        
        transform_group.setLayout(transform_layout)
        self.content_layout.insertWidget(3, transform_group)
        
        # Output section
        output_group = QGroupBox("Output")
        output_layout = QFormLayout()
        output_layout.addRow("Output Database:", QLabel(feather_config.output_database))
        output_group.setLayout(output_layout)
        self.content_layout.insertWidget(4, output_group)
        
        # Statistics section
        stats_group = QGroupBox("Statistics")
        stats_layout = QFormLayout()
        stats_layout.addRow("Total Records:", QLabel(f"{feather_config.total_records:,}"))
        
        if feather_config.date_range_start:
            stats_layout.addRow("Date Range Start:", QLabel(feather_config.date_range_start))
        if feather_config.date_range_end:
            stats_layout.addRow("Date Range End:", QLabel(feather_config.date_range_end))
        
        stats_group.setLayout(stats_layout)
        self.content_layout.insertWidget(5, stats_group)
        
        # Metadata section
        meta_group = QGroupBox("Metadata")
        meta_layout = QFormLayout()
        meta_layout.addRow("Created Date:", QLabel(feather_config.created_date))
        
        if feather_config.created_by:
            meta_layout.addRow("Created By:", QLabel(feather_config.created_by))
        
        if feather_config.description:
            desc_label = QLabel(feather_config.description)
            desc_label.setWordWrap(True)
            meta_layout.addRow("Description:", desc_label)
        
        if feather_config.notes:
            notes_label = QLabel(feather_config.notes)
            notes_label.setWordWrap(True)
            meta_layout.addRow("Notes:", notes_label)
        
        meta_group.setLayout(meta_layout)
        self.content_layout.insertWidget(6, meta_group)
    
    def display_wing_details(self, wing_config: WingConfig):
        """
        Display wing configuration details.
        
        Args:
            wing_config: Wing configuration to display
        """
        self._clear_content()
        
        # Identification section
        id_group = QGroupBox("Identification")
        id_layout = QFormLayout()
        id_layout.addRow("Config Name:", QLabel(wing_config.config_name))
        id_layout.addRow("Wing Name:", QLabel(wing_config.wing_name))
        id_layout.addRow("Wing ID:", QLabel(wing_config.wing_id))
        id_layout.addRow("Version:", QLabel(wing_config.version))
        id_group.setLayout(id_layout)
        self.content_layout.insertWidget(0, id_group)
        
        # Wing definition section
        def_group = QGroupBox("Wing Definition")
        def_layout = QFormLayout()
        def_layout.addRow("Author:", QLabel(wing_config.author))
        
        desc_label = QLabel(wing_config.description)
        desc_label.setWordWrap(True)
        def_layout.addRow("Description:", desc_label)
        
        proves_label = QLabel(wing_config.proves)
        proves_label.setWordWrap(True)
        def_layout.addRow("Proves:", proves_label)
        
        def_group.setLayout(def_layout)
        self.content_layout.insertWidget(1, def_group)
        
        # Feathers section
        feathers_group = QGroupBox(f"Feathers ({len(wing_config.feathers)})")
        feathers_layout = QVBoxLayout()
        
        for i, feather_ref in enumerate(wing_config.feathers, 1):
            feather_info = QLabel(
                f"{i}. {feather_ref.feather_id} ({feather_ref.artifact_type})\n"
                f"   Config: {feather_ref.feather_config_name}\n"
                f"   Database: {feather_ref.feather_database_path}"
            )
            feather_info.setWordWrap(True)
            feather_info.setStyleSheet("padding: 5px; background-color: #f5f5f5; border-radius: 3px;")
            feathers_layout.addWidget(feather_info)
        
        feathers_group.setLayout(feathers_layout)
        self.content_layout.insertWidget(2, feathers_group)
        
        # Correlation rules section
        rules_group = QGroupBox("Correlation Rules")
        rules_layout = QFormLayout()
        rules_layout.addRow("Time Window:", QLabel(f"{wing_config.time_window_minutes} minutes"))
        rules_layout.addRow("Minimum Matches:", QLabel(str(wing_config.minimum_matches)))
        rules_group.setLayout(rules_layout)
        self.content_layout.insertWidget(3, rules_group)
        
        # Filters section
        filters_group = QGroupBox("Filters")
        filters_layout = QFormLayout()
        filters_layout.addRow("Apply To:", QLabel(wing_config.apply_to))
        
        if wing_config.target_application:
            filters_layout.addRow("Target Application:", QLabel(wing_config.target_application))
        if wing_config.target_file_path:
            filters_layout.addRow("Target File Path:", QLabel(wing_config.target_file_path))
        if wing_config.target_event_id:
            filters_layout.addRow("Target Event ID:", QLabel(wing_config.target_event_id))
        
        filters_group.setLayout(filters_layout)
        self.content_layout.insertWidget(4, filters_group)
        
        # Anchor priority section
        anchor_group = QGroupBox("Anchor Priority")
        anchor_layout = QVBoxLayout()
        
        priority_text = " → ".join(wing_config.anchor_priority)
        priority_label = QLabel(priority_text)
        priority_label.setWordWrap(True)
        anchor_layout.addWidget(priority_label)
        
        anchor_group.setLayout(anchor_layout)
        self.content_layout.insertWidget(5, anchor_group)
        
        # Metadata section
        meta_group = QGroupBox("Metadata")
        meta_layout = QFormLayout()
        meta_layout.addRow("Created Date:", QLabel(wing_config.created_date))
        meta_layout.addRow("Last Modified:", QLabel(wing_config.last_modified))
        
        if wing_config.tags:
            tags_text = ", ".join(wing_config.tags)
            meta_layout.addRow("Tags:", QLabel(tags_text))
        
        if wing_config.case_types:
            case_types_text = ", ".join(wing_config.case_types)
            meta_layout.addRow("Case Types:", QLabel(case_types_text))
        
        meta_group.setLayout(meta_layout)
        self.content_layout.insertWidget(6, meta_group)
    
    def clear(self):
        """Clear the detail panel"""
        self._show_empty_message()
