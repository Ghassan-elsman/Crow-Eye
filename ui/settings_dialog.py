"""
Settings Dialog for Crow Eye Forensic Tool

This module provides a centralized settings interface with sections for:
- General Settings (global application preferences)
- Case Management (view and manage all cases)
- Case Settings (case-specific configuration)
"""

from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox, QFileDialog

import os
import sys
import json
from datetime import datetime
from pathlib import Path

# Import styles
from styles import CrowEyeStyles

# Eye AI settings persistence (pure JSON helpers, no Qt)
try:
    from config.eye_ai_settings import read_eye_ai_settings, write_eye_ai_settings
except Exception:
    read_eye_ai_settings = None
    write_eye_ai_settings = None

# Import semantic mapping manager
try:
    from correlation_engine.config.semantic_mapping import SemanticMappingManager, SemanticMapping
except ImportError:
    # Fallback if correlation engine not available
    SemanticMappingManager = None
    SemanticMapping = None

# Import advanced semantic mapping dialog
try:
    from correlation_engine.wings.ui.semantic_mapping_dialog import SemanticMappingDialog as AdvancedSemanticMappingDialog
except ImportError:
    AdvancedSemanticMappingDialog = None

# Import pipeline management tab
try:
    from correlation_engine.gui.pipeline_management_tab import PipelineManagementTab
except ImportError:
    # Fallback if correlation engine not available
    PipelineManagementTab = None


class SettingsDialog(QtWidgets.QDialog):
    """Centralized settings dialog for Crow Eye."""
    
    def __init__(self, case_history_manager, current_case_path=None, parent=None,
                 clone_case_callback=None):
        """Initialize the settings dialog.

        Args:
            case_history_manager: CaseHistoryManager instance
            current_case_path: Path to currently active case (optional)
            parent: Parent widget
            clone_case_callback: Optional callable invoked (after this dialog
                closes) when the user picks "Import Case Data from Another Case…".
        """
        super().__init__(parent)

        self.case_history_manager = case_history_manager
        self.current_case_path = current_case_path
        self.current_case = None
        self._clone_case_callback = clone_case_callback
        self._clone_requested = False
        
        if current_case_path:
            self.current_case = case_history_manager.get_case_by_path(current_case_path)
        
        # Initialize semantic mapping manager
        self.semantic_manager = None
        if SemanticMappingManager:
            self.semantic_manager = SemanticMappingManager()
            self._load_semantic_mappings()
        
        self.setup_ui()
        self.apply_styles()
        self.load_settings()
        
    def setup_ui(self):
        """Set up the dialog UI components."""
        # Set dialog properties
        self.setWindowTitle("Crow Eye - Settings")
        self.setMinimumSize(900, 700)
        self.setModal(True)
        
        # Main layout
        main_layout = QtWidgets.QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Sidebar navigation
        sidebar = self.create_sidebar()
        main_layout.addWidget(sidebar)
        
        # Content area
        self.content_stack = QtWidgets.QStackedWidget()
        main_layout.addWidget(self.content_stack, 1)
        
        # Create content panels
        self.general_panel = self.create_general_settings_panel()
        self.case_mgmt_panel = self.create_case_management_panel()
        self.case_settings_panel = self.create_case_settings_panel()
        self.semantic_mappings_panel = self.create_semantic_mappings_panel()
        self.pipeline_mgmt_panel = self.create_pipeline_management_panel()
        self.eye_ai_panel = self.create_eye_ai_panel()

        self.content_stack.addWidget(self.general_panel)
        self.content_stack.addWidget(self.case_mgmt_panel)
        self.content_stack.addWidget(self.case_settings_panel)
        self.content_stack.addWidget(self.semantic_mappings_panel)
        self.content_stack.addWidget(self.pipeline_mgmt_panel)
        self.content_stack.addWidget(self.eye_ai_panel)
        
        # Bottom buttons
        buttons_layout = QtWidgets.QHBoxLayout()
        buttons_layout.setContentsMargins(20, 10, 20, 20)
        buttons_layout.setSpacing(15)
        
        save_button = QtWidgets.QPushButton("SAVE")
        save_button.setFixedHeight(45)
        save_button.setMinimumWidth(140)
        save_button.clicked.connect(self.save_settings)
        save_button.setStyleSheet(CrowEyeStyles.GREEN_BUTTON + """
            QPushButton {
                font-size: 13px;
                font-weight: 700;
                padding: 12px 24px;
            }
        """)
        
        cancel_button = QtWidgets.QPushButton("CANCEL")
        cancel_button.setFixedHeight(45)
        cancel_button.setMinimumWidth(140)
        cancel_button.clicked.connect(self.reject)
        cancel_button.setStyleSheet(CrowEyeStyles.CLEAR_BUTTON_STYLE + """
            QPushButton {
                font-size: 13px;
                font-weight: 700;
                padding: 12px 24px;
            }
        """)
        
        buttons_layout.addStretch()
        buttons_layout.addWidget(save_button)
        buttons_layout.addWidget(cancel_button)
        
        # Add buttons to main layout
        main_widget = QtWidgets.QWidget()
        main_widget_layout = QtWidgets.QVBoxLayout(main_widget)
        main_widget_layout.setContentsMargins(0, 0, 0, 0)
        main_widget_layout.setSpacing(0)
        main_widget_layout.addWidget(self.content_stack, 1)
        main_widget_layout.addLayout(buttons_layout)
        
        main_layout.addWidget(main_widget, 1)
    
    def create_sidebar(self):
        """Create the sidebar navigation."""
        sidebar = QtWidgets.QWidget()
        sidebar.setFixedWidth(200)
        sidebar.setStyleSheet("""
            QWidget {
                background-color: #1E293B;
                border-right: 1px solid #334155;
            }
        """)
        
        sidebar_layout = QtWidgets.QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 20, 0, 20)
        sidebar_layout.setSpacing(5)
        
        # Title
        title_label = QtWidgets.QLabel("SETTINGS")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("""
            QLabel {
                color: #00FFFF;
                font-size: 18px;
                font-weight: 800;
                font-family: 'BBH Sans Bogle', 'Segoe UI', sans-serif;
                padding: 15px 0;
            }
        """)
        sidebar_layout.addWidget(title_label)
        
        # Navigation buttons
        self.nav_buttons = []
        
        general_btn = self.create_nav_button("⚙ General Settings", 0)
        sidebar_layout.addWidget(general_btn)
        self.nav_buttons.append(general_btn)
        
        case_mgmt_btn = self.create_nav_button("📁 Case Management", 1)
        sidebar_layout.addWidget(case_mgmt_btn)
        self.nav_buttons.append(case_mgmt_btn)
        
        case_settings_btn = self.create_nav_button("📄 Case Settings", 2)
        sidebar_layout.addWidget(case_settings_btn)
        self.nav_buttons.append(case_settings_btn)
        
        semantic_btn = self.create_nav_button("🔤 Semantic Mappings", 3)
        sidebar_layout.addWidget(semantic_btn)
        self.nav_buttons.append(semantic_btn)
        
        pipelines_btn = self.create_nav_button("🔗 Pipelines", 4)
        sidebar_layout.addWidget(pipelines_btn)
        self.nav_buttons.append(pipelines_btn)

        eye_ai_btn = self.create_nav_button("Eye AI", 5)
        eye_ai_btn.setIcon(QtGui.QIcon("GUI Resources/the Eye AI agent transparent.png"))
        eye_ai_btn.setIconSize(QtCore.QSize(20, 20))
        sidebar_layout.addWidget(eye_ai_btn)
        self.nav_buttons.append(eye_ai_btn)
        
        # Disable case settings and pipelines if no active case
        if not self.current_case:
            case_settings_btn.setEnabled(False)
            case_settings_btn.setToolTip("No active case")
            pipelines_btn.setEnabled(False)
            pipelines_btn.setToolTip("No active case")
        
        sidebar_layout.addStretch()
        
        # Set first button as active
        general_btn.setProperty("active", True)
        general_btn.style().unpolish(general_btn)
        general_btn.style().polish(general_btn)
        
        return sidebar
    
    def create_nav_button(self, text, index):
        """Create a navigation button."""
        button = QtWidgets.QPushButton(text)
        button.setFixedHeight(50)
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(lambda: self.switch_panel(index))
        button.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #94A3B8;
                border: none;
                border-left: 3px solid transparent;
                text-align: left;
                padding-left: 20px;
                font-size: 13px;
                font-weight: 600;
                font-family: 'Segoe UI', sans-serif;
            }
            QPushButton:hover {
                background-color: #334155;
                color: #E2E8F0;
            }
            QPushButton[active="true"] {
                background-color: #0F172A;
                color: #00FFFF;
                border-left: 3px solid #00FFFF;
            }
        """)
        return button
    
    def switch_panel(self, index):
        """Switch to a different settings panel."""
        self.content_stack.setCurrentIndex(index)
        
        # Update button states
        for i, btn in enumerate(self.nav_buttons):
            btn.setProperty("active", i == index)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
    
    def create_general_settings_panel(self):
        """Create the general settings panel."""
        panel = QtWidgets.QWidget()
        panel.setStyleSheet("""
            QWidget {
                background-color: #0F172A;
            }
        """)
        
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        
        # Title
        title = QtWidgets.QLabel("GENERAL SETTINGS")
        title.setStyleSheet("""
            QLabel {
                color: #00FFFF;
                font-size: 20px;
                font-weight: 700;
                font-family: 'BBH Sans Bogle', 'Segoe UI', sans-serif;
            }
        """)
        layout.addWidget(title)
        
        # Form layout
        form_widget = QtWidgets.QWidget()
        form_layout = QtWidgets.QFormLayout(form_widget)
        form_layout.setSpacing(20)
        form_layout.setLabelAlignment(Qt.AlignRight)
        form_layout.setContentsMargins(20, 20, 20, 20)
        
        # Enhanced label style
        label_style = """
            QLabel {
                color: #E2E8F0;
                font-size: 14px;
                font-weight: 600;
                font-family: 'Segoe UI', sans-serif;
                padding-right: 15px;
            }
        """
        
        # Default case directory
        dir_label = QtWidgets.QLabel("Default Case Directory:")
        dir_label.setStyleSheet(label_style)
        
        dir_layout = QtWidgets.QHBoxLayout()
        self.default_dir_input = QtWidgets.QLineEdit()
        self.default_dir_input.setStyleSheet(CrowEyeStyles.INPUT_FIELD + """
            QLineEdit {
                min-height: 35px;
                font-size: 13px;
                padding: 8px 12px;
            }
        """)
        self.default_dir_input.setPlaceholderText("C:/Cases")
        
        browse_btn = QtWidgets.QPushButton("Browse")
        browse_btn.setStyleSheet(CrowEyeStyles.BUTTON_STYLE + """
            QPushButton {
                min-height: 35px;
                padding: 8px 16px;
                font-size: 12px;
            }
        """)
        browse_btn.clicked.connect(self.browse_default_directory)
        
        dir_layout.addWidget(self.default_dir_input, 1)
        dir_layout.addWidget(browse_btn)
        
        form_layout.addRow(dir_label, dir_layout)
        
        # Recent cases display count with description
        recent_label = QtWidgets.QLabel("Recent Cases Display:")
        recent_label.setStyleSheet(label_style)
        recent_label.setToolTip("How many recent cases to show in the startup menu")
        
        recent_container = QtWidgets.QWidget()
        recent_layout = QtWidgets.QVBoxLayout(recent_container)
        recent_layout.setContentsMargins(0, 0, 0, 0)
        recent_layout.setSpacing(5)
        
        self.recent_count_spin = QtWidgets.QSpinBox()
        self.recent_count_spin.setRange(5, 20)
        self.recent_count_spin.setValue(10)
        self.recent_count_spin.setStyleSheet("""
            QSpinBox {
                background-color: #1E293B;
                color: #FFFFFF;
                border: 2px solid #475569;
                border-radius: 6px;
                padding: 8px 12px;
                min-height: 35px;
                font-size: 16px;
                font-weight: 700;
                font-family: 'Segoe UI', sans-serif;
            }
            QSpinBox:hover {
                border: 2px solid #00FFFF;
                background-color: #263449;
            }
            QSpinBox:focus {
                border: 2px solid #00FFFF;
                background-color: #263449;
            }
            QSpinBox::up-button {
                subcontrol-origin: border;
                subcontrol-position: top right;
                width: 30px;
                border-left: 2px solid #475569;
                border-top-right-radius: 6px;
                background-color: #334155;
            }
            QSpinBox::up-button:hover {
                background-color: #3B82F6;
            }
            QSpinBox::up-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-bottom: 6px solid #00FFFF;
                width: 0;
                height: 0;
            }
            QSpinBox::down-button {
                subcontrol-origin: border;
                subcontrol-position: bottom right;
                width: 30px;
                border-left: 2px solid #475569;
                border-bottom-right-radius: 6px;
                background-color: #334155;
            }
            QSpinBox::down-button:hover {
                background-color: #3B82F6;
            }
            QSpinBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 6px solid #00FFFF;
                width: 0;
                height: 0;
            }
        """)
        self.recent_count_spin.setToolTip("Number of recent cases shown in startup menu (5-20)")
        
        recent_desc = QtWidgets.QLabel("💡 Controls how many cases appear in the startup menu")
        recent_desc.setStyleSheet("""
            QLabel {
                color: #94A3B8;
                font-size: 11px;
                font-style: italic;
                padding-top: 3px;
            }
        """)
        
        recent_layout.addWidget(self.recent_count_spin)
        recent_layout.addWidget(recent_desc)
        
        form_layout.addRow(recent_label, recent_container)
        
        # Max history size with description
        max_label = QtWidgets.QLabel("Max History Size:")
        max_label.setStyleSheet(label_style)
        max_label.setToolTip("Maximum number of cases to keep in history")
        
        max_container = QtWidgets.QWidget()
        max_layout = QtWidgets.QVBoxLayout(max_container)
        max_layout.setContentsMargins(0, 0, 0, 0)
        max_layout.setSpacing(5)
        
        self.max_history_spin = QtWidgets.QSpinBox()
        self.max_history_spin.setRange(50, 500)
        self.max_history_spin.setValue(200)
        self.max_history_spin.setStyleSheet("""
            QSpinBox {
                background-color: #1E293B;
                color: #FFFFFF;
                border: 2px solid #475569;
                border-radius: 6px;
                padding: 8px 12px;
                min-height: 35px;
                font-size: 16px;
                font-weight: 700;
                font-family: 'Segoe UI', sans-serif;
            }
            QSpinBox:hover {
                border: 2px solid #00FFFF;
                background-color: #263449;
            }
            QSpinBox:focus {
                border: 2px solid #00FFFF;
                background-color: #263449;
            }
            QSpinBox::up-button {
                subcontrol-origin: border;
                subcontrol-position: top right;
                width: 30px;
                border-left: 2px solid #475569;
                border-top-right-radius: 6px;
                background-color: #334155;
            }
            QSpinBox::up-button:hover {
                background-color: #3B82F6;
            }
            QSpinBox::up-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-bottom: 6px solid #00FFFF;
                width: 0;
                height: 0;
            }
            QSpinBox::down-button {
                subcontrol-origin: border;
                subcontrol-position: bottom right;
                width: 30px;
                border-left: 2px solid #475569;
                border-bottom-right-radius: 6px;
                background-color: #334155;
            }
            QSpinBox::down-button:hover {
                background-color: #3B82F6;
            }
            QSpinBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 6px solid #00FFFF;
                width: 0;
                height: 0;
            }
        """)
        self.max_history_spin.setToolTip("Maximum cases stored in history (50-500)")
        
        max_desc = QtWidgets.QLabel("💡 Total cases remembered (oldest removed when limit reached)")
        max_desc.setStyleSheet("""
            QLabel {
                color: #94A3B8;
                font-size: 11px;
                font-style: italic;
                padding-top: 3px;
            }
        """)
        
        max_layout.addWidget(self.max_history_spin)
        max_layout.addWidget(max_desc)
        
        form_layout.addRow(max_label, max_container)
        
        # Identity Semantic Phase setting with description
        semantic_label = QtWidgets.QLabel("Identity Semantic Phase:")
        semantic_label.setStyleSheet(label_style)
        semantic_label.setToolTip("Enable identity-level semantic mapping for optimized correlation analysis")
        
        semantic_container = QtWidgets.QWidget()
        semantic_layout = QtWidgets.QVBoxLayout(semantic_container)
        semantic_layout.setContentsMargins(0, 0, 0, 0)
        semantic_layout.setSpacing(5)
        
        self.identity_semantic_phase_checkbox = QtWidgets.QCheckBox("Enable identity-level semantic mapping")
        self.identity_semantic_phase_checkbox.setChecked(True)
        self.identity_semantic_phase_checkbox.setStyleSheet("""
            QCheckBox {
                color: #E2E8F0;
                font-size: 13px;
                font-weight: 600;
                font-family: 'Segoe UI', sans-serif;
                spacing: 10px;
            }
            QCheckBox::indicator {
                width: 24px;
                height: 24px;
                border: 2px solid #475569;
                border-radius: 4px;
                background-color: #1E293B;
            }
            QCheckBox::indicator:hover {
                border: 2px solid #00FFFF;
                background-color: #263449;
            }
            QCheckBox::indicator:checked {
                background-color: #00FFFF;
                border: 2px solid #00FFFF;
                image: none;
            }
        """)
        self.identity_semantic_phase_checkbox.setToolTip(
            "When enabled, semantic mappings are applied once per identity after correlation completes,\n"
            "reducing redundant processing and improving performance. Recommended for most use cases."
        )
        
        semantic_desc = QtWidgets.QLabel(
            "💡 Applies semantic mappings at identity-level for better performance\n"
            "   (Recommended: Enabled for optimized correlation analysis)"
        )
        semantic_desc.setStyleSheet("""
            QLabel {
                color: #94A3B8;
                font-size: 11px;
                font-style: italic;
                padding-top: 3px;
            }
        """)
        
        semantic_layout.addWidget(self.identity_semantic_phase_checkbox)
        semantic_layout.addWidget(semantic_desc)
        
        form_layout.addRow(semantic_label, semantic_container)
        
        # Wings Semantic Mapping setting with description
        wings_semantic_label = QtWidgets.QLabel("Wings Semantic Mapping:")
        wings_semantic_label.setStyleSheet(label_style)
        wings_semantic_label.setToolTip("Enable semantic mapping for Wings correlation results")
        
        wings_semantic_container = QtWidgets.QWidget()
        wings_semantic_layout = QtWidgets.QVBoxLayout(wings_semantic_container)
        wings_semantic_layout.setContentsMargins(0, 0, 0, 0)
        wings_semantic_layout.setSpacing(5)
        
        self.wings_semantic_mapping_checkbox = QtWidgets.QCheckBox("Enable semantic mapping for Wings")
        self.wings_semantic_mapping_checkbox.setChecked(True)  # On by default
        self.wings_semantic_mapping_checkbox.setStyleSheet("""
            QCheckBox {
                color: #E2E8F0;
                font-size: 13px;
                font-weight: 600;
                font-family: 'Segoe UI', sans-serif;
                spacing: 10px;
            }
            QCheckBox::indicator {
                width: 24px;
                height: 24px;
                border: 2px solid #475569;
                border-radius: 4px;
                background-color: #1E293B;
            }
            QCheckBox::indicator:hover {
                border: 2px solid #00FFFF;
                background-color: #263449;
            }
            QCheckBox::indicator:checked {
                background-color: #00FFFF;
                border: 2px solid #00FFFF;
                image: none;
            }
        """)
        self.wings_semantic_mapping_checkbox.setToolTip(
            "When enabled, semantic mappings are applied to Wings correlation results\n"
            "after correlation completes. Disable to skip semantic mapping phase."
        )
        
        wings_semantic_desc = QtWidgets.QLabel(
            "💡 Applies semantic rules to Wings correlation results\n"
            "   (Recommended: Enabled for enhanced correlation analysis)"
        )
        wings_semantic_desc.setStyleSheet("""
            QLabel {
                color: #94A3B8;
                font-size: 11px;
                font-style: italic;
                padding-top: 3px;
            }
        """)
        wings_semantic_layout.addWidget(self.wings_semantic_mapping_checkbox)
        wings_semantic_layout.addWidget(wings_semantic_desc)

        form_layout.addRow(wings_semantic_label, wings_semantic_container)

        # Cascade Tree Expansion setting
        cascade_label = QtWidgets.QLabel("Cascade Tree Expansion:")
        cascade_label.setStyleSheet(label_style)
        cascade_label.setToolTip("Enable recursive expansion of tree items (Identity -> Anchor -> Evidence) on single click")

        cascade_container = QtWidgets.QWidget()
        cascade_layout = QtWidgets.QVBoxLayout(cascade_container)
        cascade_layout.setContentsMargins(0, 0, 0, 0)
        cascade_layout.setSpacing(5)

        self.cascade_expansion_checkbox = QtWidgets.QCheckBox("Enable cascade tree expansion")
        self.cascade_expansion_checkbox.setChecked(True)  # On by default
        self.cascade_expansion_checkbox.setStyleSheet("""
            QCheckBox {
                color: #E2E8F0;
                font-size: 13px;
                font-weight: 600;
                font-family: 'Segoe UI', sans-serif;
                spacing: 10px;
            }
            QCheckBox::indicator {
                width: 24px;
                height: 24px;
                border: 2px solid #475569;
                border-radius: 4px;
                background-color: #1E293B;
            }
            QCheckBox::indicator:hover {
                border: 2px solid #00FFFF;
                background-color: #263449;
            }
            QCheckBox::indicator:checked {
                background-color: #00FFFF;
                border: 2px solid #00FFFF;
                image: none;
            }
        """)

        cascade_desc = QtWidgets.QLabel(
            "💡 Automatically expands all underlying levels (Identity/Anchor/Evidence) when an item is clicked\n"
            "   (Recommended: Enabled for faster investigation)"
        )
        cascade_desc.setStyleSheet("""
            QLabel {
                color: #94A3B8;
                font-size: 11px;
                font-style: italic;
                padding-top: 3px;
            }
        """)

        cascade_layout.addWidget(self.cascade_expansion_checkbox)
        cascade_layout.addWidget(cascade_desc)

        form_layout.addRow(cascade_label, cascade_container)

        # Add form to panel layout
        layout.addWidget(form_widget)
        layout.addStretch()

        return panel

    def create_case_management_panel(self):
        """Create the case management panel."""
        panel = QtWidgets.QWidget()
        panel.setStyleSheet("""
            QWidget {
                background-color: #0F172A;
            }
        """)
        
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        
        # Title
        title = QtWidgets.QLabel("CASE MANAGEMENT")
        title.setStyleSheet("""
            QLabel {
                color: #00FFFF;
                font-size: 20px;
                font-weight: 700;
                font-family: 'BBH Sans Bogle', 'Segoe UI', sans-serif;
            }
        """)
        layout.addWidget(title)
        
        # Search bar
        search_layout = QtWidgets.QHBoxLayout()
        self.search_input = QtWidgets.QLineEdit()
        self.search_input.setPlaceholderText("Search cases...")
        self.search_input.setStyleSheet(CrowEyeStyles.INPUT_FIELD + """
            QLineEdit {
                min-height: 40px;
                font-size: 14px;
                padding: 10px 15px;
                border: 2px solid #475569;
            }
            QLineEdit:focus {
                border: 2px solid #00FFFF;
            }
        """)
        self.search_input.textChanged.connect(self.filter_cases)
        search_layout.addWidget(self.search_input)
        layout.addLayout(search_layout)
        
        # Cases table (NO Actions or Description columns)
        self.cases_table = QtWidgets.QTableWidget()
        self.cases_table.setColumnCount(4)  # Removed Actions and Description columns
        self.cases_table.setHorizontalHeaderLabels([
            "Case Name", "Path", "Created", "Last Opened"
        ])
        self.cases_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.cases_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        CrowEyeStyles.apply_table_styles(self.cases_table)
        
        # Enhanced table styling for better visibility
        self.cases_table.setStyleSheet(CrowEyeStyles.UNIFIED_TABLE_STYLE + """
            QTableWidget {
                font-size: 13px;
            }
            QTableWidget::item {
                padding: 10px 8px;
                font-size: 13px;
                color: #F8FAFC;
            }
            QHeaderView::section {
                padding: 10px 8px;
                font-size: 12px;
            }
        """)
        
        self.cases_table.horizontalHeader().setStretchLastSection(True)
        self.cases_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Interactive)
        self.cases_table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.cases_table.setMinimumHeight(400)
        
        layout.addWidget(self.cases_table)
        
        # Action buttons BELOW the table
        actions_layout = QtWidgets.QHBoxLayout()
        actions_layout.setSpacing(15)
        actions_layout.setContentsMargins(0, 15, 0, 0)
        
        # Remove Selected Case button
        self.remove_case_btn = QtWidgets.QPushButton("🗑 Remove Selected Case")
        self.remove_case_btn.setFixedHeight(45)
        self.remove_case_btn.setMinimumWidth(200)
        self.remove_case_btn.setStyleSheet("""
            QPushButton {
                background-color: #DC2626;
                color: #FFFFFF;
                border: 2px solid #EF4444;
                border-radius: 8px;
                padding: 12px 24px;
                font-weight: 700;
                font-size: 13px;
                font-family: 'Segoe UI', sans-serif;
            }
            QPushButton:hover {
                background-color: #EF4444;
                border: 2px solid #F87171;
            }
            QPushButton:pressed {
                background-color: #B91C1C;
            }
            QPushButton:disabled {
                background-color: #64748B;
                color: #94A3B8;
                border: 2px solid #475569;
            }
        """)
        self.remove_case_btn.setToolTip("Remove the selected case from history (files will not be deleted)")
        self.remove_case_btn.clicked.connect(self.remove_selected_case)
        self.remove_case_btn.setEnabled(False)  # Disabled until a row is selected
        
        # Enable/disable button based on selection
        self.cases_table.itemSelectionChanged.connect(self.on_case_selection_changed)
        
        actions_layout.addWidget(self.remove_case_btn)

        actions_layout.addStretch()

        layout.addLayout(actions_layout)

        # Load cases into table
        self.load_cases_table()

        return panel

    def _on_clone_case_data(self):
        """Close Settings, then invoke the controller's clone handler (which opens
        its own file pickers + loading dialog — avoids a nested modal)."""
        self._clone_requested = True
        self.accept()
    
    def create_case_settings_panel(self):
        """Create the case settings panel."""
        panel = QtWidgets.QWidget()
        panel.setStyleSheet("""
            QWidget {
                background-color: #0F172A;
            }
        """)
        
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        
        # Title
        title = QtWidgets.QLabel("CASE SETTINGS")
        title.setStyleSheet("""
            QLabel {
                color: #00FFFF;
                font-size: 20px;
                font-weight: 700;
                font-family: 'BBH Sans Bogle', 'Segoe UI', sans-serif;
            }
        """)
        layout.addWidget(title)
        
        if self.current_case:
            # Current case info
            info_label = QtWidgets.QLabel(f"Current Case: {self.current_case.name}")
            info_label.setStyleSheet("""
                QLabel {
                    color: #94A3B8;
                    font-size: 14px;
                    font-family: 'Segoe UI', sans-serif;
                    padding: 10px;
                    background-color: #1E293B;
                    border-radius: 6px;
                }
            """)
            layout.addWidget(info_label)
            
            # Case-specific settings would go here
            # For now, just a placeholder
            placeholder = QtWidgets.QLabel("Case-specific settings will be added here.")
            placeholder.setStyleSheet("""
                QLabel {
                    color: #64748B;
                    font-size: 13px;
                    font-family: 'Segoe UI', sans-serif;
                    padding: 20px;
                }
            """)
            layout.addWidget(placeholder)
        else:
            # No active case message
            no_case_label = QtWidgets.QLabel("No active case.\nCase settings are only available when a case is open.")
            no_case_label.setAlignment(Qt.AlignCenter)
            no_case_label.setStyleSheet("""
                QLabel {
                    color: #64748B;
                    font-size: 14px;
                    font-family: 'Segoe UI', sans-serif;
                    padding: 40px;
                }
            """)
            layout.addWidget(no_case_label)

        # Import Case Data from Another Case — copies another case's parsed + collected
        # artifacts INTO the current case and loads them into the GUI, WITHOUT its Eye
        # memory or correlation results. Enabled only when a case is currently open.
        self.clone_case_btn = QtWidgets.QPushButton("⧉ Import Case Data from Another Case…")
        self.clone_case_btn.setFixedHeight(45)
        self.clone_case_btn.setMinimumWidth(240)
        self.clone_case_btn.setStyleSheet("""
            QPushButton {
                background-color: #0E7490;
                color: #FFFFFF;
                border: 2px solid #22D3EE;
                border-radius: 8px;
                padding: 12px 24px;
                font-weight: 700;
                font-size: 13px;
                font-family: 'Segoe UI', sans-serif;
            }
            QPushButton:hover {
                background-color: #0891B2;
                border: 2px solid #67E8F9;
            }
            QPushButton:pressed {
                background-color: #155E75;
            }
            QPushButton:disabled {
                background-color: #64748B;
                color: #94A3B8;
                border: 2px solid #475569;
            }
        """)
        self.clone_case_btn.setToolTip(
            "Copy another case's parsed + collected artifacts into THIS case and load them "
            "into the GUI (no Eye memory / correlation results imported)."
        )
        self.clone_case_btn.setEnabled(bool(self.current_case_path))
        if not self.current_case_path:
            self.clone_case_btn.setToolTip("Open a case first to import another case's data into it.")
        self.clone_case_btn.clicked.connect(self._on_clone_case_data)
        layout.addWidget(self.clone_case_btn)

        layout.addStretch()

        return panel

    def create_semantic_mappings_panel(self):
        """Create the semantic mappings configuration panel."""
        panel = QtWidgets.QWidget()
        panel.setStyleSheet("""
            QWidget {
                background-color: #0F172A;
            }
        """)
        
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        
        # Title
        title = QtWidgets.QLabel("SEMANTIC MAPPINGS")
        title.setStyleSheet("""
            QLabel {
                color: #00FFFF;
                font-size: 20px;
                font-weight: 700;
                font-family: 'BBH Sans Bogle', 'Segoe UI', sans-serif;
            }
        """)
        layout.addWidget(title)
        
        # Info text
        info_label = QtWidgets.QLabel(
            "Configure global semantic mappings that apply to all Wings. "
            "Map technical values (e.g., Event IDs) to human-readable meanings."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("""
            QLabel {
                color: #94A3B8;
                font-size: 13px;
                font-family: 'Segoe UI', sans-serif;
                padding: 10px;
                background-color: #1E293B;
                border-radius: 6px;
            }
        """)
        layout.addWidget(info_label)
        
        # Toolbar
        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setSpacing(10)
        
        add_btn = QtWidgets.QPushButton("➕ Add Mapping")
        add_btn.setFixedHeight(40)
        add_btn.setStyleSheet(CrowEyeStyles.BUTTON_STYLE + """
            QPushButton {
                font-size: 12px;
                padding: 8px 16px;
            }
        """)
        add_btn.clicked.connect(self.add_semantic_mapping)
        
        edit_btn = QtWidgets.QPushButton("✏ Edit Selected")
        edit_btn.setFixedHeight(40)
        edit_btn.setStyleSheet(CrowEyeStyles.BUTTON_STYLE + """
            QPushButton {
                font-size: 12px;
                padding: 8px 16px;
            }
        """)
        edit_btn.clicked.connect(self.edit_semantic_mapping)
        
        delete_btn = QtWidgets.QPushButton("🗑 Delete Selected")
        delete_btn.setFixedHeight(40)
        delete_btn.setStyleSheet("""
            QPushButton {
                background-color: #DC2626;
                color: #FFFFFF;
                border: 2px solid #EF4444;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: 600;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #EF4444;
            }
        """)
        delete_btn.clicked.connect(self.delete_semantic_mapping)
        
        import_btn = QtWidgets.QPushButton("📥 Import")
        import_btn.setFixedHeight(40)
        import_btn.setStyleSheet(CrowEyeStyles.BUTTON_STYLE + """
            QPushButton {
                font-size: 12px;
                padding: 8px 16px;
            }
        """)
        import_btn.clicked.connect(self.import_semantic_mappings)
        
        export_btn = QtWidgets.QPushButton("📤 Export")
        export_btn.setFixedHeight(40)
        export_btn.setStyleSheet(CrowEyeStyles.BUTTON_STYLE + """
            QPushButton {
                font-size: 12px;
                padding: 8px 16px;
            }
        """)
        export_btn.clicked.connect(self.export_semantic_mappings)
        
        reset_btn = QtWidgets.QPushButton("🔄 Reset to Defaults")
        reset_btn.setFixedHeight(40)
        reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #F59E0B;
                color: #FFFFFF;
                border: 2px solid #FBBF24;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: 600;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #FBBF24;
            }
        """)
        reset_btn.clicked.connect(self.reset_semantic_mappings)
        
        toolbar.addWidget(add_btn)
        toolbar.addWidget(edit_btn)
        toolbar.addWidget(delete_btn)
        toolbar.addStretch()
        toolbar.addWidget(import_btn)
        toolbar.addWidget(export_btn)
        toolbar.addWidget(reset_btn)
        
        layout.addLayout(toolbar)
        
        # Semantic mappings table - 9 columns to show both Simple and Advanced rules
        self.semantic_table = QtWidgets.QTableWidget()
        self.semantic_table.setColumnCount(9)
        self.semantic_table.setHorizontalHeaderLabels([
            "Type", "Category", "Name", "Logic", "Conditions/Value", "Semantic Value", "Severity", "Feathers", "Description"
        ])
        self.semantic_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.semantic_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        CrowEyeStyles.apply_table_styles(self.semantic_table)
        
        self.semantic_table.setStyleSheet(CrowEyeStyles.UNIFIED_TABLE_STYLE + """
            QTableWidget {
                font-size: 13px;
            }
            QTableWidget::item {
                padding: 10px 8px;
                font-size: 13px;
                color: #F8FAFC;
            }
            QHeaderView::section {
                padding: 10px 8px;
                font-size: 12px;
            }
        """)
        
        self.semantic_table.horizontalHeader().setStretchLastSection(True)
        self.semantic_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)  # Type
        self.semantic_table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)  # Category
        self.semantic_table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)  # Name
        self.semantic_table.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents)  # Logic
        self.semantic_table.horizontalHeader().setSectionResizeMode(4, QtWidgets.QHeaderView.Stretch)  # Conditions/Value
        self.semantic_table.horizontalHeader().setSectionResizeMode(5, QtWidgets.QHeaderView.ResizeToContents)  # Semantic Value
        self.semantic_table.horizontalHeader().setSectionResizeMode(6, QtWidgets.QHeaderView.ResizeToContents)  # Severity
        self.semantic_table.horizontalHeader().setSectionResizeMode(7, QtWidgets.QHeaderView.ResizeToContents)  # Feathers
        self.semantic_table.horizontalHeader().setSectionResizeMode(8, QtWidgets.QHeaderView.Stretch)  # Description
        self.semantic_table.setMinimumHeight(400)
        
        layout.addWidget(self.semantic_table)
        
        # Load semantic mappings into table
        if self.semantic_manager:
            self.load_semantic_mappings_table()
        else:
            # Show message if semantic manager not available
            no_manager_label = QtWidgets.QLabel(
                "⚠ Semantic Mapping Manager not available.\n"
                "Please ensure the correlation engine is properly installed."
            )
            no_manager_label.setAlignment(Qt.AlignCenter)
            no_manager_label.setStyleSheet("""
                QLabel {
                    color: #F59E0B;
                    font-size: 14px;
                    padding: 40px;
                }
            """)
            layout.addWidget(no_manager_label)
        
        return panel
    
    def create_pipeline_management_panel(self):
        """Create the pipeline management panel."""
        panel = QtWidgets.QWidget()
        panel.setStyleSheet("""
            QWidget {
                background-color: #0F172A;
            }
        """)
        
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        if self.current_case and PipelineManagementTab:
            # Create pipeline management tab with current case directory
            try:
                self.pipeline_tab = PipelineManagementTab(self.current_case_path, self)
                layout.addWidget(self.pipeline_tab)
            except Exception as e:
                # Show error message if pipeline tab fails to load
                error_label = QtWidgets.QLabel(
                    f"⚠ Failed to load Pipeline Management:\n{str(e)}"
                )
                error_label.setAlignment(Qt.AlignCenter)
                error_label.setStyleSheet("""
                    QLabel {
                        color: #F59E0B;
                        font-size: 14px;
                        padding: 40px;
                    }
                """)
                layout.addWidget(error_label)
        else:
            # No active case or PipelineManagementTab not available
            if not self.current_case:
                no_case_label = QtWidgets.QLabel(
                    "No active case.\n\n"
                    "Pipeline management is only available when a case is open."
                )
            else:
                no_case_label = QtWidgets.QLabel(
                    "⚠ Pipeline Management not available.\n\n"
                    "Please ensure the correlation engine is properly installed."
                )
            
            no_case_label.setAlignment(Qt.AlignCenter)
            no_case_label.setStyleSheet("""
                QLabel {
                    color: #64748B;
                    font-size: 14px;
                    font-family: 'Segoe UI', sans-serif;
                    padding: 40px;
                }
            """)
            layout.addWidget(no_case_label)
        
        return panel
    
    def create_eye_ai_panel(self):
        """Create the Eye AI settings panel (Compliance payload storage)."""
        panel = QtWidgets.QWidget()
        panel.setStyleSheet("QWidget { background-color: #0F172A; }")

        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        # Brand term is "Eye" / "Eye AI" — never uppercased to "EYE".
        # (PyQt5 ignores text-transform/letter-spacing anyway, so the literal
        # casing is what matters.)
        title_row = QtWidgets.QHBoxLayout()
        title_row.setSpacing(10)
        title_icon = QtWidgets.QLabel()
        title_icon.setPixmap(
            QtGui.QPixmap("GUI Resources/the Eye AI agent transparent.png").scaled(
                28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        title = QtWidgets.QLabel("Eye AI")
        title.setStyleSheet("""
            QLabel {
                color: #00FFFF;
                font-size: 20px;
                font-weight: 700;
                font-family: 'BBH Sans Bogle', 'Segoe UI', sans-serif;
            }
        """)
        title_row.addWidget(title_icon)
        title_row.addWidget(title)
        title_row.addStretch()
        layout.addLayout(title_row)

        info = QtWidgets.QLabel(
            "Chain-of-custody storage for what the Eye sent to the model. "
            "Changes apply the next time the Eye is opened."
        )
        info.setWordWrap(True)
        info.setStyleSheet("""
            QLabel {
                color: #94A3B8; font-size: 13px; font-family: 'Segoe UI', sans-serif;
                padding: 10px; background-color: #1E293B; border-radius: 6px;
            }
        """)
        layout.addWidget(info)

        # Backend / model display + buttons that launch the existing Eye dialogs.
        btn_style = CrowEyeStyles.BUTTON_STYLE + " QPushButton { font-size: 12px; padding: 8px 16px; min-height: 35px; }"
        backend_row = QtWidgets.QHBoxLayout()
        self.eye_backend_label = QtWidgets.QLabel("Backend: —")
        self.eye_backend_label.setStyleSheet(
            "QLabel { color: #E2E8F0; font-size: 13px; font-weight: 600; font-family: 'Segoe UI', sans-serif; }")
        self.eye_configure_btn = QtWidgets.QPushButton("Configure Backend, Model & API Key…")
        self.eye_configure_btn.setStyleSheet(btn_style)
        self.eye_configure_btn.clicked.connect(self._open_eye_onboarding)
        backend_row.addWidget(self.eye_backend_label, 1)
        backend_row.addWidget(self.eye_configure_btn)
        layout.addLayout(backend_row)

        checkbox_style = """
            QCheckBox { color: #E2E8F0; font-size: 13px; font-weight: 600;
                        font-family: 'Segoe UI', sans-serif; spacing: 10px; }
            QCheckBox::indicator { width: 24px; height: 24px; border: 2px solid #475569;
                        border-radius: 4px; background-color: #1E293B; }
            QCheckBox::indicator:hover { border: 2px solid #00FFFF; background-color: #263449; }
            QCheckBox::indicator:checked { background-color: #00FFFF; border: 2px solid #00FFFF; }
        """
        # Style BOTH QSpinBox and QDoubleSpinBox (the Evidence Confidence field is a
        # QDoubleSpinBox and was previously unstyled), and fully style the up/down
        # buttons + arrows — once a spin box is partly stylesheeted Qt stops drawing
        # the native buttons cleanly, which is why they looked "missing the style".
        spin_style = """
            QSpinBox, QDoubleSpinBox {
                background-color: #1E293B; color: #FFFFFF; border: 2px solid #475569;
                border-radius: 6px; padding: 8px 12px; min-height: 35px;
                font-size: 14px; font-weight: 600; font-family: 'Segoe UI', sans-serif;
            }
            QSpinBox:hover, QSpinBox:focus,
            QDoubleSpinBox:hover, QDoubleSpinBox:focus {
                border: 2px solid #00FFFF; background-color: #263449;
            }
            QSpinBox::up-button, QDoubleSpinBox::up-button {
                subcontrol-origin: border; subcontrol-position: top right;
                width: 22px; background-color: #334155;
                border-left: 1px solid #475569; border-top-right-radius: 6px;
            }
            QSpinBox::down-button, QDoubleSpinBox::down-button {
                subcontrol-origin: border; subcontrol-position: bottom right;
                width: 22px; background-color: #334155;
                border-left: 1px solid #475569; border-bottom-right-radius: 6px;
            }
            QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
            QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
                background-color: #00FFFF;
            }
            QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
                width: 0; height: 0;
                border-left: 5px solid transparent; border-right: 5px solid transparent;
                border-bottom: 7px solid #E2E8F0;
            }
            QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
                width: 0; height: 0;
                border-left: 5px solid transparent; border-right: 5px solid transparent;
                border-top: 7px solid #E2E8F0;
            }
            QSpinBox::up-arrow:hover, QDoubleSpinBox::up-arrow:hover {
                border-bottom: 7px solid #0F172A;
            }
            QSpinBox::down-arrow:hover, QDoubleSpinBox::down-arrow:hover {
                border-top: 7px solid #0F172A;
            }
            QSpinBox:disabled, QDoubleSpinBox:disabled {
                background-color: #1E293B; color: #64748B; border: 2px solid #334155;
            }
        """
        desc_style = "QLabel { color: #94A3B8; font-size: 11px; font-style: italic; padding-top: 3px; }"
        # Text-input style matching the spin boxes (the embedding Model/Endpoint fields
        # were previously handed spin_style, whose QSpinBox-only selectors never matched
        # a QLineEdit — so they rendered as default white boxes).
        input_style = """
            QLineEdit {
                background-color: #1E293B; color: #FFFFFF; border: 2px solid #475569;
                border-radius: 6px; padding: 8px 12px; min-height: 35px;
                font-size: 14px; font-weight: 600; font-family: 'Segoe UI', sans-serif;
            }
            QLineEdit:hover, QLineEdit:focus { border: 2px solid #00FFFF; background-color: #263449; }
            QLineEdit:disabled { background-color: #1E293B; color: #64748B; border: 2px solid #334155; }
        """
        # Small non-italic sub-label sitting inline next to an input (e.g. "Model:",
        # "Endpoint:", "Max recalled turns:") — legible, not shrunken like desc_style.
        sublabel_style = "QLabel { color: #94A3B8; font-size: 13px; font-weight: 600; }"
        # Single shared style for every subsection header so they stay identical
        # (cyan, 15px, 700) — previously the Embeddings header drifted to grey 13px.
        section_header_style = (
            "QLabel { color: #00FFFF; font-size: 15px; font-weight: 700; "
            "font-family: 'BBH Sans Bogle', 'Segoe UI', sans-serif; padding-top: 6px; }")

        form_widget = QtWidgets.QWidget()
        form_layout = QtWidgets.QFormLayout(form_widget)
        form_layout.setSpacing(20)
        form_layout.setLabelAlignment(Qt.AlignRight)
        form_layout.setContentsMargins(20, 20, 20, 20)
        label_style = "QLabel { color: #E2E8F0; font-size: 14px; font-weight: 600; padding-right: 15px; }"

        # Store full payload toggle
        store_label = QtWidgets.QLabel("Save Full Sent Payload:")
        store_label.setStyleSheet(label_style)
        store_container = QtWidgets.QWidget()
        store_layout = QtWidgets.QVBoxLayout(store_container)
        store_layout.setContentsMargins(0, 0, 0, 0)
        store_layout.setSpacing(5)
        self.eye_store_full_payload_checkbox = QtWidgets.QCheckBox(
            "Store the exact payload (system prompt + history + tools) per seal")
        self.eye_store_full_payload_checkbox.setStyleSheet(checkbox_style)
        store_desc = QtWidgets.QLabel(
            "💡 Lets the Compliance log REPRODUCE (not just verify) each turn. "
            "Off = only the SHA-256 is kept.")
        store_desc.setWordWrap(True)
        store_desc.setStyleSheet(desc_style)
        store_layout.addWidget(self.eye_store_full_payload_checkbox)
        store_layout.addWidget(store_desc)
        form_layout.addRow(store_label, store_container)

        # Recent-uncompressed window
        recent_label = QtWidgets.QLabel("Messages Before Compress:")
        recent_label.setStyleSheet(label_style)
        recent_container = QtWidgets.QWidget()
        recent_layout = QtWidgets.QVBoxLayout(recent_container)
        recent_layout.setContentsMargins(0, 0, 0, 0)
        recent_layout.setSpacing(5)
        self.eye_recent_uncompressed_spin = QtWidgets.QSpinBox()
        self.eye_recent_uncompressed_spin.setRange(0, 1000)
        self.eye_recent_uncompressed_spin.setValue(10)
        self.eye_recent_uncompressed_spin.setStyleSheet(spin_style)
        recent_desc = QtWidgets.QLabel(
            "💡 Keep this many recent payloads uncompressed; older ones are "
            "compressed (zstd, gzip fallback) and decompressed on demand.")
        recent_desc.setWordWrap(True)
        recent_desc.setStyleSheet(desc_style)
        recent_layout.addWidget(self.eye_recent_uncompressed_spin)
        recent_layout.addWidget(recent_desc)
        form_layout.addRow(recent_label, recent_container)

        # Evidence preservation confidence threshold
        conf_label = QtWidgets.QLabel("Evidence Confidence:")
        conf_label.setStyleSheet(label_style)
        conf_container = QtWidgets.QWidget()
        conf_layout = QtWidgets.QVBoxLayout(conf_container)
        conf_layout.setContentsMargins(0, 0, 0, 0)
        conf_layout.setSpacing(5)
        self.eye_confidence_spin = QtWidgets.QDoubleSpinBox()
        self.eye_confidence_spin.setRange(0.0, 1.0)
        self.eye_confidence_spin.setSingleStep(0.05)
        self.eye_confidence_spin.setDecimals(2)
        self.eye_confidence_spin.setValue(0.70)
        self.eye_confidence_spin.setStyleSheet(spin_style)
        conf_desc = QtWidgets.QLabel(
            "💡 Minimum detector confidence (0–1) to auto-preserve a message as evidence.")
        conf_desc.setWordWrap(True)
        conf_desc.setStyleSheet(desc_style)
        conf_layout.addWidget(self.eye_confidence_spin)
        conf_layout.addWidget(conf_desc)
        form_layout.addRow(conf_label, conf_container)

        # Max context tokens + lock
        ctx_label = QtWidgets.QLabel("Max Context Tokens:")
        ctx_label.setStyleSheet(label_style)
        ctx_container = QtWidgets.QWidget()
        ctx_layout = QtWidgets.QVBoxLayout(ctx_container)
        ctx_layout.setContentsMargins(0, 0, 0, 0)
        ctx_layout.setSpacing(5)
        self.eye_max_tokens_spin = QtWidgets.QSpinBox()
        self.eye_max_tokens_spin.setRange(1000, 2000000)
        self.eye_max_tokens_spin.setSingleStep(1000)
        self.eye_max_tokens_spin.setValue(64000)
        self.eye_max_tokens_spin.setStyleSheet(spin_style)
        self.eye_lock_tokens_checkbox = QtWidgets.QCheckBox(
            "Lock — don't auto-resolve to the model's real window")
        self.eye_lock_tokens_checkbox.setStyleSheet(checkbox_style)
        ctx_desc = QtWidgets.QLabel(
            "💡 Fallback window for unknown models. Locking pins this value instead of "
            "auto-detecting the backend's real context window.")
        ctx_desc.setWordWrap(True)
        ctx_desc.setStyleSheet(desc_style)
        ctx_layout.addWidget(self.eye_max_tokens_spin)
        ctx_layout.addWidget(self.eye_lock_tokens_checkbox)
        ctx_layout.addWidget(ctx_desc)
        form_layout.addRow(ctx_label, ctx_container)

        # Max tool output chars
        tool_label = QtWidgets.QLabel("Max Tool Output Chars:")
        tool_label.setStyleSheet(label_style)
        tool_container = QtWidgets.QWidget()
        tool_layout = QtWidgets.QVBoxLayout(tool_container)
        tool_layout.setContentsMargins(0, 0, 0, 0)
        tool_layout.setSpacing(5)
        self.eye_tool_output_spin = QtWidgets.QSpinBox()
        self.eye_tool_output_spin.setRange(1000, 5000000)
        self.eye_tool_output_spin.setSingleStep(1000)
        self.eye_tool_output_spin.setValue(100000)
        self.eye_tool_output_spin.setStyleSheet(spin_style)
        tool_desc = QtWidgets.QLabel(
            "💡 Floor for how much of a single tool result is kept in the model's context "
            "(scales up with the window).")
        tool_desc.setWordWrap(True)
        tool_desc.setStyleSheet(desc_style)
        tool_layout.addWidget(self.eye_tool_output_spin)
        tool_layout.addWidget(tool_desc)
        form_layout.addRow(tool_label, tool_container)

        # --- Reasoning (Multi-Step Investigation) subsection ----------------
        reasoning_header = QtWidgets.QLabel("Reasoning (Multi-Step Investigation)")
        reasoning_header.setStyleSheet(section_header_style)
        form_layout.addRow(reasoning_header)

        # Decompose multi-part questions
        decomp_label = QtWidgets.QLabel("Question Decomposition:")
        decomp_label.setStyleSheet(label_style)
        decomp_container = QtWidgets.QWidget()
        decomp_layout = QtWidgets.QVBoxLayout(decomp_container)
        decomp_layout.setContentsMargins(0, 0, 0, 0)
        decomp_layout.setSpacing(5)
        self.eye_enable_decomposition_checkbox = QtWidgets.QCheckBox(
            "Split multi-part questions into sub-questions and correlate the answers")
        self.eye_enable_decomposition_checkbox.setStyleSheet(checkbox_style)
        decomp_desc = QtWidgets.QLabel(
            "💡 Each part is investigated to completion, then merged into one consolidated answer.")
        decomp_desc.setWordWrap(True)
        decomp_desc.setStyleSheet(desc_style)
        decomp_layout.addWidget(self.eye_enable_decomposition_checkbox)
        decomp_layout.addWidget(decomp_desc)
        form_layout.addRow(decomp_label, decomp_container)

        # Max sub-questions
        subq_label = QtWidgets.QLabel("Max Sub-Questions:")
        subq_label.setStyleSheet(label_style)
        subq_container = QtWidgets.QWidget()
        subq_layout = QtWidgets.QVBoxLayout(subq_container)
        subq_layout.setContentsMargins(0, 0, 0, 0)
        subq_layout.setSpacing(5)
        self.eye_max_subq_spin = QtWidgets.QSpinBox()
        self.eye_max_subq_spin.setRange(1, 20)
        self.eye_max_subq_spin.setValue(6)
        self.eye_max_subq_spin.setStyleSheet(spin_style)
        subq_desc = QtWidgets.QLabel(
            "💡 Upper bound on how many sub-questions a single query is split into.")
        subq_desc.setWordWrap(True)
        subq_desc.setStyleSheet(desc_style)
        subq_layout.addWidget(self.eye_max_subq_spin)
        subq_layout.addWidget(subq_desc)
        form_layout.addRow(subq_label, subq_container)

        # --- Hierarchical Investigation (verdict → narrative → sub-narrative) ---
        hier_header = QtWidgets.QLabel("Hierarchical Investigation")
        hier_header.setStyleSheet(section_header_style)
        form_layout.addRow(hier_header)

        # Enable the claim-hierarchy engine
        hier_label = QtWidgets.QLabel("Plan-Driven Hierarchy:")
        hier_label.setStyleSheet(label_style)
        hier_container = QtWidgets.QWidget()
        hier_layout = QtWidgets.QVBoxLayout(hier_container)
        hier_layout.setContentsMargins(0, 0, 0, 0)
        hier_layout.setSpacing(5)
        self.eye_enable_hierarchy_checkbox = QtWidgets.QCheckBox(
            "Plan the case as a Verdict → Narrative → Sub-narrative claim hierarchy and prove it step by step")
        self.eye_enable_hierarchy_checkbox.setStyleSheet(checkbox_style)
        hier_desc = QtWidgets.QLabel(
            "💡 The Eye builds the plan up front, seeds it onto the Narrative Map, then proves one "
            "sub-narrative at a time with the right tools — flipping each card as evidence lands. "
            "Off = the classic flat sub-question flow.")
        hier_desc.setWordWrap(True)
        hier_desc.setStyleSheet(desc_style)
        hier_layout.addWidget(self.eye_enable_hierarchy_checkbox)
        hier_layout.addWidget(hier_desc)
        form_layout.addRow(hier_label, hier_container)

        # Max narratives
        narr_label = QtWidgets.QLabel("Max Narratives:")
        narr_label.setStyleSheet(label_style)
        narr_container = QtWidgets.QWidget()
        narr_layout = QtWidgets.QVBoxLayout(narr_container)
        narr_layout.setContentsMargins(0, 0, 0, 0)
        narr_layout.setSpacing(5)
        self.eye_max_narratives_spin = QtWidgets.QSpinBox()
        self.eye_max_narratives_spin.setRange(1, 30)
        self.eye_max_narratives_spin.setValue(12)
        self.eye_max_narratives_spin.setStyleSheet(spin_style)
        narr_desc = QtWidgets.QLabel(
            "💡 Upper bound on the activities/behaviors the plan splits the verdict into.")
        narr_desc.setWordWrap(True)
        narr_desc.setStyleSheet(desc_style)
        narr_layout.addWidget(self.eye_max_narratives_spin)
        narr_layout.addWidget(narr_desc)
        form_layout.addRow(narr_label, narr_container)

        # Max sub-narratives per narrative
        subnarr_label = QtWidgets.QLabel("Max Sub-Narratives:")
        subnarr_label.setStyleSheet(label_style)
        subnarr_container = QtWidgets.QWidget()
        subnarr_layout = QtWidgets.QVBoxLayout(subnarr_container)
        subnarr_layout.setContentsMargins(0, 0, 0, 0)
        subnarr_layout.setSpacing(5)
        self.eye_max_sub_narratives_spin = QtWidgets.QSpinBox()
        self.eye_max_sub_narratives_spin.setRange(1, 20)
        self.eye_max_sub_narratives_spin.setValue(8)
        self.eye_max_sub_narratives_spin.setStyleSheet(spin_style)
        subnarr_desc = QtWidgets.QLabel(
            "💡 Upper bound on the evidence-bearing steps inside EACH narrative.")
        subnarr_desc.setWordWrap(True)
        subnarr_desc.setStyleSheet(desc_style)
        subnarr_layout.addWidget(self.eye_max_sub_narratives_spin)
        subnarr_layout.addWidget(subnarr_desc)
        form_layout.addRow(subnarr_label, subnarr_container)

        # Max iterations (overall model-call budget for one hierarchical run)
        maxiter_label = QtWidgets.QLabel("Max Iterations:")
        maxiter_label.setStyleSheet(label_style)
        maxiter_container = QtWidgets.QWidget()
        maxiter_layout = QtWidgets.QVBoxLayout(maxiter_container)
        maxiter_layout.setContentsMargins(0, 0, 0, 0)
        maxiter_layout.setSpacing(5)
        self.eye_max_iterations_spin = QtWidgets.QSpinBox()
        self.eye_max_iterations_spin.setRange(20, 2000)
        self.eye_max_iterations_spin.setSingleStep(20)
        self.eye_max_iterations_spin.setValue(300)
        self.eye_max_iterations_spin.setStyleSheet(spin_style)
        maxiter_desc = QtWidgets.QLabel(
            "💡 Upper bound on the model-call steps one investigation may use (scaled to plan size, "
            "capped here). Raise it for very large plans; each sub-narrative is still individually bounded.")
        maxiter_desc.setWordWrap(True)
        maxiter_desc.setStyleSheet(desc_style)
        maxiter_layout.addWidget(self.eye_max_iterations_spin)
        maxiter_layout.addWidget(maxiter_desc)
        form_layout.addRow(maxiter_label, maxiter_container)

        # Premise verification
        premise_label = QtWidgets.QLabel("Premise Verification:")
        premise_label.setStyleSheet(label_style)
        premise_container = QtWidgets.QWidget()
        premise_layout = QtWidgets.QVBoxLayout(premise_container)
        premise_layout.setContentsMargins(0, 0, 0, 0)
        premise_layout.setSpacing(5)
        self.eye_enable_premise_checkbox = QtWidgets.QCheckBox(
            "Prove or disprove the investigator's claims against the artifacts")
        self.eye_enable_premise_checkbox.setStyleSheet(checkbox_style)
        premise_desc = QtWidgets.QLabel(
            "💡 Treats stated facts as hypotheses; tells you when a claim is contradicted by evidence.")
        premise_desc.setWordWrap(True)
        premise_desc.setStyleSheet(desc_style)
        premise_layout.addWidget(self.eye_enable_premise_checkbox)
        premise_layout.addWidget(premise_desc)
        form_layout.addRow(premise_label, premise_container)

        # Question memory (reuse prior answers)
        qmem_label = QtWidgets.QLabel("Answer Memory:")
        qmem_label.setStyleSheet(label_style)
        qmem_container = QtWidgets.QWidget()
        qmem_layout = QtWidgets.QVBoxLayout(qmem_container)
        qmem_layout.setContentsMargins(0, 0, 0, 0)
        qmem_layout.setSpacing(5)
        self.eye_enable_question_memory_checkbox = QtWidgets.QCheckBox(
            "Remember prior answers and reuse them on related follow-ups")
        self.eye_enable_question_memory_checkbox.setStyleSheet(checkbox_style)
        qmem_desc = QtWidgets.QLabel(
            "💡 Saves each answer + its findings to the case, so related questions reuse data "
            "instead of re-querying.")
        qmem_desc.setWordWrap(True)
        qmem_desc.setStyleSheet(desc_style)
        qmem_layout.addWidget(self.eye_enable_question_memory_checkbox)
        qmem_layout.addWidget(qmem_desc)
        form_layout.addRow(qmem_label, qmem_container)

        # Prior findings to reuse
        prior_label = QtWidgets.QLabel("Prior Findings to Reuse:")
        prior_label.setStyleSheet(label_style)
        prior_container = QtWidgets.QWidget()
        prior_layout = QtWidgets.QVBoxLayout(prior_container)
        prior_layout.setContentsMargins(0, 0, 0, 0)
        prior_layout.setSpacing(5)
        self.eye_prior_findings_spin = QtWidgets.QSpinBox()
        self.eye_prior_findings_spin.setRange(0, 20)
        self.eye_prior_findings_spin.setValue(3)
        self.eye_prior_findings_spin.setStyleSheet(spin_style)
        prior_desc = QtWidgets.QLabel(
            "💡 How many recent prior-question findings are surfaced to the model for reuse "
            "(0 disables reuse).")
        prior_desc.setWordWrap(True)
        prior_desc.setStyleSheet(desc_style)
        prior_layout.addWidget(self.eye_prior_findings_spin)
        prior_layout.addWidget(prior_desc)
        form_layout.addRow(prior_label, prior_container)

        # --- Resilience subsection (v0.11.2): Gemini 500s, big questions, big data ---
        resilience_header = QtWidgets.QLabel("Resilience (Large Questions & Data)")
        resilience_header.setStyleSheet(section_header_style)
        form_layout.addRow(resilience_header)

        # Model retry attempts (transient 500 backoff)
        retry_label = QtWidgets.QLabel("Model Retry Attempts:")
        retry_label.setStyleSheet(label_style)
        retry_container = QtWidgets.QWidget()
        retry_layout = QtWidgets.QVBoxLayout(retry_container)
        retry_layout.setContentsMargins(0, 0, 0, 0)
        retry_layout.setSpacing(5)
        self.eye_model_retry_spin = QtWidgets.QSpinBox()
        self.eye_model_retry_spin.setRange(1, 6)
        self.eye_model_retry_spin.setValue(3)
        self.eye_model_retry_spin.setStyleSheet(spin_style)
        retry_desc = QtWidgets.QLabel(
            "💡 Attempts (with exponential backoff) when the provider returns a transient error "
            "such as a Gemini 500/INTERNAL. 1 = no retry.")
        retry_desc.setWordWrap(True)
        retry_desc.setStyleSheet(desc_style)
        retry_layout.addWidget(self.eye_model_retry_spin)
        retry_layout.addWidget(retry_desc)
        form_layout.addRow(retry_label, retry_container)

        # Auto-segment big questions
        seg_label = QtWidgets.QLabel("Auto-Segment Big Questions:")
        seg_label.setStyleSheet(label_style)
        seg_container = QtWidgets.QWidget()
        seg_layout = QtWidgets.QVBoxLayout(seg_container)
        seg_layout.setContentsMargins(0, 0, 0, 0)
        seg_layout.setSpacing(5)
        self.eye_auto_segment_checkbox = QtWidgets.QCheckBox(
            "Let the Eye (LLM) break a big/complex question into focused logical sub-questions")
        self.eye_auto_segment_checkbox.setStyleSheet(checkbox_style)
        seg_desc = QtWidgets.QLabel(
            "💡 The model decides the split along logical boundaries (artifacts, time ranges, "
            "entities, claims) and works each in turn, then consolidates. Off = split only "
            "genuinely multi-part questions. (No character-length rule.)")
        seg_desc.setWordWrap(True)
        seg_desc.setStyleSheet(desc_style)
        seg_layout.addWidget(self.eye_auto_segment_checkbox)
        seg_layout.addWidget(seg_desc)
        form_layout.addRow(seg_label, seg_container)

        # Auto map-reduce big data reads
        mr_label = QtWidgets.QLabel("Auto Map-Reduce Big Data:")
        mr_label.setStyleSheet(label_style)
        mr_container = QtWidgets.QWidget()
        mr_layout = QtWidgets.QVBoxLayout(mr_container)
        mr_layout.setContentsMargins(0, 0, 0, 0)
        mr_layout.setSpacing(5)
        self.eye_auto_mapreduce_checkbox = QtWidgets.QCheckBox(
            "Analyze very large query results in full via sealed map-reduce segments")
        self.eye_auto_mapreduce_checkbox.setStyleSheet(checkbox_style)
        self.eye_auto_mapreduce_rows_spin = QtWidgets.QSpinBox()
        self.eye_auto_mapreduce_rows_spin.setRange(100, 1000000)
        self.eye_auto_mapreduce_rows_spin.setSingleStep(100)
        self.eye_auto_mapreduce_rows_spin.setValue(1500)
        self.eye_auto_mapreduce_rows_spin.setStyleSheet(spin_style)
        mr_desc = QtWidgets.QLabel(
            "💡 A query returning at least this many rows is auto-divided and analyzed in full "
            "(every segment sealed in the Compliance log) instead of sampled.")
        mr_desc.setWordWrap(True)
        mr_desc.setStyleSheet(desc_style)
        mr_layout.addWidget(self.eye_auto_mapreduce_checkbox)
        mr_layout.addWidget(self.eye_auto_mapreduce_rows_spin)
        mr_layout.addWidget(mr_desc)
        form_layout.addRow(mr_label, mr_container)

        # --- Reasoning transparency & tuning subsection (v0.11.3) ---
        rtune_header = QtWidgets.QLabel("Reasoning Transparency & Tuning")
        rtune_header.setStyleSheet(section_header_style)
        form_layout.addRow(rtune_header)

        # Reasoning trace (why each sub-question + why each conclusion)
        rtrace_label = QtWidgets.QLabel("Reasoning Trace:")
        rtrace_label.setStyleSheet(label_style)
        rtrace_container = QtWidgets.QWidget()
        rtrace_layout = QtWidgets.QVBoxLayout(rtrace_container)
        rtrace_layout.setContentsMargins(0, 0, 0, 0)
        rtrace_layout.setSpacing(5)
        self.eye_reasoning_trace_checkbox = QtWidgets.QCheckBox(
            "Record WHY each sub-question was created and WHY each conclusion follows from its evidence")
        self.eye_reasoning_trace_checkbox.setStyleSheet(checkbox_style)
        rtrace_desc = QtWidgets.QLabel(
            "💡 After a decomposed question, a sealed pass captures the decomposition + per-conclusion "
            "rationale (with evidence refs) and shows it in the Compliance window.")
        rtrace_desc.setWordWrap(True)
        rtrace_desc.setStyleSheet(desc_style)
        rtrace_layout.addWidget(self.eye_reasoning_trace_checkbox)
        rtrace_layout.addWidget(rtrace_desc)
        form_layout.addRow(rtrace_label, rtrace_container)

        # Answer temperature
        atemp_label = QtWidgets.QLabel("Answer Temperature:")
        atemp_label.setStyleSheet(label_style)
        atemp_container = QtWidgets.QWidget()
        atemp_layout = QtWidgets.QVBoxLayout(atemp_container)
        atemp_layout.setContentsMargins(0, 0, 0, 0)
        atemp_layout.setSpacing(5)
        self.eye_answer_temp_spin = QtWidgets.QDoubleSpinBox()
        self.eye_answer_temp_spin.setRange(0.0, 2.0)
        self.eye_answer_temp_spin.setSingleStep(0.1)
        self.eye_answer_temp_spin.setValue(0.2)
        self.eye_answer_temp_spin.setStyleSheet(spin_style)
        atemp_desc = QtWidgets.QLabel(
            "💡 Sampling temperature for investigative/synthesis answers. Lower = more deterministic, "
            "evidence-faithful output (0.2 recommended for forensics).")
        atemp_desc.setWordWrap(True)
        atemp_desc.setStyleSheet(desc_style)
        atemp_layout.addWidget(self.eye_answer_temp_spin)
        atemp_layout.addWidget(atemp_desc)
        form_layout.addRow(atemp_label, atemp_container)

        # Planning temperature
        ptemp_label = QtWidgets.QLabel("Planning Temperature:")
        ptemp_label.setStyleSheet(label_style)
        ptemp_container = QtWidgets.QWidget()
        ptemp_layout = QtWidgets.QVBoxLayout(ptemp_container)
        ptemp_layout.setContentsMargins(0, 0, 0, 0)
        ptemp_layout.setSpacing(5)
        self.eye_planning_temp_spin = QtWidgets.QDoubleSpinBox()
        self.eye_planning_temp_spin.setRange(0.0, 2.0)
        self.eye_planning_temp_spin.setSingleStep(0.1)
        self.eye_planning_temp_spin.setValue(0.0)
        self.eye_planning_temp_spin.setStyleSheet(spin_style)
        ptemp_desc = QtWidgets.QLabel(
            "💡 Temperature for the planning + reasoning-trace passes. Near-zero for repeatable "
            "decomposition.")
        ptemp_desc.setWordWrap(True)
        ptemp_desc.setStyleSheet(desc_style)
        ptemp_layout.addWidget(self.eye_planning_temp_spin)
        ptemp_layout.addWidget(ptemp_desc)
        form_layout.addRow(ptemp_label, ptemp_container)

        # RAG top-k
        ragk_label = QtWidgets.QLabel("Knowledge Chunks (RAG top-k):")
        ragk_label.setStyleSheet(label_style)
        ragk_container = QtWidgets.QWidget()
        ragk_layout = QtWidgets.QVBoxLayout(ragk_container)
        ragk_layout.setContentsMargins(0, 0, 0, 0)
        ragk_layout.setSpacing(5)
        self.eye_rag_topk_spin = QtWidgets.QSpinBox()
        self.eye_rag_topk_spin.setRange(1, 20)
        self.eye_rag_topk_spin.setValue(5)
        self.eye_rag_topk_spin.setStyleSheet(spin_style)
        ragk_desc = QtWidgets.QLabel(
            "💡 Max ranked knowledge-base chunks retrieved per query (semantic when an embedding "
            "server is present, otherwise the built-in lexical ranker) beyond keyword-mapped docs.")
        ragk_desc.setWordWrap(True)
        ragk_desc.setStyleSheet(desc_style)
        ragk_layout.addWidget(self.eye_rag_topk_spin)
        ragk_layout.addWidget(ragk_desc)
        form_layout.addRow(ragk_label, ragk_container)

        # Sub-question-aware RAG
        ragsq_label = QtWidgets.QLabel("Sub-Question Knowledge:")
        ragsq_label.setStyleSheet(label_style)
        ragsq_container = QtWidgets.QWidget()
        ragsq_layout = QtWidgets.QVBoxLayout(ragsq_container)
        ragsq_layout.setContentsMargins(0, 0, 0, 0)
        ragsq_layout.setSpacing(5)
        self.eye_rag_subq_checkbox = QtWidgets.QCheckBox(
            "Retrieve targeted knowledge for each sub-question (not just the main query)")
        self.eye_rag_subq_checkbox.setStyleSheet(checkbox_style)
        ragsq_desc = QtWidgets.QLabel(
            "💡 After decomposition, each sub-question pulls its own artifact knowledge so multi-part "
            "questions aren't limited to the main query's matches.")
        ragsq_desc.setWordWrap(True)
        ragsq_desc.setStyleSheet(desc_style)
        ragsq_layout.addWidget(self.eye_rag_subq_checkbox)
        ragsq_layout.addWidget(ragsq_desc)
        form_layout.addRow(ragsq_label, ragsq_container)

        # Conversation memory — sliding window size (turns kept verbatim)
        winturns_label = QtWidgets.QLabel("Conversation Window (turns):")
        winturns_label.setStyleSheet(label_style)
        winturns_container = QtWidgets.QWidget()
        winturns_layout = QtWidgets.QVBoxLayout(winturns_container)
        winturns_layout.setContentsMargins(0, 0, 0, 0)
        winturns_layout.setSpacing(5)
        self.eye_history_window_spin = QtWidgets.QSpinBox()
        self.eye_history_window_spin.setRange(1, 50)
        self.eye_history_window_spin.setValue(5)
        self.eye_history_window_spin.setStyleSheet(spin_style)
        winturns_desc = QtWidgets.QLabel(
            "💡 Most-recent turns kept VERBATIM (the sliding window). Older non-evidence turns are "
            "folded into a rolling summary; evidence/pinned turns and the first turn are always kept.")
        winturns_desc.setWordWrap(True)
        winturns_desc.setStyleSheet(desc_style)
        winturns_layout.addWidget(self.eye_history_window_spin)
        winturns_layout.addWidget(winturns_desc)
        form_layout.addRow(winturns_label, winturns_container)

        # Conversation memory — summarization buffer toggle
        sumbuf_label = QtWidgets.QLabel("Summarization Buffer:")
        sumbuf_label.setStyleSheet(label_style)
        sumbuf_container = QtWidgets.QWidget()
        sumbuf_layout = QtWidgets.QVBoxLayout(sumbuf_container)
        sumbuf_layout.setContentsMargins(0, 0, 0, 0)
        sumbuf_layout.setSpacing(5)
        self.eye_summary_buffer_checkbox = QtWidgets.QCheckBox(
            "Summarize older turns before dropping them (Stage 1)")
        self.eye_summary_buffer_checkbox.setStyleSheet(checkbox_style)
        sumbuf_desc = QtWidgets.QLabel(
            "💡 When the window fills, fold older turns into a rolling summary first; the "
            "sliding-window drop (Stage 2) is the hard floor when even that won't fit.")
        sumbuf_desc.setWordWrap(True)
        sumbuf_desc.setStyleSheet(desc_style)
        sumbuf_layout.addWidget(self.eye_summary_buffer_checkbox)
        sumbuf_layout.addWidget(sumbuf_desc)
        form_layout.addRow(sumbuf_label, sumbuf_container)

        # Conversation memory — long-term recall toggle + top-k
        recall_label = QtWidgets.QLabel("Conversation Recall:")
        recall_label.setStyleSheet(label_style)
        recall_container = QtWidgets.QWidget()
        recall_layout = QtWidgets.QVBoxLayout(recall_container)
        recall_layout.setContentsMargins(0, 0, 0, 0)
        recall_layout.setSpacing(5)
        self.eye_conversation_recall_checkbox = QtWidgets.QCheckBox(
            "Recall earlier (summarized / slid-out) turns relevant to the query")
        self.eye_conversation_recall_checkbox.setStyleSheet(checkbox_style)
        recall_topk_row = QtWidgets.QHBoxLayout()
        recall_topk_row.setContentsMargins(0, 0, 0, 0)
        recall_topk_inner_label = QtWidgets.QLabel("Max recalled turns:")
        recall_topk_inner_label.setStyleSheet(sublabel_style)
        self.eye_conversation_recall_topk_spin = QtWidgets.QSpinBox()
        self.eye_conversation_recall_topk_spin.setRange(1, 20)
        self.eye_conversation_recall_topk_spin.setValue(3)
        self.eye_conversation_recall_topk_spin.setStyleSheet(spin_style)
        recall_topk_row.addWidget(recall_topk_inner_label)
        recall_topk_row.addWidget(self.eye_conversation_recall_topk_spin)
        recall_topk_row.addStretch()
        recall_desc = QtWidgets.QLabel(
            "💡 Long-term memory: retrieve specific older turns by relevance and inject a "
            "'Recalled Earlier Conversation' block, so nothing is truly lost when the window fills.")
        recall_desc.setWordWrap(True)
        recall_desc.setStyleSheet(desc_style)
        recall_layout.addWidget(self.eye_conversation_recall_checkbox)
        recall_layout.addLayout(recall_topk_row)
        recall_layout.addWidget(recall_desc)
        form_layout.addRow(recall_label, recall_container)

        # --- Semantic retrieval (embeddings) subsection ---
        emb_header = QtWidgets.QLabel("Semantic Retrieval (Embeddings)")
        emb_header.setStyleSheet(section_header_style)
        form_layout.addRow(emb_header)

        emb_label = QtWidgets.QLabel("Embedding Server:")
        emb_label.setStyleSheet(label_style)
        emb_container = QtWidgets.QWidget()
        emb_layout = QtWidgets.QVBoxLayout(emb_container)
        emb_layout.setContentsMargins(0, 0, 0, 0)
        emb_layout.setSpacing(5)
        self.eye_embedding_enabled_checkbox = QtWidgets.QCheckBox(
            "Enable embedding-backed semantic retrieval (requires a reachable server, e.g. Ollama)")
        self.eye_embedding_enabled_checkbox.setStyleSheet(checkbox_style)
        emb_model_row = QtWidgets.QHBoxLayout()
        emb_model_row.setContentsMargins(0, 0, 0, 0)
        emb_model_lbl = QtWidgets.QLabel("Model:")
        emb_model_lbl.setStyleSheet(sublabel_style)
        self.eye_embedding_model_input = QtWidgets.QLineEdit()
        self.eye_embedding_model_input.setPlaceholderText("nomic-embed-text")
        self.eye_embedding_model_input.setStyleSheet(input_style)
        emb_model_row.addWidget(emb_model_lbl)
        emb_model_row.addWidget(self.eye_embedding_model_input)
        emb_ep_row = QtWidgets.QHBoxLayout()
        emb_ep_row.setContentsMargins(0, 0, 0, 0)
        emb_ep_lbl = QtWidgets.QLabel("Endpoint:")
        emb_ep_lbl.setStyleSheet(sublabel_style)
        self.eye_embedding_endpoint_input = QtWidgets.QLineEdit()
        self.eye_embedding_endpoint_input.setPlaceholderText("http://localhost:11434")
        self.eye_embedding_endpoint_input.setStyleSheet(input_style)
        emb_ep_row.addWidget(emb_ep_lbl)
        emb_ep_row.addWidget(self.eye_embedding_endpoint_input)
        self.eye_embedding_index_evidence_checkbox = QtWidgets.QCheckBox(
            "Build a per-case semantic index over forensic data (enables semantic_search_artifacts)")
        self.eye_embedding_index_evidence_checkbox.setStyleSheet(checkbox_style)
        emb_desc = QtWidgets.QLabel(
            "💡 Optional. When off (or the server is unreachable) the Eye uses the built-in BM25 "
            "lexical ranker — Cloud/CLI deployments are unaffected. Semantic search is a DISCOVERY "
            "aid; exact SQL stays authoritative for counts, timelines, and completeness.")
        emb_desc.setWordWrap(True)
        emb_desc.setStyleSheet(desc_style)
        emb_layout.addWidget(self.eye_embedding_enabled_checkbox)
        emb_layout.addLayout(emb_model_row)
        emb_layout.addLayout(emb_ep_row)
        emb_layout.addWidget(self.eye_embedding_index_evidence_checkbox)
        emb_layout.addWidget(emb_desc)
        form_layout.addRow(emb_label, emb_container)

        layout.addWidget(form_widget)

        # Advanced context / token-budget dialog (existing Eye dialog).
        self.eye_advanced_ctx_btn = QtWidgets.QPushButton("Advanced Context & Token Budget…")
        self.eye_advanced_ctx_btn.setStyleSheet(btn_style)
        self.eye_advanced_ctx_btn.clicked.connect(self._open_eye_context_dialog)
        adv_row = QtWidgets.QHBoxLayout()
        adv_row.addStretch()
        adv_row.addWidget(self.eye_advanced_ctx_btn)
        layout.addLayout(adv_row)

        layout.addStretch()

        # Disable native controls if the helper module could not be imported
        # (the launcher buttons have their own import guards).
        if read_eye_ai_settings is None or write_eye_ai_settings is None:
            for w in (self.eye_store_full_payload_checkbox, self.eye_recent_uncompressed_spin,
                      self.eye_confidence_spin, self.eye_max_tokens_spin,
                      self.eye_lock_tokens_checkbox, self.eye_tool_output_spin,
                      self.eye_enable_decomposition_checkbox, self.eye_max_subq_spin,
                      self.eye_enable_hierarchy_checkbox, self.eye_max_narratives_spin,
                      self.eye_max_sub_narratives_spin, self.eye_max_iterations_spin,
                      self.eye_enable_premise_checkbox, self.eye_enable_question_memory_checkbox,
                      self.eye_prior_findings_spin,
                      self.eye_model_retry_spin, self.eye_auto_segment_checkbox,
                      self.eye_auto_mapreduce_checkbox,
                      self.eye_auto_mapreduce_rows_spin,
                      self.eye_reasoning_trace_checkbox, self.eye_answer_temp_spin,
                      self.eye_planning_temp_spin, self.eye_rag_topk_spin,
                      self.eye_rag_subq_checkbox, self.eye_history_window_spin,
                      self.eye_summary_buffer_checkbox, self.eye_conversation_recall_checkbox,
                      self.eye_conversation_recall_topk_spin,
                      self.eye_embedding_enabled_checkbox, self.eye_embedding_model_input,
                      self.eye_embedding_endpoint_input, self.eye_embedding_index_evidence_checkbox):
                w.setEnabled(False)
            info.setText("Eye AI settings module unavailable (config.eye_ai_settings could not be imported).")

        # Wrap the (tall) settings stack in a scroll area so every setting stays
        # reachable on short windows instead of being clipped/collapsed.
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(panel)
        scroll.setStyleSheet(
            "QScrollArea{border:none;background:#0F172A;} "
            "QScrollBar:vertical{background:#0F172A;width:10px;margin:0;border:none;} "
            "QScrollBar::handle:vertical{background:#334155;border-radius:5px;min-height:30px;} "
            "QScrollBar::handle:vertical:hover{background:#475569;} "
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;background:none;} "
            # Without explicit add-page/sub-page (the groove above & below the handle)
            # PyQt5 reverts the track to the pale native painting once the bar is styled.
            "QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{background:#0F172A;} "
            "QScrollBar::corner{background:#0F172A;}"
        )
        scroll.viewport().setStyleSheet("background:#0F172A;")
        return scroll

    def _open_eye_onboarding(self):
        """Launch the existing Eye OnboardingWizard (backend / model / API key)."""
        try:
            from eye.services.config_manager import ConfigManager
            from eye.services.credential_manager import CredentialManager
            from eye.ui.onboarding_wizard import OnboardingWizard
        except Exception as e:
            QMessageBox.warning(self, "Eye AI", f"Eye onboarding is unavailable:\n{e}")
            return
        try:
            wizard = OnboardingWizard(ConfigManager(), CredentialManager(), None, self)
            wizard.exec_()
            self.load_settings()  # refresh backend label + any changed values
        except Exception as e:
            QMessageBox.critical(self, "Eye AI", f"Failed to open onboarding wizard:\n{e}")

    def _open_eye_context_dialog(self):
        """Launch the existing Eye ContextWindowSettingsDialog (advanced tuning)."""
        try:
            from eye.services.context_window_config_manager import ContextWindowConfigManager
            from eye.services.config_manager import ConfigManager
            from eye.ui.settings_dialog import ContextWindowSettingsDialog
        except Exception as e:
            QMessageBox.warning(self, "Eye AI", f"Advanced context settings are unavailable:\n{e}")
            return
        try:
            backend = ""
            try:
                backend = ConfigManager().load_config().get("backend", "") or ""
            except Exception:
                pass
            dlg = ContextWindowSettingsDialog(ContextWindowConfigManager(), backend, self)
            dlg.exec_()
            self.load_settings()
        except Exception as e:
            QMessageBox.critical(self, "Eye AI", f"Failed to open advanced context settings:\n{e}")

    def _load_semantic_mappings(self):
        """Load semantic mappings from file."""
        if not self.semantic_manager:
            return
        
        # Get user's home directory
        home_dir = Path.home()
        crow_eye_dir = home_dir / ".crow_eye"
        mappings_file = crow_eye_dir / "semantic_mappings.json"
        
        # Create directory if it doesn't exist
        crow_eye_dir.mkdir(exist_ok=True)
        
        # Load from file if it exists
        if mappings_file.exists():
            try:
                self.semantic_manager.load_from_file(mappings_file)
            except Exception as e:
                print(f"Error loading semantic mappings: {e}")
    
    def load_semantic_mappings_table(self):
        """Load semantic mappings and advanced rules into the table with 9 columns."""
        if not self.semantic_manager:
            return
        
        self.semantic_table.setRowCount(0)
        
        # Get all global mappings (simple)
        mappings = self.semantic_manager.get_all_mappings(scope="global")
        
        # Get all global rules (advanced with AND/OR logic)
        rules = self.semantic_manager.get_rules(scope="global")
        
        print(f"[Settings] Loading {len(mappings)} simple mappings and {len(rules)} advanced rules")
        
        # Categorize mappings
        categories = {
            'user_activity': [],
            'system_events': [],
            'process_execution': [],
            'other': []
        }
        
        for mapping in mappings:
            # Determine category based on source and semantic value
            if 'Login' in mapping.semantic_value or 'Logoff' in mapping.semantic_value or 'Session' in mapping.semantic_value:
                categories['user_activity'].append(mapping)
            elif 'System' in mapping.semantic_value or 'Shutdown' in mapping.semantic_value or 'Startup' in mapping.semantic_value:
                categories['system_events'].append(mapping)
            elif 'Process' in mapping.semantic_value:
                categories['process_execution'].append(mapping)
            else:
                categories['other'].append(mapping)
        
        # Add mappings to table by category
        category_names = {
            'user_activity': 'User Activity',
            'system_events': 'System Events',
            'process_execution': 'Process Execution',
            'other': 'Other'
        }
        
        # Add simple mappings first
        for category_key, category_mappings in categories.items():
            if not category_mappings:
                continue
            
            for mapping in category_mappings:
                row = self.semantic_table.rowCount()
                self.semantic_table.insertRow(row)
                
                # Type (Simple - green)
                type_item = QtWidgets.QTableWidgetItem("Simple")
                type_item.setForeground(QtGui.QColor("#10B981"))
                type_item.setData(Qt.UserRole, mapping)  # Store mapping object
                type_item.setData(Qt.UserRole + 1, "simple")  # Store type
                self.semantic_table.setItem(row, 0, type_item)
                
                # Category
                category_item = QtWidgets.QTableWidgetItem(category_names[category_key])
                self.semantic_table.setItem(row, 1, category_item)
                
                # Name (Source.Field)
                name_item = QtWidgets.QTableWidgetItem(f"{mapping.source}.{mapping.field}")
                self.semantic_table.setItem(row, 2, name_item)
                
                # Logic (N/A for simple)
                logic_item = QtWidgets.QTableWidgetItem("-")
                logic_item.setForeground(QtGui.QColor("#64748B"))
                self.semantic_table.setItem(row, 3, logic_item)
                
                # Conditions/Value
                value_item = QtWidgets.QTableWidgetItem(f"= {mapping.technical_value}")
                self.semantic_table.setItem(row, 4, value_item)
                
                # Semantic Value (cyan)
                semantic_item = QtWidgets.QTableWidgetItem(mapping.semantic_value)
                semantic_item.setForeground(QtGui.QColor("#00FFFF"))
                self.semantic_table.setItem(row, 5, semantic_item)
                
                # Severity
                severity = mapping.severity if hasattr(mapping, 'severity') else 'info'
                severity_item = QtWidgets.QTableWidgetItem(severity)
                severity_colors = {"info": "#3B82F6", "low": "#10B981", "medium": "#F59E0B", "high": "#EF4444", "critical": "#DC2626"}
                severity_item.setForeground(QtGui.QColor(severity_colors.get(severity, "#64748B")))
                self.semantic_table.setItem(row, 6, severity_item)
                
                # Feathers
                feather_item = QtWidgets.QTableWidgetItem(mapping.source)
                self.semantic_table.setItem(row, 7, feather_item)
                
                # Description
                desc_item = QtWidgets.QTableWidgetItem(mapping.description if hasattr(mapping, 'description') else '')
                self.semantic_table.setItem(row, 8, desc_item)
        
        # Add advanced rules
        for rule in rules:
            row = self.semantic_table.rowCount()
            self.semantic_table.insertRow(row)
            
            # Type (Advanced - cyan bold)
            type_item = QtWidgets.QTableWidgetItem("Advanced")
            type_item.setForeground(QtGui.QColor("#00FFFF"))
            font = type_item.font()
            font.setBold(True)
            type_item.setFont(font)
            type_item.setData(Qt.UserRole, rule)  # Store rule object
            type_item.setData(Qt.UserRole + 1, "advanced")  # Store type
            self.semantic_table.setItem(row, 0, type_item)
            
            # Category (determine from conditions)
            category = "Advanced Rule"
            if hasattr(rule, 'conditions') and rule.conditions:
                first_feather = rule.conditions[0].feather_id if rule.conditions else ""
                if "Security" in first_feather:
                    category = "User Activity"
                elif "System" in first_feather:
                    category = "System Events"
                elif "Prefetch" in first_feather or "Process" in first_feather:
                    category = "Process Execution"
            category_item = QtWidgets.QTableWidgetItem(category)
            self.semantic_table.setItem(row, 1, category_item)
            
            # Name (rule name - bold)
            name_item = QtWidgets.QTableWidgetItem(rule.name)
            name_item.setFont(font)
            self.semantic_table.setItem(row, 2, name_item)
            
            # Logic (AND/OR with color)
            logic_item = QtWidgets.QTableWidgetItem(rule.logic_operator)
            logic_color = "#10B981" if rule.logic_operator == "AND" else "#F59E0B"
            logic_item.setForeground(QtGui.QColor(logic_color))
            logic_item.setFont(font)
            self.semantic_table.setItem(row, 3, logic_item)
            
            # Conditions (detailed format with tooltip)
            conditions_parts = []
            for c in rule.conditions:
                op_symbol = {"equals": "=", "contains": "~", "wildcard": "*", "regex": "≈"}.get(c.operator, "=")
                conditions_parts.append(f"{c.feather_id}.{c.field_name}{op_symbol}{c.value}")
            conditions_str = f" {rule.logic_operator} ".join(conditions_parts)
            conditions_item = QtWidgets.QTableWidgetItem(conditions_str)
            conditions_item.setToolTip(f"Conditions ({len(rule.conditions)}):\n" + "\n".join([f"• {c.feather_id}.{c.field_name} {c.operator} '{c.value}'" for c in rule.conditions]))
            self.semantic_table.setItem(row, 4, conditions_item)
            
            # Semantic Value (cyan bold)
            semantic_item = QtWidgets.QTableWidgetItem(rule.semantic_value)
            semantic_item.setForeground(QtGui.QColor("#00FFFF"))
            semantic_item.setFont(font)
            self.semantic_table.setItem(row, 5, semantic_item)
            
            # Severity (color-coded)
            severity = rule.severity if hasattr(rule, 'severity') else 'info'
            severity_item = QtWidgets.QTableWidgetItem(severity)
            severity_colors = {"info": "#3B82F6", "low": "#10B981", "medium": "#F59E0B", "high": "#EF4444", "critical": "#DC2626"}
            severity_item.setForeground(QtGui.QColor(severity_colors.get(severity, "#64748B")))
            severity_item.setFont(font)
            self.semantic_table.setItem(row, 6, severity_item)
            
            # Feathers (unique list)
            feathers = set([c.feather_id for c in rule.conditions])
            feathers_str = ", ".join(sorted(feathers))
            feather_item = QtWidgets.QTableWidgetItem(feathers_str)
            self.semantic_table.setItem(row, 7, feather_item)
            
            # Description
            desc_item = QtWidgets.QTableWidgetItem(rule.description if hasattr(rule, 'description') else '')
            self.semantic_table.setItem(row, 8, desc_item)
        
        print(f"[Settings] Table now has {self.semantic_table.rowCount()} rows")
    
    def add_semantic_mapping(self):
        """Add a new semantic mapping using the advanced dialog."""
        if not self.semantic_manager:
            return
        
        # Use the advanced SemanticMappingDialog if available
        if AdvancedSemanticMappingDialog:
            dialog = AdvancedSemanticMappingDialog(
                parent=self,
                mapping=None,
                scope='global',
                wing_id=None,
                mode='simple'  # Default to simple, user can switch to advanced
            )
            
            if dialog.exec_() == QtWidgets.QDialog.Accepted:
                # Check if it's an advanced rule or simple mapping
                rule = dialog.get_rule()
                
                if rule and len(rule.conditions) > 0:
                    # Advanced rule with conditions
                    self.semantic_manager.add_rule(rule)
                else:
                    # Simple mapping
                    mapping_data = dialog.get_mapping()
                    if mapping_data:
                        mapping = SemanticMapping(
                            source=mapping_data.get('source', ''),
                            field=mapping_data.get('field', ''),
                            technical_value=mapping_data.get('technical_value', ''),
                            semantic_value=mapping_data.get('semantic_value', ''),
                            description=mapping_data.get('description', ''),
                            scope='global'
                        )
                        self.semantic_manager.add_mapping(mapping)
                
                self.load_semantic_mappings_table()
        else:
            # Fallback to simple dialog
            dialog = SimpleSemanticMappingDialog(self)
            if dialog.exec_() == QtWidgets.QDialog.Accepted:
                mapping_data = dialog.get_mapping_data()
                
                mapping = SemanticMapping(
                    source=mapping_data['source'],
                    field=mapping_data['field'],
                    technical_value=mapping_data['technical_value'],
                    semantic_value=mapping_data['semantic_value'],
                    description=mapping_data.get('description', ''),
                    scope='global'
                )
                
                self.semantic_manager.add_mapping(mapping)
                self.load_semantic_mappings_table()
    
    def edit_semantic_mapping(self):
        """Edit the selected semantic mapping or advanced rule using the advanced dialog."""
        if not self.semantic_manager:
            return
        
        selected_rows = self.semantic_table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "No Selection", "Please select a mapping or rule to edit.")
            return
        
        row = selected_rows[0].row()
        type_item = self.semantic_table.item(row, 0)
        item_data = type_item.data(Qt.UserRole)
        item_type = type_item.data(Qt.UserRole + 1)  # "simple" or "advanced"
        
        if not item_data:
            return
        
        # Use the advanced SemanticMappingDialog if available
        if AdvancedSemanticMappingDialog:
            if item_type == "advanced":
                # Editing an advanced rule
                dialog = AdvancedSemanticMappingDialog(
                    parent=self,
                    mapping=None,
                    scope='global',
                    wing_id=None,
                    mode='advanced',
                    rule=item_data  # Pass the rule object
                )
                
                if dialog.exec_() == QtWidgets.QDialog.Accepted:
                    # Remove old rule
                    self.semantic_manager.remove_rule(item_data.name, scope='global')
                    
                    # Add new rule
                    new_rule = dialog.get_rule()
                    if new_rule:
                        self.semantic_manager.add_rule(new_rule)
                    
                    self.load_semantic_mappings_table()
            else:
                # Editing a simple mapping
                mapping = item_data
                mapping_dict = {
                    'source': mapping.source,
                    'field': mapping.field,
                    'technical_value': mapping.technical_value,
                    'semantic_value': mapping.semantic_value,
                    'description': mapping.description or ''
                }
                
                dialog = AdvancedSemanticMappingDialog(
                    parent=self,
                    mapping=mapping_dict,
                    scope='global',
                    wing_id=None,
                    mode='simple'
                )
                
                if dialog.exec_() == QtWidgets.QDialog.Accepted:
                    # Remove old mapping
                    self.semantic_manager.remove_mapping(
                        mapping.source, mapping.field, mapping.technical_value, scope='global'
                    )
                    
                    # Check if it's an advanced rule or simple mapping
                    rule = dialog.get_rule()
                    
                    if rule and len(rule.conditions) > 0:
                        # Advanced rule with conditions
                        self.semantic_manager.add_rule(rule)
                    else:
                        # Simple mapping
                        mapping_data = dialog.get_mapping()
                        if mapping_data:
                            new_mapping = SemanticMapping(
                                source=mapping_data.get('source', ''),
                                field=mapping_data.get('field', ''),
                                technical_value=mapping_data.get('technical_value', ''),
                                semantic_value=mapping_data.get('semantic_value', ''),
                                description=mapping_data.get('description', ''),
                                scope='global'
                            )
                            self.semantic_manager.add_mapping(new_mapping)
                    
                    self.load_semantic_mappings_table()
        else:
            # Fallback to simple dialog (only for simple mappings)
            if item_type == "advanced":
                QMessageBox.warning(self, "Not Supported", "Advanced rule editing requires the advanced dialog.")
                return
            
            mapping = item_data
            dialog = SimpleSemanticMappingDialog(self, mapping)
            if dialog.exec_() == QtWidgets.QDialog.Accepted:
                mapping_data = dialog.get_mapping_data()
                
                # Remove old mapping
                self.semantic_manager.remove_mapping(
                    mapping.source, mapping.field, mapping.technical_value, scope='global'
                )
                
                # Add updated mapping
                new_mapping = SemanticMapping(
                    source=mapping_data['source'],
                    field=mapping_data['field'],
                    technical_value=mapping_data['technical_value'],
                    semantic_value=mapping_data['semantic_value'],
                    description=mapping_data.get('description', ''),
                    scope='global'
                )
                
                self.semantic_manager.add_mapping(new_mapping)
                self.load_semantic_mappings_table()
    
    def delete_semantic_mapping(self):
        """Delete the selected semantic mapping or advanced rule."""
        if not self.semantic_manager:
            return
        
        selected_rows = self.semantic_table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "No Selection", "Please select a mapping or rule to delete.")
            return
        
        row = selected_rows[0].row()
        type_item = self.semantic_table.item(row, 0)
        item_data = type_item.data(Qt.UserRole)
        item_type = type_item.data(Qt.UserRole + 1)  # "simple" or "advanced"
        
        if not item_data:
            return
        
        # Confirm deletion
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Delete Mapping")
        
        if item_type == "advanced":
            msg_box.setText(f"Delete advanced rule '{item_data.name}'?")
        else:
            msg_box.setText(f"Delete mapping for {item_data.source}.{item_data.field} = {item_data.technical_value}?")
        
        msg_box.setIcon(QMessageBox.Question)
        msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg_box.setDefaultButton(QMessageBox.No)
        msg_box.setStyleSheet(CrowEyeStyles.MESSAGE_BOX_STYLE)
        
        if msg_box.exec_() == QMessageBox.Yes:
            if item_type == "advanced":
                # Delete advanced rule
                self.semantic_manager.remove_rule(item_data.name, scope='global')
            else:
                # Delete simple mapping
                self.semantic_manager.remove_mapping(
                    item_data.source, item_data.field, item_data.technical_value, scope='global'
                )
            self.load_semantic_mappings_table()
    
    def import_semantic_mappings(self):
        """Import semantic mappings from a JSON file."""
        if not self.semantic_manager:
            return
        
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Semantic Mappings",
            "",
            "JSON Files (*.json);;All Files (*)"
        )
        
        if file_path:
            try:
                self.semantic_manager.load_from_file(Path(file_path))
                self.load_semantic_mappings_table()
                
                QMessageBox.information(
                    self,
                    "Import Successful",
                    "Semantic mappings imported successfully."
                )
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Import Error",
                    f"Failed to import semantic mappings:\n{str(e)}"
                )
    
    def export_semantic_mappings(self):
        """Export semantic mappings to a JSON file."""
        if not self.semantic_manager:
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Semantic Mappings",
            "semantic_mappings.json",
            "JSON Files (*.json);;All Files (*)"
        )
        
        if file_path:
            try:
                self.semantic_manager.save_to_file(Path(file_path), scope='global')
                
                QMessageBox.information(
                    self,
                    "Export Successful",
                    f"Semantic mappings exported to:\n{file_path}"
                )
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Export Error",
                    f"Failed to export semantic mappings:\n{str(e)}"
                )
    
    def reset_semantic_mappings(self):
        """Reset semantic mappings to defaults."""
        if not self.semantic_manager:
            return
        
        # Confirm reset
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Reset to Defaults")
        msg_box.setText(
            "Reset all semantic mappings to defaults?\n\n"
            "This will remove all custom mappings and restore the default set."
        )
        msg_box.setIcon(QMessageBox.Warning)
        msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg_box.setDefaultButton(QMessageBox.No)
        msg_box.setStyleSheet(CrowEyeStyles.MESSAGE_BOX_STYLE)
        
        if msg_box.exec_() == QMessageBox.Yes:
            # Clear all global mappings
            self.semantic_manager.global_mappings.clear()
            
            # Reload defaults
            self.semantic_manager._load_default_mappings()
            
            # Refresh table
            self.load_semantic_mappings_table()
            
            QMessageBox.information(
                self,
                "Reset Complete",
                "Semantic mappings have been reset to defaults."
            )
    
    def load_cases_table(self):
        """Load all cases into the table."""
        self.cases_table.setRowCount(0)
        
        cases = self.case_history_manager.case_history
        
        for case in cases:
            row = self.cases_table.rowCount()
            self.cases_table.insertRow(row)
            
            # Store case object in first item for later retrieval
            name_item = QtWidgets.QTableWidgetItem(case.name)
            name_item.setData(Qt.UserRole, case)  # Store case object
            self.cases_table.setItem(row, 0, name_item)
            
            # Path
            path_item = QtWidgets.QTableWidgetItem(case.path)
            self.cases_table.setItem(row, 1, path_item)
            
            # Created date
            created_item = QtWidgets.QTableWidgetItem(self._format_datetime(case.created_date))
            self.cases_table.setItem(row, 2, created_item)
            
            # Last opened
            opened_item = QtWidgets.QTableWidgetItem(self._format_datetime(case.last_opened))
            self.cases_table.setItem(row, 3, opened_item)
    
    def filter_cases(self, text):
        """Filter cases table based on search text."""
        for row in range(self.cases_table.rowCount()):
            show = False
            for col in range(4):  # Check all 4 columns (no actions or description columns)
                item = self.cases_table.item(row, col)
                if item and text.lower() in item.text().lower():
                    show = True
                    break
            self.cases_table.setRowHidden(row, not show)
    
    def on_case_selection_changed(self):
        """Enable/disable remove button based on selection."""
        has_selection = len(self.cases_table.selectedItems()) > 0
        self.remove_case_btn.setEnabled(has_selection)
    
    def remove_selected_case(self):
        """Remove the currently selected case from history."""
        selected_rows = self.cases_table.selectionModel().selectedRows()
        if not selected_rows:
            return
        
        # Get the case object from the first column
        row = selected_rows[0].row()
        name_item = self.cases_table.item(row, 0)
        case = name_item.data(Qt.UserRole)
        
        if not case:
            return
        
        # Create styled message box
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Remove Case")
        msg_box.setText(f"Remove '{case.name}' from history?\n\nThis will not delete the case files.")
        msg_box.setIcon(QMessageBox.Question)
        msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg_box.setDefaultButton(QMessageBox.No)
        
        # Apply cyberpunk styling
        msg_box.setStyleSheet(CrowEyeStyles.MESSAGE_BOX_STYLE)
        
        reply = msg_box.exec_()
        
        if reply == QMessageBox.Yes:
            self.case_history_manager.remove_case(case.path)
            self.load_cases_table()
            self.remove_case_btn.setEnabled(False)  # Disable after removal
    
    def browse_default_directory(self):
        """Browse for default case directory."""
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Default Case Directory",
            self.default_dir_input.text() or "C:/"
        )
        if directory:
            self.default_dir_input.setText(directory)
    
    def load_settings(self):
        """Load current settings into the form."""
        config = self.case_history_manager.global_config
        
        self.default_dir_input.setText(config.default_case_directory)
        self.recent_count_spin.setValue(config.recent_cases_display_count)
        self.max_history_spin.setValue(config.max_history_size)
        self.identity_semantic_phase_checkbox.setChecked(config.identity_semantic_phase_enabled)
        
        # Load wings semantic mapping setting (default to True if not present)
        wings_semantic_enabled = getattr(config, 'wings_semantic_mapping_enabled', True)
        self.wings_semantic_mapping_checkbox.setChecked(wings_semantic_enabled)
        
        # Load cascade tree expansion setting (default to True if not present)
        cascade_enabled = getattr(config, 'cascade_tree_expansion_enabled', True)
        self.cascade_expansion_checkbox.setChecked(cascade_enabled)

        # Load Eye AI settings from configs/eye_config.json
        if read_eye_ai_settings is not None:
            try:
                eye_ai = read_eye_ai_settings()
                self.eye_store_full_payload_checkbox.setChecked(bool(eye_ai["store_full_payload"]))
                self.eye_recent_uncompressed_spin.setValue(int(eye_ai["sealed_payload_recent_uncompressed"]))
                self.eye_confidence_spin.setValue(float(eye_ai["confidence_threshold"]))
                self.eye_max_tokens_spin.setValue(int(eye_ai["max_total_tokens"]))
                self.eye_lock_tokens_checkbox.setChecked(bool(eye_ai["lock_max_total_tokens"]))
                self.eye_tool_output_spin.setValue(int(eye_ai["max_tool_output_chars"]))
                # Reasoning (v0.11.1) — tolerant of missing keys.
                self.eye_enable_decomposition_checkbox.setChecked(bool(eye_ai.get("enable_decomposition", True)))
                self.eye_max_subq_spin.setValue(int(eye_ai.get("max_sub_questions", 6)))
                self.eye_enable_hierarchy_checkbox.setChecked(bool(eye_ai.get("enable_hierarchy", True)))
                self.eye_max_narratives_spin.setValue(int(eye_ai.get("max_narratives", 12)))
                self.eye_max_sub_narratives_spin.setValue(int(eye_ai.get("max_sub_narratives", 8)))
                self.eye_max_iterations_spin.setValue(int(eye_ai.get("max_iterations", 300)))
                self.eye_enable_premise_checkbox.setChecked(bool(eye_ai.get("enable_premise_verification", True)))
                self.eye_enable_question_memory_checkbox.setChecked(bool(eye_ai.get("enable_question_memory", True)))
                self.eye_prior_findings_spin.setValue(int(eye_ai.get("prior_findings_count", 3)))
                self.eye_model_retry_spin.setValue(int(eye_ai.get("model_retry_max_attempts", 3)))
                self.eye_auto_segment_checkbox.setChecked(bool(eye_ai.get("auto_segment_question", True)))
                self.eye_auto_mapreduce_checkbox.setChecked(bool(eye_ai.get("enable_auto_map_reduce", True)))
                self.eye_auto_mapreduce_rows_spin.setValue(int(eye_ai.get("auto_map_reduce_row_threshold", 1500)))
                # Reasoning transparency & tuning (v0.11.3).
                self.eye_reasoning_trace_checkbox.setChecked(bool(eye_ai.get("enable_reasoning_trace", True)))
                self.eye_answer_temp_spin.setValue(float(eye_ai.get("answer_temperature", 0.2)))
                self.eye_planning_temp_spin.setValue(float(eye_ai.get("planning_temperature", 0.0)))
                self.eye_rag_topk_spin.setValue(int(eye_ai.get("rag_top_k", 5)))
                self.eye_rag_subq_checkbox.setChecked(bool(eye_ai.get("rag_subquestion_aware", True)))
                self.eye_history_window_spin.setValue(int(eye_ai.get("history_window_turns", 5)))
                self.eye_summary_buffer_checkbox.setChecked(bool(eye_ai.get("enable_summary_buffer", True)))
                self.eye_conversation_recall_checkbox.setChecked(bool(eye_ai.get("enable_conversation_recall", True)))
                self.eye_conversation_recall_topk_spin.setValue(int(eye_ai.get("conversation_recall_top_k", 3)))
                self.eye_embedding_enabled_checkbox.setChecked(bool(eye_ai.get("embedding_enabled", False)))
                self.eye_embedding_model_input.setText(str(eye_ai.get("embedding_model", "nomic-embed-text")))
                self.eye_embedding_endpoint_input.setText(str(eye_ai.get("embedding_endpoint", "http://localhost:11434")))
                self.eye_embedding_index_evidence_checkbox.setChecked(bool(eye_ai.get("embedding_index_evidence", False)))
                backend = eye_ai.get("backend") or "—"
                model = eye_ai.get("model_name") or "—"
                self.eye_backend_label.setText(f"Backend: {backend} / {model}")
            except Exception as e:
                print(f"[Settings] Could not load Eye AI settings: {e}")
    
    def save_settings(self):
        """Save settings and close dialog."""
        try:
            # Update global config
            self.case_history_manager.update_global_config(
                default_case_directory=self.default_dir_input.text(),
                recent_cases_display_count=self.recent_count_spin.value(),
                max_history_size=self.max_history_spin.value(),
                identity_semantic_phase_enabled=self.identity_semantic_phase_checkbox.isChecked(),
                wings_semantic_mapping_enabled=self.wings_semantic_mapping_checkbox.isChecked(),
                cascade_tree_expansion_enabled=self.cascade_expansion_checkbox.isChecked()
            )

            # Persist Eye AI settings to configs/eye_config.json
            if write_eye_ai_settings is not None:
                write_eye_ai_settings({
                    "store_full_payload": self.eye_store_full_payload_checkbox.isChecked(),
                    "sealed_payload_recent_uncompressed": self.eye_recent_uncompressed_spin.value(),
                    "confidence_threshold": self.eye_confidence_spin.value(),
                    "max_total_tokens": self.eye_max_tokens_spin.value(),
                    "lock_max_total_tokens": self.eye_lock_tokens_checkbox.isChecked(),
                    "max_tool_output_chars": self.eye_tool_output_spin.value(),
                    "enable_decomposition": self.eye_enable_decomposition_checkbox.isChecked(),
                    "max_sub_questions": self.eye_max_subq_spin.value(),
                    "enable_hierarchy": self.eye_enable_hierarchy_checkbox.isChecked(),
                    "max_narratives": self.eye_max_narratives_spin.value(),
                    "max_sub_narratives": self.eye_max_sub_narratives_spin.value(),
                    "max_iterations": self.eye_max_iterations_spin.value(),
                    "enable_premise_verification": self.eye_enable_premise_checkbox.isChecked(),
                    "enable_question_memory": self.eye_enable_question_memory_checkbox.isChecked(),
                    "prior_findings_count": self.eye_prior_findings_spin.value(),
                    "model_retry_max_attempts": self.eye_model_retry_spin.value(),
                    "auto_segment_question": self.eye_auto_segment_checkbox.isChecked(),
                    "enable_auto_map_reduce": self.eye_auto_mapreduce_checkbox.isChecked(),
                    "auto_map_reduce_row_threshold": self.eye_auto_mapreduce_rows_spin.value(),
                    "enable_reasoning_trace": self.eye_reasoning_trace_checkbox.isChecked(),
                    "answer_temperature": self.eye_answer_temp_spin.value(),
                    "planning_temperature": self.eye_planning_temp_spin.value(),
                    "rag_top_k": self.eye_rag_topk_spin.value(),
                    "rag_subquestion_aware": self.eye_rag_subq_checkbox.isChecked(),
                    "history_window_turns": self.eye_history_window_spin.value(),
                    "enable_summary_buffer": self.eye_summary_buffer_checkbox.isChecked(),
                    "enable_conversation_recall": self.eye_conversation_recall_checkbox.isChecked(),
                    "conversation_recall_top_k": self.eye_conversation_recall_topk_spin.value(),
                    "embedding_enabled": self.eye_embedding_enabled_checkbox.isChecked(),
                    "embedding_model": self.eye_embedding_model_input.text(),
                    "embedding_endpoint": self.eye_embedding_endpoint_input.text(),
                    "embedding_index_evidence": self.eye_embedding_index_evidence_checkbox.isChecked(),
                })

            # Save semantic mappings if manager is available
            if self.semantic_manager:
                home_dir = Path.home()
                crow_eye_dir = home_dir / ".crow_eye"
                mappings_file = crow_eye_dir / "semantic_mappings.json"
                
                # Create directory if it doesn't exist
                crow_eye_dir.mkdir(exist_ok=True)
                
                # Save mappings to file
                try:
                    self.semantic_manager.save_to_file(mappings_file, scope='global')
                except Exception as e:
                    print(f"Error saving semantic mappings: {e}")
            
            # Create styled success message box
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Settings Saved")
            msg_box.setText("Settings have been saved successfully.")
            msg_box.setIcon(QMessageBox.Information)
            msg_box.setStandardButtons(QMessageBox.Ok)
            msg_box.setStyleSheet(CrowEyeStyles.MESSAGE_BOX_STYLE)
            msg_box.exec_()
            
            self.accept()
            
        except Exception as e:
            # Create styled error message box
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Error")
            msg_box.setText(f"Failed to save settings:\n{str(e)}")
            msg_box.setIcon(QMessageBox.Critical)
            msg_box.setStandardButtons(QMessageBox.Ok)
            msg_box.setStyleSheet(CrowEyeStyles.MESSAGE_BOX_STYLE)
            msg_box.exec_()
    
    def apply_styles(self):
        """Apply cyberpunk styles to the dialog."""
        self.setStyleSheet(CrowEyeStyles.DIALOG_STYLE)
    
    def _format_datetime(self, dt):
        """Format datetime for display."""
        if isinstance(dt, str):
            try:
                dt = datetime.fromisoformat(dt)
            except:
                return dt
        
        if isinstance(dt, datetime):
            return dt.strftime("%Y-%m-%d %H:%M")
        return str(dt)


class SimpleSemanticMappingDialog(QtWidgets.QDialog):
    """Simple dialog for adding/editing semantic mappings (fallback when advanced dialog not available)."""
    
    def __init__(self, parent=None, mapping=None):
        """
        Initialize the dialog.
        
        Args:
            parent: Parent widget
            mapping: Existing SemanticMapping to edit (None for new mapping)
        """
        super().__init__(parent)
        self.mapping = mapping
        self.setup_ui()
        
        if mapping:
            self.load_mapping(mapping)
    
    def setup_ui(self):
        """Set up the dialog UI."""
        self.setWindowTitle("Add Semantic Mapping" if not self.mapping else "Edit Semantic Mapping")
        self.setMinimumWidth(500)
        self.setModal(True)
        
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Form layout
        form_layout = QtWidgets.QFormLayout()
        form_layout.setSpacing(15)
        form_layout.setLabelAlignment(Qt.AlignRight)
        
        label_style = """
            QLabel {
                color: #E2E8F0;
                font-size: 13px;
                font-weight: 600;
                padding-right: 10px;
            }
        """
        
        input_style = CrowEyeStyles.INPUT_FIELD + """
            QLineEdit, QComboBox {
                min-height: 35px;
                font-size: 13px;
                padding: 8px 12px;
            }
        """
        
        # Source
        source_label = QtWidgets.QLabel("Source:")
        source_label.setStyleSheet(label_style)
        self.source_combo = QtWidgets.QComboBox()
        self.source_combo.addItems([
            "SecurityLogs",
            "SystemLogs",
            "ApplicationLogs",
            "Registry",
            "Prefetch",
            "AmCache",
            "ShimCache",
            "SRUM",
            "Other"
        ])
        self.source_combo.setEditable(True)
        self.source_combo.setStyleSheet(input_style)
        form_layout.addRow(source_label, self.source_combo)
        
        # Field
        field_label = QtWidgets.QLabel("Field:")
        field_label.setStyleSheet(label_style)
        self.field_combo = QtWidgets.QComboBox()
        self.field_combo.addItems([
            "EventID",
            "Status",
            "Code",
            "Type",
            "Value"
        ])
        self.field_combo.setEditable(True)
        self.field_combo.setStyleSheet(input_style)
        form_layout.addRow(field_label, self.field_combo)
        
        # Technical Value
        tech_label = QtWidgets.QLabel("Technical Value:")
        tech_label.setStyleSheet(label_style)
        self.tech_value_input = QtWidgets.QLineEdit()
        self.tech_value_input.setPlaceholderText("e.g., 4624")
        self.tech_value_input.setStyleSheet(input_style)
        form_layout.addRow(tech_label, self.tech_value_input)
        
        # Semantic Value
        semantic_label = QtWidgets.QLabel("Semantic Value:")
        semantic_label.setStyleSheet(label_style)
        self.semantic_value_input = QtWidgets.QLineEdit()
        self.semantic_value_input.setPlaceholderText("e.g., User Login")
        self.semantic_value_input.setStyleSheet(input_style)
        form_layout.addRow(semantic_label, self.semantic_value_input)
        
        # Description (optional)
        desc_label = QtWidgets.QLabel("Description:")
        desc_label.setStyleSheet(label_style)
        self.description_input = QtWidgets.QLineEdit()
        self.description_input.setPlaceholderText("Optional description")
        self.description_input.setStyleSheet(input_style)
        form_layout.addRow(desc_label, self.description_input)
        
        layout.addLayout(form_layout)
        
        # Buttons
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.setSpacing(15)
        
        save_btn = QtWidgets.QPushButton("SAVE")
        save_btn.setFixedHeight(40)
        save_btn.setMinimumWidth(120)
        save_btn.clicked.connect(self.accept)
        save_btn.setStyleSheet(CrowEyeStyles.GREEN_BUTTON + """
            QPushButton {
                font-size: 12px;
                font-weight: 700;
                padding: 10px 20px;
            }
        """)
        
        cancel_btn = QtWidgets.QPushButton("CANCEL")
        cancel_btn.setFixedHeight(40)
        cancel_btn.setMinimumWidth(120)
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setStyleSheet(CrowEyeStyles.CLEAR_BUTTON_STYLE + """
            QPushButton {
                font-size: 12px;
                font-weight: 700;
                padding: 10px 20px;
            }
        """)
        
        button_layout.addStretch()
        button_layout.addWidget(save_btn)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout)
        
        # Apply dialog style
        self.setStyleSheet(CrowEyeStyles.DIALOG_STYLE)
    
    def load_mapping(self, mapping):
        """Load existing mapping into form."""
        self.source_combo.setCurrentText(mapping.source)
        self.field_combo.setCurrentText(mapping.field)
        self.tech_value_input.setText(mapping.technical_value)
        self.semantic_value_input.setText(mapping.semantic_value)
        self.description_input.setText(mapping.description or "")
    
    def get_mapping_data(self):
        """Get mapping data from form."""
        return {
            'source': self.source_combo.currentText(),
            'field': self.field_combo.currentText(),
            'technical_value': self.tech_value_input.text(),
            'semantic_value': self.semantic_value_input.text(),
            'description': self.description_input.text()
        }


def show_settings_dialog(case_history_manager, current_case_path=None, parent=None,
                         clone_case_callback=None):
    """
    Show the settings dialog.

    Args:
        case_history_manager: CaseHistoryManager instance
        current_case_path: Path to currently active case (optional)
        parent: Parent widget
        clone_case_callback: Optional callable run after the dialog closes when the
            user chose "Import Case Data from Another Case…" in the Case Management panel.

    Returns:
        True if settings were saved, False if cancelled
    """
    dialog = SettingsDialog(case_history_manager, current_case_path, parent,
                            clone_case_callback=clone_case_callback)
    result = dialog.exec_()
    # Run the clone flow AFTER Settings has closed so its file pickers / loading
    # dialog don't stack on top of a modal.
    if getattr(dialog, '_clone_requested', False) and clone_case_callback:
        try:
            clone_case_callback()
        except Exception as e:
            print(f"[Settings] Clone-case callback failed: {e}")
        return False
    return result == QtWidgets.QDialog.Accepted


if __name__ == "__main__":
    # Test the dialog
    from config import CaseHistoryManager
    
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    
    # Create test case history manager
    manager = CaseHistoryManager()
    
    result = show_settings_dialog(manager)
    print(f"Settings saved: {result}")
    
    sys.exit(0)
