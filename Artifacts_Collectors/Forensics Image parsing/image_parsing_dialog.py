import os
import sys
from PyQt5 import QtWidgets, QtCore, QtGui

class ImageParsingDialog(QtWidgets.QDialog):
    """
    Placeholder dialog for the Forensics Image Parsing module.
    This module is currently under development.
    """
    def __init__(self, parent=None):
        super(ImageParsingDialog, self).__init__(parent)
        self.setWindowTitle("Forensics Image Parsing - Under Development")
        self.setMinimumSize(500, 350)
        self.setup_ui()
        self.apply_styles()

    def setup_ui(self):
        self.layout = QtWidgets.QVBoxLayout(self)
        
        # Header Icon/Banner Placeholder
        self.header_label = QtWidgets.QLabel()
        self.header_label.setAlignment(QtCore.Qt.AlignCenter)
        # Attempt to load a generic icon or just use text if not available
        self.header_label.setText("🔍")
        self.header_label.setFont(QtGui.QFont("Segoe UI", 48))
        self.layout.addWidget(self.header_label)

        # Title
        self.title_label = QtWidgets.QLabel("Forensics Image Parsing")
        self.title_label.setAlignment(QtCore.Qt.AlignCenter)
        font = QtGui.QFont("Segoe UI", 16, QtGui.QFont.Bold)
        self.title_label.setFont(font)
        self.layout.addWidget(self.title_label)

        # Status Badge
        self.status_label = QtWidgets.QLabel("UNDER DEVELOPMENT")
        self.status_label.setAlignment(QtCore.Qt.AlignCenter)
        self.status_label.setStyleSheet("""
            background-color: #ff9800;
            color: black;
            padding: 5px;
            border-radius: 3px;
            font-weight: bold;
            margin: 10px 100px;
        """)
        self.layout.addWidget(self.status_label)

        # Description
        self.desc_label = QtWidgets.QLabel(
            "The Forensics Image Parsing module is currently being implemented.\n\n"
            "Future features will include:\n"
            "• Direct mounting of E01 (Expert Witness) images\n"
            "• Support for Raw/DD images and VMDK/VHD virtual disks\n"
            "• Automated partition detection and file system mounting\n"
            "• Seamless integration with Crow-Claw for automated artifact extraction"
        )
        self.desc_label.setWordWrap(True)
        self.desc_label.setAlignment(QtCore.Qt.AlignLeft)
        self.desc_label.setStyleSheet("margin: 20px; line-height: 1.5;")
        self.layout.addWidget(self.desc_label)

        # Spacer
        self.layout.addStretch()

        # Close Button
        self.button_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        self.button_box.rejected.connect(self.reject)
        self.layout.addWidget(self.button_box)

    def apply_styles(self):
        # Apply dark theme consistent with Crow-eye
        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e1e;
                color: #e0e0e0;
            }
            QLabel {
                color: #e0e0e0;
            }
            QPushButton {
                background-color: #333333;
                color: white;
                border: 1px solid #555555;
                padding: 5px 15px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #444444;
                border: 1px solid #777777;
            }
        """)

def show_dialog(parent=None):
    dialog = ImageParsingDialog(parent)
    return dialog.exec_()

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    show_dialog()
    sys.exit(app.exec_())
