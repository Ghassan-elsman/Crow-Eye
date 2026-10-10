"""
Case Dialog Component for Crow Eye Forensic Tool

This module provides a custom dialog for case management operations (create new case,
open existing case) with enhanced cyberpunk styling and improved user experience.
"""

from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox, QGraphicsDropShadowEffect
from PyQt5.QtSvg import QSvgWidget
from PyQt5.QtGui import QPixmap, QPainter

import os
import sys
from pathlib import Path

# Import styles
from styles import CrowEyeStyles, Colors



# The option cards are plain QWidgets: their card look and hover edge live in
# the window sheet (WA_StyledBackground on each card makes the rule paint).
_CARD_RULES = """
QWidget#option_card { background: #0F172A; border: 1px solid #1E293B; border-radius: 16px; }
QWidget#option_card:hover { border-color: rgba(99, 102, 241, 0.55); background: #111A33; }
QWidget#option_card QWidget, QWidget#option_card QLabel { background: transparent; border: none; }
"""

class CaseDialog(QtWidgets.QDialog):
    """
    Custom dialog for case management with enhanced cyberpunk styling.
    
    This dialog provides options to create a new case or open an existing case
    with a modern, forensic-focused interface.
    """
    
    def __init__(self, parent=None):
        """Initialize the case dialog."""
        super(CaseDialog, self).__init__(parent)
        
        self.parent = parent
        self.choice = None  # Will store user choice: 'create' or 'open'

        from ui.site_theme import begin_site_theme
        begin_site_theme(self, extra=_CARD_RULES)   # before the widgets exist
        self.setup_ui()
        self.apply_styles()
        
    def setup_ui(self):
        """Set up the dialog UI components."""
        # Set dialog properties
        self.setWindowTitle("Crow Eye - Case Management")
        self.setMinimumSize(600, 500)
        self.setMaximumSize(700, 600)
        self.setModal(True)
        
        # Main layout with better spacing
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(30, 30, 30, 30)
        main_layout.setSpacing(25)
        
        # Header section
        header_widget = self.create_header()
        main_layout.addWidget(header_widget)
        
        # Stylish divider
        divider = self.create_stylish_divider()
        main_layout.addWidget(divider)
        
        # Content section with enhanced spacing
        content_widget = self.create_content()
        main_layout.addWidget(content_widget)
        
        # Button section
        button_widget = self.create_buttons()
        main_layout.addWidget(button_widget)
        
        # Add spacer
        main_layout.addStretch()
        
    def create_stylish_divider(self):
        """Create a stylish cyberpunk divider."""
        divider_widget = QtWidgets.QWidget()
        divider_widget.setFixedHeight(3)
        divider_widget.setStyleSheet("""
            QWidget {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 transparent, 
                    stop:0.2 #6366F1, 
                    stop:0.5 #22D3EE, 
                    stop:0.8 #6366F1, 
                    stop:1 transparent);
                border-radius: 1px;
            }
        """)
        divider_widget.setProperty("keepStyle", True)
        return divider_widget
        
    def create_header(self):
        """Create the header section with title and description."""
        header_widget = QtWidgets.QWidget()
        header_layout = QtWidgets.QVBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(15)
        
        # Title with enhanced styling
        title_label = QtWidgets.QLabel("CASE MANAGEMENT")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setObjectName("dialog_title")
        
        # Description with better formatting
        desc_label = QtWidgets.QLabel(
            "No active case found. Please choose an option to continue:"
        )
        desc_label.setAlignment(Qt.AlignCenter)
        desc_label.setWordWrap(True)
        desc_label.setObjectName("dialog_description")
        
        header_layout.addWidget(title_label)
        header_layout.addWidget(desc_label)
        
        return header_widget
        
    def create_content(self):
        """Create the content section with enhanced option cards."""
        content_widget = QtWidgets.QWidget()
        content_layout = QtWidgets.QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(20)
        
        # Create new case card with enhanced design
        create_card = self.create_enhanced_option_card(
            "Create New Case",
            "Start a new forensic investigation with a fresh case",
            "new-case-icon.svg",  # SVG icon
            "create",
            "#4ADE80"  # Green accent (site ok)
        )
        content_layout.addWidget(create_card)
        
        # Open existing case card with enhanced design
        open_card = self.create_enhanced_option_card(
            "Open Existing Case", 
            "Continue working with an existing case or review previous findings",
            "open-case-icon.svg",  # SVG icon
            "open",
            "#22D3EE"  # Cyan accent (site info)
        )
        content_layout.addWidget(open_card)
        
        return content_widget
        
    def create_enhanced_option_card(self, title, description, icon, choice_value, accent_color):
        """Create an enhanced interactive option card with better visual design."""
        card = QtWidgets.QWidget()
        card.setCursor(Qt.PointingHandCursor)
        card.mousePressEvent = lambda event: self.handle_card_click(choice_value)
        card.setObjectName("option_card")
        
        # Store original accent color for animations
        card.accent_color = accent_color
        card.is_hovered = False
        
        # Add shadow effect for depth
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(15)
        shadow.setColor(QtGui.QColor(0, 0, 0, 110))
        shadow.setOffset(0, 5)
        card.setGraphicsEffect(shadow)
        card.setAttribute(Qt.WA_StyledBackground, True)     # paint the card rule
        card.setAttribute(Qt.WA_Hover, True)
        
        # Add hover animations
        def on_enter(event):
            card.is_hovered = True
            # Enhance shadow on hover
            shadow.setBlurRadius(25)
            shadow.setColor(QtGui.QColor(99, 102, 241, 90))
            shadow.setOffset(0, 8)
            
            # Enhance icon container on hover (keep transparent)
            if hasattr(card, 'icon_container'):
                card.icon_container.setStyleSheet("""
                    QWidget {
                        background: transparent;
                        border: none;
                    }
                """)
            
        def on_leave(event):
            card.is_hovered = False
            # Reset shadow
            shadow.setBlurRadius(15)
            shadow.setColor(QtGui.QColor(0, 0, 0, 110))
            shadow.setOffset(0, 5)
            
            # Reset icon container (keep transparent)
            if hasattr(card, 'icon_container'):
                card.icon_container.setStyleSheet("""
                    QWidget {
                        background: transparent;
                        border: none;
                    }
                """)
            
        card.enterEvent = on_enter
        card.leaveEvent = on_leave
        
        card_layout = QtWidgets.QHBoxLayout(card)
        card_layout.setContentsMargins(25, 20, 25, 20)
        card_layout.setSpacing(20)
        
        # Enhanced icon section
        icon_widget = QtWidgets.QWidget()
        icon_widget.setFixedSize(80, 80)
        icon_layout = QtWidgets.QVBoxLayout(icon_widget)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        
        # Create SVG icon widget
        icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "GUI Resources", "icons", icon)
        
        if os.path.exists(icon_path) and icon.endswith('.svg'):
            # Use SVG widget for SVG files
            icon_label = QSvgWidget(icon_path)
            icon_label.setFixedSize(40, 40)
        else:
            # Fallback to text label for non-SVG or missing files
            icon_label = QtWidgets.QLabel(icon)
            icon_label.setAlignment(Qt.AlignCenter)
            
        icon_label.setObjectName("icon_label")
        
        # Create container for icon with styling
        icon_container = QtWidgets.QWidget()
        icon_container.setFixedSize(80, 80)
        icon_container_layout = QtWidgets.QVBoxLayout(icon_container)
        icon_container_layout.setContentsMargins(0, 0, 0, 0)
        icon_container_layout.setAlignment(Qt.AlignCenter)
        icon_container_layout.addWidget(icon_label)
        
        icon_container.setStyleSheet("""
            QWidget {
                background: transparent;
                border: none;
            }
        """)
        
        # Store reference to icon for hover effects
        card.icon_label = icon_label
        card.icon_container = icon_container
        
        icon_layout.addWidget(icon_container)
        card_layout.addWidget(icon_widget)
        
        # Enhanced text content
        text_widget = QtWidgets.QWidget()
        text_layout = QtWidgets.QVBoxLayout(text_widget)
        text_layout.setContentsMargins(0, 5, 0, 5)
        text_layout.setSpacing(8)
        
        title_label = QtWidgets.QLabel(title)
        title_label.setStyleSheet(f"""
            QLabel {{
                color: {accent_color};
                font-size: 18px;
                font-weight: 700;
                font-family: 'Segoe UI', sans-serif;
            }}
        """)
        
        desc_label = QtWidgets.QLabel(description)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet(f"""
            QLabel {{
                color: {Colors.TEXT_PRIMARY};
                font-size: 14px;
                font-weight: 400;
                line-height: 1.4;
                font-family: 'Segoe UI', sans-serif;
            }}
        """)
        
        card.title_label = title_label
        card.desc_label = desc_label
        text_layout.addWidget(title_label)
        text_layout.addWidget(desc_label)
        text_layout.addStretch()
        
        card_layout.addWidget(text_widget, 1)
        
        # Add arrow indicator
        arrow_label = QtWidgets.QLabel("→")
        arrow_label.setAlignment(Qt.AlignCenter)
        arrow_label.setStyleSheet(f"""
            QLabel {{
                color: {accent_color};
                font-size: 24px;
                font-weight: bold;
                padding: 10px;
            }}
        """)
        arrow_label.setProperty("keepStyle", True)      # the card's accent arrow
        card_layout.addWidget(arrow_label)

        return card
        
    def create_buttons(self):
        """Create the enhanced button section."""
        button_widget = QtWidgets.QWidget()
        button_layout = QtWidgets.QHBoxLayout(button_widget)
        button_layout.setContentsMargins(0, 10, 0, 0)
        button_layout.setSpacing(15)
        
        # Enhanced exit button
        exit_button = QtWidgets.QPushButton("EXIT")
        exit_button.setFixedSize(120, 45)
        exit_button.clicked.connect(self.reject)
        self.exit_button = exit_button
        exit_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #DC2626, stop:1 #B91C1C);
                color: #FFFFFF;
                border: 2px solid #EF4444;
                border-radius: 8px;
                font-size: 14px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #EF4444, stop:1 #DC2626);
                border: 2px solid #F87171;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #B91C1C, stop:1 #991B1B);
            }
        """)
        
        button_layout.addStretch()
        button_layout.addWidget(exit_button)
        
        return button_widget
        
    def apply_styles(self):
        """The site look (ui/site_theme.py): one sheet, roles for the labels,
        the option cards as site cards, EXIT as the stop button."""
        from ui.site_theme import apply_site_theme, set_role, set_variant, set_status
        apply_site_theme(self, extra=_CARD_RULES)
        title_widget = self.findChild(QtWidgets.QLabel, "dialog_title")
        if title_widget:
            set_role(title_widget, "title")
        desc_widget = self.findChild(QtWidgets.QLabel, "dialog_description")
        if desc_widget:
            set_role(desc_widget, "muted")
        for card in self.findChildren(QtWidgets.QWidget, "option_card"):
            set_role(card.title_label, "subtitle")
            set_status(card.title_label, "ok" if card.accent_color == "#4ADE80" else "info")
        set_variant(self.exit_button, "danger")

    def handle_card_click(self, choice_value):
        """Handle card click event with visual feedback."""
        self.choice = choice_value
        self.accept()
        
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


def show_case_dialog(parent=None):
    """
    Show the case dialog and return user choice.
    
    Returns:
        str: 'create', 'open', or None if cancelled
    """
    dialog = CaseDialog(parent)
    return dialog.exec_()


# Compatibility function for easy migration from old message box
def show_case_message_box(parent=None):
    """
    Compatibility function that mimics the old message box behavior.
    
    Returns:
        str: 'create', 'open', or None if cancelled
    """
    return show_case_dialog(parent)


if __name__ == "__main__":
    # Test the dialog
    app = QtWidgets.QApplication(sys.argv)
    
    # Apply global cyberpunk style for testing
    app.setStyle("Fusion")
    
    choice = show_case_dialog()
    print(f"User choice: {choice}")
    
    sys.exit(0)