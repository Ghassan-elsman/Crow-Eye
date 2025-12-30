"""
Wing Selection Dialog
Allows users to select which Wings to execute in a Pipeline.
"""

from typing import List, Optional
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QScrollArea, QWidget, QGroupBox, QFrame
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from .ui_styling import CorrelationEngineStyles


from ..config import WingConfig


class WingSelectionDialog(QDialog):
    """Dialog for selecting Wings to execute"""
    
    def __init__(self, wings: List[WingConfig], parent=None):
        """
        Initialize Wing selection dialog.
        
        Args:
            wings: List of WingConfig objects to display
            parent: Parent widget
        """
        super().__init__(parent)
        
        self.wings = wings
        self.wing_checkboxes = {}  # wing_id -> QCheckBox
        self.selected_wing_ids = []
        
        self._init_ui()
        
        # Select all by default
        self._select_all()
    
    def _init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle("Select Wings to Execute")
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)
        
        # Main layout
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        # Header
        header_label = QLabel("Select which Wings to execute:")
        header_label.setFont(QFont("Segoe UI", 12, QFont.Bold))
        layout.addWidget(header_label)
        
        # Info label
        info_label = QLabel(
            f"Found {len(self.wings)} Wing(s) in the Pipeline. "
            "Select the Wings you want to execute."
        )
        info_label.setStyleSheet("color: #94A3B8; font-size: 10px;")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setStyleSheet("background-color: #334155;")
        layout.addWidget(separator)
        
        # Wings list in scroll area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: 1px solid #334155;
                border-radius: 4px;
                background-color: #1E293B;
            }
        """)
        
        # Container widget for wings
        wings_container = QWidget()
        wings_layout = QVBoxLayout(wings_container)
        wings_layout.setSpacing(10)
        wings_layout.setContentsMargins(10, 10, 10, 10)
        
        # Create checkbox for each wing
        for wing in self.wings:
            wing_widget = self._create_wing_checkbox(wing)
            wings_layout.addWidget(wing_widget)
        
        wings_layout.addStretch()
        scroll_area.setWidget(wings_container)
        layout.addWidget(scroll_area)
        
        # Selection buttons
        selection_buttons_layout = QHBoxLayout()
        selection_buttons_layout.setSpacing(10)
        
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(self._select_all)
        select_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                color: #E2E8F0;
                border: 1px solid #475569;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #475569;
                border-color: #64748B;
            }
            QPushButton:pressed {
                background-color: #1E293B;
            }
        """)
        selection_buttons_layout.addWidget(select_all_btn)
        
        deselect_all_btn = QPushButton("Deselect All")
        deselect_all_btn.clicked.connect(self._deselect_all)
        deselect_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                color: #E2E8F0;
                border: 1px solid #475569;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #475569;
                border-color: #64748B;
            }
            QPushButton:pressed {
                background-color: #1E293B;
            }
        """)
        selection_buttons_layout.addWidget(deselect_all_btn)
        
        selection_buttons_layout.addStretch()
        layout.addLayout(selection_buttons_layout)
        
        # Dialog buttons
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(10)
        
        buttons_layout.addStretch()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setMinimumWidth(100)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #475569;
                color: #E2E8F0;
                border: 1px solid #64748B;
                border-radius: 4px;
                padding: 10px 20px;
                font-weight: 600;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #64748B;
                border-color: #94A3B8;
            }
            QPushButton:pressed {
                background-color: #334155;
            }
        """)
        buttons_layout.addWidget(cancel_btn)
        
        ok_btn = QPushButton("Execute Selected")
        CorrelationEngineStyles.add_button_icon(ok_btn, "execute", "#FFFFFF")
        ok_btn.clicked.connect(self._on_ok_clicked)
        ok_btn.setMinimumWidth(150)
        ok_btn.setDefault(True)
        ok_btn.setStyleSheet("""
            QPushButton {
                background-color: #3B82F6;
                color: #FFFFFF;
                border: 1px solid #2563EB;
                border-radius: 4px;
                padding: 10px 20px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #2563EB;
                border-color: #1D4ED8;
            }
            QPushButton:pressed {
                background-color: #1D4ED8;
            }
            QPushButton:disabled {
                background-color: #475569;
                color: #94A3B8;
                border-color: #334155;
            }
        """)
        buttons_layout.addWidget(ok_btn)
        
        layout.addLayout(buttons_layout)
        
        # Apply dark theme styling
        self.setStyleSheet("""
            QDialog {
                background-color: #0F172A;
                color: #E2E8F0;
            }
            QLabel {
                color: #E2E8F0;
            }
        """)
    
    def _create_wing_checkbox(self, wing: WingConfig) -> QWidget:
        """
        Create a checkbox widget for a Wing.
        
        Args:
            wing: WingConfig to create checkbox for
            
        Returns:
            QWidget containing the checkbox and Wing info
        """
        container = QGroupBox()
        container.setStyleSheet("""
            QGroupBox {
                background-color: #1E293B;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 10px;
                margin-top: 0px;
            }
            QGroupBox:hover {
                border-color: #475569;
                background-color: #263449;
            }
        """)
        
        layout = QVBoxLayout(container)
        layout.setSpacing(5)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Checkbox with Wing name
        checkbox = QCheckBox(wing.wing_name)
        checkbox.setFont(QFont("Segoe UI", 11, QFont.Bold))
        checkbox.setStyleSheet("""
            QCheckBox {
                color: #E2E8F0;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 2px solid #475569;
                border-radius: 3px;
                background-color: #1E293B;
            }
            QCheckBox::indicator:hover {
                border-color: #64748B;
                background-color: #263449;
            }
            QCheckBox::indicator:checked {
                background-color: #3B82F6;
                border-color: #2563EB;
                image: url(none);
            }
            QCheckBox::indicator:checked:hover {
                background-color: #2563EB;
            }
        """)
        
        # Store checkbox reference
        self.wing_checkboxes[wing.wing_id] = checkbox
        
        layout.addWidget(checkbox)
        
        # Wing description
        if wing.description:
            desc_label = QLabel(wing.description)
            desc_label.setWordWrap(True)
            desc_label.setStyleSheet("""
                color: #94A3B8;
                font-size: 10px;
                padding-left: 26px;
            """)
            layout.addWidget(desc_label)
        
        # Wing details
        details_layout = QHBoxLayout()
        details_layout.setContentsMargins(26, 5, 0, 0)
        details_layout.setSpacing(15)
        
        # Feather count
        feather_count_label = QLabel(f"📊 {len(wing.feathers)} Feather(s)")
        feather_count_label.setStyleSheet("color: #64748B; font-size: 9px;")
        details_layout.addWidget(feather_count_label)
        
        # Time window
        time_window_label = QLabel(f"⏱ {wing.time_window_minutes} min window")
        time_window_label.setStyleSheet("color: #64748B; font-size: 9px;")
        details_layout.addWidget(time_window_label)
        
        # Weighted scoring indicator
        if wing.use_weighted_scoring:
            scoring_label = QLabel("⚖ Weighted Scoring")
            scoring_label.setStyleSheet("color: #3B82F6; font-size: 9px; font-weight: bold;")
            details_layout.addWidget(scoring_label)
        
        details_layout.addStretch()
        layout.addLayout(details_layout)
        
        return container
    
    def _select_all(self):
        """Select all Wings"""
        for checkbox in self.wing_checkboxes.values():
            checkbox.setChecked(True)
    
    def _deselect_all(self):
        """Deselect all Wings"""
        for checkbox in self.wing_checkboxes.values():
            checkbox.setChecked(False)
    
    def _on_ok_clicked(self):
        """Handle OK button click"""
        # Collect selected wing IDs
        self.selected_wing_ids = [
            wing_id for wing_id, checkbox in self.wing_checkboxes.items()
            if checkbox.isChecked()
        ]
        
        # Validate selection
        if not self.selected_wing_ids:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(
                self,
                "No Wings Selected",
                "Please select at least one Wing to execute."
            )
            return
        
        # Accept dialog
        self.accept()
    
    def get_selected_wing_ids(self) -> List[str]:
        """
        Get list of selected Wing IDs.
        
        Returns:
            List of selected wing_id strings
        """
        return self.selected_wing_ids


def show_wing_selection_dialog(wings: List[WingConfig], 
                               parent=None) -> Optional[List[str]]:
    """
    Show Wing selection dialog and return selected Wing IDs.
    
    Args:
        wings: List of WingConfig objects to display
        parent: Parent widget
        
    Returns:
        List of selected wing_id strings, or None if cancelled
    """
    dialog = WingSelectionDialog(wings, parent)
    
    if dialog.exec_() == QDialog.Accepted:
        return dialog.get_selected_wing_ids()
    
    return None
