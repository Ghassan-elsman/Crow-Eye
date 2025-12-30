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


class JsonViewerDialog(QDialog):
    """Dialog for viewing Wing JSON output"""
    
    def __init__(self, wing: Wing, parent=None):
        super().__init__(parent)
        self.wing = wing
        self.init_ui()
    
    def init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle(f"Wing JSON - {self.wing.wing_name or 'Untitled'}")
        self.setGeometry(200, 200, 800, 600)
        
        layout = QVBoxLayout(self)
        
        # Header
        header_label = QLabel("Generated Wing JSON")
        header_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #00d9ff;")
        layout.addWidget(header_label)
        
        info_label = QLabel(
            "This JSON can be saved to a file and shared with other analysts. "
            "It contains all the configuration needed to run this Wing."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #666; margin-bottom: 10px;")
        layout.addWidget(info_label)
        
        # JSON text area
        self.json_text = QTextEdit()
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
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)
        
        # Apply styles
        self.setStyleSheet("""
            QDialog {
                background-color: #0B1220;
                color: #FFFFFF;
            }
            QTextEdit {
                background-color: #1a1f2e;
                color: #FFFFFF;
                border: 1px solid #334155;
                border-radius: 4px;
                padding: 8px;
            }
            QPushButton {
                background-color: #3B82F6;
                color: #FFFFFF;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2563EB;
            }
            QPushButton:pressed {
                background-color: #1D4ED8;
            }
        """)
    
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
