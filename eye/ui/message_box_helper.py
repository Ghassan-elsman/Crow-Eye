"""
Message Box Helper for EYE AI Forensic Assistant.

This module provides styled QMessageBox dialogs that are consistent with
the dark theme used throughout the EYE interface.
"""

from PyQt5.QtWidgets import QMessageBox, QApplication
from PyQt5.QtCore import Qt


# Global stylesheet for QMessageBox to ensure text is visible on dark backgrounds
MESSAGEBOX_STYLESHEET = """
QMessageBox {
    background-color: #0B1220;
    color: #E5E7EB;
}
QMessageBox QLabel {
    color: #E5E7EB;
    font-size: 10pt;
    background: transparent;
}
QMessageBox QPushButton {
    background-color: #1E293B;
    color: #E5E7EB;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 10pt;
    font-weight: bold;
    min-width: 80px;
    min-height: 30px;
}
QMessageBox QPushButton:hover {
    background-color: #334155;
    border: 1px solid #00FFFF;
}
QMessageBox QPushButton:pressed {
    background-color: #475569;
}
QMessageBox QTextEdit {
    background-color: #1E293B;
    color: #E5E7EB;
    border: 1px solid #334155;
    border-radius: 4px;
}
"""


def apply_messagebox_style():
    """
    Apply dark theme styling to all QMessageBox dialogs globally.
    
    This function should be called once during application initialization
    to ensure all message boxes have visible text on dark backgrounds.
    """
    app = QApplication.instance()
    if app:
        # Get existing stylesheet
        existing_style = app.styleSheet()
        
        # Append messagebox stylesheet if not already present
        if "QMessageBox" not in existing_style:
            app.setStyleSheet(existing_style + "\n" + MESSAGEBOX_STYLESHEET)


def information(parent, title, text):
    """
    Show an information message box with dark theme styling.
    
    Args:
        parent: Parent widget
        title: Dialog title
        text: Message text
        
    Returns:
        QMessageBox.StandardButton: The button that was clicked
    """
    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Information)
    msg.setWindowTitle(title)
    msg.setText(text)
    msg.setStyleSheet(MESSAGEBOX_STYLESHEET)
    msg.setStandardButtons(QMessageBox.Ok)
    return msg.exec_()


def warning(parent, title, text):
    """
    Show a warning message box with dark theme styling.
    
    Args:
        parent: Parent widget
        title: Dialog title
        text: Message text
        
    Returns:
        QMessageBox.StandardButton: The button that was clicked
    """
    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Warning)
    msg.setWindowTitle(title)
    msg.setText(text)
    msg.setStyleSheet(MESSAGEBOX_STYLESHEET)
    msg.setStandardButtons(QMessageBox.Ok)
    return msg.exec_()


def critical(parent, title, text):
    """
    Show a critical error message box with dark theme styling.
    
    Args:
        parent: Parent widget
        title: Dialog title
        text: Message text
        
    Returns:
        QMessageBox.StandardButton: The button that was clicked
    """
    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Critical)
    msg.setWindowTitle(title)
    msg.setText(text)
    msg.setStyleSheet(MESSAGEBOX_STYLESHEET)
    msg.setStandardButtons(QMessageBox.Ok)
    return msg.exec_()


def question(parent, title, text, buttons=QMessageBox.Yes | QMessageBox.No, default_button=QMessageBox.No):
    """
    Show a question message box with dark theme styling.
    
    Args:
        parent: Parent widget
        title: Dialog title
        text: Message text
        buttons: Standard buttons to show (default: Yes | No)
        default_button: Default button (default: No)
        
    Returns:
        QMessageBox.StandardButton: The button that was clicked
    """
    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Question)
    msg.setWindowTitle(title)
    msg.setText(text)
    msg.setStyleSheet(MESSAGEBOX_STYLESHEET)
    msg.setStandardButtons(buttons)
    msg.setDefaultButton(default_button)
    return msg.exec_()
