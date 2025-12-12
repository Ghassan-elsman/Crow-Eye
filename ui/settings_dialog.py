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
from datetime import datetime

# Import styles
from styles import CrowEyeStyles


class SettingsDialog(QtWidgets.QDialog):
    """Centralized settings dialog for Crow Eye."""
    
    def __init__(self, case_history_manager, current_case_path=None, parent=None):
        """Initialize the settings dialog.
        
        Args:
            case_history_manager: CaseHistoryManager instance
            current_case_path: Path to currently active case (optional)
            parent: Parent widget
        """
        super().__init__(parent)
        
        self.case_history_manager = case_history_manager
        self.current_case_path = current_case_path
        self.current_case = None
        
        if current_case_path:
            self.current_case = case_history_manager.get_case_by_path(current_case_path)
        
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
        
        self.content_stack.addWidget(self.general_panel)
        self.content_stack.addWidget(self.case_mgmt_panel)
        self.content_stack.addWidget(self.case_settings_panel)
        
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
                text-transform: uppercase;
                letter-spacing: 2px;
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
        
        # Disable case settings if no active case
        if not self.current_case:
            case_settings_btn.setEnabled(False)
            case_settings_btn.setToolTip("No active case")
        
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
                text-transform: uppercase;
                letter-spacing: 1px;
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
                text-transform: uppercase;
                letter-spacing: 1px;
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
                text-transform: uppercase;
                letter-spacing: 1px;
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
        
        layout.addStretch()
        
        return panel
    
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
    
    def save_settings(self):
        """Save settings and close dialog."""
        try:
            # Update global config
            self.case_history_manager.update_global_config(
                default_case_directory=self.default_dir_input.text(),
                recent_cases_display_count=self.recent_count_spin.value(),
                max_history_size=self.max_history_spin.value()
            )
            
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


def show_settings_dialog(case_history_manager, current_case_path=None, parent=None):
    """
    Show the settings dialog.
    
    Args:
        case_history_manager: CaseHistoryManager instance
        current_case_path: Path to currently active case (optional)
        parent: Parent widget
        
    Returns:
        True if settings were saved, False if cancelled
    """
    dialog = SettingsDialog(case_history_manager, current_case_path, parent)
    result = dialog.exec_()
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
