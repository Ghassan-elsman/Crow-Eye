from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt, pyqtSignal
from datetime import datetime
import sys
import os
import json

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from styles import CrowEyeStyles

class SearchFilterDialog(QtWidgets.QDialog):
    # Signal to emit when filter is applied
    filterApplied = pyqtSignal(list, str, str)
    
    def __init__(self, parent=None, saved_tables=None, saved_start_time=None, saved_end_time=None):
        super(SearchFilterDialog, self).__init__(parent)
        self.setWindowTitle("Search Filter")
        self.setMinimumWidth(550)
        self.setMinimumHeight(600)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        
        # Enhanced cyberpunk style for the dialog
        self.setStyleSheet(CrowEyeStyles.DIALOG_STYLE + """
            QDialog, QWidget {
                background-color: #1a1a2e;
            }
            QDialog {
                border: 1px solid #00FFFF;
                border-radius: 5px;
            }
            QGroupBox {
                background-color: #1a1a2e;
                border: 1px solid #334155;
                border-radius: 5px;
                margin-top: 10px;
                font-weight: bold;
                color: #00FFFF;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 5px;
                color: #00FFFF;
            }
            QLabel {
                color: #e0e0e0;
            }
            QCheckBox {
                color: #e0e0e0;
            }
        """)
        
        # Store saved filter settings
        self.saved_tables = saved_tables
        self.saved_start_time = saved_start_time
        self.saved_end_time = saved_end_time
        
        # Main layout
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(20, 20, 20, 20)
        self.main_layout.setSpacing(15)
        
        # Create table selection group
        self.create_table_selection_group()
        
        # Create time range selection group
        self.create_time_range_group()
        
        # Create buttons
        self.create_buttons()
        
        # Set the layout
        self.setLayout(self.main_layout)
        
        # Load saved filter settings if available
        self.load_saved_filter()
    
    def create_table_selection_group(self):
        # Group box for table selection
        self.table_group = QtWidgets.QGroupBox("Select Tables to Search")
        self.table_group.setStyleSheet(CrowEyeStyles.GROUP_BOX + """
            QGroupBox {
                background-color: #1a1a2e;
                border: 1px solid #00FFFF;
                border-radius: 8px;
                margin-top: 15px;
                padding: 5px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                color: #00FFFF;
                font-weight: bold;
                font-size: 14px;
                padding: 0 10px;
            }
            QLabel {
                color: #e0e0e0;
            }
            QCheckBox {
                color: #e0e0e0;
            }
        """)
        self.table_layout = QtWidgets.QVBoxLayout()
        
        # Add "Select All" checkbox
        self.select_all_checkbox = QtWidgets.QCheckBox("Select All")
        self.select_all_checkbox.setStyleSheet(CrowEyeStyles.CHECKBOX_STYLE)
        self.select_all_checkbox.stateChanged.connect(self.toggle_all_tables)
        self.table_layout.addWidget(self.select_all_checkbox)
        
        # Add a scroll area for tables
        self.scroll_area = QtWidgets.QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QtWidgets.QFrame.NoFrame)
        
        # Cyberpunk scrollbar style
        scrollbar_style = """
            QScrollBar:vertical {
                background: #1a1a2e;
                width: 12px;
                border: none;
            }
            QScrollBar::handle:vertical {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00BFFF, stop:1 #0080FF);
                min-height: 20px;
                border-radius: 6px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
                background: none;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
            QScrollBar:horizontal {
                background: #1a1a2e;
                height: 12px;
                border: none;
            }
            QScrollBar::handle:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #00BFFF, stop:1 #0080FF);
                min-width: 20px;
                border-radius: 6px;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
                background: none;
            }
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                background: none;
            }
        """
        # Apply scrollbar style and background color
        self.scroll_area.setStyleSheet(scrollbar_style)
        self.scroll_area.setFrameShape(QtWidgets.QFrame.NoFrame)
        palette = self.scroll_area.palette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor("#1a1a2e"))
        self.scroll_area.setPalette(palette)
        self.scroll_area.setAutoFillBackground(True)
        
        # Container widget for checkboxes
        self.table_container = QtWidgets.QWidget()
        self.table_container.setStyleSheet("background-color: #1a1a2e;")
        self.table_container_layout = QtWidgets.QVBoxLayout(self.table_container)
        
        # Add checkboxes for common tables
        self.table_checkboxes = {}
        
        # Create category labels and tables
        # Execution Evidence
        self.execution_label = QtWidgets.QLabel("Execution Evidence")
        self.execution_label.setStyleSheet("QLabel { color: #00FFFF; font-weight: bold; font-size: 14px; padding: 5px; border-bottom: 1px solid #334155; margin-top: 10px; }")
        self.table_container_layout.addWidget(self.execution_label)
        
        self.execution_tables = [
            ("Prefetch", "Prefetch_table"),
            ("Amcache - File Entries", "Amcache_table"),
            ("Amcache - Programs", "Amcache_Programs_table"),
            ("Amcache - Shortcuts", "Amcache_Shortcuts_table"),
            ("Amcache - DLL", "Amcache_DLL_table"),
            ("Amcache - Application", "Amcache_InventoryApplication_table"),
            ("Amcache - Application File", "Amcache_InventoryApplicationFile_table"),
            ("Amcache - Application Shortcut", "Amcache_InventoryApplicationShortcut_table"),
            ("Amcache - Driver Binary", "Amcache_InventoryDriverBinary_table"),
            ("Amcache - Driver Package", "Amcache_InventoryDriverPackage_table"),
            ("ShimCache", "ShimCache_main_table"),
            ("LNK Files", "LNK_table"),
            ("Automatic Jump Lists", "AJL_table"),
            ("Custom Jump Lists", "Clj_table"),
            ("BAM", "Bam_table"),
            ("DAM", "Dam_table"),
            ("System Logs", "SystemLogs_table"),
            ("Application Logs", "ApplicationLogs_table"),
            ("Security Logs", "SecurityLogs_table")
        ]
        
        # Registry Evidence
        self.registry_label = QtWidgets.QLabel("Registry Evidence")
        self.registry_label.setStyleSheet("QLabel { color: #00FFFF; font-weight: bold; font-size: 14px; padding: 5px; border-bottom: 1px solid #334155; margin-top: 10px; }")
        self.table_container_layout.addWidget(self.registry_label)
        
        self.registry_tables = [
            ("User Run", "UserRun_table"),
            ("Machine Run", "MachineRun_table"),
            ("Machine RunOnce", "MachineRunOnce_table"),
            ("Open/Save MRU", "OpenSaveMRU_table"),
            ("Last Save MRU", "LastSaveMRU_table"),
            ("Typed Paths", "TypedPath_table"),
            ("Recent Docs", "RecentDocs_table"),
            ("Search Via Explorer", "SearchViaExplorer_table"),
            ("Computer Name", "computerName_table"),
            ("Last Update Info", "LastUpdateInfo_table"),
            ("Shutdown", "ShutDown_table")
        ]
        
        # System Information
        self.system_label = QtWidgets.QLabel("System Information")
        self.system_label.setStyleSheet("QLabel { color: #00FFFF; font-weight: bold; font-size: 14px; padding: 5px; border-bottom: 1px solid #334155; margin-top: 10px; }")
        self.table_container_layout.addWidget(self.system_label)
        
        self.system_tables = [
            ("Network Interfaces", "NetworkInterface_table"),
            ("Network Lists", "NetworkLists_table"),
            ("Time Zone", "TimeZone_table"),
            ("System Services", "tableWidget_2"),
            ("Installed Software", "tableWidget"),
            ("Browser History", "Browser_history_table"),
            ("USB Devices", "USBDevices_table"),
            ("USB Properties", "USBProperties_table"),
            ("USB Instances", "USBInstances_table"),
            ("USB Devices", "USBStorageDevices_table"),
            ("USB Volume", "USBStorageVolumes_table")
        ]
        
        # Combine all tables for the select all functionality
        self.main_tables = self.execution_tables + self.registry_tables + self.system_tables
        
        # Create a layout for each category to organize checkboxes
        self.execution_layout = QtWidgets.QVBoxLayout()
        self.execution_layout.setContentsMargins(10, 0, 10, 10)
        self.execution_layout.setSpacing(5)
        
        self.registry_layout = QtWidgets.QVBoxLayout()
        self.registry_layout.setContentsMargins(10, 0, 10, 10)
        self.registry_layout.setSpacing(5)
        
        self.system_layout = QtWidgets.QVBoxLayout()
        self.system_layout.setContentsMargins(10, 0, 10, 10)
        self.system_layout.setSpacing(5)
        
        # Add checkboxes for Execution Evidence category
        for display_name, table_name in self.execution_tables:
            checkbox = QtWidgets.QCheckBox(display_name)
            checkbox.setStyleSheet(CrowEyeStyles.CHECKBOX_STYLE)
            checkbox.setChecked(True)  # Default to checked
            self.table_checkboxes[table_name] = checkbox
            self.execution_layout.addWidget(checkbox)
        
        # Add checkboxes for Registry Evidence category
        for display_name, table_name in self.registry_tables:
            checkbox = QtWidgets.QCheckBox(display_name)
            checkbox.setStyleSheet(CrowEyeStyles.CHECKBOX_STYLE)
            checkbox.setChecked(True)  # Default to checked
            self.table_checkboxes[table_name] = checkbox
            self.registry_layout.addWidget(checkbox)
        
        # Add checkboxes for System Information category
        for display_name, table_name in self.system_tables:
            checkbox = QtWidgets.QCheckBox(display_name)
            checkbox.setStyleSheet(CrowEyeStyles.CHECKBOX_STYLE)
            checkbox.setChecked(True)  # Default to checked
            self.table_checkboxes[table_name] = checkbox
            self.system_layout.addWidget(checkbox)
        
        # Add each category layout to the main container layout
        self.table_container_layout.addWidget(self.execution_label)
        self.table_container_layout.addLayout(self.execution_layout)
        
        self.table_container_layout.addWidget(self.registry_label)
        self.table_container_layout.addLayout(self.registry_layout)
        
        self.table_container_layout.addWidget(self.system_label)
        self.table_container_layout.addLayout(self.system_layout)
        
        # Add a spacer at the end
        self.table_container_layout.addStretch()
        
        # Set the container as the scroll area widget
        self.scroll_area.setWidget(self.table_container)
        self.table_layout.addWidget(self.scroll_area)
        
        # Set the layout to the group box
        self.table_group.setLayout(self.table_layout)
        
        # Add the group box to the main layout
        self.main_layout.addWidget(self.table_group)
    
    def create_time_range_group(self):
        # Group box for time range selection
        self.time_group = QtWidgets.QGroupBox("Time Range Filter")
        self.time_group.setStyleSheet(CrowEyeStyles.GROUP_BOX + """
            QGroupBox {
                background-color: #1a1a2e;
                border: 1px solid #00FFFF;
                border-radius: 8px;
                margin-top: 15px;
                padding: 5px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                color: #00FFFF;
                font-weight: bold;
                font-size: 14px;
                padding: 0 10px;
            }
            QLabel {
                color: #e0e0e0;
            }
            QCheckBox {
                color: #e0e0e0;
            }
        """)
        self.time_layout = QtWidgets.QVBoxLayout()
        
        # Enable time filtering checkbox
        self.enable_time_checkbox = QtWidgets.QCheckBox("Enable Time Filtering")
        self.enable_time_checkbox.setStyleSheet(CrowEyeStyles.CHECKBOX_STYLE)
        self.enable_time_checkbox.stateChanged.connect(self.toggle_time_widgets)
        self.time_layout.addWidget(self.enable_time_checkbox)
        
        # Start time widgets
        self.start_time_layout = QtWidgets.QHBoxLayout()
        self.start_time_label = QtWidgets.QLabel("Start Time:")
        self.start_time_label.setStyleSheet(CrowEyeStyles.LABEL_STYLE)
        self.start_time_edit = QtWidgets.QDateTimeEdit()
        self.start_time_edit.setStyleSheet(CrowEyeStyles.DATE_TIME_EDIT)
        self.start_time_edit.setCalendarPopup(True)
        self.start_time_edit.setDateTime(QtCore.QDateTime.currentDateTime().addDays(-30))  # Default to 30 days ago
        self.start_time_edit.setEnabled(False)  # Disabled by default
        
        self.start_time_layout.addWidget(self.start_time_label)
        self.start_time_layout.addWidget(self.start_time_edit)
        self.time_layout.addLayout(self.start_time_layout)
        
        # End time widgets
        self.end_time_layout = QtWidgets.QHBoxLayout()
        self.end_time_label = QtWidgets.QLabel("End Time:")
        self.end_time_label.setStyleSheet(CrowEyeStyles.LABEL_STYLE)
        self.end_time_edit = QtWidgets.QDateTimeEdit()
        self.end_time_edit.setStyleSheet(CrowEyeStyles.DATE_TIME_EDIT)
        self.end_time_edit.setCalendarPopup(True)
        self.end_time_edit.setDateTime(QtCore.QDateTime.currentDateTime())  # Default to now
        self.end_time_edit.setEnabled(False)  # Disabled by default
        
        self.end_time_layout.addWidget(self.end_time_label)
        self.end_time_layout.addWidget(self.end_time_edit)
        self.time_layout.addLayout(self.end_time_layout)
        
        # Set the layout to the group box
        self.time_group.setLayout(self.time_layout)
        
        # Add the group box to the main layout
        self.main_layout.addWidget(self.time_group)
    
    def create_buttons(self):
        # Button layout
        self.button_layout = QtWidgets.QHBoxLayout()
        
        # Apply button with enhanced cyberpunk style
        self.apply_button = QtWidgets.QPushButton("Apply")
        self.apply_button.setStyleSheet(CrowEyeStyles.PRIMARY_BUTTON + """
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00FFFF, stop:1 #0080FF);
                color: #000000;
                font-weight: bold;
                border: none;
                border-radius: 5px;
                padding: 8px 16px;
                min-width: 100px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00FFFF, stop:1 #00BFFF);
                border: 1px solid #00FFFF;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0080FF, stop:1 #00FFFF);
            }
        """)
        self.apply_button.clicked.connect(self.apply_filter)
        
        # Cancel button with enhanced cyberpunk style
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.cancel_button.setStyleSheet(CrowEyeStyles.SECONDARY_BUTTON + """
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF0080, stop:1 #FF00FF);
                color: #000000;
                font-weight: bold;
                border: none;
                border-radius: 5px;
                padding: 8px 16px;
                min-width: 100px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF0080, stop:1 #FF40FF);
                border: 1px solid #FF00FF;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF00FF, stop:1 #FF0080);
            }
        """)
        self.cancel_button.clicked.connect(self.reject)
        
        # Add buttons to layout
        self.button_layout.addStretch()
        self.button_layout.addWidget(self.apply_button)
        self.button_layout.addWidget(self.cancel_button)
        
        # Add button layout to main layout
        self.main_layout.addLayout(self.button_layout)
    
    def toggle_all_tables(self, state):
        # Toggle all table checkboxes based on the Select All checkbox
        for checkbox in self.table_checkboxes.values():
            checkbox.setChecked(state == Qt.Checked)
    
    def toggle_time_widgets(self, state):
        # Enable/disable time widgets based on the checkbox state
        enabled = state == Qt.Checked
        self.start_time_edit.setEnabled(enabled)
        self.end_time_edit.setEnabled(enabled)
    
    def apply_filter(self):
        # Get selected tables
        selected_tables = [table_name for table_name, checkbox in self.table_checkboxes.items() 
                          if checkbox.isChecked()]
        
        # Get time range if enabled
        start_time = ""
        end_time = ""
        if self.enable_time_checkbox.isChecked():
            # Use Qt's ISODate format which is compatible with Python's datetime parsing
            start_time = self.start_time_edit.dateTime().toString(Qt.ISODate)
            end_time = self.end_time_edit.dateTime().toString(Qt.ISODate)
        
        # Save the filter settings
        self.save_filter_settings(selected_tables, start_time, end_time)
        
        # Emit signal with selected tables and time range
        self.filterApplied.emit(selected_tables, start_time, end_time)
        
        # Close the dialog
        self.accept()
    
    def save_filter_settings(self, selected_tables, start_time, end_time):
        """Save the filter settings to a JSON file"""
        try:
            filter_settings = {
                "selected_tables": selected_tables,
                "start_time": start_time,
                "end_time": end_time,
                "time_filter_enabled": self.enable_time_checkbox.isChecked()
            }
            
            # Create the config directory if it doesn't exist
            config_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config")
            os.makedirs(config_dir, exist_ok=True)
            
            # Save the settings to a JSON file
            with open(os.path.join(config_dir, "search_filter_settings.json"), "w") as f:
                json.dump(filter_settings, f)
        except Exception as e:
            print(f"ERROR saving filter settings: {str(e)}")
    
    def load_saved_filter(self):
        """Load saved filter settings if available"""
        try:
            # If we have settings passed directly to the constructor, use those
            if self.saved_tables is not None:
                # Set the checkboxes based on saved tables
                for table_name, checkbox in self.table_checkboxes.items():
                    checkbox.setChecked(table_name in self.saved_tables)
                
                # Set time filter if available
                if self.saved_start_time and self.saved_end_time:
                    self.enable_time_checkbox.setChecked(True)
                    self.start_time_edit.setDateTime(QtCore.QDateTime.fromString(self.saved_start_time, Qt.ISODate))
                    self.end_time_edit.setDateTime(QtCore.QDateTime.fromString(self.saved_end_time, Qt.ISODate))
                    self.toggle_time_widgets(Qt.Checked)
                return
            
            # Otherwise try to load from file
            config_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                                      "config", "search_filter_settings.json")
            
            if os.path.exists(config_file):
                with open(config_file, "r") as f:
                    settings = json.load(f)
                
                # Set the checkboxes based on saved tables
                saved_tables = settings.get("selected_tables", [])
                for table_name, checkbox in self.table_checkboxes.items():
                    checkbox.setChecked(table_name in saved_tables)
                
                # Set time filter if enabled
                if settings.get("time_filter_enabled", False):
                    self.enable_time_checkbox.setChecked(True)
                    
                    # Set start time if available
                    start_time = settings.get("start_time", "")
                    if start_time:
                        self.start_time_edit.setDateTime(QtCore.QDateTime.fromString(start_time, Qt.ISODate))
                    
                    # Set end time if available
                    end_time = settings.get("end_time", "")
                    if end_time:
                        self.end_time_edit.setDateTime(QtCore.QDateTime.fromString(end_time, Qt.ISODate))
                    
                    # Enable time widgets
                    self.toggle_time_widgets(Qt.Checked)
        except Exception as e:
            print(f"ERROR loading filter settings: {str(e)}")


if __name__ == "__main__":
    # Test the dialog
    app = QtWidgets.QApplication(sys.argv)
    dialog = SearchFilterDialog()
    if dialog.exec_() == QtWidgets.QDialog.Accepted:
        print("Dialog accepted")
    else:
        print("Dialog rejected")