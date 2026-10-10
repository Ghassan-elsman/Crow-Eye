"""
JSON Viewer Dialog
Dialog for viewing and copying Wing JSON output.
"""

import json
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton,
    QLabel, QMessageBox, QApplication
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QClipboard

from correlation_engine.wings.core.wing_model import Wing

# The site look (ui/site_theme.py); standalone it keeps Qt's own style.
try:
    from ui import site_theme as _site
except Exception:
    _site = None


class JsonViewerDialog(QDialog):
    """Dialog for viewing Wing JSON output"""
    
    def __init__(self, wing: Wing, parent=None):
        super().__init__(parent)
        self.wing = wing
        if _site is not None:
            _site.begin_site_theme(self)        # before the children exist
        self.init_ui()
    
    def init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle(f"Wing JSON - {self.wing.wing_name or 'Untitled'}")
        self.setGeometry(200, 200, 800, 600)
        
        layout = QVBoxLayout(self)
        
        # Header
        header_label = QLabel("Generated Wing JSON")
        if _site is not None:
            _site.set_role(header_label, "section")
        layout.addWidget(header_label)
        
        info_label = QLabel(
            "This JSON can be saved to a file and shared with other analysts. "
            "It contains all the configuration needed to run this Wing."
        )
        info_label.setWordWrap(True)
        info_label.setContentsMargins(0, 0, 0, 10)
        if _site is not None:
            _site.set_role(info_label, "muted")
        layout.addWidget(info_label)
        
        # JSON text area
        self.json_text = QTextEdit()
        if _site is not None:
            # A mono well, as the loading dialog's log view.
            self.json_text.setStyleSheet(_site.log_view_sheet())
            _site.keep_style(self.json_text)
        else:
            self.json_text.setFont(QFont("Consolas", 10))
        self.json_text.setReadOnly(True)
        
        # Generate and display JSON
        try:
            json_str = self.wing.to_json(indent=2)
            self.json_text.setPlainText(json_str)
        except Exception as e:
            self.json_text.setPlainText(f"Error generating JSON: {str(e)}")
        
        layout.addWidget(self.json_text)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        # Copy button
        copy_btn = QPushButton("Copy to Clipboard")
        copy_btn.clicked.connect(self.copy_to_clipboard)
        button_layout.addWidget(copy_btn)
        
        # Save button
        save_btn = QPushButton("Save to File")
        save_btn.clicked.connect(self.save_to_file)
        button_layout.addWidget(save_btn)
        
        button_layout.addStretch()
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        if _site is not None:
            _site.set_variant(copy_btn, "ghost")
            _site.set_variant(save_btn, "primary")
            _site.set_variant(close_btn, "ghost")
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)
        
        # The site look (the sheet was set before the children)
        if _site is not None:
            _site.apply_site_theme(self)
    
    def copy_to_clipboard(self):
        """Copy JSON to clipboard"""
        clipboard = QApplication.clipboard()
        clipboard.setText(self.json_text.toPlainText())
        
        QMessageBox.information(
            self, "Copied", 
            "Wing JSON has been copied to clipboard."
        )
    
    def save_to_file(self):
        """Save JSON to file"""
        from PyQt5.QtWidgets import QFileDialog
        
        # Suggest filename based on wing name
        suggested_name = "wing.json"
        if self.wing.wing_name:
            suggested_name = self.wing.wing_name.lower().replace(' ', '_') + '.json'
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Wing JSON", suggested_name, 
            "JSON Files (*.json);;All Files (*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w') as f:
                    f.write(self.json_text.toPlainText())
                
                QMessageBox.information(
                    self, "Saved", 
                    f"Wing JSON saved to: {file_path}"
                )
            except Exception as e:
                QMessageBox.critical(
                    self, "Save Error", 
                    f"Failed to save file: {str(e)}"
                )
