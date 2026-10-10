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
from ui.site_theme import (begin_site_theme, apply_site_theme, set_role, set_variant,
                           set_status, font as site_font)

# The wing cards: titleless group boxes, so none of the site group box's title
# margin; the hover keeps the old affordance in the site's indigo.
_EXTRA = """
QGroupBox#wingCard { margin-top: 0px; padding: 10px; }
QGroupBox#wingCard:hover { border-color: rgba(99, 102, 241, 0.55); }
"""


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
        self.wing_checkboxes = {} # wing_id -> QCheckBox
        self.selected_wing_ids = []

        begin_site_theme(self, extra=_EXTRA)
        self._init_ui()
        apply_site_theme(self, extra=_EXTRA)
        
        # Select all by default
        self._select_all()
    
    def _init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle("Select Wings to Execute")
        from .crow_eye_icons import CrowEyeIcons
        self.setWindowIcon(CrowEyeIcons.wing())
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)
        
        # Main layout
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        # Header
        header_label = QLabel("Select which Wings to execute:")
        header_label.setFont(site_font("ui", 16, QFont.Bold))
        layout.addWidget(header_label)
        
        # Info label
        info_label = QLabel(
            f"Found {len(self.wings)} Wing(s) in the Pipeline. "
            "Select the Wings you want to execute."
        )
        set_role(info_label, "muted")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        layout.addWidget(separator)
        
        # Wings list in scroll area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        
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
        set_variant(select_all_btn, "ghost")
        selection_buttons_layout.addWidget(select_all_btn)
        
        deselect_all_btn = QPushButton("Deselect All")
        deselect_all_btn.clicked.connect(self._deselect_all)
        set_variant(deselect_all_btn, "ghost")
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
        set_variant(cancel_btn, "ghost")
        buttons_layout.addWidget(cancel_btn)
        
        ok_btn = QPushButton("Execute Selected")
        CorrelationEngineStyles.add_button_icon(ok_btn, "execute", "#FFFFFF")
        ok_btn.clicked.connect(self._on_ok_clicked)
        ok_btn.setMinimumWidth(150)
        ok_btn.setDefault(True)
        set_variant(ok_btn, "primary")
        buttons_layout.addWidget(ok_btn)
        
        layout.addLayout(buttons_layout)
        
    
    def _create_wing_checkbox(self, wing: WingConfig) -> QWidget:
        """
        Create a checkbox widget for a Wing.
        
        Args:
            wing: WingConfig to create checkbox for
            
        Returns:
            QWidget containing the checkbox and Wing info
        """
        container = QGroupBox()
        container.setObjectName("wingCard")
        
        layout = QVBoxLayout(container)
        layout.setSpacing(5)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Checkbox with Wing name
        checkbox = QCheckBox(wing.wing_name)
        checkbox.setFont(site_font("ui", 15, QFont.Bold))
        
        # Store checkbox reference
        self.wing_checkboxes[wing.wing_id] = checkbox
        
        layout.addWidget(checkbox)
        
        # Wing description
        if wing.description:
            desc_label = QLabel(wing.description)
            desc_label.setWordWrap(True)
            set_role(desc_label, "muted")
            desc_label.setContentsMargins(26, 0, 0, 0)
            layout.addWidget(desc_label)
        
        # Wing details
        details_layout = QHBoxLayout()
        details_layout.setContentsMargins(26, 5, 0, 0)
        details_layout.setSpacing(15)
        
        # Feather count
        feather_count_label = QLabel(f"{len(wing.feathers)} Feather(s)")
        set_role(feather_count_label, "muted")
        details_layout.addWidget(feather_count_label)
        
        # Time window
        time_window_label = QLabel(f"{wing.time_window_minutes} min window")
        set_role(time_window_label, "muted")
        details_layout.addWidget(time_window_label)
        
        # Weighted scoring indicator — icon + text in a tight QHBoxLayout
        # so the Crow-Eye chart icon sits next to the label without
        # changing the surrounding layout's stretch behavior.
        if wing.use_weighted_scoring:
            from .crow_eye_icons import CrowEyeIcons
            scoring_row = QHBoxLayout()
            scoring_row.setSpacing(4)
            scoring_row.setContentsMargins(0, 0, 0, 0)
            scoring_icon = QLabel()
            scoring_icon.setPixmap(CrowEyeIcons.chart().pixmap(12, 12))
            scoring_label = QLabel("Weighted Scoring")
            scoring_label.setFont(site_font("ui", 12, QFont.Bold))
            set_status(scoring_label, "accent")
            scoring_row.addWidget(scoring_icon)
            scoring_row.addWidget(scoring_label)
            scoring_row.addStretch()
            details_layout.addLayout(scoring_row)
        
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
