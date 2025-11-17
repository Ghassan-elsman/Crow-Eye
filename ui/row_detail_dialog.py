from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import Qt
import sys
import os
from styles import CrowEyeStyles

class CollapsibleSection(QtWidgets.QWidget):
    """
    A collapsible section widget with an arrow indicator that can be expanded/collapsed.
    """
    def __init__(self, title, parent=None):
        super(CollapsibleSection, self).__init__(parent)
        
        # Set up the UI
        self.title = title
        self.content_widget = None
        self.is_expanded = True
        
        # Create layout
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        # Create header widget
        self.header_widget = QtWidgets.QWidget()
        self.header_widget.setCursor(Qt.PointingHandCursor)
        self.header_widget.setStyleSheet("""
            background-color: #1a1a2e;
            border-radius: 4px;
            border-left: 2px solid #00BFFF;
        """)
        
        # Create header layout
        self.header_layout = QtWidgets.QHBoxLayout(self.header_widget)
        self.header_layout.setContentsMargins(10, 8, 10, 8)
        
        # Create arrow indicator
        self.arrow_label = QtWidgets.QLabel("▼")  # Down arrow for expanded
        self.arrow_label.setStyleSheet("""
            color: #00FF7F;
            font-size: 14px;
            font-weight: bold;
        """)
        self.header_layout.addWidget(self.arrow_label)
        
        # Create title label
        self.title_label = QtWidgets.QLabel(title)
        self.title_label.setStyleSheet("""
            color: #00FF7F;
            font-size: 14px;
            font-weight: bold;
        """)
        self.header_layout.addWidget(self.title_label)
        
        # Add spacer to push title to left
        self.header_layout.addStretch()
        
        # Add header to main layout
        self.main_layout.addWidget(self.header_widget)
        
        # Create content area (initially empty)
        self.content_area = QtWidgets.QWidget()
        self.content_area.setStyleSheet("""
            background-color: #121212;
            border-left: 2px solid #334155;
            margin-left: 10px;
        """)
        self.content_layout = QtWidgets.QVBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        
        # Add content area to main layout
        self.main_layout.addWidget(self.content_area)
        
        # Connect header click event
        self.header_widget.mousePressEvent = self.toggle_expanded
    
    def setContentWidget(self, widget):
        """Set the content widget for this section."""
        # Clear existing content
        if self.content_layout.count() > 0:
            # Remove existing widget
            existing_widget = self.content_layout.itemAt(0).widget()
            if existing_widget:
                existing_widget.setParent(None)
        
        # Add new widget
        self.content_widget = widget
        self.content_layout.addWidget(widget)
    
    def toggle_expanded(self, event):
        """Toggle the expanded state of the section."""
        self.is_expanded = not self.is_expanded
        
        # Update arrow indicator
        self.arrow_label.setText("▼" if self.is_expanded else "▶")
        
        # Show/hide content
        self.content_area.setVisible(self.is_expanded)
        
        # Emit layout changed signal to parent
        self.updateGeometry()

class RowDetailDialog(QtWidgets.QDialog):
    """
    Dialog to display detailed information from a table row.
    Allows multiple instances to be opened for comparison.
    """
    
    # Keep track of open dialogs to manage positioning
    open_dialogs = []
    
    def __init__(self, data, title, parent=None):
        """
        Initialize the dialog with row data
        
        Args:
            data (dict): Dictionary of row data (header: value)
            title (str): Dialog title
            parent: Parent widget
        """
        super(RowDetailDialog, self).__init__(parent)
        
        # Store the dialog in the class-level list
        RowDetailDialog.open_dialogs.append(self)
        
        # Store data and title
        self.row_data = data
        self.table_name = title
        
        # Track if dialog is maximized
        self.is_maximized = False
        
        # Set up the UI
        self._setup_ui()
        
        # Position the dialog based on how many are already open
        self._position_dialog()
        
        # Populate the grid with row data
        if data:
            self._populate_grid(data)

    def _setup_ui(self):
        """Set up the dialog UI components."""
        # Set dialog properties
        self.setWindowTitle(f"Row Details - {self.table_name}")
        self.setMinimumSize(700, 500)
        # Set window flags to allow maximize button in the title bar
        self.setWindowFlags(Qt.Dialog | Qt.WindowMaximizeButtonHint | Qt.WindowCloseButtonHint)
        
        # Create main layout
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Create title bar
        title_bar = QtWidgets.QWidget()
        title_bar.setObjectName("titleBar")
        title_bar.setStyleSheet("""
            #titleBar {
                background-color: #1a1a2e;
                border-bottom: 1px solid #334155;
                padding: 5px 0;
            }
        """)
        title_bar_layout = QtWidgets.QHBoxLayout(title_bar)
        title_bar_layout.setContentsMargins(15, 12, 15, 12)
        
        # Add title label
        title_label = QtWidgets.QLabel("Forensic Data Analysis")
        title_label.setStyleSheet("""
            color: #00FF7F;
            font-size: 18px;
            font-weight: bold;
            letter-spacing: 1px;
            background-color: #1a1a2e;
            border-left: 3px solid #00BFFF;
            padding-left: 10px;
            border-radius: 2px;
        """)
        title_bar_layout.addWidget(title_label)
        
        # Add title bar to main layout
        main_layout.addWidget(title_bar)
        
        # Create content widget with scroll area
        scroll_area = QtWidgets.QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: #121212;
                border: none;
            }
            
            /* Vertical scrollbar styling */
            QScrollBar:vertical {
                background-color: #121212;
                width: 14px;
                margin: 0px;
                border-radius: 7px;
            }
            QScrollBar::handle:vertical {
                background-color: #334155;
                min-height: 30px;
                border-radius: 7px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #00BFFF;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background-color: #1a1a2e;
                border-radius: 7px;
            }
            
            /* Horizontal scrollbar styling */
            QScrollBar:horizontal {
                background-color: #121212;
                height: 14px;
                margin: 0px;
                border-radius: 7px;
            }
            QScrollBar::handle:horizontal {
                background-color: #334155;
                min-width: 30px;
                border-radius: 7px;
            }
            QScrollBar::handle:horizontal:hover {
                background-color: #00BFFF;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
            }
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                background-color: #1a1a2e;
                border-radius: 7px;
            }
        """)
        
        self.content_widget = QtWidgets.QWidget()
        self.content_widget.setStyleSheet("""
            background-color: #121212;
            
            QLabel[class="field-name"] {
                color: #00BFFF;
                font-weight: bold;
                padding-right: 10px;
                font-size: 12px;
            }
            
            QLabel[class="field-value"] {
                color: #00FF7F;
                background-color: #1a1a2e;
                border-radius: 4px;
                padding: 8px 10px;
                border-left: 2px solid #00BFFF;
                font-size: 12px;
                font-weight: bold;
                line-height: 1.4;
            }
        """)
        
        self.content_layout = QtWidgets.QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(20, 20, 20, 20)
        self.content_layout.setSpacing(15)
        
        # Add content widget to scroll area
        scroll_area.setWidget(self.content_widget)
        main_layout.addWidget(scroll_area)
        
        # Create button bar
        button_bar = QtWidgets.QWidget()
        button_bar.setStyleSheet("""
            background-color: #1a1a2e;
            border-top: 1px solid #334155;
        """)
        button_layout = QtWidgets.QHBoxLayout(button_bar)
        button_layout.setContentsMargins(15, 10, 15, 10)
        
        # Add copy button
        copy_button = QtWidgets.QPushButton("Copy to Clipboard")
        copy_button.setStyleSheet(CrowEyeStyles.BUTTON_STYLE)
        copy_button.clicked.connect(self._copy_to_clipboard)
        button_layout.addWidget(copy_button)
        
        # Add export button
        export_button = QtWidgets.QPushButton("Export")
        export_button.setStyleSheet(CrowEyeStyles.BUTTON_STYLE)
        export_button.clicked.connect(self._export_data)
        button_layout.addWidget(export_button)
        
        # Add spacer
        button_layout.addStretch()
        
        # Add close button
        close_button = QtWidgets.QPushButton("Close")
        close_button.setStyleSheet(CrowEyeStyles.BUTTON_STYLE)
        close_button.clicked.connect(self.close)
        button_layout.addWidget(close_button)
        
        # Add button bar to main layout
        main_layout.addWidget(button_bar)

    def _toggle_maximize(self):
        """Toggle between maximized and normal window state"""
        if self.is_maximized:
            # Restore to normal size
            self.showNormal()
            self.maximize_button.setText("□")
            self.is_maximized = False
        else:
            # Maximize
            self.showMaximized()
            self.maximize_button.setText("❐")
            self.is_maximized = True

    def _populate_grid(self, row_data):
        """Populate the grid layout with row data grouped by categories."""
        # Define categories with their display names and fields
        categories = {
            "File Info": [
                "Filename", "Executable Name", "Hash"
            ],
            "Timestamps": [
                "Run Count", "Last Executed", "Run Times"
            ],
            "Attributes": [
                "apptype", "artifact", "data_flags", "volume_label", "entry_number", 
                "network_device_name", "network_share_flags", "network_share_name", 
                "network_share_name_uni", "file_permissions", "num_hard_links", "inode_number", "owner_uid"
            ]
        }
        
        # Track processed fields to avoid duplicates
        processed_fields = set()
        
        # Create a vertical layout to hold category groups
        for category_name, fields in categories.items():
            category_fields = []
            
            # Gather fields for this category if they exist in row_data
            for field in fields:
                if field in row_data and row_data[field] and str(row_data[field]).strip():
                    category_fields.append(field)
            
            # Skip empty categories
            if not category_fields:
                continue
                
            # Create collapsible section
            collapsible_section = self._create_collapsible_section(category_name)
            self.content_layout.addWidget(collapsible_section)
            
            # Create content widget for this section
            section_content = QtWidgets.QWidget()
            section_content_layout = QtWidgets.QVBoxLayout(section_content)
            section_content_layout.setContentsMargins(10, 5, 10, 5)
            section_content_layout.setSpacing(8)
            
            # Create a grid for this category
            category_grid = QtWidgets.QGridLayout()
            category_grid.setColumnStretch(1, 1)
            category_grid.setHorizontalSpacing(15)
            category_grid.setVerticalSpacing(8)
            
            # Add fields for this category
            category_row = 0
            for field in category_fields:
                if field in row_data and row_data[field] and str(row_data[field]).strip():
                    # Create label for field name
                    name_label = QtWidgets.QLabel(field)
                    name_label.setProperty("class", "field-name")
                    name_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    # Explicit style for reliability
                    name_label.setStyleSheet("color: #00BFFF; font-weight: bold; padding-right: 10px; font-size: 12px;")
                    
                    # Create label for value
                    value_text = str(row_data[field])
                    
                    # Handle multiline for volumes if needed
                    if "Volumes" in field and "|" in value_text:
                        value_text = value_text.replace("|", "\n")
                    
                    value_label = QtWidgets.QLabel(value_text)
                    value_label.setProperty("class", "field-value")
                    value_label.setMinimumWidth(300)
                    value_label.setWordWrap(True)
                    value_label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
                    # Explicit style for reliability
                    value_label.setStyleSheet(
                        "color: #00FF7F; background-color: #1a1a2e; border-radius: 4px; padding: 8px 10px; "
                        "border-left: 2px solid #00BFFF; font-size: 12px; font-weight: bold; line-height: 1.4;"
                    )
                    value_label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
                    
                    # Add to category grid
                    category_grid.addWidget(name_label, category_row, 0)
                    category_grid.addWidget(value_label, category_row, 1)
                    # Mark as processed
                    processed_fields.add(field)
                    category_row += 1
            
            # Add the category grid to the section content
            section_content_layout.addLayout(category_grid)
            
            # Add the section content to the collapsible section
            collapsible_section.setContentWidget(section_content)
        
        # Special handling for Directories, Files, and Resources
        special_sections = []
        
        # Directories and Files
        has_dir_files = False
        dir_files_widget = QtWidgets.QWidget()
        dir_files_layout = QtWidgets.QHBoxLayout(dir_files_widget)
        dir_files_layout.setContentsMargins(10, 5, 10, 5)
        dir_files_layout.setSpacing(20)
        
        # Directories column
        if "Directories" in row_data and row_data["Directories"] and str(row_data["Directories"]).strip():
            dirs = row_data["Directories"].split("|")
            # Filter out empty directory entries
            dirs = [d.strip() for d in dirs if d.strip()]
            if dirs:
                has_dir_files = True
                dir_vbox = QtWidgets.QVBoxLayout()
                dir_header = QtWidgets.QLabel("Directories")
                dir_header.setProperty("class", "category-header")
                dir_header.setStyleSheet("color: #00FF7F; font-weight: bold; font-size: 14px; padding: 8px; border-bottom: 1px solid #00FF7F; margin-top: 10px; margin-bottom: 5px; background-color: #1a1a2e; border-radius: 4px;")
                dir_vbox.addWidget(dir_header)
                
                for d in dirs:
                    d_label = QtWidgets.QLabel(d)
                    d_label.setProperty("class", "field-value")
                    d_label.setWordWrap(True)
                    d_label.setStyleSheet("color: #00FF7F; background-color: #1a1a2e; border-radius: 4px; padding: 8px 10px; border-left: 2px solid #00BFFF; font-size: 12px; font-weight: bold; line-height: 1.4;")
                    d_label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
                    dir_vbox.addWidget(d_label)
                
                dir_files_layout.addLayout(dir_vbox)
                processed_fields.add("Directories")
        
        # Files column
        if "Files" in row_data and row_data["Files"] and str(row_data["Files"]).strip():
            files = row_data["Files"].split("|")
            # Filter out empty file entries
            files = [f.strip() for f in files if f.strip()]
            if files:
                has_dir_files = True
                file_vbox = QtWidgets.QVBoxLayout()
                file_header = QtWidgets.QLabel("Files")
                file_header.setProperty("class", "category-header")
                file_header.setStyleSheet("color: #00FF7F; font-weight: bold; font-size: 14px; padding: 8px; border-bottom: 1px solid #00FF7F; margin-top: 10px; margin-bottom: 5px; background-color: #1a1a2e; border-radius: 4px;")
                file_vbox.addWidget(file_header)
                
                for f in files:
                    f_label = QtWidgets.QLabel(f)
                    f_label.setProperty("class", "field-value")
                    f_label.setWordWrap(True)
                    f_label.setStyleSheet("color: #00FF7F; background-color: #1a1a2e; border-radius: 4px; padding: 8px 10px; border-left: 2px solid #00BFFF; font-size: 12px; font-weight: bold; line-height: 1.4;")
                    f_label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
                    file_vbox.addWidget(f_label)
                
                dir_files_layout.addLayout(file_vbox)
                processed_fields.add("Files")
        
        # Only add the paths section if we have directories or files
        if has_dir_files:
            paths_section = self._create_collapsible_section("Paths")
            paths_section.setContentWidget(dir_files_widget)
            self.content_layout.addWidget(paths_section)
            special_sections.append("Paths")
        
        # Resources in its own section
        if "Resources" in row_data and row_data["Resources"] and str(row_data["Resources"]).strip():
            resources = row_data["Resources"].split("|")
            # Filter out empty resource entries
            resources = [r.strip() for r in resources if r.strip()]
            if resources:
                resources_widget = QtWidgets.QWidget()
                res_vbox = QtWidgets.QVBoxLayout(resources_widget)
                res_vbox.setContentsMargins(10, 5, 10, 5)
                
                for r in resources:
                    r_label = QtWidgets.QLabel(r)
                    r_label.setProperty("class", "field-value")
                    r_label.setWordWrap(True)
                    r_label.setStyleSheet("color: #00FF7F; background-color: #1a1a2e; border-radius: 4px; padding: 8px 10px; border-left: 2px solid #00BFFF; font-size: 12px; font-weight: bold; line-height: 1.4;")
                    r_label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
                    res_vbox.addWidget(r_label)
                
                resources_section = self._create_collapsible_section("Resources")
                resources_section.setContentWidget(resources_widget)
                self.content_layout.addWidget(resources_section)
                processed_fields.add("Resources")
                special_sections.append("Resources")
             
        # Add any remaining fields that weren't categorized
        remaining_fields = [f for f in row_data.keys() if f not in processed_fields and row_data[f] and str(row_data[f]).strip()]
        if remaining_fields:
            other_widget = QtWidgets.QWidget()
            other_layout = QtWidgets.QVBoxLayout(other_widget)
            other_layout.setContentsMargins(10, 5, 10, 5)
            
            # Create a grid for remaining fields
            other_grid = QtWidgets.QGridLayout()
            other_grid.setColumnStretch(1, 1)
            other_grid.setHorizontalSpacing(15)
            other_grid.setVerticalSpacing(8)
            
            # Add remaining fields
            other_row = 0
            for field in remaining_fields:
                # Create label for field name
                name_label = QtWidgets.QLabel(field)
                name_label.setProperty("class", "field-name")
                name_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                name_label.setStyleSheet("color: #00BFFF; font-weight: bold; padding-right: 10px; font-size: 12px;")
                
                # Create label for value
                value_text = str(row_data[field])
                
                # Handle any field with | separator - split them into separate lines
                if "|" in value_text:
                    value_text = value_text.replace("|", "\n")
                
                value_label = QtWidgets.QLabel(value_text)
                value_label.setProperty("class", "field-value")
                value_label.setMinimumWidth(300)
                value_label.setWordWrap(True)
                value_label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
                value_label.setStyleSheet(
                    "color: #00FF7F; background-color: #1a1a2e; border-radius: 4px; padding: 8px 10px; "
                    "border-left: 2px solid #00BFFF; font-size: 12px; font-weight: bold; line-height: 1.4;"
                )
                value_label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
                
                # Add to other grid
                other_grid.addWidget(name_label, other_row, 0)
                other_grid.addWidget(value_label, other_row, 1)
                other_row += 1
            
            # Add the other grid to the layout
            other_layout.addLayout(other_grid)
            
            # Add the content directly without a collapsible section
            self.content_layout.addWidget(other_widget)

    def _create_collapsible_section(self, title):
        """Create a collapsible section with the given title."""
        section = CollapsibleSection(title)
        section.setStyleSheet("""
            QWidget {
                background-color: #121212;
            }
        """)
        return section

    def _position_dialog(self):
        """Position the dialog based on open instances."""
        # Determine position based on number of open dialogs
        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
        width = 900
        height = 600
        
        # Calculate new position based on existing dialogs
        margin = 40
        num_dialogs = len(RowDetailDialog.open_dialogs)
        x = screen.width() - (width + margin) if num_dialogs % 2 == 1 else margin
        y = margin + (num_dialogs // 2) * (height // 2)
        
        # Set dialog geometry
        self.setGeometry(x, y, width, height)

    def _copy_to_clipboard(self):
        """Copy row data to clipboard in a human-readable format."""
        clipboard = QtWidgets.QApplication.clipboard()
        formatted_data = []
        
        for i in range(self.content_layout.count()):
            item = self.content_layout.itemAt(i)
            if isinstance(item, QtWidgets.QGridLayout):
                # Process each row in the grid
                for row in range(item.rowCount()):
                    name_item = item.itemAtPosition(row, 0)
                    value_item = item.itemAtPosition(row, 1)
                    if name_item and value_item:
                        name_widget = name_item.widget()
                        value_widget = value_item.widget()
                        if isinstance(name_widget, QtWidgets.QLabel) and isinstance(value_widget, QtWidgets.QLabel):
                            name = name_widget.text()
                            value = value_widget.text()
                            formatted_data.append(f"{name}: {value}")
            elif isinstance(item, QtWidgets.QWidgetItem):
                # Skip category headers
                continue
        
        clipboard.setText("\n".join(formatted_data))
        
        # Show a message box to confirm copy
        QtWidgets.QMessageBox.information(
            self,
            "Copied",
            "Row details have been copied to the clipboard."
        )

    def _export_data(self):
        """Export row data to a file (e.g., CSV or TXT)."""
        try:
            # Ask user where to save the file
            options = QtWidgets.QFileDialog.Options()
            file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self,
                "Export Row Details",
                "row_details.txt",
                "Text Files (*.txt);;CSV Files (*.csv)",
                options=options
            )
            
            if not file_path:
                return
            
            # Gather data
            export_lines = []
            for i in range(self.content_layout.count()):
                item = self.content_layout.itemAt(i)
                if isinstance(item, QtWidgets.QGridLayout):
                    for row in range(item.rowCount()):
                        name_item = item.itemAtPosition(row, 0)
                        value_item = item.itemAtPosition(row, 1)
                        if name_item and value_item:
                            name_widget = name_item.widget()
                            value_widget = value_item.widget()
                            if isinstance(name_widget, QtWidgets.QLabel) and isinstance(value_widget, QtWidgets.QLabel):
                                name = name_widget.text()
                                value = value_widget.text()
                                export_lines.append((name, value))
            
            # Write data to file
            with open(file_path, "w", encoding="utf-8") as f:
                if file_path.lower().endswith('.csv'):
                    f.write("Name,Value\n")
                    for name, value in export_lines:
                        # Escape quotes and wrap each field in quotes for CSV safety
                        name = name.replace('"', '""')
                        value = value.replace('"', '""')
                        f.write(f'"{name}","{value}"\n')
                else:
                    for name, value in export_lines:
                        f.write(f"{name}: {value}\n")
                
            # Show confirmation message
            QtWidgets.QMessageBox.information(
                self, 
                "Export Successful", 
                f"Row details have been exported to {file_path}"
            )
                
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Export Failed",
                f"Failed to export data: {str(e)}"
            )
    
    def closeEvent(self, event):
        """Handle dialog close event."""
        # Remove this dialog from the class-level list
        if self in RowDetailDialog.open_dialogs:
            RowDetailDialog.open_dialogs.remove(self)
        
        # Accept the close event
        event.accept()
