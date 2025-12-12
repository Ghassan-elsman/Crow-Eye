"""
Startup Menu Dialog for Crow Eye Forensic Tool

This module provides a startup menu that displays recent cases and allows users
to quickly select a case, create a new one, or open an existing case.
"""

from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox, QGraphicsDropShadowEffect, QScrollArea
from PyQt5.QtGui import QPixmap, QPainter

import os
import sys
from pathlib import Path
from datetime import datetime

# Import styles
from styles import CrowEyeStyles


class CaseCardWidget(QtWidgets.QWidget):
    """Widget representing a single case card in the startup menu."""
    
    clicked = QtCore.pyqtSignal(object)  # Emits case metadata when clicked
    
    def __init__(self, case_metadata, parent=None):
        """Initialize the case card widget.
        
        Args:
            case_metadata: CaseMetadata object containing case information
            parent: Parent widget
        """
        super().__init__(parent)
        
        self.case_metadata = case_metadata
        self.is_available = os.path.exists(case_metadata.path)
        
        self.setup_ui()
        self.apply_styles()
        
    def setup_ui(self):
        """Set up the card UI components."""
        self.setCursor(Qt.PointingHandCursor if self.is_available else Qt.ForbiddenCursor)
        self.setObjectName("option_card")
        
        # Add shadow effect
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(15)
        if self.is_available:
            shadow.setColor(QtGui.QColor(0, 255, 255, 100))
        else:
            shadow.setColor(QtGui.QColor(239, 68, 68, 100))  # Red for unavailable
        shadow.setOffset(0, 5)
        self.setGraphicsEffect(shadow)
        
        # Set dark background for card - NO WHITE BACKGROUNDS!
        if self.is_available:
            self.setStyleSheet("""
                QWidget#option_card {
                    background-color: #1E293B;
                    border: 2px solid #475569;
                    border-radius: 12px;
                }
                QWidget#option_card:hover {
                    background-color: #334155;
                    border: 3px solid #00FFFF;
                }
                QWidget {
                    background-color: transparent;
                }
                QLabel {
                    background-color: transparent;
                }
            """)
        else:
            self.setStyleSheet("""
                QWidget#option_card {
                    background-color: #1E293B;
                    border: 3px solid #EF4444;
                    border-radius: 12px;
                    opacity: 0.7;
                }
                QWidget {
                    background-color: transparent;
                }
                QLabel {
                    background-color: transparent;
                }
            """)
        
        # Main layout
        card_layout = QtWidgets.QVBoxLayout(self)
        card_layout.setContentsMargins(20, 15, 20, 15)
        card_layout.setSpacing(8)
        
        # Case name (bold, bright cyan)
        name_label = QtWidgets.QLabel(self.case_metadata.name)
        name_label.setStyleSheet("""
            QLabel {
                color: #00FFFF;
                font-size: 18px;
                font-weight: 800;
                font-family: 'BBH Sans Bogle', 'Segoe UI', sans-serif;
                letter-spacing: 0.8px;
                background-color: transparent;
                text-transform: uppercase;
            }
        """)
        card_layout.addWidget(name_label)
        
        # Case path (brighter gray, readable)
        path_label = QtWidgets.QLabel(self.case_metadata.path)
        path_label.setStyleSheet("""
            QLabel {
                color: #CBD5E1;
                font-size: 12px;
                font-family: 'Segoe UI', sans-serif;
                background-color: transparent;
                font-weight: 500;
            }
        """)
        path_label.setWordWrap(True)
        card_layout.addWidget(path_label)
        
        # Timestamps row
        timestamps_widget = QtWidgets.QWidget()
        timestamps_layout = QtWidgets.QHBoxLayout(timestamps_widget)
        timestamps_layout.setContentsMargins(0, 5, 0, 0)
        timestamps_layout.setSpacing(15)
        
        # Created date (brighter, more visible)
        created_label = QtWidgets.QLabel(f"📅 Created: {self._format_datetime(self.case_metadata.created_date)}")
        created_label.setStyleSheet("""
            QLabel {
                color: #94A3B8;
                font-size: 11px;
                font-family: 'Segoe UI', sans-serif;
                background-color: transparent;
                font-weight: 600;
            }
        """)
        timestamps_layout.addWidget(created_label)
        
        # Last opened date (brighter, more visible)
        last_opened_label = QtWidgets.QLabel(f"🕒 Last Opened: {self._format_datetime(self.case_metadata.last_opened)}")
        last_opened_label.setStyleSheet("""
            QLabel {
                color: #94A3B8;
                font-size: 11px;
                font-family: 'Segoe UI', sans-serif;
                background-color: transparent;
                font-weight: 600;
            }
        """)
        timestamps_layout.addWidget(last_opened_label)
        timestamps_layout.addStretch()
        
        card_layout.addWidget(timestamps_widget)
        
        # Description (if available) - brighter and more visible
        if self.case_metadata.description:
            desc_label = QtWidgets.QLabel(self.case_metadata.description)
            desc_label.setStyleSheet("""
                QLabel {
                    color: #CBD5E1;
                    font-size: 13px;
                    font-family: 'Segoe UI', sans-serif;
                    font-style: italic;
                    background-color: transparent;
                    padding: 5px 0;
                }
            """)
            desc_label.setWordWrap(True)
            card_layout.addWidget(desc_label)
        
        # Warning for unavailable cases
        if not self.is_available:
            warning_label = QtWidgets.QLabel(f"⚠ Case not found at: {self.case_metadata.path}")
            warning_label.setStyleSheet("""
                QLabel {
                    color: #EF4444;
                    font-size: 11px;
                    font-weight: 600;
                    font-family: 'Segoe UI', sans-serif;
                    padding: 5px;
                    background-color: rgba(239, 68, 68, 0.1);
                    border-radius: 3px;
                }
            """)
            warning_label.setWordWrap(True)
            card_layout.addWidget(warning_label)
    
    def apply_styles(self):
        """Apply styles to the card."""
        # Styles are now applied in setup_ui()
        pass
    
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
    
    def mousePressEvent(self, event):
        """Handle mouse press event."""
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.case_metadata)
    
    def enterEvent(self, event):
        """Handle mouse enter event."""
        if self.is_available:
            shadow = self.graphicsEffect()
            if shadow:
                shadow.setBlurRadius(25)
                shadow.setColor(QtGui.QColor(0, 255, 255, 150))
                shadow.setOffset(0, 8)
    
    def leaveEvent(self, event):
        """Handle mouse leave event."""
        if self.is_available:
            shadow = self.graphicsEffect()
            if shadow:
                shadow.setBlurRadius(15)
                shadow.setColor(QtGui.QColor(0, 255, 255, 100))
                shadow.setOffset(0, 5)


class StartupMenuDialog(QtWidgets.QDialog):
    """
    Startup menu dialog for case selection.
    
    Displays recent cases and provides options to create new or open existing cases.
    """
    
    def __init__(self, case_history_manager, parent=None):
        """Initialize the startup menu dialog.
        
        Args:
            case_history_manager: CaseHistoryManager instance
            parent: Parent widget
        """
        super().__init__(parent)
        
        self.case_history_manager = case_history_manager
        self.selected_case = None
        self.choice = None  # 'create', 'open', or case metadata
        
        self.setup_ui()
        self.apply_styles()
        self.load_recent_cases()
        
    def setup_ui(self):
        """Set up the dialog UI components."""
        # Set dialog properties
        self.setWindowTitle("Crow Eye - Select Case")
        self.setMinimumSize(800, 600)
        self.setMaximumSize(1000, 800)
        self.setModal(True)
        
        # Main layout
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(30, 30, 30, 30)
        main_layout.setSpacing(20)
        
        # Header section
        header_widget = self.create_header()
        main_layout.addWidget(header_widget)
        
        # Stylish divider
        divider = self.create_stylish_divider()
        main_layout.addWidget(divider)
        
        # Recent cases section
        cases_widget = self.create_cases_section()
        main_layout.addWidget(cases_widget, 1)  # Stretch to fill space
        
        # Action buttons
        buttons_widget = self.create_buttons()
        main_layout.addWidget(buttons_widget)
    
    def create_stylish_divider(self):
        """Create a stylish cyberpunk divider."""
        divider_widget = QtWidgets.QWidget()
        divider_widget.setFixedHeight(3)
        divider_widget.setStyleSheet("""
            QWidget {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 transparent, 
                    stop:0.2 #00FFFF, 
                    stop:0.5 #00FF7F, 
                    stop:0.8 #00FFFF, 
                    stop:1 transparent);
                border-radius: 1px;
            }
        """)
        return divider_widget
    
    def create_header(self):
        """Create the header section."""
        header_widget = QtWidgets.QWidget()
        header_layout = QtWidgets.QVBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(10)
        
        # Title
        title_label = QtWidgets.QLabel("CROW EYE")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setObjectName("dialog_title")
        
        # Subtitle
        subtitle_label = QtWidgets.QLabel("Select a case to begin investigation")
        subtitle_label.setAlignment(Qt.AlignCenter)
        subtitle_label.setObjectName("dialog_description")
        
        header_layout.addWidget(title_label)
        header_layout.addWidget(subtitle_label)
        
        return header_widget
    
    def create_cases_section(self):
        """Create the recent cases section with scroll area."""
        cases_widget = QtWidgets.QWidget()
        cases_layout = QtWidgets.QVBoxLayout(cases_widget)
        cases_layout.setContentsMargins(0, 0, 0, 0)
        cases_layout.setSpacing(10)
        
        # Section title
        section_title = QtWidgets.QLabel("RECENT CASES")
        section_title.setStyleSheet("""
            QLabel {
                color: #00FFFF;
                font-size: 14px;
                font-weight: 700;
                font-family: 'BBH Sans Bogle', 'Segoe UI', sans-serif;
                text-transform: uppercase;
                letter-spacing: 1px;
                padding: 5px 0;
            }
        """)
        cases_layout.addWidget(section_title)
        
        # Scroll area for case cards
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: 1px solid #334155;
                border-radius: 8px;
                background-color: #0B1220;
            }
            QScrollBar:vertical {
                background: #1E293B;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background: #3B82F6;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: #60A5FA;
            }
        """)
        
        # Container for case cards - DARK BACKGROUND
        self.cases_container = QtWidgets.QWidget()
        self.cases_container.setStyleSheet("""
            QWidget {
                background-color: #0B1220;
            }
        """)
        self.cases_container_layout = QtWidgets.QVBoxLayout(self.cases_container)
        self.cases_container_layout.setContentsMargins(10, 10, 10, 10)
        self.cases_container_layout.setSpacing(15)
        self.cases_container_layout.addStretch()
        
        scroll_area.setWidget(self.cases_container)
        cases_layout.addWidget(scroll_area)
        
        return cases_widget
    
    def create_buttons(self):
        """Create the action buttons section."""
        buttons_widget = QtWidgets.QWidget()
        buttons_layout = QtWidgets.QHBoxLayout(buttons_widget)
        buttons_layout.setContentsMargins(0, 10, 0, 0)
        buttons_layout.setSpacing(15)
        
        # Create New Case button
        create_button = QtWidgets.QPushButton("CREATE NEW CASE")
        create_button.setFixedHeight(45)
        create_button.setMinimumWidth(180)
        create_button.clicked.connect(self.on_create_new_case)
        create_button.setStyleSheet(CrowEyeStyles.GREEN_BUTTON)
        
        # Add icon to create button
        icon_new_case = QtGui.QIcon()
        icon_new_case.addPixmap(QtGui.QPixmap(":/Icons/icons/new-case-icon.svg"), QtGui.QIcon.Normal, QtGui.QIcon.Off)
        create_button.setIcon(icon_new_case)
        create_button.setIconSize(QtCore.QSize(20, 20))
        
        # Open Existing Case button
        open_button = QtWidgets.QPushButton("OPEN EXISTING CASE")
        open_button.setFixedHeight(45)
        open_button.setMinimumWidth(180)
        open_button.clicked.connect(self.on_open_existing_case)
        open_button.setStyleSheet(CrowEyeStyles.CASE_BUTTON)
        
        # Add icon to open button
        icon_open_case = QtGui.QIcon()
        icon_open_case.addPixmap(QtGui.QPixmap(":/Icons/icons/open-case-icon.svg"), QtGui.QIcon.Normal, QtGui.QIcon.Off)
        open_button.setIcon(icon_open_case)
        open_button.setIconSize(QtCore.QSize(20, 20))
        
        # Exit button
        exit_button = QtWidgets.QPushButton("EXIT")
        exit_button.setFixedSize(120, 45)
        exit_button.clicked.connect(self.reject)
        exit_button.setStyleSheet(CrowEyeStyles.RED_BUTTON)
        
        buttons_layout.addWidget(create_button)
        buttons_layout.addWidget(open_button)
        buttons_layout.addStretch()
        buttons_layout.addWidget(exit_button)
        
        return buttons_widget
    
    def load_recent_cases(self):
        """Load and display recent cases."""
        # Get recent cases from history manager
        recent_cases = self.case_history_manager.get_recent_cases(limit=10)
        
        if not recent_cases:
            # Show "no cases" message
            no_cases_label = QtWidgets.QLabel("No recent cases found.\nCreate a new case or open an existing one to get started.")
            no_cases_label.setAlignment(Qt.AlignCenter)
            no_cases_label.setStyleSheet("""
                QLabel {
                    color: #94A3B8;
                    font-size: 14px;
                    font-family: 'Segoe UI', sans-serif;
                    padding: 40px;
                }
            """)
            self.cases_container_layout.insertWidget(0, no_cases_label)
        else:
            # Create case cards
            for case_metadata in recent_cases:
                case_card = CaseCardWidget(case_metadata, self)
                case_card.clicked.connect(self.on_case_selected)
                self.cases_container_layout.insertWidget(
                    self.cases_container_layout.count() - 1,  # Before stretch
                    case_card
                )
    
    def on_case_selected(self, case_metadata):
        """Handle case selection.
        
        Args:
            case_metadata: CaseMetadata object for the selected case
        """
        # Check if case directory exists
        if not os.path.exists(case_metadata.path):
            self.show_missing_case_dialog(case_metadata)
        else:
            # Valid case, update access time and return
            self.case_history_manager.update_case_access(case_metadata.path)
            self.selected_case = case_metadata
            self.choice = case_metadata
            self.accept()
    
    def show_missing_case_dialog(self, case_metadata):
        """Show dialog for missing case directory.
        
        Args:
            case_metadata: CaseMetadata object for the missing case
        """
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Case Directory Not Found")
        msg_box.setText(f"The case directory no longer exists at:\n{case_metadata.path}\n\nWhat would you like to do?")
        msg_box.setIcon(QMessageBox.Warning)
        msg_box.setStyleSheet(CrowEyeStyles.MESSAGE_BOX_STYLE)
        
        # Add custom buttons
        browse_button = msg_box.addButton("Browse to New Location", QMessageBox.ActionRole)
        remove_button = msg_box.addButton("Remove from History", QMessageBox.DestructiveRole)
        cancel_button = msg_box.addButton("Cancel", QMessageBox.RejectRole)
        
        msg_box.exec_()
        
        clicked_button = msg_box.clickedButton()
        
        if clicked_button == browse_button:
            # Browse for new location
            new_path = QtWidgets.QFileDialog.getExistingDirectory(
                self,
                "Select Case Directory",
                os.path.dirname(case_metadata.path)
            )
            if new_path:
                # Update case path
                case_metadata.path = new_path
                self.case_history_manager.save_case_history()
                # Reload cases
                self.reload_cases()
        elif clicked_button == remove_button:
            # Remove from history
            self.case_history_manager.remove_case(case_metadata.path)
            # Reload cases
            self.reload_cases()
    
    def reload_cases(self):
        """Reload the cases list."""
        # Clear existing cards
        while self.cases_container_layout.count() > 1:  # Keep the stretch
            item = self.cases_container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # Reload cases
        self.load_recent_cases()
    
    def on_create_new_case(self):
        """Handle create new case button click."""
        self.choice = 'create'
        self.accept()
    
    def on_open_existing_case(self):
        """Handle open existing case button click."""
        self.choice = 'open'
        self.accept()
    
    def apply_styles(self):
        """Apply cyberpunk styles to the dialog."""
        self.setStyleSheet(CrowEyeStyles.CASE_DIALOG_STYLE)
        
        # Apply specific styles
        title_widget = self.findChild(QtWidgets.QLabel, "dialog_title")
        if title_widget:
            title_widget.setStyleSheet(CrowEyeStyles.DIALOG_TITLE)
        
        desc_widget = self.findChild(QtWidgets.QLabel, "dialog_description")
        if desc_widget:
            desc_widget.setStyleSheet(CrowEyeStyles.DIALOG_DESCRIPTION)
    
    def get_choice(self):
        """Get the user's choice."""
        return self.choice
    
    def exec_(self):
        """Execute the dialog and return the choice."""
        result = super().exec_()
        if result == QtWidgets.QDialog.Accepted:
            return self.choice
        else:
            return None


def show_startup_menu(case_history_manager, parent=None):
    """
    Show the startup menu dialog.
    
    Args:
        case_history_manager: CaseHistoryManager instance
        parent: Parent widget
        
    Returns:
        Case metadata object, 'create', 'open', or None if cancelled
    """
    dialog = StartupMenuDialog(case_history_manager, parent)
    return dialog.exec_()


if __name__ == "__main__":
    # Test the dialog
    from config import CaseHistoryManager
    
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    
    # Create test case history manager
    manager = CaseHistoryManager()
    
    choice = show_startup_menu(manager)
    print(f"User choice: {choice}")
    
    sys.exit(0)
