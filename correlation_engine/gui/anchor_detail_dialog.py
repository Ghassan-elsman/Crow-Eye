"""
Anchor Detail Dialog

Displays detailed information about a temporal anchor including:
- Temporal information (start/end time, duration)
- Evidence list with roles
- Basic timeline visualization

Implements Task 10: Create Anchor Detail Dialog
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QPushButton, QTextEdit, QGroupBox
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont
from datetime import datetime

from correlation_engine.engine.data_structures import Anchor
from correlation_engine.gui.timeline_widget import TimelineWidget
from correlation_engine.gui.ui_styling import CorrelationEngineStyles


class AnchorDetailDialog(QDialog):
    """
    Detailed view of a temporal anchor with evidence list.
    
    Implements Task 10: Anchor Detail Dialog
    """
    
    def __init__(self, anchor: Anchor, parent=None):
        """
        Initialize anchor detail dialog.
        
        Args:
            anchor: Anchor object to display
            parent: Parent widget
        """
        super().__init__(parent)
        self.anchor = anchor
        self.setup_ui()
        self.load_data()
        # GUI-polish pass: unified slate / cyan / emerald look across
        # every widget in this dialog. See ui_styling.py.
        CorrelationEngineStyles.apply_evidence_detail_styling(self)
    
    def setup_ui(self):
        """Setup dialog UI."""
        self.setWindowTitle(f"Anchor Details: {self.anchor.anchor_id[:8]}")
        self.setMinimumSize(800, 600)
        
        layout = QVBoxLayout(self)
        
        # Title
        title = QLabel("<h2>Temporal Anchor Details</h2>")
        layout.addWidget(title)
        
        # Metadata section
        metadata_group = QGroupBox("Anchor Metadata")
        metadata_layout = QVBoxLayout()
        self.metadata_text = QTextEdit()
        self.metadata_text.setReadOnly(True)
        self.metadata_text.setMaximumHeight(150)
        metadata_layout.addWidget(self.metadata_text)
        metadata_group.setLayout(metadata_layout)
        layout.addWidget(metadata_group)
        
        # Timeline section (using TimelineWidget)
        timeline_label = QLabel("<h3>Timeline Visualization</h3>")
        layout.addWidget(timeline_label)
        
        self.timeline_widget = TimelineWidget()
        layout.addWidget(self.timeline_widget)
        
        # Evidence list
        evidence_label = QLabel("<h3>Evidence in Anchor</h3>")
        layout.addWidget(evidence_label)
        
        self.evidence_table = QTableWidget()
        self.evidence_table.setColumnCount(5)
        self.evidence_table.setHorizontalHeaderLabels([
            "Feather ID", "Artifact", "Role", "Timestamp", "Semantic"
        ])
        self.evidence_table.horizontalHeader().setStretchLastSection(True)
        self.evidence_table.setAlternatingRowColors(True)
        layout.addWidget(self.evidence_table)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)
    
    def load_data(self):
        """Load anchor data."""
        self._load_metadata()
        self._load_timeline()
        self._load_evidence()
    
    def _load_metadata(self):
        """Load anchor metadata."""
        start_str = self.anchor.start_time.strftime("%Y-%m-%d %H:%M:%S") if self.anchor.start_time else "N/A"
        end_str = self.anchor.end_time.strftime("%Y-%m-%d %H:%M:%S") if self.anchor.end_time else "N/A"
        
        # Pre-format confidence outside the f-string — Python f-strings
        # don't accept `value:.2f if cond else 'N/A'` as a format spec.
        confidence_str = (
            f"{self.anchor.confidence:.2f}" if self.anchor.confidence else "N/A"
        )
        metadata_html = f"""
<b>Anchor ID:</b> {self.anchor.anchor_id}<br>
<b>Start Time:</b> {start_str}<br>
<b>End Time:</b> {end_str}<br>
<b>Duration:</b> {self.anchor.duration_minutes:.1f} minutes<br>
<br>
<b>Evidence Counts:</b><br>
Total: {len(self.anchor.rows)}<br>
Primary: {self.anchor.primary_count}<br>
Secondary: {self.anchor.secondary_count}<br>
<br>
<b>Primary Artifact:</b> {self.anchor.primary_artifact or 'N/A'}<br>
<b>Confidence:</b> {confidence_str}
        """
        self.metadata_text.setHtml(metadata_html)
    
    def _load_timeline(self):
        """Load timeline visualization into the embedded TimelineWidget.

        Hands the sorted evidence list off to TimelineWidget.load_events
        when available; otherwise falls back silently (the timeline area
        is purely visual and never blocks the rest of the dialog).
        """
        if not self.anchor.rows:
            return

        # Sort evidence by timestamp
        sorted_evidence = sorted(
            [e for e in self.anchor.rows if e.timestamp],
            key=lambda e: e.timestamp
        )
        if not sorted_evidence:
            return

        # Best-effort handoff to the TimelineWidget instance built by
        # setup_ui. Older builds of TimelineWidget expose a different
        # API, so we probe before calling — the timeline view is a
        # nice-to-have, not a blocker.
        for method_name in ("load_events", "load_anchor", "set_events", "update_events"):
            method = getattr(self.timeline_widget, method_name, None)
            if callable(method):
                try:
                    method(sorted_evidence)
                except Exception:
                    pass
                return
    
    def _load_evidence(self):
        """Load evidence list."""
        self.evidence_table.setRowCount(len(self.anchor.rows))
        
        for i, evidence in enumerate(self.anchor.rows):
            # Feather ID
            self.evidence_table.setItem(i, 0, QTableWidgetItem(evidence.feather_id))
            
            # Artifact
            self.evidence_table.setItem(i, 1, QTableWidgetItem(evidence.artifact))
            
            # Role — map to the Crow-Eye semantic palette so the badge
            # color matches the rest of the engine (Score/Confidence
            # categories in the main viewers use the same hues).
            role_item = QTableWidgetItem(evidence.role.upper())
            if evidence.role == "primary":
                role_item.setForeground(QColor(CorrelationEngineStyles.SCORE_WEAK)) # red — primary = strongest claim
                font = QFont()
                font.setBold(True)
                role_item.setFont(font)
            elif evidence.role == "secondary":
                role_item.setForeground(QColor(CorrelationEngineStyles.SCORE_PROBABLE)) # amber
            else:
                role_item.setForeground(QColor(CorrelationEngineStyles.SCORE_CONFIRMED)) # emerald — supporting
            self.evidence_table.setItem(i, 2, role_item)
            
            # Timestamp
            timestamp_str = evidence.timestamp.strftime("%Y-%m-%d %H:%M:%S") if evidence.timestamp else "N/A"
            self.evidence_table.setItem(i, 3, QTableWidgetItem(timestamp_str))
            
            # Semantic
            if evidence.semantic_data and 'meaning' in evidence.semantic_data:
                semantic_str = evidence.semantic_data['meaning']
            else:
                semantic_str = "N/A"
            self.evidence_table.setItem(i, 4, QTableWidgetItem(semantic_str))
