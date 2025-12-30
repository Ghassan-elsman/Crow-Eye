"""
Progress Display Widget
Displays real-time progress during correlation execution.
"""

from PyQt5.QtWidgets import QTextEdit
from PyQt5.QtCore import Qt
from datetime import datetime


class ProgressDisplayWidget(QTextEdit):
    """
    Widget for displaying real-time correlation progress.
    
    Shows detailed progress information including:
    - Wing information
    - Anchor collection statistics
    - Correlation progress updates
    - Summary statistics
    """
    
    def __init__(self, parent=None):
        """
        Initialize progress display widget.
        
        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumHeight(200)
        self.setStyleSheet("""
            QTextEdit {
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 10pt;
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #3a3a3a;
            }
        """)
    
    def append_progress(self, message: str):
        """
        Append a progress message and auto-scroll to bottom.
        
        Args:
            message: Progress message to display
        """
        self.append(message)
        # Auto-scroll to bottom
        scrollbar = self.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def handle_progress_event(self, event):
        """
        Handle progress event from correlation engine.
        
        Args:
            event: ProgressEvent object with event_type and data
        """
        event_type = event.event_type
        data = event.data
        
        if event_type == "wing_start":
            self.append_progress(f"\n[Correlation] Wing: {data['wing_name']} (ID: {data['wing_id']})")
            self.append_progress(f"[Correlation] Feathers in wing: {data['feather_count']}")
        
        elif event_type == "anchor_collection":
            self.append_progress(
                f"[Correlation]   • {data['feather_id']} "
                f"({data['artifact_type']}): {data['anchor_count']} anchors"
            )
        
        elif event_type == "correlation_start":
            self.append_progress(f"[Correlation] Total anchors collected: {data['total_anchors']}")
            self.append_progress(f"[Correlation] Time window: {data['time_window']} minutes")
            self.append_progress(f"[Correlation] Minimum matches required: {data['minimum_matches']}")
            self.append_progress("[Correlation] Starting correlation analysis...")
        
        elif event_type == "anchor_progress":
            # Only show every 100th anchor to avoid flooding
            if data['anchor_index'] % 100 == 0:
                self.append_progress(
                    f"    [Analyzing] Anchor {data['anchor_index']}/{data['total_anchors']} "
                    f"from {data['feather_id']} ({data['artifact_type']}) "
                    f"at {data['timestamp']}"
                )
        
        elif event_type == "summary_progress":
            # Show summary every 1000 anchors
            self.append_progress(
                f"    Progress: {data['anchors_processed']}/{data['total_anchors']} "
                f"anchors processed, {data['matches_found']} matches found"
            )
    
    def clear_progress(self):
        """Clear all progress messages."""
        self.clear()
    
    def get_progress_text(self) -> str:
        """
        Get all progress text.
        
        Returns:
            Complete progress text
        """
        return self.toPlainText()
