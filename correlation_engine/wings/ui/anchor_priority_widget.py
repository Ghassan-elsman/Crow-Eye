"""
Anchor Priority Widget
Widget for managing artifact type priority ordering.
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
    QPushButton, QLabel, QListWidgetItem
)
from PyQt5.QtCore import Qt, pyqtSignal


class AnchorPriorityWidget(QWidget):
    """Widget for managing anchor priority list"""
    
    priority_changed = pyqtSignal(list)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
    
    def init_ui(self):
        """Initialize the user interface"""
        layout = QVBoxLayout(self)
        
        # Info label
        info_label = QLabel(
            "Drag items to reorder priority (higher = preferred as anchor)"
        )
        info_label.setStyleSheet("color: #666; font-size: 8pt;")
        layout.addWidget(info_label)
        
        # List widget
        self.list_widget = QListWidget()
        self.list_widget.setDragDropMode(QListWidget.InternalMove)
        self.list_widget.setMaximumHeight(150)
        self.list_widget.model().rowsMoved.connect(self.on_rows_moved)
        
        # Default priority order
        default_priority = [
            "Logs", "Prefetch", "SRUM", "AmCache", 
            "ShimCache", "Jumplists", "LNK", "MFT", "USN"
        ]
        
        for artifact_type in default_priority:
            self.list_widget.addItem(artifact_type)
        
        layout.addWidget(self.list_widget)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        reset_btn = QPushButton("Reset to Default")
        reset_btn.clicked.connect(self.reset_to_default)
        button_layout.addWidget(reset_btn)
        
        button_layout.addStretch()
        
        layout.addLayout(button_layout)
    
    def on_rows_moved(self):
        """Handle row reordering"""
        priority = self.get_priority()
        self.priority_changed.emit(priority)
    
    def get_priority(self):
        """Get current priority list"""
        priority = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            priority.append(item.text())
        return priority
    
    def set_priority(self, priority):
        """Set priority list"""
        self.list_widget.clear()
        for artifact_type in priority:
            self.list_widget.addItem(artifact_type)
    
    def reset_to_default(self):
        """Reset to default priority"""
        default_priority = [
            "Logs", "Prefetch", "SRUM", "AmCache", 
            "ShimCache", "Jumplists", "LNK", "MFT", "USN"
        ]
        self.set_priority(default_priority)
        self.priority_changed.emit(default_priority)
